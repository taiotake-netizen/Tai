"""予測精度の集計。確定（価格データで検証済み）と暫定（会話由来など）は必ず分けて集計する。"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Evaluation, Event, ForecastVersion


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _summarize(evals: list[Evaluation]) -> dict:
    dir_hits = [e.metrics["direction"]["hit"] for e in evals if "direction" in e.metrics]
    ind_err = [r["abs_error"] for e in evals for r in e.metrics.get("indicators", [])]
    by_h = {}
    for n in ("1", "5", "15", "30", "60"):
        hits = [e.metrics["direction_by_horizon"][n]["hit"] for e in evals if n in e.metrics.get("direction_by_horizon", {})]
        by_h[n] = {"n": len(hits), "accuracy": round(sum(hits) / len(hits) * 100, 1) if hits else None}
    obs = [e.metrics["direction_observed"]["hit"] for e in evals if "direction_observed" in e.metrics]
    return {
        "direction_basis": "5分後終着地（±{:.0f}ドル以内は横ばい）".format(settings.flat_band_usd),
        "direction_by_horizon": by_h,
        "direction_observed_reference": {"n": len(obs), "hits": sum(obs)},
        "n_evaluations": len(evals),
        "direction_n": len(dir_hits),
        "direction_accuracy": round(sum(dir_hits) / len(dir_hits) * 100, 1) if dir_hits else None,
        "d5_mae": _mean([e.metrics["d5"]["abs_error"] for e in evals if "d5" in e.metrics]),
        "d5_n": sum(1 for e in evals if "d5" in e.metrics),
        "d30_mae": _mean([e.metrics["d30"]["abs_error"] for e in evals if "d30" in e.metrics]),
        "max_excursion_mae": _mean([e.metrics["max_excursion_5m"]["abs_error"] for e in evals if "max_excursion_5m" in e.metrics]),
        "max_excursion_n": sum(1 for e in evals if "max_excursion_5m" in e.metrics),
        "indicator_mae": _mean(ind_err),
        "indicator_n": len(ind_err),
        "brier_reach": _mean([e.metrics.get("brier_reach_mean") for e in evals]),
        "brier_direction": _mean([e.metrics.get("brier_direction") for e in evals]),
    }


def _calibration(evals: list[Evaluation]) -> list[dict]:
    bins = defaultdict(lambda: {"n": 0, "prob_sum": 0.0, "hits": 0})
    for e in evals:
        for r in e.metrics.get("reach", []):
            b = min(int(r["prob"] // 10), 9)
            bins[b]["n"] += 1
            bins[b]["prob_sum"] += r["prob"]
            bins[b]["hits"] += 1 if r["hit"] else 0
    return [
        {"bin": f"{b*10}-{b*10+10}%", "n": v["n"], "mean_prob": round(v["prob_sum"] / v["n"], 1),
         "hit_rate": round(v["hits"] / v["n"] * 100, 1)}
        for b, v in sorted(bins.items())
    ]


def accuracy_dashboard(db: Session) -> dict:
    evals = db.scalars(
        select(Evaluation).options(
            selectinload(Evaluation.forecast).selectinload(ForecastVersion.event).selectinload(Event.indicators),
            selectinload(Evaluation.outcome),
        )
    ).all()
    # 各イベントの「発表前最終バージョン」を主評価対象にする
    last_ver = {}
    for e in evals:
        ev = e.forecast.event
        last_ver[ev.id] = max(last_ver.get(ev.id, 0), e.forecast.version_no)
    primary = [e for e in evals if e.forecast.version_no == last_ver[e.forecast.event_id]]

    out = {}
    for label, verified in (("confirmed", True), ("tentative", False)):
        sel = [e for e in primary if e.outcome.verified == verified]
        by_cat = defaultdict(list)
        by_model = defaultdict(list)
        for e in sel:
            by_cat[e.forecast.event.category].append(e)
            by_model[f"{e.forecast.model_name} v{e.forecast.model_version}"].append(e)
        out[label] = {
            "overall": _summarize(sel),
            "by_category": {k: _summarize(v) for k, v in sorted(by_cat.items())},
            "by_model": {k: _summarize(v) for k, v in sorted(by_model.items())},
            "calibration": _calibration(sel),
        }

    # 改善履歴: イベント×バージョン順の誤差推移
    history = []
    for e in sorted(evals, key=lambda e: (e.forecast.event.release_at or e.forecast.created_at, e.forecast.version_no)):
        history.append({
            "event_id": e.forecast.event_id, "event": e.forecast.event.title,
            "release_at": e.forecast.event.release_at, "version_no": e.forecast.version_no,
            "label": e.forecast.label, "model": f"{e.forecast.model_name} v{e.forecast.model_version}",
            "verified": e.outcome.verified, "outcome_kind": e.outcome.kind,
            "direction_hit": e.metrics.get("direction", {}).get("hit"),
            "direction_observed_hit": e.metrics.get("direction_observed", {}).get("hit"),
            "d5_abs_error": e.metrics.get("d5", {}).get("abs_error"),
            "excursion_abs_error": e.metrics.get("max_excursion_5m", {}).get("abs_error"),
            "brier_reach": e.metrics.get("brier_reach_mean"),
        })
    out["history"] = history
    out["notice"] = (
        "confirmed は価格データで検証済みの実績のみで集計。tentative は会話由来など未照合の記録で、"
        "研究の参考値であり学習・モデル採用判断には使用しません。"
    )
    return out
