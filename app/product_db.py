from __future__ import annotations


from pathlib import Path
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(
    dotenv_path=_PROJECT_ROOT / ".env",
    override=False,
)

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def configured() -> bool:
    return bool(database_url())


def _raw_connection() -> Connection:
    url = database_url()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not configured. Add a PostgreSQL/Neon connection string "
            "to the Render environment before using accounts or persistent chats."
        )
    return psycopg.connect(url, row_factory=dict_row)


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "migrations" / "001_v1_mvp_postgres.sql"


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        path = _schema_path()
        if not path.exists():
            raise RuntimeError(f"Missing V1 schema migration: {path}")

        sql = path.read_text(encoding="utf-8")
        # This migration intentionally contains only ordinary DDL, so splitting
        # on semicolons is safe and avoids driver differences around multi-query
        # execution.
        statements = []
        buff: list[str] = []
        for line in sql.splitlines():
            stripped = line.strip()
            if stripped.startswith("--"):
                continue
            buff.append(line)
        cleaned = "\n".join(buff)
        for part in cleaned.split(";"):
            stmt = part.strip()
            if stmt:
                statements.append(stmt)

        with _raw_connection() as conn:
            with conn.cursor() as cur:
                for statement in statements:
                    cur.execute(statement)

        _SCHEMA_READY = True


@contextmanager
def connection() -> Iterator[Connection]:
    ensure_schema()
    with _raw_connection() as conn:
        yield conn
