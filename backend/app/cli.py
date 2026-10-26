"""python -m app.cli init|seed|refresh"""
import sys

from .db import SessionLocal, init_db
from .seed.loader import seed, sync_official_schedule
from .services.pipeline import refresh_statuses

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    init_db()
    with SessionLocal() as db:
        if cmd in ("init", "seed"):
            print(seed(db))
            print(sync_official_schedule(db))
        if cmd in ("init", "refresh"):
            print(refresh_statuses(db))
