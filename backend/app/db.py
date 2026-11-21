"""SQLite engine + session helper."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import func
from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)


def create_all() -> None:
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Tiny additive migration: create_all doesn't add new columns to existing tables, so a
    database from before a model change (live demo server, no reseed) gets them via ALTER TABLE."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if isinstance(default, bool):
                    default = int(default)
                dflt = f" DEFAULT {default!r}" if isinstance(default, (str, int, float)) else ""
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{dflt}'))


def drop_all() -> None:
    from . import models  # noqa: F401

    SQLModel.metadata.drop_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine, expire_on_commit=False) as session:
        yield session


def next_id(session: Session, model, prefix: str) -> str:
    """Short sequential ids: case_0001, doc_0002, ..."""
    n = session.exec(select(func.count()).select_from(model)).one()
    while True:
        n += 1
        candidate = f"{prefix}_{n:04d}"
        if session.get(model, candidate) is None:
            return candidate
