import argparse
import json

from . import db
from .ingest import run_ingestion
from .vector_store import ensure_collection


def main():
    parser = argparse.ArgumentParser(prog="bhajan-ai")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backfill = sub.add_parser("backfill")
    group = p_backfill.add_mutually_exclusive_group(required=True)
    group.add_argument("--limit", type=int)
    group.add_argument("--all", action="store_true")
    p_backfill.add_argument("--force", action="store_true")

    p_update = sub.add_parser("update")
    p_update.add_argument("--latest", type=int, default=40)
    p_update.add_argument("--force", action="store_true")

    sub.add_parser("stats")

    args = parser.parse_args()
    db.init_db()
    ensure_collection()

    if args.cmd == "backfill":
        limit = None if args.all else args.limit
        result = run_ingestion(
            limit=limit,
            force=args.force,
            mode="backfill",
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "update":
        result = run_ingestion(
            limit=args.latest,
            force=args.force,
            mode="update",
        )
        print(json.dumps(result, indent=2))
    elif args.cmd == "stats":
        print(json.dumps(db.stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
