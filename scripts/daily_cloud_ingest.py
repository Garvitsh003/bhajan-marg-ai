"""Discover new channel uploads and index transcript chunks into Qdrant Cloud.

This job is deliberately gated by TRANSCRIPT_USE_AUTHORIZED=true. Publicly
visible captions do not by themselves grant redistribution rights.
"""
import argparse
import json
import os
import sys
import uuid


def point_id_for(video_id: str, chunk_index: int) -> str:
    """Match the deterministic IDs used by the local indexer."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"bhajan-marg:{video_id}:{chunk_index}"))


def video_is_indexed(client, collection: str, video_id: str) -> bool:
    from qdrant_client import models

    result = client.count(
        collection_name=collection,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="video_id",
                    match=models.MatchValue(value=video_id),
                )
            ]
        ),
        exact=True,
    )
    return result.count > 0


def build_points(video, chunks, transcript_source, dense_model, sparse_model):
    from qdrant_client import models

    points = []
    for chunk in chunks:
        payload = {
            "video_id": video["video_id"],
            "title": video["title"],
            "url": video["url"],
            "published_at": video.get("published_at"),
            "content_type": video.get("content_type", "video"),
            "channel": video.get("channel", "Bhajan Marg"),
            "chunk_index": chunk["chunk_index"],
            "start_ms": chunk["start_ms"],
            "end_ms": chunk["end_ms"],
            "segment_start": chunk["segment_start"],
            "segment_end": chunk["segment_end"],
            "text": chunk["text"],
            "caption_segments": chunk.get("caption_segments", []),
            "transcript_source": transcript_source,
        }
        points.append(
            models.PointStruct(
                id=point_id_for(video["video_id"], chunk["chunk_index"]),
                payload=payload,
                vector={
                    "dense_vector": models.Document(
                        text=chunk["text"],
                        model=dense_model,
                    ),
                    "bm25_sparse_vector": models.Document(
                        text=chunk["text"],
                        model=sparse_model,
                    ),
                },
            )
        )
    return points


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latest", type=int, default=40)
    args = parser.parse_args()

    if os.getenv("TRANSCRIPT_USE_AUTHORIZED", "").strip().lower() != "true":
        raise SystemExit(
            "Blocked: set the repository variable TRANSCRIPT_USE_AUTHORIZED=true "
            "only after confirming you have permission to store and serve these transcripts."
        )
    if args.latest < 1 or args.latest > 200:
        raise SystemExit("--latest must be between 1 and 200")

    qdrant_url = os.getenv("QDRANT_URL", "").strip()
    qdrant_key = os.getenv("QDRANT_API_KEY", "").strip()
    collection = os.getenv("QDRANT_COLLECTION", "").strip()
    if not qdrant_url or not qdrant_key or not collection:
        raise SystemExit("Missing QDRANT_URL, QDRANT_API_KEY, or QDRANT_COLLECTION.")

    from qdrant_client import QdrantClient
    from app.chunking import chunk_transcript
    from app.config import settings
    from app.youtube import enrich_video, get_or_create_transcript, list_channel_videos

    dense_model = os.getenv("QDRANT_DENSE_MODEL", "sentence-transformers/all-minilm-l6-v2")
    sparse_model = os.getenv("QDRANT_BM25_MODEL", "qdrant/bm25")
    client = QdrantClient(
        url=qdrant_url,
        api_key=qdrant_key,
        cloud_inference=True,
        timeout=120,
    )

    counts = {"discovered": 0, "indexed": 0, "skipped": 0, "failed": 0}
    errors = []
    videos = list_channel_videos(limit=args.latest)
    counts["discovered"] = len(videos)

    for number, discovered in enumerate(videos, 1):
        video_id = discovered["video_id"]
        title = discovered.get("title") or video_id
        try:
            if video_is_indexed(client, collection, video_id):
                counts["skipped"] += 1
                print(f"[{number}/{len(videos)}] SKIP {video_id} — already indexed", flush=True)
                continue

            video = enrich_video(discovered)
            segments, transcript_source, _path, _digest = get_or_create_transcript(video)
            chunks = chunk_transcript(segments)
            if not chunks:
                raise RuntimeError("Transcript produced zero searchable chunks")

            points = build_points(video, chunks, transcript_source, dense_model, sparse_model)
            client.upload_points(
                collection_name=collection,
                points=points,
                batch_size=8,
                wait=True,
            )
            counts["indexed"] += 1
            print(
                f"[{number}/{len(videos)}] INDEXED {video_id} — "
                f"{len(chunks)} chunks ({transcript_source})",
                flush=True,
            )
        except Exception as exc:
            counts["failed"] += 1
            errors.append({"video_id": video_id, "title": title, "error": type(exc).__name__})
            print(f"[{number}/{len(videos)}] FAILED {video_id}: {type(exc).__name__}", flush=True)

    summary = {"counts": counts, "errors": errors, "collection": collection}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## Daily transcript ingestion\n\n")
            handle.write("| Discovered | Indexed | Skipped | Failed |\n|---:|---:|---:|---:|\n")
            handle.write(
                f"| {counts['discovered']} | {counts['indexed']} | "
                f"{counts['skipped']} | {counts['failed']} |\n"
            )
            if errors:
                handle.write("\n### Failed videos\n")
                for item in errors:
                    handle.write(f"- `{item['video_id']}` — {item['error']}\n")

    if counts["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
