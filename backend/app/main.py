import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import SessionLocal, init_db
from .routers import data, events
from .seed.loader import seed
from .services.pipeline import refresh_statuses

log = logging.getLogger("xauusd")


def _job():
    with SessionLocal() as db:
        try:
            refresh_statuses(db)
        except Exception:  # noqa: BLE001
            log.exception("refresh_statuses failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.seed_on_startup:
        with SessionLocal() as db:
            seed(db)
    _job()
    scheduler = None
    if settings.scheduler_enabled:
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(_job, "interval", seconds=settings.scheduler_interval_sec, max_instances=1, coalesce=True)
        scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="XAUUSD 経済指標AI研究システム", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(events.router)
app.include_router(data.router)
