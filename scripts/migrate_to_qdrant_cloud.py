import argparse
import os

from qdrant_client import QdrantClient, models


DENSE_VECTOR = "dense_vector"
SPARSE_VECTOR = "bm25_sparse_vector"
DENSE_MODEL = os.getenv(
    "QDRANT_DENSE_MODEL",
    "sentence-transformers/all-minilm-l6-v2",
)
BM25_MODEL = os.getenv("QDRANT_BM25_MODEL", "qdrant/bm25")


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def ensure_cloud_collection(
    client: QdrantClient,
    collection: str,
    *,
    recreate: bool,
):
    existing = {x.name for x in client.get_collections().collections}

    if collection in existing and recreate:
        print(f"Deleting existing cloud collection: {collection}")
        client.delete_collection(collection_name=collection)
        existing.remove(collection)

    if collection in existing:
        print(f"Cloud collection already exists: {collection}")
        return

    print(f"Creating cloud collection: {collection}")
    client.create_collection(
        collection_name=collection,
        vectors_config={
            DENSE_VECTOR: models.VectorParams(
                size=384,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            SPARSE_VECTOR: models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            )
        },
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    local_url = os.getenv("LOCAL_QDRANT_URL", "http://localhost:6333")
    local_collection = os.getenv(
        "LOCAL_QDRANT_COLLECTION",
        "bhajan_marg_chunks",
    )

    cloud_url = require_env("CLOUD_QDRANT_URL")
    cloud_key = require_env("CLOUD_QDRANT_API_KEY")
    cloud_collection = os.getenv(
        "CLOUD_QDRANT_COLLECTION",
        "bhajan_marg_chunks_cloud_v1",
    )

    local = QdrantClient(url=local_url, timeout=60)
    cloud = QdrantClient(
        url=cloud_url,
        api_key=cloud_key,
        cloud_inference=True,
        timeout=90,
    )

    print("Local collection:", local_collection)
    print("Cloud collection:", cloud_collection)
    print("Dense model:", DENSE_MODEL)
    print("Sparse model:", BM25_MODEL)

    ensure_cloud_collection(
        cloud,
        cloud_collection,
        recreate=args.recreate,
    )

    offset = None
    total = 0

    while True:
        points, next_offset = local.scroll(
            collection_name=local_collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        if not points:
            break

        upload = []

        for point in points:
            payload = dict(point.payload or {})
            text = str(payload.get("text", "")).strip()
            if not text:
                continue

            upload.append(
                models.PointStruct(
                    id=point.id,
                    payload=payload,
                    vector={
                        DENSE_VECTOR: models.Document(
                            text=text,
                            model=DENSE_MODEL,
                        ),
                        SPARSE_VECTOR: models.Document(
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
            total += len(upload)
            print(f"Uploaded {total} chunks")

        if next_offset is None:
            break

        offset = next_offset

    print()
    print("Migration complete")
    print("Total cloud chunks:", total)

    count = cloud.count(
        collection_name=cloud_collection,
        exact=True,
    ).count
    print("Verified Qdrant Cloud count:", count)


if __name__ == "__main__":
    main()
