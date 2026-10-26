from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.models import Evaluation, Event, EventStatus, ForecastVersion, Outcome, utcnow
from app.seed.loader import seed
from app.services.pipeline import refresh_statuses
from app.services.validation import validate_forecast

from .helpers import synthetic_bars_csv


def _ev(db, slug):
    return db.scalar(select(Event).where(Event.slug == slug))


def _eval(db, slug, version_no, kind="conversation_record"):
    ev = _ev(db, slug)
    f = next(f for f in ev.forecasts if f.version_no == version_no)
    o = next(o for o in ev.outcomes if o.kind == kind)
    return db.scalar(select(Evaluation).where(Evaluation.forecast_id == f.id, Evaluation.outcome_id == o.id))


# ---------------------------------------------------------------- 初期データ

def test_seed_is_idempotent_and_statuses(db):
    seed(db)
    assert seed(db)["created"] == []
    refresh_statuses(db, use_llm=False)
    assert _ev(db, "cpi-2026-10").status == EventStatus.HISTORICAL_UNVERIFIED
    ism = _ev(db, "ism-unknown-2026")
    assert ism.release_at is None and ism.status == EventStatus.HISTORICAL_UNVERIFIED
    fomc = _ev(db, "fomc-2026-10")
    if fomc.release_at > utcnow():
        assert fomc.status == EventStatus.FORECASTED
        assert [f.version_no for f in fomc.forecasts] == [1, 2, 3]
        assert [f.d5 for f in fomc.forecasts] == [-12, -20, -12]
    assert _ev(db, "fomc-2026-10-presser").parent_id == fomc.id


def test_seed_conversation_evaluations(db):
    seed(db)
    refresh_statuses(db, use_llm=False)
    # CPI 修正版: 5分後 −9 vs 会話記録 −16 → 誤差7ドル、方向は下落で的中（暫定）
    m = _eval(db, "cpi-2026-10", 2).metrics
    assert m["d5"]["abs_error"] == 7
    assert m["direction"]["hit"] is True
    assert _eval(db, "cpi-2026-10", 1).metrics["direction"]["hit"] is False
    # NFP: 数値予測誤差7.6万人、時間幅不明の差は72ドル（comparable=False）、条件付きシナリオは範囲内
    m = _eval(db, "nfp-2026-10", 1).metrics
    nfp = next(r for r in m["indicators"] if r["code"] == "NFP")
    assert nfp["abs_error"] == pytest.approx(7.6)
    assert nfp["actual_verified"] is False
    assert m["headline_move"]["abs_error"] == 72 and m["headline_move"]["comparable"] is False
    sc = m["scenarios"][0]
    assert sc["triggered"] and sc["reaction_in_range"] and sc["comparable"] is False
    assert "d5" not in m  # 時間幅不明の値を5分後と比較しない
    for e in db.scalars(select(Evaluation)):
        assert e.tentative is True


# ---------------------------------------------------------------- 予測の不変性・妥当性

def test_forecast_versions_are_immutable(db):
    seed(db)
    f = db.scalar(select(ForecastVersion).limit(1))
    f.d5 = 999
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()
    with pytest.raises(Exception):
        with db.begin_nested():
            db.execute(text("UPDATE forecast_versions SET d5 = 1"))


def test_validation_rules():
    now = utcnow()
    rel = now + timedelta(hours=1)
    errs, _ = validate_forecast({"prob_up": 50, "prob_down": 40, "prob_flat": 5}, rel, now)
    assert any("合計" in e for e in errs)
    errs, _ = validate_forecast({"reach_probs": {"10": {"either": 50}, "20": {"either": 60}}}, rel, now)
    assert any("上回って" in e for e in errs)
    errs, _ = validate_forecast({"reach_probs": {"10": {"up": 60, "down": 67, "either": 50}}}, rel, now)
    assert errs
    errs, _ = validate_forecast({"d5": -10}, now - timedelta(minutes=1), now)
    assert any("発表時刻以降" in e for e in errs)
    errs, _ = validate_forecast({"news_used": [{"title": "x", "published_at": (now + timedelta(minutes=5)).isoformat()}]},
                                rel, now)
    assert any("ニュース" in e for e in errs)
    errs, _ = validate_forecast({"range_5m": 50, "range_30m": 40}, rel, now)
    assert errs
    errs, _ = validate_forecast({"prob_up": 45, "prob_down": 50, "prob_flat": 5, "max_excursion_5m": 35,
                                 "range_5m": 45, "range_30m": 60, "range_60m": 80,
                                 "reach_probs": {"10": {"either": 90}, "100": {"either": 3}}}, rel, now)
    assert errs == []


def test_api_forecast_versioning(client):
    rel = (utcnow() + timedelta(days=2)).isoformat()
    ev = client.post("/api/events", json={"title": "Test CPI", "category": "CPI", "release_at": rel,
                                          "indicators": [{"code": "CPI_YOY", "name": "CPI前年比", "unit": "%"}]}).json()
    assert ev["status"] == "upcoming"
    r1 = client.post(f"/api/events/{ev['id']}/forecasts", json={"prob_up": 40, "prob_down": 55, "prob_flat": 5, "d5": -10})
    assert r1.status_code == 201, r1.text
    r2 = client.post(f"/api/events/{ev['id']}/forecasts", json={"prob_up": 50, "prob_down": 45, "prob_flat": 5, "d5": 5})
    assert r2.json()["version_no"] == 2 and "d5: -10.0 → 5.0" in r2.json()["change_summary"]
    bad = client.post(f"/api/events/{ev['id']}/forecasts", json={"prob_up": 90, "prob_down": 45, "prob_flat": 5})
    assert bad.status_code == 422
    d = client.get(f"/api/events/{ev['id']}").json()
    assert d["status"] == "forecasted" and len(d["forecasts"]) == 2
    # 発表前に実績は入れられない
    ind = d["indicators"][0]
    assert client.patch(f"/api/indicators/{ind['id']}", json={"actual": 3.0}).status_code == 409
    # 統計ベースラインはデータ不足を正直に返す
    assert client.post(f"/api/events/{ev['id']}/forecasts/baseline").status_code == 422


# ---------------------------------------------------------------- CSV取込 → 自動検証 → 過去へ移動

def test_csv_import_and_auto_verification(client, db):
    release = (utcnow() - timedelta(hours=3)).replace(second=0, microsecond=0)
    ev = Event(slug="t-nfp", title="テストNFP", category="NFP", categories=["NFP"], release_at=release,
               status=EventStatus.FORECASTED, origin="manual")
    db.add(ev)
    db.commit()
    from app.models import Indicator
    db.add(Indicator(event_id=ev.id, code="NFP", name="NFP", unit="万人", consensus=10))
    db.add(ForecastVersion(event_id=ev.id, version_no=1, source="manual", model_name="manual", model_version="1",
                           created_at=release - timedelta(hours=1), prob_up=30, prob_down=60, prob_flat=10,
                           dominant_direction="down", d5=-10, max_excursion_5m=20, max_up_5m=10, max_down_5m=20,
                           reversal_prob=20, reach_probs={"10": {"either": 80, "up": 40, "down": 60}},
                           indicator_forecasts=[{"code": "NFP", "point": 12}]))
    db.commit()

    # 発表時刻を過ぎたら過去側（データ待ち）へ
    refresh_statuses(db, use_llm=False)
    db.expire_all()
    assert _ev(db, "t-nfp").status == EventStatus.AWAITING_DATA

    base = 4000.0
    # 初動で+30ドル上昇 → 5分後には+8ドルへ戻す
    path = [(4000, 4012, 3998, 4010), (4010, 4030, 4008, 4025), (4025, 4026, 4012, 4015),
            (4015, 4016, 4005, 4006), (4006, 4010, 4004, 4008)]
    csv = synthetic_bars_csv(release, base, path)
    r = client.post("/api/data/import", files={"file": ("xau.csv", csv, "text/csv")}, data={"symbol": "XAUUSD"})
    assert r.status_code == 200, r.text
    assert r.json()["batch"]["timeframe_min"] == 1
    assert r.json()["batch"]["rows_inserted"] == 91
    # 同じCSVの再取込は重複として全件スキップ
    r2 = client.post("/api/data/import", files={"file": ("xau.csv", csv, "text/csv")}, data={"symbol": "XAUUSD"})
    assert r2.json()["batch"]["rows_inserted"] == 0 and r2.json()["batch"]["rows_skipped"] == 91

    db.expire_all()
    ev = _ev(db, "t-nfp")
    oc = next(o for o in ev.outcomes if o.kind == "price_bars")
    assert oc.verified and oc.base_price == 4000
    assert oc.d1 == 10 and oc.d5 == 8
    assert oc.max_up_5m == 30 and oc.max_down_5m == 2 and oc.max_excursion_5m == 30
    assert oc.range_5m == 32
    assert oc.initial_direction == "up" and oc.reversed_ is True and oc.reversal_size == 22
    assert oc.direction_5m == "up"
    # 指標実績が未照合なので「検証完了」にはしない
    assert ev.status == EventStatus.AWAITING_DATA
    ev_eval = db.scalar(select(Evaluation).where(Evaluation.outcome_id == oc.id))
    assert ev_eval.tentative is False
    assert ev_eval.metrics["direction"]["hit"] is False
    assert ev_eval.metrics["max_excursion_5m"]["error"] == -10
    assert ev_eval.metrics["excursion_bias"] == "過小評価"
    rep = [r for r in ev.reports if r.generated_by == "rule_engine"][-1]
    assert rep.confirmed_facts and rep.hypotheses and rep.improvements

    ind = ev.indicators[0]
    assert client.patch(f"/api/indicators/{ind.id}", json={"actual": 2.0, "actual_verified": True}).status_code == 422
    r = client.patch(f"/api/indicators/{ind.id}", json={"actual": 2.0, "actual_verified": True, "actual_source": "BLS雇用統計"})
    assert r.status_code == 200
    v = client.post(f"/api/events/{ev.id}/verify").json()
    assert v["result"] == "verified"
    acc = client.get("/api/accuracy").json()
    assert acc["confirmed"]["overall"]["direction_n"] == 1
    assert acc["confirmed"]["overall"]["d5_mae"] == 18
    # 会話由来データは確定集計に混ざらない
    assert all(h["verified"] for h in acc["history"] if h["event"] == "テストNFP")


def test_csv_rejects_bad_rows(client):
    bad = b"time,open,high,low,close\n1700000000,10,9,8,9.5\n1700000060,10,11,9,10\n"
    r = client.post("/api/data/import", files={"file": ("bad.csv", bad, "text/csv")}, data={"symbol": "XAUUSD"})
    assert r.status_code == 422
    st = client.get("/api/data/status").json()
    assert st["batches"][0]["status"] == "failed"


def test_baseline_uses_only_verified_past(db):
    from app.services import baseline

    now = utcnow()
    for i in range(3):
        e = Event(slug=f"b{i}", title=f"b{i}", category="CPI", release_at=now - timedelta(days=30 * (i + 1)),
                  status=EventStatus.VERIFIED, origin="manual")
        db.add(e)
        db.flush()
        db.add(Outcome(event_id=e.id, kind="price_bars", verified=True, source="t", d5=-5 * (i + 1),
                       max_up_5m=10 + i, max_down_5m=20 + 5 * i, max_excursion_5m=20 + 5 * i,
                       range_5m=30 + i, range_30m=40, range_60m=50, direction_5m="down", reversed_=i == 0))
    # 未検証の会話記録は学習に使わない
    e = Event(slug="conv", title="conv", category="CPI", release_at=now - timedelta(days=5), origin="conversation")
    db.add(e)
    db.flush()
    db.add(Outcome(event_id=e.id, kind="conversation_record", verified=False, source="c", max_down_5m=500))
    db.commit()
    samples = baseline.training_outcomes(db, "CPI", now)
    assert len(samples) == 3
    p = baseline.fit_predict(samples)
    assert p["max_excursion_5m"] == 25
    assert validate_forecast(p, now + timedelta(days=1), now)[0] == []
    # 予測時点より後の実績は使わない
    assert len(baseline.training_outcomes(db, "CPI", now - timedelta(days=45))) == 2
