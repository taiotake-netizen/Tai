from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import serializers as S
from ..db import get_db
from ..models import (
    CATEGORIES, Event, EventStatus, ImportBatch, JobRun, ModelVersion, PriceBar, ResearchReport, utcnow,
)
from ..services.accuracy import accuracy_dashboard
from ..services.csv_import import SUPPORTED_SYMBOLS, CsvImportError, import_csv
from ..services.pipeline import refresh_statuses
from .events import LOAD

router = APIRouter(prefix="/api", tags=["data"])
JST = ZoneInfo("Asia/Tokyo")

# 予定しているデータソース。接続していないものは「未接続」と表示し、成功扱いしない。
DATA_SOURCES = [
    {"key": "tradingview_csv", "name": "TradingView CSVインポート", "targets": "XAUUSD/DXY/US02Y/US10Y/USOIL", "phase": 1},
    {"key": "economic_calendar", "name": "経済指標カレンダー自動取得", "targets": "日程・市場予想", "phase": 2},
    {"key": "official_releases", "name": "公式発表（BLS/BEA/FRB）", "targets": "指標実績", "phase": 2},
    {"key": "price_api", "name": "価格データAPI（規約適合のもの）", "targets": "XAUUSD/DXY/金利", "phase": 2},
    {"key": "news", "name": "ニュース取得", "targets": "最新ニュース", "phase": 2},
]


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok", "time": utcnow()}


@router.post("/data/import")
async def import_prices(file: UploadFile = File(...), symbol: str = Form("XAUUSD"), assumed_tz: str = Form("UTC"),
                        db: Session = Depends(get_db)):
    content = await file.read()
    try:
        batch = import_csv(db, content, file.filename or "upload.csv", symbol=symbol, assumed_tz=assumed_tz)
    except CsvImportError as e:
        db.rollback()
        db.add(ImportBatch(filename=file.filename or "upload.csv", symbol=symbol.upper(), source="tradingview_csv",
                           assumed_tz=assumed_tz, status="failed", message=str(e)))
        db.commit()
        raise HTTPException(422, str(e)) from e
    result = refresh_statuses(db)
    return {"batch": S._cols(batch), "refresh": result}


@router.get("/data/status")
def data_status(db: Session = Depends(get_db)):
    coverage = db.execute(
        select(PriceBar.symbol, PriceBar.timeframe_min, func.count(), func.min(PriceBar.ts), func.max(PriceBar.ts))
        .group_by(PriceBar.symbol, PriceBar.timeframe_min)
    ).all()
    batches = db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(20)).all()
    jobs = db.scalars(select(JobRun).order_by(JobRun.id.desc()).limit(20)).all()
    sources = []
    have_csv = any(b.status == "success" for b in batches)
    for s in DATA_SOURCES:
        status = ("利用中" if have_csv else "未取込") if s["key"] == "tradingview_csv" else "未接続"
        sources.append({**s, "status": status})
    return {
        "coverage": [{"symbol": c[0], "timeframe_min": c[1], "bars": c[2], "first": c[3], "last": c[4]} for c in coverage],
        "batches": [S._cols(b) for b in batches],
        "jobs": [S._cols(j) for j in jobs],
        "sources": sources,
        "supported_symbols": sorted(SUPPORTED_SYMBOLS),
    }


@router.post("/jobs/refresh")
def run_refresh(db: Session = Depends(get_db)):
    return refresh_statuses(db)


@router.get("/accuracy")
def accuracy(db: Session = Depends(get_db)):
    return accuracy_dashboard(db)


@router.get("/models")
def models(db: Session = Depends(get_db)):
    return [S._cols(m) for m in db.scalars(select(ModelVersion).order_by(ModelVersion.id))]


@router.get("/home")
def home(db: Session = Depends(get_db)):
    now = utcnow()
    events = db.scalars(select(Event).options(*LOAD)).all()
    future = sorted((e for e in events if e.release_at and e.release_at > now), key=lambda e: e.release_at)
    past = sorted((e for e in events if e.release_at and e.release_at <= now), key=lambda e: e.release_at, reverse=True)
    nxt = next((e for e in future if e.importance >= 7), future[0] if future else None)

    jnow = now.astimezone(JST)
    week_start = (jnow - timedelta(days=jnow.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    week = [e for e in events if e.release_at and week_start <= e.release_at.astimezone(JST) < week_end]
    week.sort(key=lambda e: e.release_at)

    acc = accuracy_dashboard(db)
    counts = defaultdict(int)
    for e in events:
        counts[e.status] += 1
    reports = db.scalar(select(func.count()).select_from(ResearchReport))
    seen, improvements = set(), []
    for r in db.scalars(select(ResearchReport).order_by(ResearchReport.id.desc()).limit(30)):
        for t in r.improvements:
            if t not in seen:
                seen.add(t)
                improvements.append({"event_id": r.event_id, "text": t})
    improvements = improvements[:8]
    ds = data_status(db)
    latest_fc = sorted((f for e in events for f in e.forecasts), key=lambda f: f.created_at, reverse=True)[:1]
    return {
        "now": now,
        "next_event": S.event_summary(nxt) if nxt else None,
        "latest_forecast": ({**S.forecast(latest_fc[0]), "event_title": next(e.title for e in events if e.id == latest_fc[0].event_id)}
                            if latest_fc else None),
        "week_events": [S.event_summary(e) for e in week],
        "recent_results": [S.event_summary(e) for e in past[:5]],
        "accuracy": {"confirmed": acc["confirmed"]["overall"], "tentative": acc["tentative"]["overall"]},
        "research": {"status_counts": {S.STATUS_JA.get(k, k): v for k, v in counts.items()}, "reports": reports, "improvements": improvements,
                     "models": models(db)},
        "data": {"coverage": ds["coverage"], "sources": ds["sources"], "last_job": ds["jobs"][0] if ds["jobs"] else None},
    }


@router.get("/lab")
def lab_index(db: Session = Depends(get_db)):
    rows = db.execute(select(Event.category, func.count()).group_by(Event.category)).all()
    counts = dict(rows)
    return [{"category": c, "events": counts.get(c, 0)} for c in CATEGORIES if counts.get(c) or c in
            ("FOMC", "CPI", "NFP", "GDP", "PCE", "ADP", "ISM")]


@router.get("/lab/{category}")
def lab_category(category: str, db: Session = Depends(get_db)):
    if category not in CATEGORIES:
        raise HTTPException(404, "未対応のカテゴリです")
    events = [e for e in db.scalars(select(Event).options(*LOAD)).all()
              if e.category == category or category in (e.categories or [])]
    events = sorted(events, key=lambda e: (e.release_at is None, e.release_at))
    now = utcnow()

    def dist(verified: bool):
        vals = defaultdict(list)
        for e in events:
            for o in e.outcomes:
                if o.verified != verified:
                    continue
                for k in ("max_excursion_5m", "max_up_5m", "max_down_5m", "range_5m", "range_30m", "range_60m", "d5", "d60"):
                    v = getattr(o, k)
                    if v is not None:
                        vals[k].append({"event_id": e.id, "value": v})
        return vals

    reversal = {"verified": [], "tentative": []}
    for e in events:
        for o in e.outcomes:
            if o.initial_direction:
                reversal["verified" if o.verified else "tentative"].append({
                    "event_id": e.id, "title": e.title, "initial_direction": o.initial_direction,
                    "initial_move": o.initial_move, "d5": o.d5, "reversed": o.reversed_,
                    "reversal_size": o.reversal_size,
                    "observations": [f"{x['label']}: {x['value']}" for x in o.observations or []],
                })
    lessons = [
        {"event_id": r.event_id, "generated_by": r.generated_by, "tentative": r.tentative,
         "reflections": r.reflections, "improvements": r.improvements}
        for e in events for r in e.reports
    ]
    acc = accuracy_dashboard(db)
    return {
        "category": category,
        "upcoming": [S.event_summary(e) for e in events if e.release_at and e.release_at > now],
        "past": [S.event_summary(e) for e in events if not (e.release_at and e.release_at > now)],
        "distribution": {"verified": dist(True), "tentative": dist(False)},
        "reversal_patterns": reversal,
        "lessons": lessons,
        "accuracy": {
            "confirmed": acc["confirmed"]["by_category"].get(category),
            "tentative": acc["tentative"]["by_category"].get(category),
        },
        "status_counts": {s: sum(1 for e in events if e.status == s) for s in EventStatus.ALL},
    }
