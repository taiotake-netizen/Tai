"""インポートされた価格バーから発表後の実績値動きを算出する。

定義（混同しないこと）:
- 発表直前価格(base): 発表時刻ちょうどで終わるバーの終値
- dN（終着地）: 発表N分後に終わるバーの終値 − base
- max_up_5m / max_down_5m: 発表後5分間の高値−base / base−安値（0以上）
- max_excursion_5m（最大到達幅）: max(max_up_5m, max_down_5m)
- range_Nm（高値安値レンジ）: 発表後N分間の高値−安値
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import HORIZONS_MIN, settings
from ..models import Outcome, PriceBar

RELATED_SYMBOLS = ("DXY", "US02Y", "US10Y")


def _load_bars(db: Session, symbol: str, tf: int, start: datetime, end: datetime) -> dict:
    rows = db.scalars(
        select(PriceBar)
        .where(
            PriceBar.symbol == symbol,
            PriceBar.timeframe_min == tf,
            PriceBar.ts >= start,
            PriceBar.ts <= end,
        )
        .order_by(PriceBar.ts)
    ).all()
    # 同じ時刻に複数ソースがある場合はユーザー取込のCSVを優先する
    out: dict = {}
    for b in sorted(rows, key=lambda b: (b.ts, b.source != "tradingview_csv")):
        out.setdefault(b.ts, b)
    return out


def available_timeframes(db: Session, symbol: str, release_at: datetime) -> list[int]:
    tfs = db.scalars(
        select(PriceBar.timeframe_min)
        .where(
            PriceBar.symbol == symbol,
            PriceBar.ts >= release_at - timedelta(hours=2),
            PriceBar.ts <= release_at + timedelta(minutes=60),
        )
        .distinct()
    ).all()
    return sorted(tfs)


def _window(bars: dict, release_at: datetime, tf: int, minutes: int):
    if minutes % tf:
        return None
    seq = [bars.get(release_at + timedelta(minutes=m)) for m in range(0, minutes, tf)]
    if any(b is None for b in seq):
        return None
    return seq


def compute_price_metrics(db: Session, symbol: str, release_at: datetime) -> dict | None:
    """バーが無ければ None。部分的に欠損していれば missing に列挙する。"""
    tfs = available_timeframes(db, symbol, release_at)
    if not tfs:
        return None
    tf = tfs[0]
    bars = _load_bars(db, symbol, tf, release_at - timedelta(minutes=tf), release_at + timedelta(minutes=60))
    base_bar = bars.get(release_at - timedelta(minutes=tf))
    missing: list[str] = []
    m: dict = {"timeframe_min": tf, "missing": missing}
    if base_bar is None:
        missing.append("発表直前バー")
        return m
    base = base_bar.close
    m["base_price"] = base
    m["bar_source"] = base_bar.source
    m["base_ts"] = base_bar.ts + timedelta(minutes=tf)

    for n in HORIZONS_MIN:
        b = bars.get(release_at + timedelta(minutes=n - tf)) if n % tf == 0 else None
        if b is None:
            missing.append(f"{n}分後価格")
            m[f"d{n}"] = None
        else:
            m[f"d{n}"] = round(b.close - base, 4)

    for n in (5, 30, 60):
        w = _window(bars, release_at, tf, n)
        if w is None:
            missing.append(f"{n}分間の高値安値")
            continue
        hi = max(b.high for b in w)
        lo = min(b.low for b in w)
        m[f"range_{n}m"] = round(hi - lo, 4)
        if n == 5:
            m["high_5m"], m["low_5m"] = hi, lo
            m["max_up_5m"] = round(max(hi - base, 0.0), 4)
            m["max_down_5m"] = round(max(base - lo, 0.0), 4)
            m["max_excursion_5m"] = max(m["max_up_5m"], m["max_down_5m"])

    if m.get("d5") is not None:
        band = settings.flat_band_usd
        m["direction_5m"] = "up" if m["d5"] > band else "down" if m["d5"] < -band else "flat"

    # 初動と反転（1分足が必要）
    w5 = _window(bars, release_at, tf, 5)
    if tf == 1 and w5 is not None and "max_up_5m" in m:
        thr = settings.initial_move_threshold_usd
        init = None
        for b in w5:
            up, dn = b.high - base, base - b.low
            if up >= thr or dn >= thr:
                init = "up" if up >= dn else "down"
                break
        if init is None:
            m["initial_direction"] = "flat"
            m["initial_move"] = 0.0
            m["reversed_"] = False
            m["reversal_size"] = 0.0
        else:
            m["initial_direction"] = init
            close5 = w5[-1].close
            if init == "up":
                m["initial_move"] = m["max_up_5m"]
                m["reversal_size"] = round(m["high_5m"] - close5, 4)
            else:
                m["initial_move"] = -m["max_down_5m"]
                m["reversal_size"] = round(close5 - m["low_5m"], 4)
            m["reversed_"] = m["reversal_size"] >= 0.5 * abs(m["initial_move"])
    else:
        missing.append("初動・反転（1分足が必要）")
    return m


def compute_related_markets(db: Session, release_at: datetime) -> dict:
    out = {}
    for sym in RELATED_SYMBOLS:
        pm = compute_price_metrics(db, sym, release_at)
        if pm and pm.get("base_price") is not None:
            out[sym] = {k: pm.get(k) for k in ("base_price", "d5", "d60", "range_60m")}
    return out


PRICE_FIELDS = [
    "base_price", "base_ts", "d1", "d5", "d15", "d30", "d60", "high_5m", "low_5m", "max_up_5m",
    "max_down_5m", "max_excursion_5m", "range_5m", "range_30m", "range_60m", "direction_5m",
    "initial_direction", "initial_move", "reversed_", "reversal_size", "timeframe_min",
]


def is_price_complete(m: dict | None) -> bool:
    return bool(m) and all(m.get(k) is not None for k in ("base_price", "d5", "max_up_5m", "max_down_5m"))


def upsert_bar_outcome(db: Session, event, metrics: dict) -> Outcome:
    """価格バー由来の実績を作成/更新する（会話由来の記録は変更しない）。"""
    oc = next((o for o in event.outcomes if o.kind == "price_bars"), None)
    if oc is None:
        oc = Outcome(event_id=event.id, kind="price_bars", source="")
        db.add(oc)
        event.outcomes.append(oc)
    for k in PRICE_FIELDS:
        setattr(oc, k, metrics.get(k))
    oc.missing = metrics.get("missing", [])
    oc.verified = is_price_complete(metrics)
    oc.source = f"価格データ（XAUUSD {metrics.get('timeframe_min')}分足・{metrics.get('bar_source', '取込')}）"
    oc.related_markets = compute_related_markets(db, event.release_at)
    from ..models import utcnow

    oc.computed_at = utcnow()
    return oc
