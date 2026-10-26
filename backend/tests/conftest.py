import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://xau:xau@localhost:5432/xauusd_test")
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture()
def db():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    init_db()
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c
