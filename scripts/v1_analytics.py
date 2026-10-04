#!/usr/bin/env python3

import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(
    dotenv_path=ROOT / ".env",
    override=False,
)

from app.product_db import connection


with connection() as conn:

    def one(sql):
        return conn.execute(sql).fetchone()["value"]

    print("Bhajan Marg AI — V1 analytics")
    print("=" * 44)

    print(
        "Users:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM users
            """
        ),
    )

    print(
        "DAU:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM users
            WHERE last_active >= NOW() - INTERVAL '24 hours'
            """
        ),
    )

    print(
        "Conversations:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM conversations
            """
        ),
    )

    print(
        "Questions:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM messages
            WHERE role='user'
            """
        ),
    )

    print(
        "Helpful:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM feedback
            WHERE rating=1
            """
        ),
    )

    print(
        "Not helpful:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM feedback
            WHERE rating=-1
            """
        ),
    )

    print(
        "No-source answers:",
        one(
            """
            SELECT COUNT(*) AS value
            FROM messages
            WHERE role='assistant'
              AND evidence_level='none'
            """
        ),
    )

    print(
        "Avg response ms:",
        one(
            """
            SELECT
                COALESCE(
                    ROUND(AVG(elapsed_ms)),
                    0
                )::bigint AS value
            FROM messages
            WHERE role='assistant'
              AND elapsed_ms IS NOT NULL
            """
        ),
    )

    print()
    print("Most referenced videos")

    rows = conn.execute(
        """
        SELECT
            video_id,
            MAX(video_title) AS title,
            COUNT(*) AS refs
        FROM message_sources
        WHERE video_id IS NOT NULL
        GROUP BY video_id
        ORDER BY refs DESC
        LIMIT 10
        """
    ).fetchall()

    if not rows:
        print("No referenced videos yet.")
    else:
        for row in rows:
            print(
                f"{row['refs']:>4}  "
                f"{row['title'] or row['video_id']}"
            )
