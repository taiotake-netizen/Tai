"""ステータス自動移行と発表後の自動検証。"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Evaluation, Event, EventStatus, JobRun, ResearchReport, utcnow
from . import analysis
from .evaluation import evaluate
from .outcomes import compute_price_metrics, upsert_bar_outcome


def _indicators_confirmed(event: Event) -> bool:
    return all(i.actual is not None and i.actual_verified for i in event.indicators)


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def evaluate_event(db: Session, event: Event) -> list[Evaluation]:
    """全バージョン × 全実績を評価し直す（評価結果は再計算可能な派生データ）。"""
    results = []
    existing = {
        (e.forecast_id, e.outcome_id): e
        for e in db.scalars(select(Evaluation).where(Evaluation.forecast_id.in_([f.id for f in event.forecasts])))
    } if event.forecasts else {}
    for o in event.outcomes:
        for f in event.forecasts:
            metrics, notes = evaluate(event, f, o)
            ev = existing.get((f.id, o.id))
            if ev is None:
                ev = Evaluation(forecast_id=f.id, outcome_id=o.id, forecast=f, outcome=o)
                db.add(ev)
            ev.metrics, ev.notes, ev.tentative, ev.created_at = metrics, notes, not o.verified, utcnow()
            results.append(ev)
    db.flush()
    return results


def build_report(db: Session, event: Event, evals: list[Evaluation], use_llm: bool = True) -> ResearchReport | None:
    outcome = analysis.best_outcome(event)
    if outcome is None:
        return None
    oc_evals = sorted([e for e in evals if e.outcome_id == outcome.id], key=lambda e: e.forecast.version_no)
    res = analysis.rule_based_analysis(event, outcome, oc_evals)
    inputs = {"outcome": outcome.id, "metrics": [e.metrics for e in oc_evals], "verified": outcome.verified,
              "ind": [(i.code, i.actual, i.actual_verified) for i in event.indicators]}
    h = _hash(inputs)
    latest = next((r for r in reversed(event.reports) if r.generated_by != "conversation_import"), None)
    if latest is not None and latest.checklist.get("input_hash") == h:
        return latest  # 入力が変わっていなければ再生成しない

    generated_by = "rule_engine"
    if use_llm:
        llm = analysis.llm_analysis({
            "event": {"title": event.title, "category": event.category, "release_at": event.release_at},
            "indicators": [{"name": i.name, "previous": i.previous, "consensus": i.consensus,
                            "actual": i.actual, "verified": i.actual_verified} for i in event.indicators],
            "evaluations": [{"version": e.forecast.version_no, "metrics": e.metrics} for e in oc_evals],
            "outcome_verified": outcome.verified,
            "rule_findings": res["hypotheses"],
        })
        if llm:
            res["hypotheses"] += llm["hypotheses"]
            res["improvements"] = list(dict.fromkeys(res["improvements"] + llm["improvements"]))
            generated_by = "rule_engine+llm"

    f = analysis.primary_forecast(event)
    checklist = {
        "input_hash": h,
        "indicator_forecast_missed": any(abs(r["error"]) > 0 for e in oc_evals for r in e.metrics.get("indicators", [])),
        "direction_missed": any(not e.metrics["direction"]["hit"] for e in oc_evals[-1:] if "direction" in e.metrics),
        "excursion_underestimated": any(e.metrics.get("excursion_bias") == "過小評価" for e in oc_evals[-1:]),
        "reversal_occurred": outcome.reversed_,
        "related_markets_available": bool(outcome.related_markets),
        "primary_version": f.version_no if f else None,
    }
    rep = ResearchReport(
        event_id=event.id, outcome_id=outcome.id, tentative=not outcome.verified, generated_by=generated_by,
        summary=res["summary"], confirmed_facts=res["confirmed_facts"], hypotheses=res["hypotheses"],
        improvements=res["improvements"], checklist=checklist,
    )
    db.add(rep)
    event.reports.append(rep)
    return rep


def verify_event(db: Session, event: Event, use_llm: bool = True) -> dict:
    """発表済みイベントを検証する。データが不足していれば未検証のまま保持する。"""
    if event.release_at is None or event.release_at > utcnow():
        return {"event_id": event.id, "result": "skipped", "reason": "未発表、または発表日時が不明"}
    prev_status = event.status
    event.status = EventStatus.VERIFYING
    db.flush()

    metrics = compute_price_metrics(db, "XAUUSD", event.release_at)
    if metrics is not None:
        upsert_bar_outcome(db, event, metrics)
        db.flush()
    evals = evaluate_event(db, event)
    report = build_report(db, event, evals, use_llm=use_llm)

    bar_oc = next((o for o in event.outcomes if o.kind == "price_bars"), None)
    price_ok = bool(bar_oc and bar_oc.verified)
    if price_ok and _indicators_confirmed(event):
        event.status = EventStatus.VERIFIED
    elif event.origin == "conversation" or prev_status == EventStatus.HISTORICAL_UNVERIFIED:
        event.status = EventStatus.HISTORICAL_UNVERIFIED
    else:
        event.status = EventStatus.AWAITING_DATA
    db.commit()
    missing = []
    if not price_ok:
        missing.append("XAUUSD価格データ（発表直前〜5分後）")
        if bar_oc:
            missing += bar_oc.missing
    missing += [f"{i.name}の公式実績" for i in event.indicators if not (i.actual is not None and i.actual_verified)]
    return {"event_id": event.id, "result": event.status, "report_id": report.id if report else None,
            "missing": missing}


def expected_status(event: Event, now: datetime) -> str:
    if event.release_at is None:
        return event.status if event.status not in EventStatus.FUTURE else EventStatus.HISTORICAL_UNVERIFIED
    if event.release_at > now:
        return EventStatus.FORECASTED if event.forecasts else EventStatus.UPCOMING
    return event.status  # 過去側の状態は verify_event が決める


def refresh_statuses(db: Session, now: datetime | None = None, use_llm: bool = True) -> dict:
    """定期ジョブ: 未来⇔過去の振り分けと、発表済みイベントの自動検証。"""
    now = now or utcnow()
    run = JobRun(job="refresh_statuses")
    db.add(run)
    db.commit()
    moved, verified = [], []
    try:
        events = db.scalars(
            select(Event).options(selectinload(Event.forecasts), selectinload(Event.outcomes),
                                  selectinload(Event.indicators), selectinload(Event.reports))
        ).all()
        for ev in events:
            if ev.release_at is not None and ev.release_at <= now and ev.status in EventStatus.FUTURE:
                ev.status = EventStatus.AWAITING_DATA if ev.origin != "conversation" else EventStatus.HISTORICAL_UNVERIFIED
                moved.append(ev.id)
            else:
                ev.status = expected_status(ev, now)
        db.commit()
        for ev in events:
            if ev.release_at is not None and ev.release_at <= now and ev.status != EventStatus.VERIFIED:
                r = verify_event(db, ev, use_llm=use_llm)
                if r["result"] == EventStatus.VERIFIED:
                    verified.append(ev.id)
        run.status = "success"
        run.message = f"過去へ移動 {len(moved)}件 / 検証完了 {len(verified)}件"
        run.details = {"moved": moved, "verified": verified}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run.status = "failed"
        run.message = str(e)[:2000]
        raise
    finally:
        run.finished_at = utcnow()
        db.add(run)
        db.commit()
    return {"moved": moved, "verified": verified}
