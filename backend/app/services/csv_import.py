"""価格CSVのインポート（TradingView / Dukascopy）。

対応形式（列名で自動判定）:
- TradingView「チャートデータをエクスポート」: time,open,high,low,close[,Volume,...]
  time は UNIX秒 もしくは ISO8601。タイムゾーンが無い場合は assumed_tz で解釈する。
- Dukascopy ヒストリカルデータ: "Gmt time,Open,High,Low,Close,Volume"
  （時刻 "01.10.2026 00:00:00.000"、GMT）または "Local time" 列（"... GMT+0900" 付き）。
  出来高0で始値=高値=安値=終値の行（休場時の埋め草）は取り込まない。
- timestamp 列（UNIXミリ秒、dukascopy-node 等の出力）
"""

import io
import re
from datetime import timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import ImportBatch, PriceBar

SUPPORTED_SYMBOLS = {"XAUUSD", "DXY", "US02Y", "US10Y", "USOIL"}


class CsvImportError(ValueError):
    pass


TIME_COLUMNS = ("time", "gmt time", "local time", "timestamp", "datetime", "date", "time (utc)", "utc")
_DUKAS_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}(:\d{2}(\.\d+)?)?( GMT[+-]\d{4})?$")


def _parse_dukascopy_times(t: pd.Series, utc: bool) -> pd.Series:
    """数年分（数十万行）を扱うため、ベクトル演算で解釈する。"""
    t = t.astype(str).str.strip()
    parts = t.str.split(" GMT", n=1, expand=True)
    sample = parts[0].iloc[0]
    fmt = "%d.%m.%Y %H:%M:%S.%f" if sample.count(".") == 3 else (
        "%d.%m.%Y %H:%M:%S" if sample.count(":") == 2 else "%d.%m.%Y %H:%M")
    base = pd.to_datetime(parts[0], format=fmt)
    if parts.shape[1] > 1 and parts[1].notna().any():
        off = parts[1].fillna("+0000")
        sign = off.str[0].map({"+": 1, "-": -1})
        delta = pd.to_timedelta(off.str[1:3].astype(int), unit="h") + pd.to_timedelta(off.str[3:5].astype(int), unit="m")
        return (base - delta * sign).dt.tz_localize("UTC")
    return base.dt.tz_localize("UTC") if utc else base


def detect_source(content: bytes) -> str:
    head = content[:300].decode("utf-8", "ignore").lower()
    if "gmt time" in head or "local time" in head or head.startswith("timestamp,"):
        return "dukascopy_csv"  # Dukascopy公式エクスポート / dukascopy-node の出力
    return "tradingview_csv"


def parse_tradingview_csv(content: bytes, assumed_tz: str = "UTC") -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise CsvImportError(f"CSVを読み込めません: {e}") from e
    cols = {c.lower().strip(): c for c in df.columns}
    tcol = next((cols[c] for c in TIME_COLUMNS if c in cols), None)
    missing = [c for c in ("open", "high", "low", "close") if c not in cols]
    if tcol is None:
        missing.insert(0, "time")
    if missing:
        raise CsvImportError(f"必須列がありません: {', '.join(missing)}")
    out = pd.DataFrame()
    t = df[tcol]
    sample = str(t.iloc[0]).strip() if len(t) else ""
    if not pd.api.types.is_numeric_dtype(t) and _DUKAS_RE.match(sample):
        parsed = _parse_dukascopy_times(t, utc=tcol.lower().strip() == "gmt time")
        if getattr(parsed.dt, "tz", None) is None:
            ts = parsed.dt.tz_localize(assumed_tz).dt.tz_convert("UTC")
        else:
            ts = parsed
    elif pd.api.types.is_numeric_dtype(t):
        unit = "ms" if t.max() > 10**11 else "s"
        ts = pd.to_datetime(t, unit=unit, utc=True)
    else:
        parsed = pd.to_datetime(t.astype(str), utc=False, errors="coerce", format="mixed")
        if parsed.isna().any():
            raise CsvImportError("time 列に解釈できない日時があります。")
        if getattr(parsed.dt, "tz", None) is None:
            try:
                ts = parsed.dt.tz_localize(assumed_tz).dt.tz_convert("UTC")
            except Exception as e:  # noqa: BLE001
                raise CsvImportError(f"タイムゾーンが不正です: {assumed_tz}") from e
        else:
            ts = parsed.dt.tz_convert("UTC")
    out["ts"] = ts
    for c in ("open", "high", "low", "close"):
        out[c] = pd.to_numeric(df[cols[c]], errors="coerce")
    out["volume"] = pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else None
    bad = out[["open", "high", "low", "close"]].isna().any(axis=1)
    out = out[~bad]
    if out.empty:
        raise CsvImportError("有効な価格行がありません。")
    inconsistent = (out["high"] < out[["open", "close", "low"]].max(axis=1)) | (
        out["low"] > out[["open", "close", "high"]].min(axis=1)
    )
    if inconsistent.any():
        raise CsvImportError(f"高値・安値が始値・終値と矛盾する行が{int(inconsistent.sum())}行あります。")
    # 休場時の埋め草（出来高0かつ四本値が同じ）を除外
    filler = pd.Series(False, index=out.index)
    if "volume" in cols:
        filler = (out["volume"].fillna(0) == 0) & (out["open"] == out["high"]) & (out["high"] == out["low"]) & (
            out["low"] == out["close"])
    out = out[~filler]
    if out.empty:
        raise CsvImportError("有効な価格行がありません（すべて休場時の行でした）。")
    out = out.sort_values("ts").drop_duplicates("ts")
    out.attrs["dropped_rows"] = int(bad.sum()) + int(filler.sum())
    return out


def infer_timeframe_min(df: pd.DataFrame) -> int:
    if len(df) < 2:
        raise CsvImportError("時間足を判定するには2行以上必要です。")
    diffs = df["ts"].diff().dropna().dt.total_seconds() / 60
    tf = int(round(diffs.median()))
    if tf < 1:
        raise CsvImportError("1分未満の時間足には対応していません。")
    return tf


def insert_bars(db: Session, rows: list[dict]) -> int:
    """重複（同シンボル・時間足・時刻・ソース）は無視して挿入し、追加件数を返す。"""
    inserted = 0
    if not rows:
        return 0
    if db.bind.dialect.name == "postgresql":
        for i in range(0, len(rows), 5000):
            chunk = rows[i : i + 5000]
            stmt = pg_insert(PriceBar).values(chunk).on_conflict_do_nothing(
                index_elements=["symbol", "timeframe_min", "ts", "source"]
            ).returning(PriceBar.id)
            inserted += len(db.execute(stmt).all())
        return inserted
    r0 = rows[0]
    existing = set(db.scalars(select(PriceBar.ts).where(
        PriceBar.symbol == r0["symbol"], PriceBar.timeframe_min == r0["timeframe_min"], PriceBar.source == r0["source"])))
    for r in rows:
        if r["ts"] not in existing:
            db.add(PriceBar(**r))
            inserted += 1
    return inserted


def import_csv(
    db: Session,
    content: bytes,
    filename: str,
    symbol: str = "XAUUSD",
    assumed_tz: str = "UTC",
    source: str | None = None,
    timeframe_min: int | None = None,
    events_only: bool = False,
) -> ImportBatch:
    """events_only=True なら、登録済みイベントの発表3時間前〜3時間後のバーだけを保存する（数年分の一括取込用）。"""
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise CsvImportError(f"未対応のシンボルです: {symbol}")
    source = source or detect_source(content)
    df = parse_tradingview_csv(content, assumed_tz)
    tf = timeframe_min or infer_timeframe_min(df)
    outside = 0
    if events_only:
        from ..models import Event

        rels = [r for r in db.scalars(select(Event.release_at).where(Event.release_at.is_not(None)))]
        if not rels:
            raise CsvImportError("イベントが登録されていないため、イベント前後のみの取込はできません。")
        mask = pd.Series(False, index=df.index)
        for r in rels:
            rt = pd.Timestamp(r).tz_convert("UTC")
            mask |= (df["ts"] >= rt - pd.Timedelta(hours=3)) & (df["ts"] <= rt + pd.Timedelta(hours=3))
        outside = int((~mask).sum())
        df = df[mask]
        if df.empty:
            raise CsvImportError("登録済みイベントの前後3時間に該当する行がありません（期間を確認してください）。")

    batch = ImportBatch(
        filename=filename, symbol=symbol, timeframe_min=tf, source=source,
        assumed_tz=assumed_tz, rows_total=len(df) + df.attrs.get("dropped_rows", 0) + outside,
        first_ts=df["ts"].iloc[0].to_pydatetime(), last_ts=df["ts"].iloc[-1].to_pydatetime(),
    )
    db.add(batch)
    db.flush()

    rows = [
        dict(
            symbol=symbol, timeframe_min=tf, ts=r.ts.to_pydatetime().astimezone(timezone.utc),
            open=float(r.open), high=float(r.high), low=float(r.low), close=float(r.close),
            volume=None if pd.isna(r.volume) else float(r.volume), source=source, batch_id=batch.id,
        )
        for r in df.itertuples(index=False)
    ]
    inserted = insert_bars(db, rows)
    batch.rows_inserted = inserted
    batch.rows_skipped = batch.rows_total - inserted
    batch.message = (
        f"{inserted}行を追加、{batch.rows_skipped}行をスキップ（重複・不正・休場時"
        + (f"・イベント前後以外 {outside}行" if events_only else "") + "）"
        f"（形式 {'Dukascopy' if source == 'dukascopy_csv' else 'TradingView等'}, 時間足 {tf}分, タイムゾーン前提 {assumed_tz}）"
    )
    db.commit()
    return batch
