"""週間経済カレンダー（Forex Factory形式のJSON）から市場予想・前回値を取り込む。

- 対象は USD の指標のみ。既存イベント（発表時刻±2分）の指標に市場予想・前回値を補完する。
- 公式スケジュールと時刻が食い違う場合は自動変更せず、「時刻不一致」として報告する。
- 公式スケジュールに無い高重要度の指標は、未確認（release_time_confirmed=False）のイベントとして追加する。
"""

import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Event, EventStatus, Indicator, JobRun, utcnow

SOURCE_NAME = "Forex Factory週間カレンダー"

# (正規表現, カテゴリ, 指標コード, 指標名, 単位)
MAPPING = [
    (r"^ADP Non-Farm Employment Change", "ADP", "ADP", "ADP雇用者数", "万人"),
    (r"^Non-Farm Employment Change", "NFP", "NFP", "非農業部門雇用者数", "万人"),
    (r"^Unemployment Rate", "NFP", "UNRATE", "失業率", "%"),
    (r"^Average Hourly Earnings m/m", "NFP", "AHE_MOM", "平均時給（前月比）", "%"),
    (r"^Core CPI m/m", "CPI", "CORE_CPI_MOM", "コアCPI（前月比）", "%"),
    (r"^Core CPI y/y", "CPI", "CORE_CPI_YOY", "コアCPI（前年比）", "%"),
    (r"^CPI m/m", "CPI", "CPI_MOM", "CPI（前月比）", "%"),
    (r"^CPI y/y", "CPI", "CPI_YOY", "CPI（前年比）", "%"),
    (r"^Core PCE Price Index m/m", "PCE", "CORE_PCE_MOM", "コアPCE（前月比）", "%"),
    (r"^Core PCE Price Index y/y", "PCE", "CORE_PCE_YOY", "コアPCE（前年比）", "%"),
    (r"^PCE Price Index m/m", "PCE", "PCE_MOM", "PCE総合（前月比）", "%"),
    (r"^(Advance|Prelim|Final) GDP q/q", "GDP", "GDP_QOQ_ANN", "GDP（前期比年率）", "%"),
    (r"^Federal Funds Rate", "FOMC", "FED_FUNDS_UPPER", "FF金利誘導目標（上限）", "%"),
    (r"^Unemployment Claims", "JOBLESS_CLAIMS", "INITIAL_CLAIMS", "新規失業保険申請件数", "万件"),
    (r"^Employment Cost Index q/q", "ECI", "ECI_QOQ", "雇用コスト指数（前期比）", "%"),
    (r"^ISM Manufacturing PMI", "ISM", "ISM_PMI", "ISM製造業 総合", ""),
    (r"^ISM Manufacturing Prices", "ISM", "ISM_PRICES", "ISM製造業 価格", ""),
    (r"^ISM Services PMI", "ISM", "ISM_SVC_PMI", "ISM非製造業 総合", ""),
    (r"^JOLTS Job Openings", "JOLTS", "JOLTS", "JOLTS求人件数", "万件"),
    (r"^Core Retail Sales m/m", "RETAIL_SALES", "CORE_RETAIL_MOM", "小売売上高 除自動車（前月比）", "%"),
    (r"^Retail Sales m/m", "RETAIL_SALES", "RETAIL_MOM", "小売売上高（前月比）", "%"),
    (r"^Core Durable Goods Orders m/m", "DURABLE_GOODS", "CORE_DGO_MOM", "耐久財受注 除輸送用機器（前月比）", "%"),
    (r"^Durable Goods Orders m/m", "DURABLE_GOODS", "DGO_MOM", "耐久財受注（前月比）", "%"),
    (r"^New Home Sales", "NEW_HOME_SALES", "NEW_HOME_SALES", "新築住宅販売件数（年率）", "万件"),
    (r"^CB Consumer Confidence", "CONSUMER_CONFIDENCE", "CB_CC", "コンファレンスボード消費者信頼感指数", ""),
]


def map_title(title: str):
    for pat, cat, code, name, unit in MAPPING:
        if re.match(pat, title.strip(), re.I):
            return cat, code, name, unit
    return None


def parse_value(raw: str | None, unit: str) -> float | None:
    """'0.3%' '220K' '7.20M' '-0.1%' を指標の単位へ変換。解釈できなければ None。"""
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "")
    if not s:
        return None
    m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\s*([%KMB]?)", s, re.I)
    if not m:
        return None
    v, suf = float(m.group(1)), m.group(2).upper()
    if unit in ("万人", "万件"):
        if suf == "K":
            return round(v / 10, 3)
        if suf == "M":
            return round(v * 100, 3)
        if suf == "B":
            return round(v * 100000, 3)
        return v
    return v


def apply_feed(db: Session, items: list[dict], now: datetime | None = None) -> dict:
    now = now or utcnow()
    label = f"{SOURCE_NAME}（{now.strftime('%Y-%m-%d %H:%M')} UTC取得）"
    events = db.scalars(select(Event).options(selectinload(Event.indicators)).where(Event.release_at.is_not(None))).all()
    updated, created, mismatches, skipped = [], [], [], 0
    for it in items:
        if it.get("country") != "USD":
            continue
        mp = map_title(it.get("title", ""))
        if not mp:
            skipped += 1
            continue
        cat, code, name, unit = mp
        try:
            ts = datetime.fromisoformat(it["date"])
        except (KeyError, ValueError):
            skipped += 1
            continue
        ev = next((e for e in events if abs((e.release_at - ts).total_seconds()) <= 120
                   and (e.category == cat or cat in (e.categories or []) or any(i.code == code for i in e.indicators))), None)
        if ev is None:
            near = next((e for e in events if e.category == cat and abs((e.release_at - ts).total_seconds()) <= 36 * 3600), None)
            if near is not None:
                mismatches.append({"title": it.get("title"), "feed_time": ts.isoformat(), "event_id": near.id,
                                   "event_time": near.release_at.isoformat()})
                continue
            if it.get("impact") != "High" or ts <= now:
                continue
            ev = Event(slug=f"feed-{code.lower()}-{ts.strftime('%Y%m%d%H%M')}", title=f"{name}（{ts.strftime('%m/%d')}）",
                       category=cat, categories=[cat], release_at=ts, release_time_confirmed=False, importance=7,
                       origin="calendar_feed", status=EventStatus.UPCOMING,
                       schedule_sources=[{"name": SOURCE_NAME, "url": settings.calendar_feed_url}],
                       notes="週間カレンダーから自動追加。公式スケジュールで要確認。")
            db.add(ev)
            db.flush()
            ev.indicators = []
            events.append(ev)
            created.append(ev.slug)
        ind = next((i for i in ev.indicators if i.code == code), None)
        if ind is None:
            ind = Indicator(event_id=ev.id, code=code, name=name, unit=unit, sort_order=len(ev.indicators))
            db.add(ind)
            ev.indicators.append(ind)
        changed = False
        cons = parse_value(it.get("forecast"), unit)
        if cons is not None and (ind.consensus is None or (ind.consensus_source or "").startswith(SOURCE_NAME)):
            if ind.consensus != cons:
                ind.consensus, ind.consensus_source, changed = cons, label, True
        prev = parse_value(it.get("previous"), unit)
        if prev is not None and ind.previous is None:
            ind.previous, changed = prev, True
        if changed:
            updated.append(f"{ev.title}: {name}")
    db.commit()
    return {"updated": updated, "created": created, "time_mismatches": mismatches, "unmapped": skipped}


def fetch_and_apply(db: Session, client: httpx.Client | None = None) -> dict:
    run = JobRun(job="calendar_feed")
    db.add(run)
    db.commit()
    c = client or httpx.Client(timeout=30, headers={"User-Agent": "xauusd-research/0.1"})
    try:
        r = c.get(settings.calendar_feed_url)
        r.raise_for_status()
        items = r.json()
        if not isinstance(items, list):
            raise ValueError("想定外の形式です")
        res = apply_feed(db, items)
        run.status = "success"
        run.message = (f"予想・前回値を更新 {len(res['updated'])}件 / 追加 {len(res['created'])}件 / "
                       f"時刻不一致 {len(res['time_mismatches'])}件")
        run.details = res
        return res
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run.status, run.message = "failed", f"カレンダー取得失敗: {e}"
        return {"error": str(e)}
    finally:
        if client is None:
            c.close()
        run.finished_at = utcnow()
        db.add(run)
        db.commit()
