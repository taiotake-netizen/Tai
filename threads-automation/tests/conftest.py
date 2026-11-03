from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime

import pytest

os.environ["THREADS_OPS_SKIP_DOTENV"] = "1"

from threads_ops import timeutil  # noqa: E402
from threads_ops.config import load_config  # noqa: E402
from threads_ops.context import make_ctx  # noqa: E402
from threads_ops.settings import AccountSettingsModel  # noqa: E402
from threads_ops.store import create_account  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for k in ("OPENAI_API_KEY", "THREADS_OPS_API_TOKEN", "PUBLISH_MODE", "LLM_PROVIDER", "THREADS_ACCESS_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("THREADS_OPS_DB", str(tmp_path / "t.db"))
    timeutil.set_clock(datetime(2026, 11, 2, 0, 0, tzinfo=UTC))   # Mon 09:00 JST
    yield
    timeutil.set_clock(None)


def advance(**kw):
    from datetime import timedelta
    timeutil.set_clock(timeutil.now() + timedelta(**kw))


@pytest.fixture
def ctx():
    c = make_ctx(load_config())
    yield c
    c.conn.close()


def make_settings(**over) -> AccountSettingsModel:
    s = AccountSettingsModel()
    s.autopilot_enabled = True
    s.require_approval = False
    s.checks.ai_review_enabled = True
    for k, v in over.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def account(ctx):
    return create_account(ctx.conn, "acc", "テスト", data_scope="test", settings=make_settings())


def live_ctx(ctx, *, llm_transport=None, threads_transport=None, provider="mock"):
    """Same DB, but configured like production live publishing (transports are mocked)."""
    cfg = replace(ctx.cfg, app_env="development", publish_mode="live", llm_provider=provider)
    from threads_ops.context import Ctx
    from threads_ops.llm import LLM
    return Ctx(cfg=cfg, conn=ctx.conn, llm=LLM(cfg, ctx.conn, transport=llm_transport), threads_transport=threads_transport)
