import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import serializers as S
from ..db import get_db
from ..models import Evaluation, Event, EventStatus, Indicator, PriceBar, utcnow
from ..schemas import EventCreate, EventUpdate, ForecastCreate, IndicatorCreate, IndicatorUpdate
from ..services import baseline
from ..services.forecasts import ForecastRejected, create_forecast
from ..services.pipeline import verify_event

router = APIRouter(prefix="/api", tags=["events"])

LOAD = (
    selectinload(Event.indicators), selectinload(Event.forecasts), selectinload(Event.outcomes),
    selectinload(Event.reports), selectinload(Event.children),
)


def get_event(db: Session, event_id: int) -> Event:
    ev = db.scalar(select(Event).where(Event.id == event_id).options(*LOAD))
    if ev is None:
        raise HTTPException(404, "イベントが見つかりません")
    return ev


@router.get("/events")
def list_events(scope: str = Query("all", pattern="^(upcoming|past|all)$"), category: str | None = None,
                db: Session = Depends(get_db)):
    q = select(Event).options(*LOAD)
    if category:
        q = q.where(Event.category == category)
    events = db.scalars(q).all()
    now = utcnow()
    if scope == "upcoming":
        events = [e for e in events if e.release_at and e.release_at > now]
        events.sort(key=lambda e: e.release_at)
    elif scope == "past":
        events = [e for e in events if not (e.release_at and e.release_at > now)]
        events.sort(key=lambda e: (e.release_at is not None, e.release_at), reverse=True)
    else:
        events.sort(key=lambda e: (e.release_at is None, e.release_at))
    return [S.event_summary(e) for e in events]


@router.get("/events/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    d = S.event_summary(ev)
    d["forecasts"] = [S.forecast(f) for f in ev.forecasts]
    d["outcomes"] = [S.outcome(o) for o in ev.outcomes]
    d["reports"] = [S.report(r) for r in ev.reports]
    d["children"] = [{"id": c.id, "title": c.title, "release_at": c.release_at, "status": c.status} for c in ev.children]
    if ev.parent_id:
        p = db.get(Event, ev.parent_id)
        d["parent"] = {"id": p.id, "title": p.title, "release_at": p.release_at}
    evals = db.scalars(select(Evaluation).where(Evaluation.forecast_id.in_([f.id for f in ev.forecasts]))).all() \
        if ev.forecasts else []
    d["evaluations"] = [
        {"id": e.id, "forecast_id": e.forecast_id, "outcome_id": e.outcome_id, "tentative": e.tentative,
         "metrics": e.metrics, "notes": e.notes, "created_at": e.created_at} for e in evals
    ]
    # 研究材料: 同カテゴリの過去イベント
    similar = db.scalars(
        select(Event).options(*LOAD).where(Event.category == ev.category, Event.id != ev.id)
    ).all()
    now = utcnow()
    d["similar_events"] = [
        S.event_summary(s) for s in sorted(
            (s for s in similar if not (s.release_at and s.release_at > now)),
            key=lambda s: (s.release_at is not None, s.release_at), reverse=True)
    ][:10]
    return d


def _slugify(title: str, release_at) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "event"
    suffix = release_at.strftime("%Y%m%d%H%M") if release_at else utcnow().strftime("%Y%m%d%H%M%S")
    return f"{base}-{suffix}"


@router.post("/events", status_code=201)
def create_event(body: EventCreate, db: Session = Depends(get_db)):
    now = utcnow()
    slug = _slugify(body.title, body.release_at)
    if db.scalar(select(Event).where(Event.slug == slug)):
        slug += f"-{int(now.timestamp())}"
    status = (EventStatus.UPCOMING if body.release_at and body.release_at > now
              else EventStatus.AWAITING_DATA if body.release_at else EventStatus.HISTORICAL_UNVERIFIED)
    ev = Event(slug=slug, title=body.title, category=body.category, categories=body.categories or [body.category],
               release_at=body.release_at, release_time_confirmed=body.release_time_confirmed,
               importance=body.importance, is_composite=body.is_composite, parent_id=body.parent_id,
               notes=body.notes, origin="manual", status=status)
    db.add(ev)
    db.flush()
    for i, ind in enumerate(body.indicators):
        db.add(Indicator(event_id=ev.id, sort_order=i, **ind.model_dump()))
    db.commit()
    return S.event_summary(get_event(db, ev.id))


@router.patch("/events/{event_id}")
def update_event(event_id: int, body: EventUpdate, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    data = body.model_dump(exclude_unset=True)
    if "release_at" in data and ev.forecasts:
        new = data["release_at"]
        made = [f.as_of or f.created_at for f in ev.forecasts if f.source != "chatgpt_conversation"]
        if new is None or any(m >= new for m in made):
            raise HTTPException(409, "既存の予測より前の発表時刻には変更できません（事前予測の前提が崩れるため）。")
    for k, v in data.items():
        setattr(ev, k, v)
    db.commit()
    return S.event_summary(get_event(db, event_id))


@router.post("/events/{event_id}/indicators", status_code=201)
def add_indicator(event_id: int, body: IndicatorCreate, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    if any(i.code == body.code for i in ev.indicators):
        raise HTTPException(409, "同じコードの指標が既にあります")
    ind = Indicator(event_id=ev.id, sort_order=len(ev.indicators), **body.model_dump())
    db.add(ind)
    db.commit()
    return S.indicator(ind)


@router.patch("/indicators/{indicator_id}")
def update_indicator(indicator_id: int, body: IndicatorUpdate, db: Session = Depends(get_db)):
    ind = db.get(Indicator, indicator_id)
    if ind is None:
        raise HTTPException(404, "指標が見つかりません")
    ev = db.get(Event, ind.event_id)
    data = body.model_dump(exclude_unset=True)
    released = ev.release_at is None or ev.release_at <= utcnow()  # 日時不明の過去記録は登録可
    if not released and (data.get("actual") is not None or data.get("actual_verified")):
        raise HTTPException(409, "発表前のイベントに実績は登録できません。")
    if "actual" in data and data["actual"] != ind.actual:
        # 値が変われば照合状態はリセット（明示的に verified を渡した場合を除く）
        data.setdefault("actual_verified", False)
        ind.actual_recorded_at = utcnow()
    if data.get("actual_verified"):
        src = data.get("actual_source", ind.actual_source)
        if not src or src.startswith("ChatGPT"):
            raise HTTPException(422, "公式照合済みにするには公式の出所（例: BLS発表、BEA発表）を入力してください。")
        if data.get("actual", ind.actual) is None:
            raise HTTPException(422, "実績値が未入力です。")
    for k, v in data.items():
        setattr(ind, k, v)
    db.commit()
    return S.indicator(ind)


@router.delete("/indicators/{indicator_id}", status_code=204)
def delete_indicator(indicator_id: int, db: Session = Depends(get_db)):
    ind = db.get(Indicator, indicator_id)
    if ind is None:
        raise HTTPException(404, "指標が見つかりません")
    if ind.actual is not None:
        raise HTTPException(409, "実績が登録された指標は削除できません。")
    db.delete(ind)
    db.commit()


@router.post("/events/{event_id}/forecasts", status_code=201)
def add_forecast(event_id: int, body: ForecastCreate, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    try:
        fv = create_forecast(db, ev, body.to_data(), source="manual" if body.model_name == "manual" else "external",
                             model_name=body.model_name, model_version=body.model_version)
    except ForecastRejected as e:
        db.rollback()
        raise HTTPException(422, {"errors": e.errors}) from e
    db.commit()
    return S.forecast(fv)


@router.post("/events/{event_id}/forecasts/baseline", status_code=201)
def add_baseline_forecast(event_id: int, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    now = utcnow()
    if ev.release_at is None or ev.release_at <= now:
        raise HTTPException(409, "発表前のイベントにのみ事前予測を作成できます。")
    samples = baseline.training_outcomes(db, ev.category, cutoff=now)
    try:
        pred = baseline.fit_predict(samples)
    except baseline.InsufficientData as e:
        raise HTTPException(422, {"errors": [str(e)]}) from e
    pred["label"] = f"ベースライン（n={pred.pop('n_samples')}）"
    pred["market_snapshot"] = {"training_event_ids": [o.event_id for o in samples], "cutoff": now.isoformat()}
    try:
        fv = create_forecast(db, ev, pred, source="baseline_stat", model_name=baseline.MODEL_NAME,
                             model_version=baseline.MODEL_VERSION)
    except ForecastRejected as e:
        db.rollback()
        raise HTTPException(422, {"errors": e.errors}) from e
    db.commit()
    return S.forecast(fv)


@router.post("/events/{event_id}/forecasts/ai", status_code=201)
def add_ai_forecast(event_id: int, db: Session = Depends(get_db)):
    from ..services import ai_forecast

    ev = get_event(db, event_id)
    try:
        fv = ai_forecast.generate(db, ev, label="AI予測（手動実行）")
    except ai_forecast.AiUnavailable as e:
        raise HTTPException(503, {"errors": [str(e)]}) from e
    except ForecastRejected as e:
        db.rollback()
        raise HTTPException(422, {"errors": ["AI予測が整合性チェックを通りませんでした"] + e.errors}) from e
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(502, {"errors": [f"AI予測の作成に失敗しました: {e}"]}) from e
    db.commit()
    return S.forecast(fv)


@router.post("/events/{event_id}/prices/fetch")
def fetch_event_prices(event_id: int, db: Session = Depends(get_db)):
    from ..services import price_feed

    ev = get_event(db, event_id)
    if ev.release_at is None or ev.release_at > utcnow() - timedelta(minutes=61):
        raise HTTPException(409, "発表から61分以上経過したイベントのみ取得できます。")
    try:
        res = price_feed.fetch_for_event(db, ev)
    except price_feed.PriceFeedError as e:
        db.rollback()
        raise HTTPException(502, str(e)) from e
    return {**res, "verification": verify_event(db, get_event(db, event_id))}


@router.post("/events/{event_id}/verify")
def verify(event_id: int, db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    if ev.release_at is None:
        raise HTTPException(409, "発表日時が不明なため検証できません。発表日時を設定してください。")
    if ev.release_at > utcnow():
        raise HTTPException(409, "未発表のイベントは検証できません。")
    return verify_event(db, ev)


@router.get("/events/{event_id}/bars")
def event_bars(event_id: int, symbol: str = "XAUUSD", before_min: int = 60, after_min: int = 120,
               db: Session = Depends(get_db)):
    ev = get_event(db, event_id)
    if ev.release_at is None:
        return {"bars": [], "timeframe_min": None}
    start, end = ev.release_at - timedelta(minutes=before_min), ev.release_at + timedelta(minutes=after_min)
    tfs = sorted(set(db.scalars(select(PriceBar.timeframe_min).where(
        PriceBar.symbol == symbol, PriceBar.ts >= start, PriceBar.ts <= end)).all()))
    if not tfs:
        return {"bars": [], "timeframe_min": None}
    bars = db.scalars(select(PriceBar).where(
        PriceBar.symbol == symbol, PriceBar.timeframe_min == tfs[0], PriceBar.ts >= start, PriceBar.ts <= end
    ).order_by(PriceBar.ts)).all()
    return {"timeframe_min": tfs[0], "bars": [
        {"time": int(b.ts.timestamp()), "open": b.open, "high": b.high, "low": b.low, "close": b.close} for b in bars
    ]}
