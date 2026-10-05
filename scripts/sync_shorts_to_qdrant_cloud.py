import os
import argparse

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models


load_dotenv()


DENSE_VECTOR = "dense_vector"
SPARSE_VECTOR = "bm25_sparse_vector"

DENSE_MODEL = os.getenv(
    "QDRANT_DENSE_MODEL",
    "sentence-transformers/all-minilm-l6-v2",
)

BM25_MODEL = os.getenv(
    "QDRANT_BM25_MODEL",
    "qdrant/bm25",
)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()

    if not value:
        raise SystemExit(
            f"❌ Missing required environment variable: {name}"
        )

    return value


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--batch-size",
        type=int,
        default=8,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Local
    # --------------------------------------------------------

    local_url = os.getenv(
        "QDRANT_URL",
        "http://localhost:6333",
    )

    local_collection = os.getenv(
        "QDRANT_COLLECTION",
        "bhajan_marg_chunks",
    )

    # --------------------------------------------------------
    # Cloud
    # --------------------------------------------------------

    cloud_url = require_env(
        "CLOUD_QDRANT_URL"
    )

    cloud_key = require_env(
        "CLOUD_QDRANT_API_KEY"
    )

    cloud_collection = os.getenv(
        "CLOUD_QDRANT_COLLECTION",
        "bhajan_marg_chunks_cloud_v1",
    )

    local = QdrantClient(
        url=local_url,
        timeout=60,
    )

    cloud = QdrantClient(
        url=cloud_url,
        api_key=cloud_key,
        cloud_inference=True,
        timeout=120,
    )

    # --------------------------------------------------------
    # Safety checks
    # --------------------------------------------------------

    local_names = {
        x.name
        for x in local.get_collections().collections
    }

    if local_collection not in local_names:
        raise SystemExit(
            f"❌ Local collection not found: {local_collection}"
        )

    cloud_names = {
        x.name
        for x in cloud.get_collections().collections
    }

    if cloud_collection not in cloud_names:
        raise SystemExit(
            f"❌ Cloud collection not found: {cloud_collection}"
        )

    print()
    print("LOCAL")
    print(" collection:", local_collection)

    print()
    print("CLOUD")
    print(" collection:", cloud_collection)

    print()
    print("FILTER")
    print(" content_type = short")

    # Qdrant Cloud requires indexed payload fields for
    # efficient filtered count/search/delete operations.
    for field in ("content_type", "video_id"):
        try:
            cloud.create_payload_index(
                collection_name=cloud_collection,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )
        except Exception as exc:
            # Existing indexes are fine. Verification below
            # will still fail if an actual index problem remains.
            print(
                f"Payload index {field}: {type(exc).__name__}"
            )

    short_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="content_type",
                match=models.MatchValue(
                    value="short"
                ),
            )
        ]
    )

    # --------------------------------------------------------
    # Count local Shorts chunks
    # --------------------------------------------------------

    short_count = local.count(
        collection_name=local_collection,
        count_filter=short_filter,
        exact=True,
    ).count

    print()
    print(
        "Local Shorts chunks:",
        short_count,
    )

    if short_count == 0:
        raise SystemExit(
            "❌ No content_type=short points found locally"
        )

    cloud_before = cloud.count(
        collection_name=cloud_collection,
        exact=True,
    ).count

    print(
        "Cloud chunks before:",
        cloud_before,
    )

    if args.dry_run:
        print()
        print("✅ Dry run successful")
        print(
            "No cloud data was changed."
        )
        return

    # --------------------------------------------------------
    # Upload only Shorts
    # --------------------------------------------------------

    offset = None
    uploaded = 0

    while True:
        points, next_offset = local.scroll(
            collection_name=local_collection,
            scroll_filter=short_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        upload = []

        for point in points:
            payload = dict(
                point.payload or {}
            )

            text = str(
                payload.get(
                    "text",
                    ""
                )
            ).strip()

            if not text:
                continue

            upload.append(
                models.PointStruct(
                    id=point.id,
                    payload=payload,
                    vector={
                        DENSE_VECTOR:
                            models.Document(
                                text=text,
                                model=DENSE_MODEL,
                            ),

                        SPARSE_VECTOR:
                            models.Document(
                                text=text,
                                model=BM25_MODEL,
                            ),
                    },
                )
            )

        if upload:
            cloud.upload_points(
                collection_name=cloud_collection,
                points=upload,
                batch_size=args.batch_size,
                wait=True,
            )

            uploaded += len(upload)

            print(
                f"Uploaded {uploaded}/{short_count} short chunks"
            )

        if next_offset is None:
            break

        offset = next_offset

    # --------------------------------------------------------
    # Verify
    # --------------------------------------------------------

    cloud_after = cloud.count(
        collection_name=cloud_collection,
        exact=True,
    ).count

    cloud_short_count = cloud.count(
        collection_name=cloud_collection,
        count_filter=short_filter,
        exact=True,
    ).count

    print()
    print("=" * 60)
    print("✅ SHORTS CLOUD SYNC COMPLETE")
    print("=" * 60)

    print(
        "Uploaded this run:",
        uploaded,
    )

    print(
        "Cloud Shorts chunks:",
        cloud_short_count,
    )

    print(
        "Cloud total before:",
        cloud_before,
    )

    print(
        "Cloud total after:",
        cloud_after,
    )


if __name__ == "__main__":
    main()
