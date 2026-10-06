"""Rebuild local Qdrant chunks using persisted V1.5.1 corpus intelligence.

This is the bridge from offline corpus analysis to the searchable local index.
It never downloads YouTube media and never changes transcript text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import db
from app.chunking import chunk_transcript
from app.config import settings
from app.corpus_enrichment import enrich_chunks
from app.vector_store import delete_video, index_chunks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--require-intelligence", action="store_true")
    args = parser.parse_args()

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
    indexed = skipped = failed = 0

    for i, path in enumerate(paths, 1):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            video = {
                "video_id": doc.get("video_id", path.stem),
                "title": doc.get("title", path.stem),
                "url": doc.get("url", ""),
                "channel": doc.get("channel"),
                "published_at": doc.get("published_at"),
                "content_type": doc.get("content_type", "video"),
            }
            db.upsert_video(video)
            chunks = chunk_transcript(doc.get("segments") or [])
            enriched = enrich_chunks(video, chunks)

            if args.require_intelligence and enriched and not enriched[0].get("search_text"):
                raise RuntimeError("No corpus intelligence artifact found")

            delete_video(video["video_id"])
            rows = index_chunks(video, enriched)
            db.replace_chunks(video["video_id"], rows)
            db.mark_video(
                video["video_id"],
                "indexed",
                transcript_source=doc.get("transcript_source"),
                transcript_hash=doc.get("transcript_hash"),
                transcript_path=str(path),
                error=None,
            )
            indexed += 1
            print(f"[{i}/{len(paths)}] INDEXED {video['video_id']} {video['title']}")
        except Exception as exc:
            failed += 1
            print(f"[{i}/{len(paths)}] FAILED {path.name}: {type(exc).__name__}: {exc}")

    print(f"Done: indexed={indexed} skipped={skipped} failed={failed}")


if __name__ == "__main__":
    main()
