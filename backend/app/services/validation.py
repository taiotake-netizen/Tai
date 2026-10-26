"""予測の整合性チェック。

errors があれば保存を拒否し、warnings は保存した上でバージョンに記録する。
"""

from datetime import datetime, timezone

from ..config import REACH_THRESHOLDS

KINDS = ("up", "down", "either", "both")
EPS = 0.51


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def validate_forecast(
    data: dict, release_at: datetime | None, now: datetime
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    # --- 情報の時点: 発表後の情報を事前予測に混入させない
    as_of = _aware(data.get("as_of")) or now
    release_at = _aware(release_at)
    if release_at is not None and as_of >= release_at:
        errors.append("予測時点が発表時刻以降です。事前予測として保存できません。")
    for n in data.get("news_used") or []:
        pub = n.get("published_at")
        if isinstance(pub, str):
            try:
                pub = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"ニュースの公開日時を解釈できません: {n.get('title')}")
                continue
        pub = _aware(pub)
        if pub is not None and pub > as_of:
            errors.append(f"予測時点より後に公開されたニュースは使用できません: {n.get('title')}")

    # --- 方向確率
    probs = {k: data.get(f"prob_{k}") for k in ("up", "down", "flat")}
    for k, v in probs.items():
        if v is not None and not (0 <= v <= 100):
            errors.append(f"prob_{k} は0〜100で指定してください。")
    given = [v for v in probs.values() if v is not None]
    if len(given) == 3 and abs(sum(given) - 100) > EPS:
        errors.append(f"方向確率の合計が100%ではありません（{sum(given):.1f}%）。")
    elif 0 < len(given) < 3:
        if sum(given) > 100 + EPS:
            errors.append("方向確率の合計が100%を超えています。")
        warnings.append("方向確率の一部が未記録です。")

    # --- 値幅（絶対値で扱う項目は負にできない）
    for k in ("max_up_5m", "max_down_5m", "max_excursion_5m", "max_excursion_5m_low",
              "max_excursion_5m_high", "range_5m", "range_30m", "range_60m", "reversal_size"):
        v = data.get(k)
        if v is not None and v < 0:
            errors.append(f"{k} は0以上の値幅で指定してください。")

    lo, pt, hi = (data.get("max_excursion_5m_low"), data.get("max_excursion_5m"),
                  data.get("max_excursion_5m_high"))
    if lo is not None and hi is not None and lo > hi:
        errors.append("最大変動幅の予測区間の下限が上限を上回っています。")
    if pt is not None and lo is not None and pt < lo:
        errors.append("最大変動幅の一点予想が予測区間の下限を下回っています。")
    if pt is not None and hi is not None and pt > hi:
        errors.append("最大変動幅の一点予想が予測区間の上限を上回っています。")

    mu, md = data.get("max_up_5m"), data.get("max_down_5m")
    if pt is not None and mu is not None and md is not None and abs(pt - max(mu, md)) > EPS:
        warnings.append("最大到達幅が最大上昇幅・最大下落幅の大きい方と一致していません。")

    r5, r30, r60 = data.get("range_5m"), data.get("range_30m"), data.get("range_60m")
    if r5 is not None and r30 is not None and r30 < r5:
        errors.append("30分レンジが5分レンジより小さくなっています（時間幅が入れ子のため不可能）。")
    if r30 is not None and r60 is not None and r60 < r30:
        errors.append("60分レンジが30分レンジより小さくなっています（時間幅が入れ子のため不可能）。")
    if r5 is not None and pt is not None and r5 < pt:
        warnings.append("5分高値安値レンジが最大到達幅より小さくなっています。")

    for k in ("reversal_prob", "confidence"):
        v = data.get(k)
        if v is not None and not (0 <= v <= 100):
            errors.append(f"{k} は0〜100で指定してください。")
    imp = data.get("importance")
    if imp is not None and not (1 <= imp <= 10):
        errors.append("重要度は1〜10で指定してください。")

    # --- 到達確率
    reach = data.get("reach_probs") or {}
    for key in reach:
        if int(float(key)) not in REACH_THRESHOLDS:
            errors.append(f"未対応の値幅しきい値です: {key}")
    for kind in KINDS:
        seq = []
        for t in REACH_THRESHOLDS:
            v = (reach.get(str(t)) or {}).get(kind)
            if v is None:
                continue
            if not (0 <= v <= 100):
                errors.append(f"{t}ドル {kind} の到達確率が0〜100の範囲外です。")
            seq.append((t, v))
        for (t1, v1), (t2, v2) in zip(seq, seq[1:]):
            if v2 > v1 + 1e-9:
                errors.append(
                    f"{kind}: {t2}ドルの到達確率({v2}%)が{t1}ドル({v1}%)を上回っています。"
                )
    for t in REACH_THRESHOLDS:
        p = reach.get(str(t)) or {}
        up, down, either, both = (p.get(k) for k in KINDS)
        if either is not None:
            for name, v in (("上方向", up), ("下方向", down)):
                if v is not None and either + 1e-9 < v:
                    errors.append(f"{t}ドル: 上下どちらかの確率が{name}の確率を下回っています。")
            if up is not None and down is not None and either > up + down + 1e-9:
                errors.append(f"{t}ドル: 上下どちらかの確率が上方向＋下方向を上回っています。")
        if both is not None:
            for v in (up, down):
                if v is not None and both > v + 1e-9:
                    errors.append(f"{t}ドル: 上下両方向の確率が片方向の確率を上回っています。")
        if None not in (up, down, either, both) and abs(up + down - both - either) > 1.0:
            warnings.append(f"{t}ドル: 上＋下−両方 ≠ どちらか（包除原理と不整合）。")

    return errors, warnings


def derive_dominant(data: dict) -> str | None:
    if data.get("dominant_direction"):
        return data["dominant_direction"]
    probs = {k: data.get(f"prob_{k}") for k in ("up", "down", "flat")}
    if all(v is not None for v in probs.values()):
        return max(probs, key=lambda k: probs[k])
    return None
