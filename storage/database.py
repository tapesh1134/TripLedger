"""Short-lived, transaction-scoped connections. Never expose a DSN in errors."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


class StorageError(RuntimeError):
    pass


def database_url() -> str:
    load_dotenv(override=False)
    return os.getenv("DATABASE_URL", "").strip()


@contextmanager
def connection() -> Iterator[Any]:
    url = database_url()
    if not url:
        raise StorageError("Set DATABASE_URL and run python -m app.database init")
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as db:
            db.execute("SET LOCAL statement_timeout = '15s'")
            yield db
    except psycopg.Error:
        raise StorageError(
            "PostgreSQL operation failed; check database setup and availability"
        ) from None
