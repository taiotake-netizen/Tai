"""ベースライン統計モデル「過去の平均値幅モデル」。

検証済み（価格データで確定した）同カテゴリの過去イベントのみを使い、予測時点より前に
発表されたものだけを参照する（未来情報のリーク防止）。データが足りなければ予測を作らない。
"""

from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import REACH_THRESHOLDS, settings
from ..models import Event, Outcome

MODEL_NAME = "baseline_avg_range"
MODEL_VERSION = "0.1.0"
MIN_SAMPLES = 3


class InsufficientData(ValueError):
    pass


def training_outcomes(db: Session, category: str, cutoff: datetime) -> list[Outcome]:
    return list(db.scalars(
        select(Outcome).join(Event)
        .where(Event.category == category, Event.release_at < cutoff,
               Outcome.kind == "price_bars", Outcome.verified.is_(True))
        .order_by(Event.release_at)
    ))


def fit_predict(samples: list[Outcome]) -> dict:
    if len(samples) < MIN_SAMPLES:
        raise InsufficientData(f"検証済みの過去データが{len(samples)}件しかありません（最低{MIN_SAMPLES}件必要）。")
    n = len(samples)

    def col(name):
        return np.array([getattr(o, name) for o in samples if getattr(o, name) is not None], dtype=float)

    exc = col("max_excursion_5m")
    up, down = col("max_up_5m"), col("max_down_5m")
    dirs = [o.direction_5m for o in samples if o.direction_5m]
    cnt = {d: dirs.count(d) for d in ("up", "down", "flat")}
    # ラプラス平滑化した頻度
    tot = len(dirs) + 3
    p = {d: (cnt[d] + 1) / tot * 100 for d in cnt}
    p_round = {d: round(v, 1) for d, v in p.items()}
    p_round["flat"] = round(100 - p_round["up"] - p_round["down"], 1)

    reach = {}
    prev = {"up": 100.0, "down": 100.0, "either": 100.0, "both": 100.0}
    for t in REACH_THRESHOLDS:
        hits = {
            "up": [u >= t for u in up],
            "down": [d >= t for d in down],
            "either": [max(o.max_up_5m, o.max_down_5m) >= t for o in samples if o.max_up_5m is not None and o.max_down_5m is not None],
            "both": [min(o.max_up_5m, o.max_down_5m) >= t for o in samples if o.max_up_5m is not None and o.max_down_5m is not None],
        }
        row = {}
        for k, h in hits.items():
            v = (sum(h) + 0.5) / (len(h) + 1) * 100 if h else None
            if v is not None:
                v = min(round(v, 1), prev[k])  # 値幅が大きいほど確率は単調非増加
                prev[k] = v
            row[k] = v
        if None not in (row["either"], row["up"], row["down"]):
            row["either"] = min(max(row["either"], row["up"], row["down"]), row["up"] + row["down"])
        if None not in (row["both"], row["up"], row["down"]):
            row["both"] = min(row["both"], row["up"], row["down"])
        reach[str(t)] = row

    def med(name):
        a = col(name)
        return round(float(np.median(a)), 2) if len(a) else None

    rev = [o.reversed_ for o in samples if o.reversed_ is not None]
    out = {
        "prob_up": p_round["up"], "prob_down": p_round["down"], "prob_flat": p_round["flat"],
        "d1": med("d1"), "d5": med("d5"), "d15": med("d15"), "d30": med("d30"), "d60": med("d60"),
        "max_up_5m": med("max_up_5m"), "max_down_5m": med("max_down_5m"),
        "max_excursion_5m": round(float(np.median(exc)), 2) if len(exc) else None,
        "max_excursion_5m_low": round(float(np.percentile(exc, 25)), 2) if len(exc) else None,
        "max_excursion_5m_high": round(float(np.percentile(exc, 75)), 2) if len(exc) else None,
        "range_5m": med("range_5m"), "range_30m": med("range_30m"), "range_60m": med("range_60m"),
        "reach_probs": reach,
        "reversal_prob": round((sum(rev) + 0.5) / (len(rev) + 1) * 100, 1) if rev else None,
        "rationale": (
            f"同カテゴリの検証済み過去イベント{n}件の統計（中央値・四分位・平滑化頻度）。"
            f"横ばい判定は±{settings.flat_band_usd}ドル。市場状況やサプライズは考慮しないベースライン。"
        ),
    }
    # 入れ子の時間幅でレンジが逆転しないよう補正
    if out["range_5m"] is not None and out["range_30m"] is not None:
        out["range_30m"] = max(out["range_30m"], out["range_5m"])
    if out["range_30m"] is not None and out["range_60m"] is not None:
        out["range_60m"] = max(out["range_60m"], out["range_30m"])
    if out["max_excursion_5m"] is not None and out["max_up_5m"] is not None and out["max_down_5m"] is not None:
        out["max_excursion_5m"] = max(out["max_excursion_5m"], out["max_up_5m"], out["max_down_5m"])
        out["max_excursion_5m_high"] = max(out["max_excursion_5m_high"], out["max_excursion_5m"])
        out["max_excursion_5m_low"] = min(out["max_excursion_5m_low"], out["max_excursion_5m"])
    out["n_samples"] = n
    return out
