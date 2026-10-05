import argparse
import json

from . import db
from .ingest import run_ingestion
from .youtube import list_channel_videos
from .vector_store import ensure_collection


CONTENT_TYPES = [
    "video",
    "short",
    "stream",
]


def main():
    parser = argparse.ArgumentParser(
        prog="bhajan-ai"
    )

    sub = parser.add_subparsers(
        dest="cmd",
        required=True,
    )

    # --------------------------------------------------------
    # discover
    # --------------------------------------------------------
    p_discover = sub.add_parser(
        "discover"
    )

    p_discover.add_argument(
        "--type",
        choices=CONTENT_TYPES,
        default=None,
    )

    p_discover.add_argument(
        "--limit",
        type=int,
        default=None,
    )

    # --------------------------------------------------------
    # backfill
    # --------------------------------------------------------
    p_backfill = sub.add_parser(
        "backfill"
    )

    group = (
        p_backfill
        .add_mutually_exclusive_group(
            required=True
        )
    )

    group.add_argument(
        "--limit",
        type=int,
    )

    group.add_argument(
        "--all",
        action="store_true",
    )

    p_backfill.add_argument(
        "--type",
        choices=CONTENT_TYPES,
        default=None,
    )

    p_backfill.add_argument(
        "--force",
        action="store_true",
    )

    # --------------------------------------------------------
    # update
    # --------------------------------------------------------
    p_update = sub.add_parser(
        "update"
    )

    p_update.add_argument(
        "--latest",
        type=int,
        default=40,
    )

    p_update.add_argument(
        "--type",
        choices=CONTENT_TYPES,
        default=None,
    )

    p_update.add_argument(
        "--force",
        action="store_true",
    )

    # --------------------------------------------------------
    # stats
    # --------------------------------------------------------
    sub.add_parser("stats")

    args = parser.parse_args()

    db.init_db()

    # Discovery does not need Qdrant.
    if args.cmd == "discover":
        items = list_channel_videos(
            limit=args.limit,
            content_type=args.type,
        )

        by_type = {}

        for item in items:
            kind = item.get(
                "content_type",
                "video",
            )
            by_type[kind] = (
                by_type.get(kind, 0)
                + 1
            )

        result = {
            "total": len(items),
            "by_type": by_type,
        }

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        return

    if args.cmd == "stats":
        print(
            json.dumps(
                db.stats(),
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    # Actual ingestion requires local Qdrant.
    ensure_collection()

    if args.cmd == "backfill":
        limit = (
            None
            if args.all
            else args.limit
        )

        mode = "backfill"

        if args.type:
            mode += "-" + args.type

        result = run_ingestion(
            limit=limit,
            force=args.force,
            mode=mode,
            content_type=args.type,
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

    elif args.cmd == "update":
        result = run_ingestion(
            limit=args.latest,
            force=args.force,
            mode="update",
            content_type=args.type,
        )

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
