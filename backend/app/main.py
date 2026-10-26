import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal, init_db
from .routers import data, events
from .seed.loader import seed, sync_official_schedule
from .models import utcnow
from .services.ai_forecast import auto_generate_due
from .services.calendar_feed import fetch_and_apply
from .services.pipeline import refresh_statuses
from .services.price_feed import fetch_due_events

log = logging.getLogger("xauusd")


def _job():
    """毎分: 価格の自動取得 → ステータス更新・自動検証 → AI予測の自動作成（各機能は設定時のみ）。"""
    with SessionLocal() as db:
        for name, fn in (("price_feed", fetch_due_events), ("refresh", refresh_statuses), ("ai", auto_generate_due)):
            try:
                fn(db)
            except Exception:  # noqa: BLE001
                db.rollback()
                log.exception("%s failed", name)


def _calendar_job():
    with SessionLocal() as db:
        fetch_and_apply(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed(db)
            sync_official_schedule(db)
    with SessionLocal() as db:
        refresh_statuses(db)
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(_job, "interval", seconds=settings.scheduler_interval_sec, max_instances=1, coalesce=True)
        if settings.calendar_feed_enabled:
            scheduler.add_job(_calendar_job, "interval", hours=6, max_instances=1, coalesce=True,
                              next_run_time=utcnow())
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="XAUUSD 経済指標AI研究システム", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(events.router)
app.include_router(data.router)
