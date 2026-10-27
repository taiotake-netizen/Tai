"""予測バージョンと実績の比較。

比較は「同じ定義・同じ時間幅」の項目同士でのみ行う。時間幅が不明な記録同士の比較は
comparable=False として別扱いにする。
"""

from ..config import HORIZONS_MIN, REACH_THRESHOLDS, settings
from ..models import Event, ForecastVersion, Outcome

DIRS = ("up", "down", "flat")


def _err(pred, actual):
    if pred is None or actual is None:
        return None
    return {"pred": pred, "actual": actual, "error": round(pred - actual, 4), "abs_error": round(abs(pred - actual), 4)}


def _reach_hits(o: Outcome, t: float) -> dict:
    up = None if o.max_up_5m is None else o.max_up_5m >= t
    down = None if o.max_down_5m is None else o.max_down_5m >= t
    if up is True or down is True:
        either = True
    elif up is False and down is False:
        either = False
    else:
        either = None
    if up is False or down is False:
        both = False
    elif up is True and down is True:
        both = True
    else:
        both = None
    return {"up": up, "down": down, "either": either, "both": both}


def evaluate(event: Event, f: ForecastVersion, o: Outcome) -> tuple[dict, list[str]]:
    m: dict = {}
    notes: list[str] = []

    # --- 方向
    # 正答率に使うのは5分後終着地の方向のみ（主評価）。他の時間幅は direction_by_horizon に別記録し、
    # 時間幅不明の観測方向は direction_observed として参考扱い（正答率に含めない）。
    pred_dir = f.dominant_direction
    band = settings.flat_band_usd
    if pred_dir:
        by_h = {}
        for n in HORIZONS_MIN:
            v = getattr(o, f"d{n}")
            if v is None:
                continue
            actual = "up" if v > band else "down" if v < -band else "flat"
            by_h[str(n)] = {"pred": pred_dir, "actual": actual, "hit": pred_dir == actual}
        if by_h:
            m["direction_by_horizon"] = by_h
        if o.direction_5m:
            m["direction"] = {"pred": pred_dir, "actual": o.direction_5m, "hit": pred_dir == o.direction_5m,
                              "basis": "5分後終着地"}
        elif o.observed_direction:
            m["direction_observed"] = {"pred": pred_dir, "actual": o.observed_direction,
                                       "hit": pred_dir == o.observed_direction, "basis": "観測方向（時間幅不明）",
                                       "comparable": False}
            notes.append("実際の方向は時間幅が不明な記録しかないため参考比較のみとし、方向正答率には含めません。")
    if o.direction_5m and None not in (f.prob_up, f.prob_down, f.prob_flat):
        p = {"up": f.prob_up / 100, "down": f.prob_down / 100, "flat": f.prob_flat / 100}
        m["brier_direction"] = round(sum((p[d] - (1.0 if d == o.direction_5m else 0.0)) ** 2 for d in DIRS), 4)
        m["prob_assigned_to_actual"] = round(p[o.direction_5m] * 100, 1)

    # --- 終着地（同じ時間幅のみ）
    for n in HORIZONS_MIN:
        e = _err(getattr(f, f"d{n}"), getattr(o, f"d{n}"))
        if e:
            m[f"d{n}"] = e
    # 時間幅が明示されていない一点予想 vs 時間幅不明の観測
    if f.headline_move is not None and o.headline_move is not None:
        e = _err(f.headline_move, o.headline_move)
        e["comparable"] = False
        m["headline_move"] = e
        notes.append("時間幅未指定の一点予想と時間幅不明の観測値動きの差です。時間幅が一致した場合のみ誤差として扱えます。")

    # --- 最大変動幅（5分間）
    for k in ("max_up_5m", "max_down_5m", "max_excursion_5m", "range_5m", "range_30m", "range_60m"):
        e = _err(getattr(f, k), getattr(o, k))
        if e:
            m[k] = e
    if o.max_excursion_5m is not None and f.max_excursion_5m_low is not None and f.max_excursion_5m_high is not None:
        m["max_excursion_5m_in_interval"] = f.max_excursion_5m_low <= o.max_excursion_5m <= f.max_excursion_5m_high
    if "max_excursion_5m" in m:
        err = m["max_excursion_5m"]["error"]
        m["excursion_bias"] = "過小評価" if err < 0 else "過大評価" if err > 0 else "一致"

    # --- 到達確率 Brier
    reach_rows = []
    for t in REACH_THRESHOLDS:
        probs = (f.reach_probs or {}).get(str(t)) or {}
        hits = _reach_hits(o, t)
        for kind, p in probs.items():
            if p is None or hits.get(kind) is None:
                continue
            y = 1.0 if hits[kind] else 0.0
            reach_rows.append({"threshold": t, "kind": kind, "prob": p, "hit": hits[kind],
                               "brier": round((p / 100 - y) ** 2, 4)})
    if reach_rows:
        m["reach"] = reach_rows
        m["brier_reach_mean"] = round(sum(r["brier"] for r in reach_rows) / len(reach_rows), 4)

    # --- 初動・反転
    if f.initial_direction and o.initial_direction:
        m["initial_direction"] = {"pred": f.initial_direction, "actual": o.initial_direction,
                                  "hit": f.initial_direction == o.initial_direction}
    e = _err(f.initial_move, o.initial_move)
    if e:
        m["initial_move"] = e
    if f.reversal_prob is not None and o.reversed_ is not None:
        y = 1.0 if o.reversed_ else 0.0
        m["reversal"] = {"prob": f.reversal_prob, "reversed": o.reversed_,
                         "brier": round((f.reversal_prob / 100 - y) ** 2, 4)}

    # --- 指標数値の予測（市場の反応予測とは別評価）
    ind_by_code = {i.code: i for i in event.indicators}
    ind_rows = []
    for fc in f.indicator_forecasts or []:
        ind = ind_by_code.get(fc.get("code"))
        if ind is None or ind.actual is None or fc.get("point") is None:
            continue
        row = {"code": ind.code, "name": ind.name, "unit": ind.unit, "pred": fc["point"],
               "actual": ind.actual, "error": round(fc["point"] - ind.actual, 4),
               "abs_error": round(abs(fc["point"] - ind.actual), 4), "actual_verified": ind.actual_verified}
        if ind.consensus is not None:
            row["consensus"] = ind.consensus
            row["surprise_vs_consensus"] = round(ind.actual - ind.consensus, 4)
            row["beat_consensus"] = abs(fc["point"] - ind.actual) < abs(ind.consensus - ind.actual)
        ind_rows.append(row)
    if ind_rows:
        m["indicators"] = ind_rows

    # --- 条件付きシナリオ（「この数値ならこう動く」の評価）
    sc_rows = []
    for sc in f.scenarios or []:
        code = sc.get("indicator_code")
        ind = ind_by_code.get(code) if code else None
        if ind is None or ind.actual is None or sc.get("min") is None or sc.get("max") is None:
            continue
        triggered = sc["min"] <= ind.actual <= sc["max"]
        row = {"label": sc.get("label"), "triggered": triggered, "indicator_actual": ind.actual}
        if triggered:
            window = sc.get("window") or "unspecified"
            obs = getattr(o, f"d{window[:-1]}", None) if window.endswith("m") and window[:-1].isdigit() else None
            comparable = obs is not None
            if obs is None:
                obs = o.headline_move
            if obs is not None and sc.get("reaction_min") is not None and sc.get("reaction_max") is not None:
                row.update(observed=obs, comparable=comparable,
                           reaction_in_range=sc["reaction_min"] <= obs <= sc["reaction_max"])
        sc_rows.append(row)
    if sc_rows:
        m["scenarios"] = sc_rows

    if not o.verified:
        notes.append("実績が未検証（会話由来など）のため、この評価は暫定です。学習用の確定データには使用しません。")
    return m, notes
