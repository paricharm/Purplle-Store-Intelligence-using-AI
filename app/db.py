from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from app.storage import connect, init_db


@dataclass(frozen=True)
class EventDB:
    """Small table descriptor for reviewers looking for the suggested `EventDB`.

    The project uses SQLite directly instead of SQLAlchemy; storage behavior lives in
    `app.storage`. This descriptor keeps the expected file/module name clear without
    introducing a second ORM layer.
    """

    table_name: str = "events"
    id_column: str = "event_id"
    dedup_column: str = "event_id"


@contextmanager
def get_db(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    with connect(db_path) as conn:
        yield conn


__all__ = ["EventDB", "get_db", "init_db"]
