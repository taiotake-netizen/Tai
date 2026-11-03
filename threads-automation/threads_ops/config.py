"""Runtime configuration from environment variables. Secret values are never logged or returned."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (does not override variables already set)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()   # inline comment on an unquoted value
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    app_env: str                      # production | development | demo | test
    db_path: str
    api_token: str | None             # shared secret for the control-center BFF
    llm_provider: str                 # openai | mock | none
    openai_model: str
    openai_reasoning_effort: str | None
    openai_base_url: str
    openai_timeout_s: float
    publish_mode: str                 # dry_run | live
    threads_api_base: str
    worker_id: str
    worker_concurrency: int
    ai_max_concurrency: int
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_demo(self) -> bool:
        return self.app_env == "demo"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def openai_key_present(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))


def load_config(env_file: Path | None = None) -> Config:
    if os.environ.get("THREADS_OPS_SKIP_DOTENV") != "1":
        _load_dotenv(env_file or ROOT / ".env")
    app_env = os.environ.get("APP_ENV", "development").strip()
    default_db = {"demo": "data/demo.db", "test": "data/test.db"}.get(app_env, "data/threads_ops.db")
    db_path = os.environ.get("THREADS_OPS_DB", str(ROOT / default_db))
    publish_mode = os.environ.get("PUBLISH_MODE", "dry_run").strip()
    if app_env in {"demo", "test"}:
        publish_mode = "dry_run"   # demo/test can never publish for real
    if publish_mode not in {"dry_run", "live"}:
        raise ValueError("PUBLISH_MODE must be dry_run or live")
    llm = os.environ.get("LLM_PROVIDER", "openai" if app_env not in {"demo", "test"} else "mock").strip()
    if app_env in {"demo", "test"} and llm == "openai" and not _bool("DEMO_ALLOW_REAL_LLM"):
        llm = "mock"
    effort = os.environ.get("OPENAI_REASONING_EFFORT", "low").strip() or None
    return Config(
        app_env=app_env,
        db_path=db_path,
        api_token=os.environ.get("THREADS_OPS_API_TOKEN") or None,
        llm_provider=llm,
        openai_model=os.environ.get("OPENAI_MODEL", "gpt-5.4-mini").strip(),
        openai_reasoning_effort=None if effort in {None, "unset"} else effort,
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        openai_timeout_s=float(os.environ.get("OPENAI_TIMEOUT_S", "60")),
        publish_mode=publish_mode,
        threads_api_base=os.environ.get("THREADS_API_BASE", "https://graph.threads.net/v1.0").rstrip("/"),
        worker_id=os.environ.get("WORKER_ID", f"worker-{os.getpid()}"),
        worker_concurrency=max(1, int(os.environ.get("WORKER_CONCURRENCY", "1"))),
        ai_max_concurrency=max(1, int(os.environ.get("AI_MAX_CONCURRENCY", "1"))),
        allowed_hosts=("api.openai.com", "graph.threads.net"),
    )


def env_presence(names: list[str]) -> dict[str, bool]:
    """Return whether each variable is set, without exposing values."""
    return {n: bool(os.environ.get(n)) for n in names}
