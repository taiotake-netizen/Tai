"""テスト専用の合成データ生成（アプリの初期データには使用しない）。"""
from datetime import datetime, timedelta


def synthetic_bars_csv(release_at: datetime, base: float, path: list[tuple[float, float, float, float]],
                       before: int = 30, after: int = 61) -> bytes:
    """release_at の before 分前から after 分後までの1分足CSV。path[i] は発表後 i 分目のバー(o,h,l,c)。"""
    lines = ["time,open,high,low,close,Volume"]
    t0 = release_at - timedelta(minutes=before)
    for i in range(before + after):
        ts = t0 + timedelta(minutes=i)
        k = i - before
        if 0 <= k < len(path):
            o, h, l, c = path[k]
        else:
            last = path[-1][3] if k >= len(path) else base
            o = h = l = c = last
        lines.append(f"{int(ts.timestamp())},{o},{h},{l},{c},100")
    return "\n".join(lines).encode()
