"""Shared runtime context passed to handlers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import httpx

from .config import Config
from .db import connect, migrate
from .llm import LLM
from .threads_api import DryRunPublisher


@dataclass
class Ctx:
    cfg: Config
    conn: sqlite3.Connection
    llm: LLM
    dry: DryRunPublisher = field(default_factory=DryRunPublisher)
    threads_transport: httpx.BaseTransport | None = None


def make_ctx(cfg: Config, *, llm_transport: httpx.BaseTransport | None = None,
             threads_transport: httpx.BaseTransport | None = None) -> Ctx:
    conn = connect(cfg.db_path)
    migrate(conn)
    return Ctx(cfg=cfg, conn=conn, llm=LLM(cfg, conn, transport=llm_transport), threads_transport=threads_transport)
