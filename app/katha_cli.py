from __future__ import annotations

import argparse
import json
from pathlib import Path

from .katha_local import add_video, list_videos, stats


def _print(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="python -m app.katha_cli",
        description="Local-only Katha V0 catalogue. Never mixes with Premanand Ji retrieval.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="Add one selected Katha video")
    add.add_argument("--speaker", required=True, choices=["indresh_ji", "rajendra_das_ji"])
    add.add_argument("--url", required=True)
    add.add_argument("--series")
    add.add_argument("--event")
    add.add_argument("--day")
    add.add_argument("--location")
    add.add_argument("--katha-type")
    add.add_argument("--with-captions", action="store_true")

    batch = sub.add_parser("add-file", help="Add selected URLs from a text file")
    batch.add_argument("--speaker", required=True, choices=["indresh_ji", "rajendra_das_ji"])
    batch.add_argument("--file", required=True)
    batch.add_argument("--series")
    batch.add_argument("--event")
    batch.add_argument("--location")
    batch.add_argument("--katha-type")
    batch.add_argument("--with-captions", action="store_true")

    ls = sub.add_parser("list", help="List local selected Katha videos")
    ls.add_argument("--speaker", required=True, choices=["indresh_ji", "rajendra_das_ji"])

    sub.add_parser("stats", help="Show isolated Katha V0 local counts")

    args = parser.parse_args()

    if args.cmd == "add":
        _print(
            add_video(
                speaker=args.speaker,
                url=args.url,
                series=args.series,
                event=args.event,
                day=args.day,
                location=args.location,
                katha_type=args.katha_type,
                with_captions=args.with_captions,
            )
        )
        return

    if args.cmd == "add-file":
        path = Path(args.file)
        if not path.exists():
            raise SystemExit(f"File not found: {path}")

        urls = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

        output = []
        for index, url in enumerate(urls, 1):
            try:
                row = add_video(
                    speaker=args.speaker,
                    url=url,
                    series=args.series,
                    event=args.event,
                    day=str(index),
                    location=args.location,
                    katha_type=args.katha_type,
                    with_captions=args.with_captions,
                )
                output.append({"ok": True, "video_id": row["video_id"], "title": row["title"]})
            except Exception as exc:
                output.append({"ok": False, "url": url, "error": str(exc)})

        _print({
            "speaker": args.speaker,
            "requested": len(urls),
            "saved": sum(1 for row in output if row["ok"]),
            "failed": sum(1 for row in output if not row["ok"]),
            "results": output,
        })
        return

    if args.cmd == "list":
        _print(list_videos(args.speaker))
        return

    if args.cmd == "stats":
        _print(stats())
        return


if __name__ == "__main__":
    main()
