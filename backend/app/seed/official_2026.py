"""公式発表スケジュールと公式実績（2026年10月26日時点の調査結果）。

- 時刻は米国東部時間(ET)で記述し、America/New_York で変換する（2026年11月1日に夏時間終了）。
- confirmed=True は発表機関（FRB/BLS/BEA/Census/ISM/ADP）の公表スケジュールで確認できたもの。
  第三者カレンダーや通常パターンのみで確認したものは False とし、source に明記する。
- 実績値の verified=True は、発表機関の公表値と一致することを確認できたもの。
- REV を上げると、既存DBのイベントにも差分が適用される（予測バージョンは変更しない）。
- REV 3: GDP 4-6月期確定値が9/30発表であることを確認（備考更新）。
- REV 2: 対象を FOMC・GDP・CPI・雇用統計 に絞った（それ以外の今後の予定は REMOVED_SLUGS で削除）。
  発表済みの過去イベント（会話由来の研究記録）は削除しない。
"""

REV = 3

# スケジュール管理の対象（重要度の低い指標は扱わない）
TRACKED_CATEGORIES = {"FOMC", "GDP", "CPI", "NFP"}

FED = {"name": "FRB FOMC日程", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"}
FED_NOV = {"name": "FRB 2026年11月カレンダー", "url": "https://www.federalreserve.gov/newsevents/2026-november.htm"}
BLS = {"name": "BLS 2026年発表スケジュール", "url": "https://www.bls.gov/schedule/news_release/current_year.asp"}
BLS_CPI = {"name": "BLS CPI発表スケジュール", "url": "https://www.bls.gov/schedule/news_release/cpi.htm"}
BLS_ECI = {"name": "BLS ECI発表スケジュール", "url": "https://www.bls.gov/schedule/news_release/eci.htm"}
BLS_JOLTS = {"name": "BLS JOLTS 2026年8月分リリース（次回日程記載）", "url": "https://www.bls.gov/news.release/jolts.htm"}
BLS_EMP = {"name": "BLS 雇用統計 2026年9月分", "url": "https://www.bls.gov/news.release/empsit.nr0.htm"}
BEA = {"name": "BEA 発表スケジュール", "url": "https://www.bea.gov/news/schedule"}
CENSUS_RETAIL = {"name": "Census 小売売上高スケジュール", "url": "https://www.census.gov/retail/release_schedule.html"}
CENSUS_DG = {"name": "Census 耐久財受注（次回日程記載）", "url": "https://www.census.gov/manufacturing/m3/adv/pdf/durgd.pdf"}
CENSUS_NRS = {"name": "Census 新築住宅販売 2026年8月分（次回日程記載）", "url": "https://www.census.gov/construction/nrs/pdf/newressales.pdf"}
CENSUS_SOC = {"name": "Census 建設統計スケジュール", "url": "https://www.census.gov/construction/soc/schedule.html"}
ISM = {"name": "ISM 発表カレンダー", "url": "https://www.ismworld.org/supply-management-news-and-reports/reports/rob-report-calendar/"}
ADP = {"name": "ADP 発表カレンダー", "url": "https://adpemploymentreport.com/"}
CB_PATTERN = {"name": "第三者カレンダー（Conference Boardは毎月最終火曜10:00 ET）", "url": "https://www.financecalendar.com/?p=1453"}
CLAIMS_PATTERN = {"name": "米労働省は通常毎週木曜8:30 ET（祝日週は前倒し、第三者カレンダーで確認）", "url": "https://www.dol.gov/ui/data.pdf"}
THIRD = {"name": "第三者カレンダー fedratecalc.com（公式未確認）", "url": "https://fedratecalc.com/us-economic-calendar/"}

FFR = {"code": "FED_FUNDS_UPPER", "name": "FF金利誘導目標（上限）", "unit": "%"}
CLAIMS = {"code": "INITIAL_CLAIMS", "name": "新規失業保険申請件数", "unit": "万件"}

# ---------------------------------------------------------------- 既存（会話由来）イベントの更新
UPDATES = {
    "fomc-2026-09": {
        "release_et": "2026-09-16T14:00", "confirmed": True, "sources": [FED],
        "notes": "FOMC 9月15-16日会合。声明は14:00 ET（日本時間9/17 03:00）、議長会見14:30 ET。25bp利上げ（3.75-4.00%、12対0）。",
        "indicators": [
            {**FFR, "previous": 3.75, "actual": 4.00, "actual_verified": True,
             "actual_source": "FRB声明 2026-09-16 https://www.federalreserve.gov/monetarypolicy/files/monetary20260916a1.pdf"},
        ],
    },
    "adp-2026-09-30": {
        "release_et": "2026-09-30T08:15", "confirmed": True, "sources": [ADP],
        "indicators": [
            {"code": "ADP", "consensus": 6.8, "consensus_source": "Dow Jones調査（報道）", "previous_revised": 3.6,
             "actual": 9.0, "actual_verified": True,
             "actual_source": "ADP National Employment Report 2026-09-30（8月分は3.8万→3.6万人に改定）"},
        ],
    },
    "pce-2026-09-30": {
        "release_et": "2026-09-30T08:30", "confirmed": True, "sources": [BEA],
        "notes": "BEA 個人所得・支出（8月分）。同日に国民経済計算の年次改定。コアPCEの値は第三者集計のみで、資料により3.0%/3.4%と食い違うため未照合のまま。",
        "indicators": [
            {"code": "PERSONAL_SPENDING", "name": "個人消費支出（名目・前月比）", "actual": 0.9, "actual_verified": True,
             "actual_source": "BEA Personal Income and Outlays, August 2026（PCE +1,908億ドル, +0.9%）"},
            {"code": "GDP_RELATED", "name": "GDP（4-6月期確定値・前期比年率）", "actual": 2.2, "actual_verified": True,
             "actual_source": "BEA GDP (Third Estimate), 2nd Quarter 2026",
             "notes": "会話記録の「GDP関連+2.2%」はQ2確定値と一致。BEAによると確定値も9月30日発表（PCEと同日）。"},
        ],
    },
    "nfp-2026-10": {
        "release_et": "2026-10-02T08:30", "confirmed": True, "sources": [BLS_EMP],
        "indicators": [
            {"code": "NFP", "consensus": 8.4, "consensus_source": "Dow Jones調査（CNBC報道）", "actual": 2.9,
             "actual_verified": True, "actual_source": "BLS Employment Situation September 2026",
             "notes": "8月分は13.3万人に改定（BLS）。7月は−1.0万人に改定。"},
            {"code": "UNRATE", "previous": 4.1, "actual": 4.2, "actual_verified": True,
             "actual_source": "BLS Employment Situation September 2026"},
            {"code": "AHE_MOM", "_delete_if_empty": True},
            {"code": "AHE_YOY", "name": "平均時給（前年比）", "unit": "%", "actual": 3.0, "actual_verified": False,
             "actual_source": "第三者集計（SimianX）。BLS原資料で要照合"},
        ],
    },
    "fomc-minutes-2026-10": {
        "release_et": "2026-10-07T14:00", "confirmed": True, "sources": [FED],
        "date_label": "2026年10月7日 14:00 ET（日本時間10月8日 03:00）",
        "notes": "9月15-16日会合の議事要旨。多くの参加者が年内の追加利上げを適切と判断。",
    },
    "cpi-2026-10": {
        "release_et": "2026-10-14T08:30", "confirmed": True, "sources": [BLS_CPI],
        "indicators": [
            {"code": "CPI_MOM", "previous": 0.4, "consensus": 0.6, "consensus_source": "Dow Jones調査（CNBC）", "actual": 0.6,
             "actual_verified": True, "actual_source": "BLS CPI September 2026"},
            {"code": "CPI_YOY", "previous": 3.4, "consensus": 3.6, "consensus_source": "Dow Jones調査（CNBC）", "actual": 3.7,
             "actual_verified": True, "actual_source": "BLS CPI September 2026"},
            {"code": "CORE_CPI_MOM", "previous": 0.3, "consensus": 0.2, "consensus_source": "Dow Jones調査（CNBC）", "actual": 0.3,
             "actual_verified": True, "actual_source": "BLS CPI September 2026"},
            {"code": "CORE_CPI_YOY", "previous": 2.4, "consensus": 2.5, "consensus_source": "Dow Jones調査（CNBC）", "actual": 2.6,
             "actual_verified": True, "actual_source": "BLS CPI September 2026"},
        ],
    },
    "ism-unknown-2026": {
        "title": "ISM製造業景況指数（2026年9月分・10月1日発表）",
        "release_et": "2026-10-01T10:00", "confirmed": True, "sources": [ISM],
        "date_label": "2026年10月1日 10:00 ET（日本時間23:00）",
        "notes": "会話記録の4項目（総合54.5・雇用52.7・新規受注55.3・価格77.9）がISM 2026年9月分製造業PMIと全て一致したため発表日時を特定。他イベントとは統合していない。",
        "indicators": [
            {"code": "ISM_PMI", "name": "ISM製造業 総合", "previous": 54.6, "consensus": 55.0,
             "consensus_source": "第三者（約55）", "actual": 54.5, "actual_verified": True,
             "actual_source": "ISM September 2026 Manufacturing PMI Report"},
            {"code": "ISM_EMPLOYMENT", "name": "ISM製造業 雇用", "previous": 51.2, "actual": 52.7, "actual_verified": True,
             "actual_source": "ISM September 2026 Manufacturing PMI Report"},
            {"code": "ISM_NEW_ORDERS", "name": "ISM製造業 新規受注", "previous": 53.7, "actual": 55.3, "actual_verified": True,
             "actual_source": "ISM September 2026 Manufacturing PMI Report"},
            {"code": "ISM_PRICES", "name": "ISM製造業 価格", "previous": 71.1, "actual": 77.9, "actual_verified": True,
             "actual_source": "ISM September 2026 Manufacturing PMI Report"},
        ],
    },
    "fomc-2026-10": {
        "release_et": "2026-10-28T14:00", "confirmed": True, "sources": [FED],
        "notes": "FOMC 10月27-28日会合。声明14:00 ET（日本時間10/29 03:00）、議長会見14:30 ET。10/26時点のCME FedWatchは据え置き約90%、12月利上げ約73%（報道）。",
        "indicators": [{**FFR, "previous": 4.00, "consensus": 4.00, "consensus_source": "CME FedWatch 据え置き約90%（10/22〜26報道）"}],
    },
    "fomc-2026-10-presser": {"release_et": "2026-10-28T14:30", "confirmed": True, "sources": [FED]},
    "gdp-pce-2026-10": {
        "title": "GDP速報値＋PCE（2026年10月29日）",
        "release_et": "2026-10-29T08:30", "confirmed": True, "sources": [BEA],
        "notes": "BEA: GDP 7-9月期速報値と個人所得・支出（9月分）を同時発表（価格変動は複合イベントとして分析）。",
        "indicators": [
            {"code": "GDP_QOQ_ANN", "previous": 2.2, "consensus": 3.2, "consensus_source": "Investing.com予想（GDPNow 3.5%、NY連銀 2.67%）"},
            {"code": "CORE_PCE_MOM", "consensus": 0.3, "consensus_source": "Continuum Economics想定（第三者）"},
            {"code": "CORE_PCE_YOY", "previous": 3.0, "consensus": 3.1, "consensus_source": "第三者プレビュー（約3.1%）",
             "notes": "前回値3.0%は第三者集計（未照合）"},
            {"code": "INITIAL_CLAIMS", "_delete_if_empty": True},
        ],
    },
}

# REV 1 で作成した対象外カテゴリの今後の予定（予測・実績が付いていなければ削除）
REMOVED_SLUGS = [
    "cb-nhs-2026-10-27", "durable-2026-10-27", "eci-2026-q3", "ism-mfg-2026-11", "jolts-2026-11-03", "adp-2026-11",
    "ism-svc-2026-11", "claims-2026-11-05", "claims-2026-11-12", "retail-2026-11", "fomc-minutes-2026-11",
    "claims-2026-11-19", "cb-2026-11", "nhs-2026-11-25", "ism-jolts-2026-12-01", "adp-2026-12", "claims-2026-12-03",
    "ism-svc-2026-12", "retail-2026-12", "claims-2026-12-17", "nhs-2026-12-23",
]

GDP_PCE_INDICATORS = lambda gdp_name: [  # noqa: E731
    {"code": "GDP_QOQ_ANN", "name": gdp_name, "unit": "%"},
    {"code": "PCE_MOM", "name": "PCE総合（前月比）", "unit": "%"},
    {"code": "CORE_PCE_MOM", "name": "コアPCE（前月比）", "unit": "%"},
    {"code": "CORE_PCE_YOY", "name": "コアPCE（前年比）", "unit": "%"},
]
CPI_INDICATORS = [
    {"code": "CPI_MOM", "name": "CPI（前月比）", "unit": "%"},
    {"code": "CPI_YOY", "name": "CPI（前年比）", "unit": "%"},
    {"code": "CORE_CPI_MOM", "name": "コアCPI（前月比）", "unit": "%"},
    {"code": "CORE_CPI_YOY", "name": "コアCPI（前年比）", "unit": "%"},
]
NFP_INDICATORS = [
    {"code": "NFP", "name": "非農業部門雇用者数", "unit": "万人"},
    {"code": "UNRATE", "name": "失業率", "unit": "%"},
    {"code": "AHE_MOM", "name": "平均時給（前月比）", "unit": "%"},
]

# ---------------------------------------------------------------- 新規（今後の予定）イベント
# 価格への影響を分けられないため、GDPと同時刻のPCEは同じ複合イベントの指標として持つ
NEW_EVENTS = [
    {"slug": "nfp-2026-11", "title": "米雇用統計 NFP（10月分）", "category": "NFP",
     "release_et": "2026-11-06T08:30", "confirmed": True, "importance": 10, "sources": [BLS_EMP, BLS],
     "notes": "BLS 9月分リリースに次回日程として記載。夏時間終了後のため日本時間22:30。",
     "indicators": [{**NFP_INDICATORS[0], "previous": 2.9}, {**NFP_INDICATORS[1], "previous": 4.2}, NFP_INDICATORS[2]]},
    {"slug": "cpi-2026-11", "title": "米消費者物価指数 CPI（10月分）", "category": "CPI",
     "release_et": "2026-11-10T08:30", "confirmed": True, "importance": 10, "sources": [BLS_CPI],
     "indicators": [{**i, "previous": p} for i, p in zip(CPI_INDICATORS, (0.6, 3.7, 0.3, 2.6))]},
    {"slug": "gdp-pce-2026-11-25", "title": "GDP改定値＋PCE（10月分）（11月25日）", "category": "GDP",
     "categories": ["GDP", "PCE"], "is_composite": True,
     "release_et": "2026-11-25T08:30", "confirmed": True, "importance": 9, "sources": [BEA],
     "notes": "BEA: 7-9月期GDP改定値と個人所得・支出（10月分）を同時発表。",
     "indicators": GDP_PCE_INDICATORS("GDP改定値（前期比年率）")},
    {"slug": "nfp-2026-12", "title": "米雇用統計 NFP（11月分）", "category": "NFP",
     "release_et": "2026-12-04T08:30", "confirmed": False, "importance": 10, "sources": [THIRD],
     "notes": "第三者カレンダーで12/4。BLS公式スケジュールで要確認。", "indicators": NFP_INDICATORS},
    {"slug": "fomc-2026-12", "title": "FOMC 政策金利・声明（2026年12月・SEP）", "category": "FOMC",
     "release_et": "2026-12-09T14:00", "confirmed": True, "importance": 10, "sources": [FED],
     "notes": "12月8-9日会合（経済見通しSEPあり）。声明14:00 ET＝日本時間12/10 04:00。",
     "indicators": [FFR],
     "children": [{"slug": "fomc-2026-12-presser", "title": "FRB議長会見（2026年12月）", "release_et": "2026-12-09T14:30",
                   "importance": 9}]},
    {"slug": "cpi-2026-12", "title": "米消費者物価指数 CPI（11月分）", "category": "CPI",
     "release_et": "2026-12-10T08:30", "confirmed": True, "importance": 10, "sources": [BLS_CPI],
     "indicators": CPI_INDICATORS},
    {"slug": "gdp-pce-2026-12-23", "title": "GDP確定値＋PCE（11月分）（12月23日）", "category": "GDP",
     "categories": ["GDP", "PCE"], "is_composite": True,
     "release_et": "2026-12-23T08:30", "confirmed": True, "importance": 8, "sources": [BEA],
     "indicators": GDP_PCE_INDICATORS("GDP確定値（前期比年率）")},
]

# REV 1 で作成済みのイベントを REV 2 の内容に合わせる
UPDATES.update({
    "gdp-pce-2026-11-25": {
        "title": "GDP改定値＋PCE（10月分）（11月25日）", "category": "GDP", "categories": ["GDP", "PCE"],
        "release_et": "2026-11-25T08:30", "confirmed": True, "sources": [BEA],
        "notes": "BEA: 7-9月期GDP改定値と個人所得・支出（10月分）を同時発表。",
        "indicators": [{"code": "INITIAL_CLAIMS", "_delete_if_empty": True}],
    },
    "gdp-pce-2026-12-23": {"category": "GDP", "categories": ["GDP", "PCE"], "release_et": "2026-12-23T08:30",
                           "confirmed": True, "sources": [BEA]},
    "cpi-2026-12": {
        "title": "米消費者物価指数 CPI（11月分）", "categories": ["CPI"], "is_composite": False,
        "release_et": "2026-12-10T08:30", "confirmed": True, "sources": [BLS_CPI],
        "indicators": [{"code": "INITIAL_CLAIMS", "_delete_if_empty": True}],
    },
})
