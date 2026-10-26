"""価格データAPI（Twelve Data）からの1分足取得。

TWELVEDATA_API_KEY が設定されている場合のみ動作する。取得失敗は失敗として記録し、成功扱いしない。
発表後65分を過ぎたイベントについて、発表前60分〜発表後90分の1分足を取得して自動検証につなげる。
"""

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Event, JobRun, Outcome, utcnow
from .csv_import import insert_bars

SOURCE = "twelvedata"
API = "https://api.twelvedata.com/time_series"
SYMBOLS = {"XAUUSD": "XAU/USD"}


class PriceFeedError(RuntimeError):
    pass


def parse_time_series(payload: dict, symbol: str) -> list[dict]:
    if payload.get("status") != "ok":
        raise PriceFeedError(f"Twelve Data エラー: {payload.get('code')} {payload.get('message')}")
    rows = []
    for v in payload.get("values", []):
        ts = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        o, h, l, c = (float(v[k]) for k in ("open", "high", "low", "close"))
        if h < max(o, c, l) or l > min(o, c, h):
            continue
        rows.append(dict(symbol=symbol, timeframe_min=1, ts=ts, open=o, high=h, low=l, close=c,
                         volume=float(v["volume"]) if v.get("volume") not in (None, "") else None, source=SOURCE))
    return rows


def fetch_bars(symbol: str, start: datetime, end: datetime, client: httpx.Client | None = None) -> list[dict]:
    if not settings.twelvedata_api_key:
        raise PriceFeedError("TWELVEDATA_API_KEY が未設定です")
    params = {
        "symbol": SYMBOLS[symbol], "interval": "1min", "timezone": "UTC", "order": "ASC", "outputsize": 5000,
        "start_date": start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": end.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "apikey": settings.twelvedata_api_key,
    }
    c = client or httpx.Client(timeout=30)
    try:
        r = c.get(API, params=params)
        r.raise_for_status()
        return parse_time_series(r.json(), symbol)
    except httpx.HTTPError as e:
        raise PriceFeedError(f"通信エラー: {e}") from e
    finally:
        if client is None:
            c.close()


def fetch_for_event(db: Session, ev: Event, client: httpx.Client | None = None) -> dict:
    rows = fetch_bars("XAUUSD", ev.release_at - timedelta(minutes=60), ev.release_at + timedelta(minutes=90), client)
    if not rows:
        raise PriceFeedError("指定期間のデータが返されませんでした（市場休場・プラン制限の可能性）")
    n = insert_bars(db, rows)
    db.commit()
    return {"event_id": ev.id, "bars": len(rows), "inserted": n}


def fetch_due_events(db: Session, now: datetime | None = None, client: httpx.Client | None = None) -> list[dict]:
    """発表から65分以上経過し、価格実績が未確定のイベントの価格を取得する（30分に1回まで再試行）。"""
    if not (settings.twelvedata_api_key and settings.price_fetch_enabled):
        return []
    now = now or utcnow()
    events = db.scalars(select(Event).where(
        Event.release_at.is_not(None), Event.release_at <= now - timedelta(minutes=65),
        Event.release_at >= now - timedelta(days=30))).all()
    results = []
    for ev in events:
        done = db.scalar(select(Outcome.id).where(Outcome.event_id == ev.id, Outcome.kind == "price_bars",
                                                  Outcome.verified.is_(True)))
        if done:
            continue
        job = f"price_fetch:{ev.id}"
        recent = db.scalar(select(JobRun.id).where(JobRun.job == job, JobRun.started_at >= now - timedelta(minutes=30)))
        if recent:
            continue
        run = JobRun(job=job)
        db.add(run)
        db.commit()
        try:
            res = fetch_for_event(db, ev, client)
            run.status, run.message, run.details = "success", f"{res['inserted']}本を追加（{ev.title}）", res
        except PriceFeedError as e:
            db.rollback()
            run.status, run.message = "failed", f"{ev.title}: {e}"
            res = {"event_id": ev.id, "error": str(e)}
        run.finished_at = utcnow()
        db.add(run)
        db.commit()
        results.append(res)
    return results
