import logging
from typing import Any

from . import db
from .chunking import chunk_transcript
from .youtube import enrich_video, get_or_create_transcript, list_channel_videos
from .vector_store import delete_video, index_chunks

log = logging.getLogger(__name__)


def ingest_one(video: dict[str, Any], force: bool = False) -> str:
    db.upsert_video(video)
    current = db.get_video(video["video_id"])
    if current and current["status"] == "indexed" and not force:
        return "skipped"

    try:
        video = enrich_video(video)
        db.upsert_video(video)
        db.mark_video(video["video_id"], "processing")

        segments, source, path, digest = get_or_create_transcript(video)

        # If forcing a refresh but transcript content is unchanged, keep index.
        current = db.get_video(video["video_id"])
        if current and current.get("transcript_hash") == digest and current["status"] == "indexed":
            return "skipped"

        chunks = chunk_transcript(segments)
        if not chunks:
            raise RuntimeError("Transcript produced zero chunks")

        delete_video(video["video_id"])
        rows = index_chunks(video, chunks)
        db.replace_chunks(video["video_id"], rows)
        db.mark_video(
            video["video_id"],
            "indexed",
            transcript_source=source,
            transcript_hash=digest,
            transcript_path=path,
            error=None,
        )
        return "indexed"
    except Exception as e:
        log.exception("Failed ingesting %s", video["video_id"])
        db.mark_video(video["video_id"], "failed", error=str(e))
        return "failed"


def run_ingestion(
    *,
    limit: int | None = None,
    force: bool = False,
    mode: str = "backfill",
    content_type: str | None = None,
) -> dict:
    db.init_db()
    run_id = db.start_run(mode)
    counts = {"discovered": 0, "indexed": 0, "skipped": 0, "failed": 0}

    try:
        videos = list_channel_videos(
            limit=limit,
            content_type=content_type,
        )
        counts["discovered"] = len(videos)

        for n, video in enumerate(videos, 1):
            print(f"[{n}/{len(videos)}] {video['title']}")
            result = ingest_one(video, force=force)
            counts[result] += 1
            print(f"    -> {result}")
        return counts
    finally:
        db.finish_run(run_id, counts)
