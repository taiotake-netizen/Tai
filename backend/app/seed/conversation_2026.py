"""ChatGPTとの会話で行った予測・分析記録（2026年9〜10月）。

すべて会話由来の暫定データ。公式の経済指標・価格データと照合するまで「未検証」として扱う。
- 実績値（指標・価格）は会話記録にあるものだけを登録し、補完・推定はしない。
- 発表時刻は会話に明記がないため、米国の通常スケジュールから推定した日本時間を入れ、
  release_time_confirmed=False とする。
- 時間幅が明示されていない値は構造化フィールドに入れず extras / observations / headline_move に入れる。
"""

CONV = "chatgpt_conversation"
CONV_MODEL = ("chatgpt-conversation", "conv-2026")
SRC = "ChatGPTとの会話記録（未照合）"
TIME_NOTE = "発表時刻は通常スケジュールからの推定。公式カレンダーで要確認。"

EVENTS = [
    # ------------------------------------------------------------------ 5-1
    {
        "slug": "fomc-2026-09",
        "title": "FOMC 政策金利・声明（2026年9月）",
        "category": "FOMC", "categories": ["FOMC"],
        "release_jst": "2026-09-17T03:00", "date_label": "2026年9月17日（日本時間）",
        "importance": 10,
        "notes": TIME_NOTE + " 声明と議長会見の値動きは区別されていない記録。",
        "indicators": [],
        "forecasts": [
            {
                "label": "事前予測", "as_of_label": "発表前（会話記録・作成日時不明）",
                "prob_down": 63, "prob_up": 37, "dominant_direction": "down",
                "initial_direction": "down", "initial_move": -45,
                "extras": [{"label": "5〜15分の想定下落", "value": "35〜60ドル（時間幅が5〜15分の幅を持つため構造化項目には入れない）"}],
                "scenarios": [{"label": "タカ派シナリオ", "value": "70〜100ドル下落", "reaction_min": -100, "reaction_max": -70}],
                "rationale": "会話記録より。横ばい確率は記録なし。",
            }
        ],
        "outcome": {
            "observed_direction": "down", "initial_direction": "down",
            "observations": [
                {"label": "発表前", "value": "4,355〜4,360ドル付近"},
                {"label": "初動後", "value": "4,313〜4,315ドルへ下落"},
                {"label": "初動", "value": "約40〜47ドル下落"},
                {"label": "その後", "value": "4,230ドル台まで下落"},
                {"label": "累計", "value": "約120〜130ドル下落という記録"},
            ],
            "notes": "時刻の記録がないため1分後・5分後等の終着地は未記録。",
        },
        "reflections": [
            "初動の方向と値幅は比較的近かった可能性",
            "その後の継続下落を過小評価した可能性",
        ],
        "improvements": ["初動と会見後の値動きを分けて分析する"],
    },
    # ------------------------------------------------------------------ 5-2
    {
        "slug": "adp-2026-09-30",
        "title": "ADP雇用統計（2026年9月30日）",
        "category": "ADP", "categories": ["ADP"],
        "release_jst": "2026-09-30T21:15", "date_label": "2026年9月30日",
        "importance": 6, "cluster": "2026-09-30 ADP・PCE関連",
        "notes": TIME_NOTE + " 会話では「ADP・PCE関連」としてまとめて記録。発表時刻が異なるため別イベントとして管理。",
        "indicators": [
            {"code": "ADP", "name": "ADP雇用者数", "unit": "万人", "actual": 9},
        ],
        "forecasts": [],
        "outcome": {
            "observed_direction": "down",
            "observations": [{"label": "値動き", "value": "ADP後に下落（値幅・時間幅の記録なし）"}],
        },
        "reflections": [],
        "improvements": ["複数指標を分離して研究する"],
    },
    {
        "slug": "pce-2026-09-30",
        "title": "PCE・個人消費・GDP関連（2026年9月30日）",
        "category": "PCE", "categories": ["PCE", "GDP"], "is_composite": True,
        "release_jst": "2026-09-30T21:30", "date_label": "2026年9月30日",
        "importance": 8, "cluster": "2026-09-30 ADP・PCE関連",
        "notes": TIME_NOTE + " 同時発表の複合イベント。経済数値は個別管理、価格変動は複合イベントとして分析。",
        "indicators": [
            {"code": "CORE_PCE_MOM", "name": "コアPCE（前月比）", "unit": "%", "actual": 0.2},
            {"code": "CORE_PCE_YOY", "name": "コアPCE（前年比）", "unit": "%", "actual": 3.0},
            {"code": "PERSONAL_SPENDING", "name": "個人消費", "unit": "%", "actual": 0.9},
            {"code": "GDP_RELATED", "name": "GDP関連（会話記録上の項目名）", "unit": "%", "actual": 2.2},
        ],
        "forecasts": [
            {
                "label": "事前予測", "as_of_label": "発表前（会話記録・作成日時不明）",
                "extras": [
                    {"label": "PCE初動最大", "value": "25〜50ドル（方向・時間幅の記録なし）"},
                    {"label": "継続時", "value": "60〜90ドル"},
                ],
                "rationale": "会話記録より。方向確率の記録なし。",
            }
        ],
        "outcome": {
            "initial_direction": "up",
            "observations": [
                {"label": "PCE直後", "value": "約15ドル上昇"},
                {"label": "その後", "value": "反落"},
            ],
        },
        "reflections": [],
        "improvements": ["複数指標を分離して研究する", "初動と反転を別々に評価する"],
    },
    # ------------------------------------------------------------------ 5-3
    {
        "slug": "nfp-2026-10",
        "title": "米雇用統計 NFP（2026年10月2日）",
        "category": "NFP", "categories": ["NFP"],
        "release_jst": "2026-10-02T21:30", "date_label": "2026年10月2日",
        "importance": 10,
        "notes": TIME_NOTE,
        "indicators": [
            {"code": "NFP", "name": "非農業部門雇用者数", "unit": "万人", "previous": 16.2,
             "previous_revised": 13.3, "actual": 2.9,
             "notes": "前月分は+16.2万人から+13.3万人へ改定（会話記録）"},
            {"code": "UNRATE", "name": "失業率", "unit": "%", "actual": 4.2},
            {"code": "AHE_MOM", "name": "平均時給（前月比）", "unit": "%"},
        ],
        "forecasts": [
            {
                "label": "予測A", "as_of_label": "発表前（会話記録・作成日時不明）",
                "indicator_forecasts": [
                    {"code": "NFP", "point": 10.5}, {"code": "UNRATE", "point": 4.1},
                ],
                "prob_down": 58, "dominant_direction": "down", "headline_move": -28,
                "scenarios": [{
                    "label": "NFP +2〜5万人ならゴールド+35〜60ドル", "indicator_code": "NFP",
                    "min": 2, "max": 5, "reaction_min": 35, "reaction_max": 60, "window": "unspecified",
                }],
                "rationale": "会話記録より。一点予想−28ドルの時間幅は記録なし。上昇・横ばい確率の記録なし。",
            },
            {
                "label": "予測B（別バージョン）", "as_of_label": "発表前（会話記録・作成日時不明）",
                "indicator_forecasts": [{"code": "NFP", "point": 11}],
                "headline_move": -25,
                "change_summary": "会話上の別バージョン（NFP +11万人、一点予想−25ドル）。両者が同一バージョンかは未確認。",
                "rationale": "会話記録より。",
            },
        ],
        "outcome": {
            "observed_direction": "up", "headline_move": 44,
            "observations": [{"label": "値動き", "value": "4,181ドル → 4,225ドル（約+44ドル、時間幅の記録なし）"}],
        },
        "reflections": [
            "雇用者数予測は7.6万人の乖離",
            "方向予測は下落優勢だったが、観測値動きは上昇",
            "予測と実績の時間幅が一致する場合、−28ドルと+44ドルの差は72ドル",
            "雇用需要の弱さと過去分の改定を過小評価した可能性",
            "事前の条件付きシナリオ（NFP +2〜5万人ならゴールド+35〜60ドル）は観測値動きと整合",
        ],
        "improvements": ["指標の数値予測と、その数値が出た場合の市場反応予測を別々に評価する"],
    },
    # ------------------------------------------------------------------ 5-4
    {
        "slug": "fomc-minutes-2026-10",
        "title": "FOMC議事要旨（2026年10月7日）",
        "category": "FOMC_MINUTES", "categories": ["FOMC_MINUTES"],
        "release_jst": "2026-10-08T03:00",
        "date_label": "2026年10月7日（会話記録の日付。米東部10/7 14:00＝日本時間10/8 03:00と推定）",
        "importance": 6,
        "notes": TIME_NOTE,
        "indicators": [],
        "forecasts": [
            {
                "label": "事前予測", "as_of_label": "発表前（会話記録・作成日時不明）",
                "prob_down": 59, "prob_up": 36, "prob_flat": 5, "d30": -12,
                "extras": [{"label": "最大値幅", "value": "20〜25ドル（時間幅未指定）"}],
                "rationale": "会話記録より。",
            }
        ],
        "outcome": {
            "observed_direction": "flat",
            "observations": [{"label": "結果", "value": "ほぼ無風"}],
        },
        "reflections": ["タカ派の内容が織り込み済みだった可能性"],
        "improvements": ["本会合と議事要旨は別モデルにする"],
    },
    # ------------------------------------------------------------------ 5-5
    {
        "slug": "cpi-2026-10",
        "title": "米消費者物価指数 CPI（2026年10月14日）",
        "category": "CPI", "categories": ["CPI"],
        "release_jst": "2026-10-14T21:30", "date_label": "2026年10月14日",
        "importance": 10,
        "notes": TIME_NOTE + " 価格記録は時刻との照合前。",
        "indicators": [
            {"code": "CPI_MOM", "name": "CPI（前月比）", "unit": "%"},
            {"code": "CPI_YOY", "name": "CPI（前年比）", "unit": "%"},
            {"code": "CORE_CPI_MOM", "name": "コアCPI（前月比）", "unit": "%"},
            {"code": "CORE_CPI_YOY", "name": "コアCPI（前年比）", "unit": "%"},
        ],
        "forecasts": [
            {
                "label": "初回予測", "as_of_label": "発表前（会話記録・作成日時不明）",
                "prob_up": 54, "prob_down": 41, "prob_flat": 5, "headline_move": 29,
                "rationale": "会話記録より。一点予想+29ドルの時間幅は記録なし。",
            },
            {
                "label": "修正版", "as_of_label": "発表前（会話記録・作成日時不明）",
                "prob_up": 47, "prob_down": 48, "prob_flat": 5, "d5": -9,
                "change_summary": "方向を上昇優勢→下落優勢（僅差）に修正、5分後−9ドル",
                "rationale": "会話記録より。",
            },
        ],
        "outcome": {
            "base_price": 4152, "d1": -8, "d5": -16, "low_5m": 4116, "max_down_5m": 36,
            "direction_5m": "down", "initial_direction": "down", "initial_move": -36,
            "observations": [
                {"label": "発表直前", "value": "4,152ドル"},
                {"label": "初動", "value": "4,116ドル（最大下落36ドル）"},
                {"label": "1分後", "value": "4,144ドル（−8ドル）"},
                {"label": "5分後", "value": "4,136ドル（−16ドル）"},
            ],
            "notes": "会話由来の価格記録を採用した場合の値。価格と時刻を照合してから正式な実績とする。5分間の高値は記録なし。",
        },
        "reflections": [
            "修正版5分後予測（−9ドル）の誤差は7ドル（会話記録の価格を採用した場合）",
            "最大下落幅と5分後終着地は異なる",
            "初動で下落しても5分後には大きく戻すことがある",
        ],
        "improvements": ["上下への往復を研究する必要がある"],
    },
    # ------------------------------------------------------------------ 5-6
    {
        "slug": "ism-unknown-2026",
        "title": "ISM関連（発表日時不明）",
        "category": "ISM", "categories": ["ISM"],
        "release_jst": None, "date_label": "発表日時不明（会話記録から特定できない）",
        "importance": 7,
        "notes": "製造業・非製造業の別および発表日時が不明のため、他のイベントに統合しない。",
        "indicators": [
            {"code": "ISM_PMI", "name": "ISM 総合", "unit": "", "actual": 54.5},
            {"code": "ISM_EMPLOYMENT", "name": "ISM 雇用", "unit": "", "actual": 52.7},
            {"code": "ISM_NEW_ORDERS", "name": "ISM 新規受注", "unit": "", "actual": 55.3},
            {"code": "ISM_PRICES", "name": "ISM 価格", "unit": "", "actual": 77.9},
        ],
        "forecasts": [],
        "outcome": {
            "observations": [{"label": "値動き", "value": "ゴールド約10ドル下落後に反発"}],
            "initial_direction": "down",
        },
        "reflections": [],
        "improvements": ["発表日時を特定してから価格データと照合する"],
    },
    # ------------------------------------------------------------------ 5-7
    {
        "slug": "fomc-2026-10",
        "title": "FOMC 政策金利・声明（2026年10月）",
        "category": "FOMC", "categories": ["FOMC"],
        "release_jst": "2026-10-29T03:00", "date_label": "2026年10月29日（日本時間）",
        "importance": 10,
        "notes": TIME_NOTE + " 声明（03:00）と議長会見（03:30）を別イベントで管理し、全体は60分レンジで評価。",
        "indicators": [],
        "children": [
            {"slug": "fomc-2026-10-presser", "title": "FRB議長会見（2026年10月）", "category": "FOMC",
             "release_jst": "2026-10-29T03:30", "importance": 9, "notes": TIME_NOTE},
        ],
        "forecasts": [
            {
                "label": "初期バージョン", "as_of_label": "会話記録・作成日時不明",
                "prob_up": 42, "prob_down": 53, "prob_flat": 5, "d5": -12, "d30": -18,
                "rationale": "会話記録より。",
            },
            {
                "label": "中間バージョン", "as_of_label": "会話記録・作成日時不明",
                "d5": -20, "d30": -30, "max_excursion_5m": 42,
                "change_summary": "5分後−12→−20ドル、30分後−18→−30ドル、最大到達値幅42ドルを追加",
                "rationale": "会話記録より。方向確率の記録なし。",
            },
            {
                "label": "最新版", "as_of_label": "10月27日時点",
                "prob_up": 45, "prob_down": 50, "prob_flat": 5, "max_excursion_5m": 35,
                "d5": -12, "d30": -20, "range_5m": 45, "range_30m": 60, "range_60m": 80,
                "reach_probs": {
                    "10": {"either": 90}, "15": {"either": 82}, "20": {"either": 73}, "30": {"either": 55},
                    "50": {"either": 27}, "70": {"either": 11}, "100": {"either": 3},
                },
                "phase_analysis": {"note": "声明（03:00）と議長会見（03:30）は別イベントとして記録。本予測は声明発表基準。"},
                "change_summary": "5分後−20→−12ドル、30分後−30→−20ドル、最大到達値幅42→35ドル、レンジと到達確率を追加",
                "rationale": "会話記録より。到達確率は上下どちらかへの到達として記録。",
            },
        ],
        "outcome": None,
        "reflections": [], "improvements": [],
    },
    # ------------------------------------------------------------------ 5-8
    {
        "slug": "gdp-pce-2026-10",
        "title": "GDP速報値＋PCE（2026年10月29日）",
        "category": "GDP", "categories": ["GDP", "PCE"], "is_composite": True,
        "release_jst": "2026-10-29T21:30", "date_label": "2026年10月29日",
        "importance": 9,
        "notes": TIME_NOTE + " 同時発表の複合イベント。経済数値は個別管理。",
        "indicators": [
            {"code": "GDP_QOQ_ANN", "name": "GDP速報値（前期比年率）", "unit": "%"},
            {"code": "PCE_MOM", "name": "PCE総合（前月比）", "unit": "%"},
            {"code": "CORE_PCE_MOM", "name": "コアPCE（前月比）", "unit": "%"},
            {"code": "CORE_PCE_YOY", "name": "コアPCE（前年比）", "unit": "%"},
        ],
        "forecasts": [
            {
                "label": "初期バージョン", "as_of_label": "会話記録・作成日時不明",
                "prob_up": 40, "prob_down": 55, "prob_flat": 5, "d5": -15, "d30": -20,
                "rationale": "会話記録より。",
            },
            {
                "label": "中間バージョン", "as_of_label": "会話記録・作成日時不明",
                "d5": -25, "d30": -35, "max_excursion_5m": 45,
                "change_summary": "5分後−15→−25ドル、30分後−20→−35ドル、最大到達値幅45ドルを追加",
                "rationale": "会話記録より。方向確率の記録なし。",
            },
            {
                "label": "最新版", "as_of_label": "10月27日時点",
                "prob_up": 43, "prob_down": 52, "prob_flat": 5, "max_excursion_5m": 38,
                "d5": -15, "d30": -23, "range_5m": 45, "range_60m": 65,
                "indicator_forecasts": [
                    {"code": "GDP_QOQ_ANN", "point": 3.3}, {"code": "PCE_MOM", "point": 0.5},
                    {"code": "CORE_PCE_MOM", "point": 0.3}, {"code": "CORE_PCE_YOY", "point": 3.1},
                ],
                "reach_probs": {
                    "10": {"up": 60, "down": 67}, "20": {"up": 34, "down": 44}, "30": {"up": 25, "down": 38},
                    "50": {"up": 12, "down": 22}, "70": {"up": 5, "down": 10},
                },
                "change_summary": "5分後−25→−15ドル、30分後−35→−23ドル、最大到達値幅45→38ドル、指標数値予測と方向別到達確率を追加",
                "rationale": "会話記録より。",
            },
        ],
        "outcome": None,
        "reflections": [], "improvements": [],
    },
]

MODELS = [
    {"name": "chatgpt-conversation", "version": "conv-2026", "kind": "conversation", "status": "reference",
     "description": "ユーザーとChatGPTの会話で作成された予測（2026年9〜10月）。比較用の参照記録。"},
    {"name": "baseline_avg_range", "version": "0.1.0", "kind": "statistical", "status": "candidate",
     "description": "同カテゴリの検証済み過去イベントの値幅・方向頻度の統計。検証済みデータが3件以上で予測可能。"},
    {"name": "manual", "version": "1", "kind": "manual", "status": "reference",
     "description": "画面から手入力された予測。"},
]
