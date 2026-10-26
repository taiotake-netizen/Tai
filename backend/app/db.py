from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 予測バージョンは一度保存したら変更・削除できない（DBレベルでも保証する）
_IMMUTABLE_FORECAST_SQL = """
CREATE OR REPLACE FUNCTION forbid_forecast_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'forecast_versions は不変です（%は禁止）', TG_OP;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS forecast_versions_immutable ON forecast_versions;
CREATE TRIGGER forecast_versions_immutable
  BEFORE UPDATE OR DELETE ON forecast_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_forecast_mutation();
"""


# create_all は既存テーブルに列を追加しないため、追加列はここで補う
_MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS schedule_sources JSON DEFAULT '[]'",
    "ALTER TABLE events ADD COLUMN IF NOT EXISTS schedule_rev INTEGER DEFAULT 0",
]


def init_db(bind=None) -> None:
    from . import models  # noqa: F401  (register tables)

    bind = bind or engine
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql":
        with bind.begin() as conn:
            for m in _MIGRATIONS:
                conn.execute(text(m))
            conn.execute(text(_IMMUTABLE_FORECAST_SQL))
