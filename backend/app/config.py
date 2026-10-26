import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://xau:xau@localhost:5432/xauusd"
    )
    # 発表直前価格からの±この値幅以内なら「横ばい」と判定する（ドル）
    flat_band_usd: float = float(os.getenv("FLAT_BAND_USD", "3.0"))
    # 初動判定に使う最小値幅（ドル）
    initial_move_threshold_usd: float = float(os.getenv("INITIAL_MOVE_THRESHOLD_USD", "5.0"))
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "1") == "1"
    scheduler_interval_sec: int = int(os.getenv("SCHEDULER_INTERVAL_SEC", "60"))
    seed_on_startup: bool = os.getenv("SEED_ON_STARTUP", "1") == "1"
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    llm_model: str = os.getenv("LLM_MODEL", "claude-opus-5-5")
    # 価格データAPI（Twelve Data。無料プランあり）。未設定なら自動取得しない
    twelvedata_api_key: str | None = os.getenv("TWELVEDATA_API_KEY") or None
    price_fetch_enabled: bool = os.getenv("PRICE_FETCH_ENABLED", "1") == "1"
    # 週間経済カレンダー（市場予想・前回値）の取得
    calendar_feed_url: str = os.getenv("CALENDAR_FEED_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    calendar_feed_enabled: bool = os.getenv("CALENDAR_FEED_ENABLED", "0") == "1"
    # APIキーがある場合、重要イベントの前日・直前にAI予測を自動作成
    auto_ai_forecast: bool = os.getenv("AUTO_AI_FORECAST", "1") == "1"
    auto_ai_min_importance: int = int(os.getenv("AUTO_AI_MIN_IMPORTANCE", "8"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )


settings = Settings()

REACH_THRESHOLDS = [10, 15, 20, 30, 50, 70, 100]
HORIZONS_MIN = [1, 5, 15, 30, 60]
