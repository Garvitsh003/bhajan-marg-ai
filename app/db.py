import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import settings

_lock = threading.RLock()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    Path(settings.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.sqlite_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    with _lock:
        conn = connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db():
    with tx() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                channel TEXT,
                published_at TEXT,
                duration_seconds INTEGER,
                content_type TEXT NOT NULL DEFAULT 'video',
                status TEXT NOT NULL DEFAULT 'discovered',
                transcript_source TEXT,
                transcript_hash TEXT,
                transcript_path TEXT,
                error TEXT,
                discovered_at TEXT NOT NULL,
                indexed_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                point_id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL,
                UNIQUE(video_id, chunk_index),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_video
            ON chunks(video_id, chunk_index);

            CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id)
                    REFERENCES conversations(conversation_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id);

            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                discovered INTEGER DEFAULT 0,
                indexed INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                details_json TEXT
            );
            """
        )

        # Non-destructive schema migration for existing installations.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(videos)"
            ).fetchall()
        }

        if "content_type" not in columns:
            conn.execute(
                """
                ALTER TABLE videos
                ADD COLUMN content_type TEXT
                NOT NULL DEFAULT 'video'
                """
            )


def upsert_video(video: dict[str, Any]):
    now = utcnow()
    with tx() as conn:
        conn.execute(
            """
            INSERT INTO videos(
                video_id,title,url,channel,published_at,duration_seconds,
                content_type,status,discovered_at,updated_at
            )
            VALUES(?,?,?,?,?,?,?,'discovered',?,?)
            ON CONFLICT(video_id) DO UPDATE SET
                title=excluded.title,
                url=excluded.url,
                channel=COALESCE(excluded.channel,videos.channel),
                published_at=COALESCE(excluded.published_at,videos.published_at),
                duration_seconds=COALESCE(excluded.duration_seconds,videos.duration_seconds),
                content_type=COALESCE(excluded.content_type,videos.content_type),
                updated_at=excluded.updated_at
            """,
            (
                video["video_id"], video["title"], video["url"],
                video.get("channel"), video.get("published_at"),
                video.get("duration_seconds"),
                video.get("content_type", "video"),
                now,
                now,
            ),
        )


def get_video(video_id: str):
    with tx() as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id=?", (video_id,)
        ).fetchone()
        return dict(row) if row else None


def is_indexed(video_id: str, transcript_hash: str | None = None) -> bool:
    v = get_video(video_id)
    if not v or v["status"] != "indexed":
        return False
    if transcript_hash is not None:
        return v.get("transcript_hash") == transcript_hash
    return True


def mark_video(
    video_id: str,
    status: str,
    *,
    transcript_source: str | None = None,
    transcript_hash: str | None = None,
    transcript_path: str | None = None,
    error: str | None = None,
):
    now = utcnow()
    with tx() as conn:
        conn.execute(
            """
            UPDATE videos SET
                status=?,
                transcript_source=COALESCE(?,transcript_source),
                transcript_hash=COALESCE(?,transcript_hash),
                transcript_path=COALESCE(?,transcript_path),
                error=?,
                indexed_at=CASE WHEN ?='indexed' THEN ? ELSE indexed_at END,
                updated_at=?
            WHERE video_id=?
            """,
            (
                status, transcript_source, transcript_hash, transcript_path,
                error, status, now, now, video_id
            ),
        )


def replace_chunks(video_id: str, rows: list[dict[str, Any]]):
    with tx() as conn:
        conn.execute("DELETE FROM chunks WHERE video_id=?", (video_id,))
        conn.executemany(
            """
            INSERT INTO chunks(
                point_id,video_id,chunk_index,start_ms,end_ms,text
            ) VALUES(?,?,?,?,?,?)
            """,
            [
                (
                    r["point_id"], video_id, r["chunk_index"],
                    r["start_ms"], r["end_ms"], r["text"]
                )
                for r in rows
            ],
        )


def get_neighbor_context(
    video_id: str, chunk_index: int, radius: int = 1
) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chunks
            WHERE video_id=? AND chunk_index BETWEEN ? AND ?
            ORDER BY chunk_index
            """,
            (video_id, chunk_index - radius, chunk_index + radius),
        ).fetchall()
        return [dict(r) for r in rows]


def ensure_conversation(conversation_id: str):
    now = utcnow()
    with tx() as conn:
        conn.execute(
            """
            INSERT INTO conversations(conversation_id,created_at,updated_at)
            VALUES(?,?,?)
            ON CONFLICT(conversation_id)
            DO UPDATE SET updated_at=excluded.updated_at
            """,
            (conversation_id, now, now),
        )


def add_message(
    conversation_id: str, role: str, content: str, metadata: dict | None = None
):
    ensure_conversation(conversation_id)
    with tx() as conn:
        conn.execute(
            """
            INSERT INTO messages(
                conversation_id,role,content,metadata_json,created_at
            ) VALUES(?,?,?,?,?)
            """,
            (
                conversation_id, role, content,
                json.dumps(metadata or {}, ensure_ascii=False), utcnow()
            ),
        )


def get_messages(conversation_id: str, limit: int = 8) -> list[dict[str, Any]]:
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT role,content,metadata_json,created_at
            FROM messages WHERE conversation_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()
        out = []
        for r in reversed(rows):
            d = dict(r)
            d["metadata"] = json.loads(d.pop("metadata_json") or "{}")
            out.append(d)
        return out


def stats() -> dict[str, Any]:
    with tx() as conn:
        video_rows = conn.execute(
            "SELECT status,COUNT(*) n FROM videos GROUP BY status"
        ).fetchall()
        total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {
            "videos": {r["status"]: r["n"] for r in video_rows},
            "chunks": total_chunks,
        }


def start_run(mode: str) -> int:
    with tx() as conn:
        cur = conn.execute(
            "INSERT INTO ingestion_runs(mode,started_at) VALUES(?,?)",
            (mode, utcnow()),
        )
        return int(cur.lastrowid)


def finish_run(run_id: int, counts: dict, details: dict | None = None):
    with tx() as conn:
        conn.execute(
            """
            UPDATE ingestion_runs SET
                finished_at=?,discovered=?,indexed=?,skipped=?,failed=?,
                details_json=?
            WHERE id=?
            """,
            (
                utcnow(),
                counts.get("discovered", 0),
                counts.get("indexed", 0),
                counts.get("skipped", 0),
                counts.get("failed", 0),
                json.dumps(details or {}, ensure_ascii=False),
                run_id,
            ),
        )
