import json
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest
from sqlalchemy import select

from app.models import Event, EventStatus, Outcome, utcnow
from app.seed.loader import seed, sync_official_schedule
from app.services import ai_forecast, calendar_feed, price_feed
from app.services.pipeline import verify_event

JST = ZoneInfo("Asia/Tokyo")


def _ev(db, slug):
    return db.scalar(select(Event).where(Event.slug == slug))


def test_official_schedule_times_and_verified_actuals(db):
    seed(db)
    r = sync_official_schedule(db)
    assert "nfp-2026-11" in r["created"] and "ism-unknown-2026" in r["updated"]
    assert sync_official_schedule(db) == {"updated": [], "created": []}
    jst = lambda slug: _ev(db, slug).release_at.astimezone(JST).strftime("%m/%d %H:%M")  # noqa: E731
    assert jst("fomc-2026-10") == "10/29 03:00"       # 夏時間 14:00 EDT
    assert jst("gdp-pce-2026-10") == "10/29 21:30"
    assert jst("nfp-2026-11") == "11/06 22:30"        # 夏時間終了後 8:30 EST
    assert jst("fomc-2026-12") == "12/10 04:00"
    assert jst("ism-unknown-2026") == "10/01 23:00"
    cpi = _ev(db, "cpi-2026-10")
    assert {i.code: (i.actual, i.actual_verified) for i in cpi.indicators}["CORE_CPI_YOY"] == (2.6, True)
    # 公式で確認できない値は未照合のまま
    pce = {i.code: i for i in _ev(db, "pce-2026-09-30").indicators}
    assert pce["CORE_PCE_YOY"].actual_verified is False
    # 会話由来の予測バージョンは変更されない
    assert [f.d5 for f in _ev(db, "fomc-2026-10").forecasts] == [-12, -20, -12]
    assert _ev(db, "nfp-2026-12").release_time_confirmed is False
    # 今後の予定は FOMC・GDP・CPI・雇用統計のみ
    upcoming = db.scalars(select(Event).where(Event.release_at > utcnow())).all()
    assert {e.category for e in upcoming} <= {"FOMC", "GDP", "CPI", "NFP"}
    assert all(i.code != "INITIAL_CLAIMS" for e in upcoming for i in e.indicators)


def test_rev1_low_priority_events_are_removed(db):
    """REV 1 で登録された対象外の今後の予定は削除し、予測が付いたものは残す。"""
    from app.models import ForecastVersion, Indicator

    seed(db)
    sync_official_schedule(db)
    rel = utcnow() + timedelta(days=5)
    db.add(Event(slug="eci-2026-q3", title="ECI", category="ECI", release_at=rel, schedule_rev=1))
    keep = Event(slug="adp-2026-11", title="ADP", category="ADP", release_at=rel, schedule_rev=1)
    db.add(keep)
    db.flush()
    db.add(Indicator(event_id=keep.id, code="ADP", name="ADP"))
    db.add(ForecastVersion(event_id=keep.id, version_no=1, source="manual", model_name="manual", model_version="1"))
    gdp = _ev(db, "gdp-pce-2026-11-25")
    gdp.schedule_rev, gdp.category = 1, "PCE"
    db.add(Indicator(event_id=gdp.id, code="INITIAL_CLAIMS", name="claims"))
    db.commit()
    r = sync_official_schedule(db)
    assert r["removed"] == ["eci-2026-q3"] and r["kept_with_data"] == ["adp-2026-11"]
    db.expire_all()
    gdp = _ev(db, "gdp-pce-2026-11-25")
    assert gdp.category == "GDP" and all(i.code != "INITIAL_CLAIMS" for i in gdp.indicators)


def _bars_payload(release, path):
    vals = []
    t0 = release - timedelta(minutes=60)
    for i in range(150):
        ts = t0 + timedelta(minutes=i)
        k = i - 60
        o = h = l = c = 4000.0
        if 0 <= k < len(path):
            o, h, l, c = path[k]
        elif k >= len(path):
            o = h = l = c = path[-1][3]
        vals.append({"datetime": ts.strftime("%Y-%m-%d %H:%M:%S"), "open": str(o), "high": str(h),
                     "low": str(l), "close": str(c), "volume": "0"})
    return {"meta": {"symbol": "XAU/USD"}, "values": vals, "status": "ok"}


def test_price_feed_fetch_and_verify(db, monkeypatch):
    monkeypatch.setattr(price_feed.settings, "twelvedata_api_key", "test", raising=False)
    release = (utcnow() - timedelta(hours=2)).replace(second=0, microsecond=0)
    ev = Event(slug="pf", title="価格取得テスト", category="CPI", release_at=release, status=EventStatus.AWAITING_DATA)
    db.add(ev)
    db.commit()
    path = [(4000, 4001, 3980, 3985), (3985, 3990, 3975, 3988), (3988, 3995, 3986, 3992), (3992, 3994, 3990, 3991),
            (3991, 3993, 3989, 3990)]
    seen = {}

    def handler(req: httpx.Request):
        seen.update(dict(req.url.params))
        return httpx.Response(200, json=_bars_payload(release, path))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = price_feed.fetch_due_events(db, client=client)
    assert res[0]["inserted"] == 150
    assert seen["symbol"] == "XAU/USD" and seen["interval"] == "1min"
    # 30分以内の再試行はしない
    assert price_feed.fetch_due_events(db, client=client) == []
    v = verify_event(db, _ev(db, "pf"), use_llm=False)
    oc = db.scalar(select(Outcome).where(Outcome.event_id == ev.id, Outcome.kind == "price_bars"))
    assert oc.verified and oc.d5 == -10 and oc.max_down_5m == 25 and "twelvedata" in oc.source
    assert v["result"] == EventStatus.VERIFIED  # 指標が無いイベントは価格のみで確定


def test_price_feed_error_is_not_success(db, monkeypatch):
    monkeypatch.setattr(price_feed.settings, "twelvedata_api_key", "test", raising=False)
    release = utcnow() - timedelta(hours=2)
    db.add(Event(slug="pf2", title="x", category="CPI", release_at=release))
    db.commit()
    client = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"status": "error", "code": 401, "message": "invalid api key"})))
    res = price_feed.fetch_due_events(db, client=client)
    assert "invalid api key" in res[0]["error"]
    from app.models import JobRun
    assert db.scalar(select(JobRun).where(JobRun.job.like("price_fetch:%"))).status == "failed"


def test_calendar_feed_apply(db):
    seed(db)
    sync_official_schedule(db)
    items = [
        {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00",
         "impact": "High", "forecast": "65K", "previous": "29K"},
        {"title": "Unemployment Rate", "country": "USD", "date": "2026-11-06T08:30:00-05:00",
         "impact": "High", "forecast": "4.2%", "previous": "4.2%"},
        {"title": "Core PCE Price Index m/m", "country": "USD", "date": "2026-11-25T08:30:00-05:00",
         "impact": "High", "forecast": "0.2%", "previous": "0.3%"},
        {"title": "CPI m/m", "country": "USD", "date": "2026-11-11T08:30:00-05:00",  # 公式は11/10
         "impact": "High", "forecast": "0.3%", "previous": "0.6%"},
        {"title": "JOLTS Job Openings", "country": "USD", "date": "2026-11-03T10:00:00-05:00",  # 対象外
         "impact": "High", "forecast": "7.15M", "previous": "7.20M"},
        {"title": "Unemployment Claims", "country": "USD", "date": "2026-11-05T08:30:00-05:00",  # 対象外
         "impact": "High", "forecast": "225K", "previous": "220K"},
        {"title": "German Ifo", "country": "EUR", "date": "2026-11-03T04:00:00-05:00", "impact": "High"},
    ]
    res = calendar_feed.apply_feed(db, items)
    nfp = {i.code: i for i in _ev(db, "nfp-2026-11").indicators}
    assert nfp["NFP"].consensus == 6.5 and nfp["NFP"].previous == 2.9  # 既存の前回値は上書きしない
    assert nfp["UNRATE"].consensus == 4.2
    pce = {i.code: i for i in _ev(db, "gdp-pce-2026-11-25").indicators}
    assert pce["CORE_PCE_MOM"].consensus == 0.2 and pce["CORE_PCE_MOM"].previous == 0.3
    assert len(res["time_mismatches"]) == 1 and res["time_mismatches"][0]["title"] == "CPI m/m"
    assert res["created"] == []  # 対象外の指標はイベントを作らない
    assert db.scalar(select(Event).where(Event.category.in_(["JOLTS", "JOBLESS_CLAIMS"]))) is None


class FakeClient:
    """messages.parse を模したテスト用クライアント。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kw):
        self.calls.append(kw)
        out = self.outputs.pop(0)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out, content=[{"type": "text", "text": "{}"}])


def _ai(**over):
    base = dict(
        prob_up=40, prob_down=50, prob_flat=10, importance=9, confidence=55, d1=-5, d5=-10, d15=-12, d30=-15, d60=-18,
        max_up_5m=15, max_down_5m=30, max_excursion_5m=30, max_excursion_5m_low=20, max_excursion_5m_high=45,
        range_5m=40, range_30m=55, range_60m=70,
        reach=[{"threshold": t, "up": u, "down": d, "either": e, "both": b} for t, u, d, e, b in
               [(10, 60, 75, 90, 45), (20, 35, 55, 70, 20), (30, 20, 40, 50, 10), (50, 8, 18, 24, 2), (100, 1, 3, 4, 0)]],
        initial_direction="down", initial_move=-25, reversal_prob=45, reversal_size=12,
        indicator_forecasts=[{"code": "GDP_QOQ_ANN", "point": 3.0, "rationale": "GDPNow等"}],
        scenarios=[{"label": "GDP 2%未満", "indicator_code": "GDP_QOQ_ANN", "min": -5, "max": 2,
                    "reaction_min": 10, "reaction_max": 40, "window": "5m"}],
        rationale="テスト", key_risks=["FOMC直後"],
    )
    base.update(over)
    return ai_forecast.AiForecast(**base)


def test_ai_forecast_generation_with_retry(db, monkeypatch):
    seed(db)
    sync_official_schedule(db)
    ev = _ev(db, "gdp-pce-2026-10")
    if ev.release_at <= utcnow():
        pytest.skip("イベントが過去になったため対象外")
    bad = _ai(prob_flat=30)  # 合計110% → 拒否され再出力
    client = FakeClient([bad, _ai()])
    fv = ai_forecast.generate(db, ev, client=client)
    db.commit()
    assert fv.source == "llm" and fv.version_no == 4 and fv.reach_probs["10"]["either"] == 90
    assert len(client.calls) == 2 and "合計" in client.calls[1]["messages"][-1]["content"]
    ctx = json.loads(client.calls[0]["messages"][0]["content"].split("\n", 1)[1])
    titles = [r["title"] for r in ctx["research_same_category"]]
    assert any("PCE" in t for t in titles)  # 過去の同カテゴリ研究材料が渡されている
    assert all(r["release_at_utc"] < ctx["forecast_time_utc"] for r in ctx["research_same_category"])


def test_ai_unavailable_without_key(db, client):
    ev = client.get("/api/events?scope=upcoming").json()[0]
    r = client.post(f"/api/events/{ev['id']}/forecasts/ai")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.text
