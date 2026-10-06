"""Rebuild the local/Qdrant index using V1.5.1 corpus intelligence.

This script reads already-saved transcript JSON files. It never downloads
YouTube videos.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.chunking import chunk_transcript
from app.config import settings
from app.corpus_enrichment import enrich_chunks
from app import db
from app.vector_store import delete_video, index_chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--require-intelligence", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )

    root = Path(settings.transcript_dir)
    paths = sorted(root.glob("*.json"))

    if args.video_id:
        wanted = set(args.video_id)
        paths = [p for p in paths if p.stem in wanted]
    elif args.limit:
        paths = paths[: args.limit]

    if not paths:
        raise SystemExit(f"No transcripts found under {root}")

    db.init_db()

    ok = failed = 0

    for index, path in enumerate(paths, 1):
        video_id = path.stem

        try:
            doc = json.loads(path.read_text(encoding="utf-8"))

            video = {
                "video_id": doc.get("video_id", video_id),
                "title": doc.get("title", video_id),
                "url": doc.get("url", ""),
                "channel": doc.get("channel"),
                "published_at": doc.get("published_at"),
                "duration_seconds": doc.get("duration_seconds"),
                "content_type": doc.get("content_type", "video"),
            }

            artifact_path = (
                Path(settings.corpus_intelligence_dir)
                / f"{video_id}.json"
            )

            if args.require_intelligence and not artifact_path.exists():
                raise RuntimeError(
                    f"Missing corpus intelligence artifact: {artifact_path}"
                )

            segments = doc.get("segments") or []
            chunks = chunk_transcript(segments)

            if not chunks:
                raise RuntimeError("Transcript produced zero chunks")

            chunks = enrich_chunks(video, chunks)

            delete_video(video_id)

            rows = index_chunks(video, chunks)
            db.replace_chunks(video_id, rows)

            db.mark_video(
                video_id,
                "indexed",
                transcript_source=doc.get("transcript_source"),
                transcript_hash=doc.get("transcript_hash"),
                transcript_path=str(path),
                error=None,
            )

            ok += 1
            print(
                f"[{index}/{len(paths)}] OK "
                f"{video_id} {video['title']}"
            )

        except Exception as exc:
            failed += 1
            logging.exception("Failed reindexing %s", video_id)
            print(
                f"[{index}/{len(paths)}] FAILED "
                f"{path.name}: {type(exc).__name__}: {exc}"
            )

    print(f"Done: ok={ok} failed={failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
