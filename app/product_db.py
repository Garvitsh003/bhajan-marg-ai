from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
import psycopg
from psycopg import Connection
from psycopg.rows import dict_row


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(
    dotenv_path=_PROJECT_ROOT / ".env",
    override=False,
)

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


def _migration_paths() -> list[Path]:
    migration_dir = _PROJECT_ROOT / "migrations"
    if not migration_dir.exists():
        raise RuntimeError(f"Missing migrations directory: {migration_dir}")

    paths = sorted(
        path
        for path in migration_dir.glob("*.sql")
        if path.is_file()
    )
    if not paths:
        raise RuntimeError(f"No SQL migrations found in: {migration_dir}")
    return paths


def _statements_from_sql(path: Path) -> list[str]:
    sql = path.read_text(encoding="utf-8")

    # Project migrations intentionally contain ordinary DDL only. Keeping the
    # parser small and deterministic also lets old deployments self-upgrade on
    # the next process start without a provider-specific migration framework.
    buff: list[str] = []
    for line in sql.splitlines():
        if line.strip().startswith("--"):
            continue
        buff.append(line)

    cleaned = "\n".join(buff)
    return [
        part.strip()
        for part in cleaned.split(";")
        if part.strip()
    ]


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        with _raw_connection() as conn:
            with conn.cursor() as cur:
                # Every migration is idempotent (CREATE ... IF NOT EXISTS /
                # ALTER ... IF NOT EXISTS), so existing installations can safely
                # execute the full ordered set at startup.
                for path in _migration_paths():
                    for statement in _statements_from_sql(path):
                        cur.execute(statement)

        _SCHEMA_READY = True


@contextmanager
def connection() -> Iterator[Connection]:
    ensure_schema()
    with _raw_connection() as conn:
        yield conn
