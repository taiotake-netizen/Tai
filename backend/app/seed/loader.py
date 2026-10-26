"""初期データ登録（冪等）。既に存在するイベントは変更しない。"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Event, EventStatus, Indicator, ModelVersion, Outcome, ResearchReport, utcnow,
)
from ..services.forecasts import create_forecast
from .conversation_2026 import CONV, CONV_MODEL, EVENTS, MODELS, SRC

JST = ZoneInfo("Asia/Tokyo")


def jst(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s).replace(tzinfo=JST) if s else None


def _event(spec: dict, parent: Event | None = None) -> Event:
    release_at = jst(spec.get("release_jst"))
    return Event(
        slug=spec["slug"], title=spec["title"], category=spec["category"],
        categories=spec.get("categories", [spec["category"]]), release_at=release_at,
        release_time_confirmed=False, date_label=spec.get("date_label"),
        importance=spec.get("importance", 5), is_composite=spec.get("is_composite", False),
        cluster=spec.get("cluster"), origin="conversation", notes=spec.get("notes"),
        parent_id=parent.id if parent else None,
        status=EventStatus.UPCOMING if release_at and release_at > utcnow() else EventStatus.HISTORICAL_UNVERIFIED,
    )


def seed(db: Session) -> dict:
    created = []
    for m in MODELS:
        if not db.scalar(select(ModelVersion).where(ModelVersion.name == m["name"], ModelVersion.version == m["version"])):
            db.add(ModelVersion(**m))
    db.flush()

    for spec in EVENTS:
        if db.scalar(select(Event).where(Event.slug == spec["slug"])):
            continue
        ev = _event(spec)
        db.add(ev)
        db.flush()
        for i, ind in enumerate(spec.get("indicators", [])):
            db.add(Indicator(
                event_id=ev.id, sort_order=i, code=ind["code"], name=ind["name"], unit=ind.get("unit", ""),
                previous=ind.get("previous"), previous_revised=ind.get("previous_revised"),
                consensus=ind.get("consensus"), actual=ind.get("actual"),
                actual_source=SRC if ind.get("actual") is not None else None,
                actual_verified=False, notes=ind.get("notes"),
            ))
        for ch in spec.get("children", []):
            db.add(_event({**ch, "categories": [ch["category"]]}, parent=ev))
        db.flush()
        db.refresh(ev)

        # 会話記録の予測は発表前に作成されたことが会話で確認できるため、検証時刻を発表直前として扱う
        vnow = ev.release_at - timedelta(seconds=1) if ev.release_at else None
        for f in spec.get("forecasts", []):
            create_forecast(db, ev, dict(f), source=CONV, model_name=CONV_MODEL[0],
                            model_version=CONV_MODEL[1], validation_now=vnow)

        oc = spec.get("outcome")
        if oc:
            db.add(Outcome(
                event_id=ev.id, kind="conversation_record", verified=False, source=SRC,
                **{k: v for k, v in oc.items()},
            ))
        if spec.get("reflections") or spec.get("improvements"):
            db.add(ResearchReport(
                event_id=ev.id, tentative=True, generated_by="conversation_import",
                summary="会話記録に残る反省・分析（未検証）",
                reflections=spec.get("reflections", []), improvements=spec.get("improvements", []),
                confirmed_facts=[], hypotheses=[{"text": r, "basis": "conversation"} for r in spec.get("reflections", [])],
            ))
        created.append(spec["slug"])
    db.commit()
    return {"created": created}
