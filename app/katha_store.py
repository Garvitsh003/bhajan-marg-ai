from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings


SPEAKERS: dict[str, dict[str, str]] = {
    "indresh_ji": {
        "display_name": "Indresh Ji Maharaj",
        "source_type": "katha_interpretation",
        "qdrant_collection": "katha_indresh_ji",
    },
    "rajendra_das_ji": {
        "display_name": "Rajendra Das Ji Maharaj",
        "source_type": "katha_interpretation",
        "qdrant_collection": "katha_rajendra_das_ji",
    },
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_speaker(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "indresh": "indresh_ji",
        "indreshji": "indresh_ji",
        "indresh_ji_maharaj": "indresh_ji",
        "rajendra": "rajendra_das_ji",
        "rajendra_das": "rajendra_das_ji",
        "rajendradas": "rajendra_das_ji",
        "rajendra_das_ji_maharaj": "rajendra_das_ji",
    }
    key = aliases.get(key, key)
    if key not in SPEAKERS:
        raise ValueError(
            "speaker must be one of: indresh_ji, rajendra_das_ji"
        )
    return key


def katha_root() -> Path:
    configured = getattr(settings, "katha_data_dir", "./data/katha")
    return Path(configured)


def speaker_root(speaker: str) -> Path:
    return katha_root() / normalize_speaker(speaker)


def paths_for(speaker: str) -> dict[str, Path]:
    root = speaker_root(speaker)
    return {
        "root": root,
        "db": root / "catalog.sqlite3",
        "metadata": root / "metadata",
        "transcripts": root / "transcripts",
        "segments": root / "segments",
        "summaries": root / "summaries",
        "exports": root / "exports",
    }


def ensure_speaker_dirs(speaker: str) -> dict[str, Path]:
    paths = paths_for(speaker)
    for key, path in paths.items():
        if key != "db":
            path.mkdir(parents=True, exist_ok=True)
    return paths


@contextmanager
def connect(speaker: str) -> Iterator[sqlite3.Connection]:
    paths = ensure_speaker_dirs(speaker)
    conn = sqlite3.connect(paths["db"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_store(speaker: str) -> None:
    speaker = normalize_speaker(speaker)
    with connect(speaker) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                channel TEXT,
                published_at TEXT,
                duration_seconds INTEGER,

                speaker TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'katha_interpretation',

                series TEXT,
                event TEXT,
                day INTEGER,
                location TEXT,
                katha_type TEXT,
                playlist TEXT,
                description TEXT,

                status TEXT NOT NULL DEFAULT 'seeded',
                transcript_source TEXT,
                transcript_hash TEXT,
                transcript_path TEXT,
                metadata_path TEXT,
                error TEXT,

                added_at TEXT NOT NULL,
                transcribed_at TEXT,
                segmented_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_katha_videos_status
            ON videos(status, updated_at);

            CREATE INDEX IF NOT EXISTS idx_katha_videos_series
            ON videos(series, event, day);

            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,

                primary_story TEXT,
                substory TEXT,
                characters_json TEXT NOT NULL DEFAULT '[]',
                concepts_json TEXT NOT NULL DEFAULT '[]',
                scripture_referenced TEXT,

                transcript TEXT NOT NULL,
                short_summary TEXT,
                detailed_summary TEXT,
                source_url TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                UNIQUE(video_id, segment_index),
                FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_katha_segments_story
            ON segments(primary_story, substory);

            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                discovered INTEGER NOT NULL DEFAULT 0,
                transcribed INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                details_json TEXT
            );
            """
        )


def init_all() -> None:
    for speaker in SPEAKERS:
        init_store(speaker)


_VIDEO_PATTERNS = (
    re.compile(r"(?:youtube\.com/watch\?[^#]*v=)([A-Za-z0-9_-]{6,})"),
    re.compile(r"(?:youtu\.be/)([A-Za-z0-9_-]{6,})"),
    re.compile(r"(?:youtube\.com/(?:shorts|live)/)([A-Za-z0-9_-]{6,})"),
)


def video_id_from_url(url: str) -> str:
    value = str(url or "").strip()
    for pattern in _VIDEO_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    raise ValueError(
        "Could not extract a YouTube video ID. Use a standard watch, youtu.be, shorts, or live URL."
    )


def add_video(
    speaker: str,
    *,
    url: str,
    title: str | None = None,
    series: str | None = None,
    event: str | None = None,
    day: int | None = None,
    location: str | None = None,
    katha_type: str | None = None,
    playlist: str | None = None,
) -> dict[str, Any]:
    speaker = normalize_speaker(speaker)
    init_store(speaker)

    video_id = video_id_from_url(url)
    now = utcnow()
    source_type = SPEAKERS[speaker]["source_type"]

    with connect(speaker) as conn:
        conn.execute(
            """
            INSERT INTO videos(
                video_id,url,title,speaker,source_type,
                series,event,day,location,katha_type,playlist,
                status,added_at,updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,'seeded',?,?)
            ON CONFLICT(video_id) DO UPDATE SET
                url=excluded.url,
                title=COALESCE(excluded.title,videos.title),
                series=COALESCE(excluded.series,videos.series),
                event=COALESCE(excluded.event,videos.event),
                day=COALESCE(excluded.day,videos.day),
                location=COALESCE(excluded.location,videos.location),
                katha_type=COALESCE(excluded.katha_type,videos.katha_type),
                playlist=COALESCE(excluded.playlist,videos.playlist),
                updated_at=excluded.updated_at
            """,
            (
                video_id,
                url,
                title,
                speaker,
                source_type,
                series,
                event,
                day,
                location,
                katha_type,
                playlist,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
    return dict(row)


def list_videos(
    speaker: str,
    *,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    speaker = normalize_speaker(speaker)
    init_store(speaker)

    sql = "SELECT * FROM videos"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY added_at ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(1, int(limit)))

    with connect(speaker) as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(row) for row in rows]


def get_video(speaker: str, video_id: str) -> dict[str, Any] | None:
    speaker = normalize_speaker(speaker)
    init_store(speaker)
    with connect(speaker) as conn:
        row = conn.execute(
            "SELECT * FROM videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
    return dict(row) if row else None


def save_metadata(speaker: str, video: dict[str, Any]) -> str:
    speaker = normalize_speaker(speaker)
    paths = ensure_speaker_dirs(speaker)
    path = paths["metadata"] / f"{video['video_id']}.json"
    path.write_text(
        json.dumps(video, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)


def save_transcript(
    speaker: str,
    video: dict[str, Any],
    segments: list[dict[str, Any]],
    transcript_source: str,
) -> tuple[str, str]:
    speaker = normalize_speaker(speaker)
    paths = ensure_speaker_dirs(speaker)

    doc = {
        "schema_version": 1,
        "source_family": "katha",
        "source_type": SPEAKERS[speaker]["source_type"],
        "speaker_slug": speaker,
        "speaker": SPEAKERS[speaker]["display_name"],
        "video_id": video["video_id"],
        "title": video.get("title"),
        "url": video["url"],
        "channel": video.get("channel"),
        "published_at": video.get("published_at"),
        "duration_seconds": video.get("duration_seconds"),
        "series": video.get("series"),
        "event": video.get("event"),
        "day": video.get("day"),
        "location": video.get("location"),
        "katha_type": video.get("katha_type"),
        "playlist": video.get("playlist"),
        "transcript_source": transcript_source,
        "segments": segments,
    }

    serialized = json.dumps(
        doc,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    path = paths["transcripts"] / f"{video['video_id']}.json"
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path), digest


def mark_video(
    speaker: str,
    video_id: str,
    *,
    status: str,
    metadata_path: str | None = None,
    transcript_path: str | None = None,
    transcript_source: str | None = None,
    transcript_hash: str | None = None,
    error: str | None = None,
) -> None:
    speaker = normalize_speaker(speaker)
    now = utcnow()

    with connect(speaker) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status=?,
                metadata_path=COALESCE(?,metadata_path),
                transcript_path=COALESCE(?,transcript_path),
                transcript_source=COALESCE(?,transcript_source),
                transcript_hash=COALESCE(?,transcript_hash),
                error=?,
                transcribed_at=CASE
                    WHEN ?='transcribed' THEN COALESCE(transcribed_at,?)
                    ELSE transcribed_at
                END,
                segmented_at=CASE
                    WHEN ?='segmented' THEN COALESCE(segmented_at,?)
                    ELSE segmented_at
                END,
                updated_at=?
            WHERE video_id=?
            """,
            (
                status,
                metadata_path,
                transcript_path,
                transcript_source,
                transcript_hash,
                error,
                status,
                now,
                status,
                now,
                now,
                video_id,
            ),
        )


def replace_segments(
    speaker: str,
    video_id: str,
    segments: list[dict[str, Any]],
) -> None:
    speaker = normalize_speaker(speaker)
    now = utcnow()

    with connect(speaker) as conn:
        conn.execute(
            "DELETE FROM segments WHERE video_id=?",
            (video_id,),
        )

        for i, segment in enumerate(segments):
            conn.execute(
                """
                INSERT INTO segments(
                    video_id,segment_index,start_ms,end_ms,
                    primary_story,substory,characters_json,concepts_json,
                    scripture_referenced,transcript,short_summary,
                    detailed_summary,source_url,status,created_at,updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    video_id,
                    int(segment.get("segment_index", i)),
                    int(segment["start_ms"]),
                    int(segment["end_ms"]),
                    segment.get("primary_story"),
                    segment.get("substory"),
                    json.dumps(segment.get("characters") or [], ensure_ascii=False),
                    json.dumps(segment.get("concepts") or [], ensure_ascii=False),
                    segment.get("scripture_referenced"),
                    segment.get("transcript") or "",
                    segment.get("short_summary"),
                    segment.get("detailed_summary"),
                    segment["source_url"],
                    segment.get("status", "draft"),
                    now,
                    now,
                ),
            )

    mark_video(speaker, video_id, status="segmented")


def stats(speaker: str) -> dict[str, Any]:
    speaker = normalize_speaker(speaker)
    init_store(speaker)

    with connect(speaker) as conn:
        rows = conn.execute(
            "SELECT status,COUNT(*) AS n FROM videos GROUP BY status"
        ).fetchall()
        segments = conn.execute(
            "SELECT COUNT(*) AS n FROM segments"
        ).fetchone()["n"]

    return {
        "speaker": speaker,
        "display_name": SPEAKERS[speaker]["display_name"],
        "root": str(speaker_root(speaker)),
        "qdrant_collection_reserved": SPEAKERS[speaker]["qdrant_collection"],
        "videos": {row["status"]: row["n"] for row in rows},
        "segments": segments,
    }


def stats_all() -> dict[str, Any]:
    return {speaker: stats(speaker) for speaker in SPEAKERS}
