import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
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
    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    )


settings = Settings()

REACH_THRESHOLDS = [10, 15, 20, 30, 50, 70, 100]
HORIZONS_MIN = [1, 5, 15, 30, 60]
