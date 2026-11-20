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
