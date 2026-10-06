"""Build V1.5.1 semantic understanding for all locally saved transcripts.

Examples:
  python -m scripts.build_corpus_intelligence --limit 20
  python -m scripts.build_corpus_intelligence --video-id 5vzzUFSo_E4 --force

The command never downloads videos. It only reads data/transcripts/*.json.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.config import settings
from app.corpus_intelligence import build_video_artifact
from app.llm import ollama_chat


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--group-size", type=int, default=8)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    root = Path(settings.transcript_dir)
    paths = sorted(root.glob("*.json"))
    if args.video_id:
        wanted = set(args.video_id)
        paths = [p for p in paths if p.stem in wanted]
    elif args.limit:
        paths = paths[: args.limit]

    if not paths:
        raise SystemExit(f"No transcripts found under {root}")

    ok = failed = 0

    for index, path in enumerate(paths, 1):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            video = {
                "video_id": doc.get("video_id", path.stem),
                "title": doc.get("title", path.stem),
                "url": doc.get("url", ""),
                "channel": doc.get("channel"),
                "published_at": doc.get("published_at"),
                "content_type": doc.get("content_type", "video"),
                "transcript_hash": doc.get("transcript_hash"),
            }
            # Existing transcript artifacts from this repo may not carry a
            # hash, so the builder still works and can be force-refreshed.
            build_video_artifact(
                video,
                doc.get("segments") or [],
                llm_call=ollama_chat,
                group_size=max(1, args.group_size),
                force=args.force,
            )
            ok += 1
            print(f"[{index}/{len(paths)}] OK {video['video_id']} {video['title']}")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(paths)}] FAILED {path.name}: {type(exc).__name__}: {exc}")

    print(f"Done: ok={ok} failed={failed}")


if __name__ == "__main__":
    main()
