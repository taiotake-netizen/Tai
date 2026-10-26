"""公式発表スケジュールと公式実績（2026年10月26日時点の調査結果）。

- 時刻は米国東部時間(ET)で記述し、America/New_York で変換する（2026年11月1日に夏時間終了）。
- confirmed=True は発表機関（FRB/BLS/BEA/Census/ISM/ADP）の公表スケジュールで確認できたもの。
  第三者カレンダーや通常パターンのみで確認したものは False とし、source に明記する。
- 実績値の verified=True は、発表機関の公表値と一致することを確認できたもの。
- REV を上げると、既存DBのイベントにも差分が適用される（予測バージョンは変更しない）。
"""

REV = 1

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
             "notes": "会話記録の「GDP関連+2.2%」はQ2確定値と一致。PCEと同日発表かは要確認。"},
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
        "title": "GDP速報値＋PCE＋新規失業保険申請（2026年10月29日）",
        "release_et": "2026-10-29T08:30", "confirmed": True, "sources": [BEA, CLAIMS_PATTERN],
        "notes": "BEA: GDP 7-9月期速報値と個人所得・支出（9月分）を同時発表。同時刻に週次失業保険申請（木曜定例）。",
        "indicators": [
            {"code": "GDP_QOQ_ANN", "previous": 2.2, "consensus": 3.2, "consensus_source": "Investing.com予想（GDPNow 3.5%、NY連銀 2.67%）"},
            {"code": "CORE_PCE_MOM", "consensus": 0.3, "consensus_source": "Continuum Economics想定（第三者）"},
            {"code": "CORE_PCE_YOY", "previous": 3.0, "consensus": 3.1, "consensus_source": "第三者プレビュー（約3.1%）",
             "notes": "前回値3.0%は第三者集計（未照合）"},
            {**CLAIMS},
        ],
    },
}

# ---------------------------------------------------------------- 新規（今後の予定）イベント
NEW_EVENTS = [
    {"slug": "cb-nhs-2026-10-27", "title": "消費者信頼感指数＋新築住宅販売（2026年10月27日）", "category": "CONSUMER_CONFIDENCE",
     "categories": ["CONSUMER_CONFIDENCE", "NEW_HOME_SALES"], "is_composite": True,
     "release_et": "2026-10-27T10:00", "confirmed": False, "importance": 5, "sources": [CENSUS_NRS, CB_PATTERN],
     "notes": "新築住宅販売（9月分）はCensusの前回リリースで10/27と確認。消費者信頼感は最終火曜10:00 ETの通常日程（公式未確認）。",
     "indicators": [{"code": "CB_CC", "name": "コンファレンスボード消費者信頼感指数", "unit": ""},
                    {"code": "NEW_HOME_SALES", "name": "新築住宅販売件数（年率）", "unit": "万件"}]},
    {"slug": "durable-2026-10-27", "title": "耐久財受注（9月速報）", "category": "DURABLE_GOODS",
     "release_et": "2026-10-27T08:30", "confirmed": True, "importance": 5, "sources": [CENSUS_DG],
     "indicators": [{"code": "DGO_MOM", "name": "耐久財受注（前月比）", "unit": "%"},
                    {"code": "CORE_DGO_MOM", "name": "耐久財受注 除輸送用機器（前月比）", "unit": "%"}]},
    {"slug": "eci-2026-q3", "title": "雇用コスト指数（7-9月期）", "category": "ECI",
     "release_et": "2026-10-30T08:30", "confirmed": True, "importance": 6, "sources": [BLS_ECI],
     "indicators": [{"code": "ECI_QOQ", "name": "雇用コスト指数（前期比）", "unit": "%"}]},
    {"slug": "ism-mfg-2026-11", "title": "ISM製造業景況指数（10月分）", "category": "ISM",
     "release_et": "2026-11-02T10:00", "confirmed": True, "importance": 7, "sources": [ISM],
     "indicators": [{"code": "ISM_PMI", "name": "ISM製造業 総合", "unit": "", "previous": 54.5},
                    {"code": "ISM_PRICES", "name": "ISM製造業 価格", "unit": "", "previous": 77.9}]},
    {"slug": "jolts-2026-11-03", "title": "JOLTS求人件数（9月分）", "category": "JOLTS",
     "release_et": "2026-11-03T10:00", "confirmed": True, "importance": 6, "sources": [BLS_JOLTS],
     "notes": "同日は米中間選挙の投票日。",
     "indicators": [{"code": "JOLTS", "name": "JOLTS求人件数", "unit": "万件"}]},
    {"slug": "adp-2026-11", "title": "ADP雇用統計（10月分）", "category": "ADP",
     "release_et": "2026-11-04T08:15", "confirmed": True, "importance": 6, "sources": [ADP],
     "indicators": [{"code": "ADP", "name": "ADP雇用者数", "unit": "万人", "previous": 9.0}]},
    {"slug": "ism-svc-2026-11", "title": "ISM非製造業景況指数（10月分）", "category": "ISM",
     "release_et": "2026-11-04T10:00", "confirmed": True, "importance": 6, "sources": [ISM],
     "indicators": [{"code": "ISM_SVC_PMI", "name": "ISM非製造業 総合", "unit": ""}]},
    {"slug": "claims-2026-11-05", "title": "新規失業保険申請件数（11月5日）", "category": "JOBLESS_CLAIMS",
     "release_et": "2026-11-05T08:30", "confirmed": False, "importance": 4, "sources": [CLAIMS_PATTERN], "indicators": [CLAIMS]},
    {"slug": "nfp-2026-11", "title": "米雇用統計 NFP（10月分）", "category": "NFP",
     "release_et": "2026-11-06T08:30", "confirmed": True, "importance": 10, "sources": [BLS_EMP, BLS],
     "notes": "BLS 9月分リリースに次回日程として記載。夏時間終了後のため日本時間22:30。",
     "indicators": [{"code": "NFP", "name": "非農業部門雇用者数", "unit": "万人", "previous": 2.9},
                    {"code": "UNRATE", "name": "失業率", "unit": "%", "previous": 4.2},
                    {"code": "AHE_MOM", "name": "平均時給（前月比）", "unit": "%"}]},
    {"slug": "cpi-2026-11", "title": "米消費者物価指数 CPI（10月分）", "category": "CPI",
     "release_et": "2026-11-10T08:30", "confirmed": True, "importance": 10, "sources": [BLS_CPI],
     "indicators": [{"code": "CPI_MOM", "name": "CPI（前月比）", "unit": "%", "previous": 0.6},
                    {"code": "CPI_YOY", "name": "CPI（前年比）", "unit": "%", "previous": 3.7},
                    {"code": "CORE_CPI_MOM", "name": "コアCPI（前月比）", "unit": "%", "previous": 0.3},
                    {"code": "CORE_CPI_YOY", "name": "コアCPI（前年比）", "unit": "%", "previous": 2.6}]},
    {"slug": "claims-2026-11-12", "title": "新規失業保険申請件数（11月12日）", "category": "JOBLESS_CLAIMS",
     "release_et": "2026-11-12T08:30", "confirmed": False, "importance": 4, "sources": [CLAIMS_PATTERN], "indicators": [CLAIMS]},
    {"slug": "retail-2026-11", "title": "小売売上高（10月分）", "category": "RETAIL_SALES",
     "release_et": "2026-11-17T08:30", "confirmed": True, "importance": 7, "sources": [CENSUS_RETAIL],
     "indicators": [{"code": "RETAIL_MOM", "name": "小売売上高（前月比）", "unit": "%"},
                    {"code": "CORE_RETAIL_MOM", "name": "小売売上高 除自動車（前月比）", "unit": "%"}]},
    {"slug": "fomc-minutes-2026-11", "title": "FOMC議事要旨（10月27-28日会合分）", "category": "FOMC_MINUTES",
     "release_et": "2026-11-18T14:00", "confirmed": True, "importance": 6, "sources": [FED_NOV], "indicators": []},
    {"slug": "claims-2026-11-19", "title": "新規失業保険申請件数（11月19日）", "category": "JOBLESS_CLAIMS",
     "release_et": "2026-11-19T08:30", "confirmed": False, "importance": 4, "sources": [CLAIMS_PATTERN], "indicators": [CLAIMS]},
    {"slug": "cb-2026-11", "title": "消費者信頼感指数（11月）", "category": "CONSUMER_CONFIDENCE",
     "release_et": "2026-11-24T10:00", "confirmed": False, "importance": 5, "sources": [CB_PATTERN],
     "indicators": [{"code": "CB_CC", "name": "コンファレンスボード消費者信頼感指数", "unit": ""}]},
    {"slug": "gdp-pce-2026-11-25", "title": "GDP改定値＋PCE（10月分）＋新規失業保険申請（11月25日）", "category": "PCE",
     "categories": ["PCE", "GDP", "JOBLESS_CLAIMS"], "is_composite": True,
     "release_et": "2026-11-25T08:30", "confirmed": True, "importance": 9, "sources": [BEA, CLAIMS_PATTERN],
     "notes": "BEA: 7-9月期GDP改定値と個人所得・支出（10月分）。失業保険申請は感謝祭(11/26)のため水曜に前倒し（第三者カレンダー）。",
     "indicators": [{"code": "GDP_QOQ_ANN", "name": "GDP改定値（前期比年率）", "unit": "%"},
                    {"code": "PCE_MOM", "name": "PCE総合（前月比）", "unit": "%"},
                    {"code": "CORE_PCE_MOM", "name": "コアPCE（前月比）", "unit": "%"},
                    {"code": "CORE_PCE_YOY", "name": "コアPCE（前年比）", "unit": "%"}, CLAIMS]},
    {"slug": "nhs-2026-11-25", "title": "新築住宅販売件数（10月分）", "category": "NEW_HOME_SALES",
     "release_et": "2026-11-25T10:00", "confirmed": False, "importance": 4, "sources": [THIRD],
     "indicators": [{"code": "NEW_HOME_SALES", "name": "新築住宅販売件数（年率）", "unit": "万件"}]},
    {"slug": "ism-jolts-2026-12-01", "title": "ISM製造業（11月分）＋JOLTS（10月分）", "category": "ISM",
     "categories": ["ISM", "JOLTS"], "is_composite": True,
     "release_et": "2026-12-01T10:00", "confirmed": True, "importance": 7, "sources": [ISM, THIRD],
     "notes": "ISM製造業はISM公式カレンダーで確認。JOLTSの12/1 10:00は第三者カレンダーのみ（公式未確認）。",
     "indicators": [{"code": "ISM_PMI", "name": "ISM製造業 総合", "unit": ""},
                    {"code": "JOLTS", "name": "JOLTS求人件数", "unit": "万件"}]},
    {"slug": "adp-2026-12", "title": "ADP雇用統計（11月分）", "category": "ADP",
     "release_et": "2026-12-02T08:15", "confirmed": True, "importance": 6, "sources": [ADP],
     "indicators": [{"code": "ADP", "name": "ADP雇用者数", "unit": "万人"}]},
    {"slug": "claims-2026-12-03", "title": "新規失業保険申請件数（12月3日）", "category": "JOBLESS_CLAIMS",
     "release_et": "2026-12-03T08:30", "confirmed": False, "importance": 4, "sources": [CLAIMS_PATTERN], "indicators": [CLAIMS]},
    {"slug": "ism-svc-2026-12", "title": "ISM非製造業景況指数（11月分）", "category": "ISM",
     "release_et": "2026-12-03T10:00", "confirmed": True, "importance": 6, "sources": [ISM],
     "indicators": [{"code": "ISM_SVC_PMI", "name": "ISM非製造業 総合", "unit": ""}]},
    {"slug": "nfp-2026-12", "title": "米雇用統計 NFP（11月分）", "category": "NFP",
     "release_et": "2026-12-04T08:30", "confirmed": False, "importance": 10, "sources": [THIRD],
     "notes": "第三者カレンダーで12/4。BLS公式スケジュールで要確認。",
     "indicators": [{"code": "NFP", "name": "非農業部門雇用者数", "unit": "万人"},
                    {"code": "UNRATE", "name": "失業率", "unit": "%"},
                    {"code": "AHE_MOM", "name": "平均時給（前月比）", "unit": "%"}]},
    {"slug": "fomc-2026-12", "title": "FOMC 政策金利・声明（2026年12月・SEP）", "category": "FOMC",
     "release_et": "2026-12-09T14:00", "confirmed": True, "importance": 10, "sources": [FED],
     "notes": "12月8-9日会合（経済見通しSEPあり）。声明14:00 ET＝日本時間12/10 04:00。",
     "indicators": [FFR],
     "children": [{"slug": "fomc-2026-12-presser", "title": "FRB議長会見（2026年12月）", "release_et": "2026-12-09T14:30",
                   "importance": 9}]},
    {"slug": "cpi-2026-12", "title": "米CPI（11月分）＋新規失業保険申請（12月10日）", "category": "CPI",
     "categories": ["CPI", "JOBLESS_CLAIMS"], "is_composite": True,
     "release_et": "2026-12-10T08:30", "confirmed": True, "importance": 10, "sources": [BLS_CPI, CLAIMS_PATTERN],
     "indicators": [{"code": "CPI_MOM", "name": "CPI（前月比）", "unit": "%"},
                    {"code": "CPI_YOY", "name": "CPI（前年比）", "unit": "%"},
                    {"code": "CORE_CPI_MOM", "name": "コアCPI（前月比）", "unit": "%"},
                    {"code": "CORE_CPI_YOY", "name": "コアCPI（前年比）", "unit": "%"}, CLAIMS]},
    {"slug": "retail-2026-12", "title": "小売売上高（11月分）", "category": "RETAIL_SALES",
     "release_et": "2026-12-16T08:30", "confirmed": True, "importance": 7, "sources": [CENSUS_RETAIL],
     "indicators": [{"code": "RETAIL_MOM", "name": "小売売上高（前月比）", "unit": "%"},
                    {"code": "CORE_RETAIL_MOM", "name": "小売売上高 除自動車（前月比）", "unit": "%"}]},
    {"slug": "claims-2026-12-17", "title": "新規失業保険申請件数（12月17日）", "category": "JOBLESS_CLAIMS",
     "release_et": "2026-12-17T08:30", "confirmed": False, "importance": 4, "sources": [CLAIMS_PATTERN], "indicators": [CLAIMS]},
    {"slug": "gdp-pce-2026-12-23", "title": "GDP確定値＋PCE（11月分）（12月23日）", "category": "PCE",
     "categories": ["PCE", "GDP"], "is_composite": True,
     "release_et": "2026-12-23T08:30", "confirmed": True, "importance": 8, "sources": [BEA],
     "indicators": [{"code": "GDP_QOQ_ANN", "name": "GDP確定値（前期比年率）", "unit": "%"},
                    {"code": "PCE_MOM", "name": "PCE総合（前月比）", "unit": "%"},
                    {"code": "CORE_PCE_MOM", "name": "コアPCE（前月比）", "unit": "%"},
                    {"code": "CORE_PCE_YOY", "name": "コアPCE（前年比）", "unit": "%"}]},
    {"slug": "nhs-2026-12-23", "title": "新築住宅販売件数（11月分）", "category": "NEW_HOME_SALES",
     "release_et": "2026-12-23T10:00", "confirmed": True, "importance": 4, "sources": [CENSUS_SOC],
     "indicators": [{"code": "NEW_HOME_SALES", "name": "新築住宅販売件数（年率）", "unit": "万件"}]},
]
