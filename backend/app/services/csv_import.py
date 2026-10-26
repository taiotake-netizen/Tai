"""TradingView CSV インポート。

TradingView の「チャートデータをエクスポート」形式に対応:
  time,open,high,low,close[,Volume,...]
time は UNIX秒 もしくは ISO8601（タイムゾーン付き推奨）。タイムゾーンが無い場合は
assumed_tz で解釈し、その前提をインポート履歴に保存する。
"""

import io
from datetime import timezone

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import ImportBatch, PriceBar

SUPPORTED_SYMBOLS = {"XAUUSD", "DXY", "US02Y", "US10Y", "USOIL"}


class CsvImportError(ValueError):
    pass


def parse_tradingview_csv(content: bytes, assumed_tz: str = "UTC") -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:  # noqa: BLE001
        raise CsvImportError(f"CSVを読み込めません: {e}") from e
    cols = {c.lower().strip(): c for c in df.columns}
    missing = [c for c in ("time", "open", "high", "low", "close") if c not in cols]
    if missing:
        raise CsvImportError(f"必須列がありません: {', '.join(missing)}")
    out = pd.DataFrame()
    t = df[cols["time"]]
    if pd.api.types.is_numeric_dtype(t):
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
    out = out.sort_values("ts").drop_duplicates("ts")
    out.attrs["dropped_rows"] = int(bad.sum())
    return out


def infer_timeframe_min(df: pd.DataFrame) -> int:
    if len(df) < 2:
        raise CsvImportError("時間足を判定するには2行以上必要です。")
    diffs = df["ts"].diff().dropna().dt.total_seconds() / 60
    tf = int(round(diffs.median()))
    if tf < 1:
        raise CsvImportError("1分未満の時間足には対応していません。")
    return tf


def import_csv(
    db: Session,
    content: bytes,
    filename: str,
    symbol: str = "XAUUSD",
    assumed_tz: str = "UTC",
    source: str = "tradingview_csv",
    timeframe_min: int | None = None,
) -> ImportBatch:
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        raise CsvImportError(f"未対応のシンボルです: {symbol}")
    df = parse_tradingview_csv(content, assumed_tz)
    tf = timeframe_min or infer_timeframe_min(df)

    batch = ImportBatch(
        filename=filename, symbol=symbol, timeframe_min=tf, source=source,
        assumed_tz=assumed_tz, rows_total=len(df) + df.attrs.get("dropped_rows", 0),
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
    inserted = 0
    if db.bind.dialect.name == "postgresql":
        for i in range(0, len(rows), 5000):
            chunk = rows[i : i + 5000]
            stmt = pg_insert(PriceBar).values(chunk).on_conflict_do_nothing(
                index_elements=["symbol", "timeframe_min", "ts", "source"]
            )
            inserted += db.execute(stmt).rowcount or 0
    else:
        existing = set(
            db.scalars(
                select(PriceBar.ts).where(
                    PriceBar.symbol == symbol, PriceBar.timeframe_min == tf, PriceBar.source == source
                )
            )
        )
        for r in rows:
            if r["ts"] not in existing:
                db.add(PriceBar(**r))
                inserted += 1
    batch.rows_inserted = inserted
    batch.rows_skipped = batch.rows_total - inserted
    batch.message = (
        f"{inserted}行を追加、{batch.rows_skipped}行は重複または不正のためスキップ"
        f"（時間足 {tf}分, タイムゾーン前提 {assumed_tz}）"
    )
    db.commit()
    return batch
