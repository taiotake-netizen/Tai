"""過去2年分（2024年11月〜2026年9月）の FOMC・CPI・雇用統計・GDP速報値（2026年10月27日調査）。

目的: Dukascopy等の1分足を取り込み、発表時の値動きの統計（値幅分布・反転率・サプライズ反応）を作るための
発表日時の登録。時刻はET（米国東部時間）で記述し、夏時間は自動変換する。

確認方針（データの信頼性ルール）:
- confirmed=True: 発表機関の資料（BLSのアーカイブURL・BEAのリリース・FRB資料）か、複数の主要報道で日付を確認できたもの。
  False は通常日程からの推定で、要確認。
- 実績値は検索で確認できたものだけを登録し、確認できない月は空欄（推測で埋めない）。
  verified=True は発表機関の資料で確認、False は報道値（要照合）。
- 2025年10〜11月の政府閉鎖で、2025年10月分CPI・雇用統計の家計調査は未公表、
  7-9月期GDPは速報値と改定値を統合した「初回推計」（12/23）に置き換え。
- GDPは速報値（初回推計）のみ。改定値・確定値は値動きが小さいため履歴には含めない。
"""

REV = 1

BLS_CPI_ARCH = "https://www.bls.gov/news.release/archives/cpi_{}.htm"
BLS_EMP_ARCH = "https://www.bls.gov/news.release/archives/empsit_{}.htm"
FED_CAL = {"name": "FRB FOMC日程", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}
BEA_SCHED = {"name": "BEA 発表スケジュール", "url": "https://www.bea.gov/news/schedule"}

# (会合終了日ET, 前回の上限, 決定後の上限, 決定の確認, 日付の確認, 備考)
FOMC = [
    ("2024-11-07", 5.00, 4.75, True, True, "25bp利下げ（4.50-4.75%）。米大統領選の2日後。"),
    ("2024-12-18", 4.75, 4.50, True, True, "25bp利下げ（4.25-4.50%）。Hammack総裁が反対。"),
    ("2025-01-29", 4.50, 4.50, False, False, "据え置き（4.25-4.50%）。"),
    ("2025-03-19", 4.50, 4.50, False, False, "据え置き。"),
    ("2025-05-07", 4.50, 4.50, False, False, "据え置き。"),
    ("2025-06-18", 4.50, 4.50, False, False, "据え置き。"),
    ("2025-07-30", 4.50, 4.50, True, True, "据え置き。2名が利下げを主張して反対。同日8:30にGDP速報値。"),
    ("2025-09-17", 4.50, 4.25, True, True, "25bp利下げ（4.00-4.25%）。Miran理事が反対。"),
    ("2025-10-29", 4.25, 4.00, True, True, "25bp利下げ（3.75-4.00%）。12/1でのQT終了を決定。"),
    ("2025-12-10", 4.00, 3.75, True, True, "25bp利下げ（3.50-3.75%）。反対3名。"),
    ("2026-01-28", 3.75, 3.75, True, True, "据え置き。Miran・Waller理事が利下げを主張。"),
    ("2026-03-18", 3.75, 3.75, True, True, "据え置き（11対1）。"),
    ("2026-04-29", 3.75, 3.75, True, True, "据え置き（8対4）。"),
    ("2026-06-17", 3.75, 3.75, True, True, "据え置き（12対0）。Warsh議長の初会合、ドットプロットが利上げ方向に。"),
    ("2026-07-29", 3.75, 3.75, True, True, "据え置き（9対3、3名が利上げを主張）。"),
]

# (発表日ET, 対象月, 日付の確認(BLSアーカイブ)/None, {code: (値, verified)}, 備考)
CPI = [
    ("2024-11-13", "2024年10月", "11132024",
     {"CPI_MOM": (0.2, False), "CPI_YOY": (2.6, False), "CORE_CPI_MOM": (0.3, False), "CORE_CPI_YOY": (3.3, False)},
     "報道値（CNBC）。市場予想と一致。"),
    ("2024-12-11", "2024年11月", None, {}, ""),
    ("2025-01-15", "2024年12月", "01152025", {"CPI_MOM": (0.4, True), "CPI_YOY": (2.9, True)}, ""),
    ("2025-02-12", "2025年1月", "02122025", {"CPI_YOY": (3.0, True)}, ""),
    ("2025-03-12", "2025年2月", "03122025", {"CPI_YOY": (2.8, True)}, ""),
    ("2025-04-10", "2025年3月", None, {}, ""),
    ("2025-05-13", "2025年4月", "05132025", {"CPI_YOY": (2.3, True), "CORE_CPI_YOY": (2.8, True)}, ""),
    ("2025-06-11", "2025年5月", "06112025", {}, ""),
    ("2025-07-15", "2025年6月", "07152025", {"CPI_YOY": (2.7, True)}, ""),
    ("2025-08-12", "2025年7月", "08122025", {}, ""),
    ("2025-09-11", "2025年8月", "09112025", {}, ""),
    ("2025-10-24", "2025年9月", "10242025", {"CORE_CPI_YOY": (3.0, True)}, "政府閉鎖のため延期して発表。"),
    ("2025-12-18", "2025年11月", "12182025", {"CPI_YOY": (2.7, True)},
     "2025年10月分は政府閉鎖で未調査のため未公表。11月分は前月比なし。"),
    ("2026-01-13", "2025年12月", "01132026", {"CPI_MOM": (0.3, True), "CPI_YOY": (2.7, True)}, ""),
    ("2026-02-13", "2026年1月", "02132026", {"CPI_MOM": (0.2, True), "CPI_YOY": (2.4, True)}, "当初予定2/11から延期。"),
    ("2026-03-11", "2026年2月", "03112026", {"CPI_MOM": (0.3, True), "CPI_YOY": (2.4, True)}, ""),
    ("2026-04-10", "2026年3月", "04102026", {"CPI_MOM": (0.9, True), "CPI_YOY": (3.3, False)}, ""),
    ("2026-05-12", "2026年4月", "05122026", {"CPI_MOM": (0.6, True), "CPI_YOY": (3.8, True)}, ""),
    ("2026-06-10", "2026年5月", "06102026", {"CPI_MOM": (0.5, True), "CPI_YOY": (4.2, True)}, ""),
    ("2026-07-14", "2026年6月", "07142026", {"CPI_MOM": (-0.4, True), "CPI_YOY": (3.5, True)},
     "前月比−0.4%は2020年4月以来の大幅低下（エネルギー主導）。"),
    ("2026-08-12", "2026年7月", "08122026", {"CPI_MOM": (0.1, True), "CPI_YOY": (3.4, True)}, ""),
    ("2026-09-11", "2026年8月", None, {"CPI_MOM": (0.4, True), "CPI_YOY": (3.4, True)},
     "発表日は第三者カレンダー複数で一致（BLSアーカイブ未確認）。"),
]

# (発表日ET, 対象月, BLSアーカイブ日付/None, 日付確認, {code: (値, verified)}, {code: 市場予想}, 備考)
NFP = [
    ("2024-11-01", "2024年10月", None, True, {"NFP": (1.2, False), "UNRATE": (4.1, False)}, {},
     "ハリケーンとストライキで大幅減速（報道値）。"),
    ("2024-12-06", "2024年11月", None, False, {}, {}, ""),
    ("2025-01-10", "2024年12月", "01102025", True, {}, {}, ""),
    ("2025-02-07", "2025年1月", "02072025", True, {}, {}, ""),
    ("2025-03-07", "2025年2月", "03072025", True, {}, {}, ""),
    ("2025-04-04", "2025年3月", "04042025", True, {"NFP": (22.8, False), "UNRATE": (4.2, False)}, {}, ""),
    ("2025-05-02", "2025年4月", "05022025", True, {}, {}, ""),
    ("2025-06-06", "2025年5月", "06062025", True, {"NFP": (13.9, True), "UNRATE": (4.2, True)}, {}, ""),
    ("2025-07-03", "2025年6月", "07032025", True, {}, {}, "独立記念日の前日（木曜）に発表。"),
    ("2025-08-01", "2025年7月", "08012025", True, {"NFP": (7.3, True), "UNRATE": (4.2, True)}, {}, ""),
    ("2025-09-05", "2025年8月", "09052025", True, {"NFP": (2.2, False), "UNRATE": (4.3, False)}, {"NFP": 7.5}, ""),
    ("2025-11-20", "2025年9月", "11202025", True, {}, {}, "政府閉鎖のため延期して発表。"),
    ("2025-12-16", "2025年11月", "12162025", True, {}, {}, "10月分（家計調査は未公表）と11月分をまとめて発表。"),
    ("2026-01-09", "2025年12月", "01092026", True, {"NFP": (5.0, False), "UNRATE": (4.4, False)}, {}, ""),
    ("2026-02-11", "2026年1月", "02112026", True, {}, {}, "年次ベンチマーク改定を含む。水曜発表。"),
    ("2026-03-06", "2026年2月", "03062026", True, {"NFP": (-9.2, False), "UNRATE": (4.4, False)}, {}, ""),
    ("2026-04-03", "2026年3月", "04032026", True, {}, {}, ""),
    ("2026-05-08", "2026年4月", "05082026", True, {}, {}, ""),
    ("2026-06-05", "2026年5月", "06052026", True, {"NFP": (17.2, True), "UNRATE": (4.3, True)}, {}, ""),
    ("2026-07-02", "2026年6月", "07022026", True, {"NFP": (5.7, True), "UNRATE": (4.2, True)}, {}, "木曜発表。"),
    ("2026-08-07", "2026年7月", "08072026", True, {"NFP": (-2.3, False), "UNRATE": (4.1, False)},
     {"NFP": 8.3, "UNRATE": 4.2}, ""),
    ("2026-09-04", "2026年8月", "09042026", True, {"NFP": (16.2, True), "UNRATE": (4.1, True)}, {"NFP": 5.3},
     "後に13.3万人へ下方改定。"),
]

# (発表日ET, 対象四半期, 日付確認, 値, verified, 出所URL, 備考)
GDP = [
    ("2025-01-30", "2024年10-12月期", False, None, False, None, ""),
    ("2025-04-30", "2025年1-3月期", False, None, False, None, ""),
    ("2025-07-30", "2025年4-6月期", False, None, False, None, "同日14:00にFOMC。"),
    ("2025-12-23", "2025年7-9月期", True, 4.3, True, "https://bea.gov/sites/default/files/2025-12/gdp3q25-ini.pdf",
     "政府閉鎖のため速報値と改定値を統合した初回推計として発表。"),
    ("2026-02-20", "2025年10-12月期", True, None, False,
     "https://www.bea.gov/news/2026/gdp-advance-estimate-4th-quarter-and-year-2025", "当初予定1/29から延期。"),
    ("2026-04-30", "2026年1-3月期", True, 2.0, True, "https://www.bea.gov/sites/default/files/2026-04/gdp1q26-adv.pdf", ""),
    ("2026-07-30", "2026年4-6月期", True, 1.5, True, "https://www.bea.gov/sites/default/files/2026-07/gdp2q26-adv.pdf", ""),
]

CPI_IND = [("CPI_MOM", "CPI（前月比）", "%"), ("CPI_YOY", "CPI（前年比）", "%"),
           ("CORE_CPI_MOM", "コアCPI（前月比）", "%"), ("CORE_CPI_YOY", "コアCPI（前年比）", "%")]
NFP_IND = [("NFP", "非農業部門雇用者数", "万人"), ("UNRATE", "失業率", "%")]


def build_events() -> list[dict]:
    out = []
    for d, prev, act, verified, conf, note in FOMC:
        y, m, _ = d.split("-")
        out.append({
            "slug": f"hist-fomc-{d.replace('-', '')}", "title": f"FOMC 政策金利・声明（{int(y)}年{int(m)}月）",
            "category": "FOMC", "release_et": f"{d}T14:00", "confirmed": conf, "importance": 10,
            "sources": [FED_CAL], "notes": note + "　議長会見は14:30 ET。",
            "indicators": [{"code": "FED_FUNDS_UPPER", "name": "FF金利誘導目標（上限）", "unit": "%", "previous": prev,
                            "actual": act, "actual_verified": verified,
                            "actual_source": "FRB声明（報道・議事要旨で確認）" if verified else "要照合（FRB声明）"}],
        })
    for d, month, arch, vals, note in CPI:
        src = [{"name": f"BLS CPI {month}分リリース", "url": BLS_CPI_ARCH.format(arch)}] if arch else []
        out.append({
            "slug": f"hist-cpi-{d.replace('-', '')}", "title": f"米CPI（{month}分）", "category": "CPI",
            "release_et": f"{d}T08:30", "confirmed": arch is not None, "importance": 10, "sources": src,
            "notes": note or None,
            "indicators": [{"code": c, "name": n, "unit": u,
                            **({"actual": vals[c][0], "actual_verified": vals[c][1],
                                "actual_source": f"BLS CPI {month}分" if vals[c][1] else "報道値（要照合）"} if c in vals else {})}
                           for c, n, u in CPI_IND],
        })
    for d, month, arch, conf, vals, cons, note in NFP:
        src = [{"name": f"BLS 雇用統計 {month}分リリース", "url": BLS_EMP_ARCH.format(arch)}] if arch else []
        out.append({
            "slug": f"hist-nfp-{d.replace('-', '')}", "title": f"米雇用統計 NFP（{month}分）", "category": "NFP",
            "release_et": f"{d}T08:30", "confirmed": conf, "importance": 10, "sources": src, "notes": note or None,
            "indicators": [{"code": c, "name": n, "unit": u,
                            **({"consensus": cons[c], "consensus_source": "Dow Jones調査（報道）"} if c in cons else {}),
                            **({"actual": vals[c][0], "actual_verified": vals[c][1],
                                "actual_source": f"BLS 雇用統計 {month}分" if vals[c][1] else "報道値（要照合）"} if c in vals else {})}
                           for c, n, u in NFP_IND],
        })
    for d, q, conf, val, verified, url, note in GDP:
        out.append({
            "slug": f"hist-gdp-{d.replace('-', '')}", "title": f"米GDP速報値（{q}）", "category": "GDP",
            "release_et": f"{d}T08:30", "confirmed": conf, "importance": 9,
            "sources": [{"name": f"BEA GDP {q}", "url": url}] if url else [BEA_SCHED], "notes": note or None,
            "indicators": [{"code": "GDP_QOQ_ANN", "name": "GDP速報値（前期比年率）", "unit": "%",
                            **({"actual": val, "actual_verified": verified, "actual_source": f"BEA GDP {q}"} if val is not None else {})}],
        })
    return out
