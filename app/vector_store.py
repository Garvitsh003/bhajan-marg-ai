import math
import uuid
from functools import lru_cache
from typing import Any

import numpy as np
from qdrant_client import QdrantClient, models
from sentence_transformers import CrossEncoder, SentenceTransformer

from .config import settings
from .text import lexical_sparse


@lru_cache(maxsize=1)
def embedding_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model)


@lru_cache(maxsize=1)
def reranker_model() -> CrossEncoder:
    return CrossEncoder(settings.reranker_model)


@lru_cache(maxsize=1)
def client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def ensure_collection():
    c = client()
    existing = {x.name for x in c.get_collections().collections}
    if settings.qdrant_collection in existing:
        return

    dim = embedding_model().get_sentence_embedding_dimension()
    c.create_collection(
        collection_name=settings.qdrant_collection,
        vectors_config={
            "dense": models.VectorParams(
                size=dim,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            "lexical": models.SparseVectorParams(
                modifier=models.Modifier.IDF
            )
        },
    )


def stable_point_id(video_id: str, chunk_index: int) -> str:
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"bhajan-marg:{video_id}:{chunk_index}"
    ))


def delete_video(video_id: str):
    ensure_collection()
    client().delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="video_id",
                        match=models.MatchValue(value=video_id),
                    )
                ]
            )
        ),
        wait=True,
    )


def index_chunks(video: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict]:
    ensure_collection()
    if not chunks:
        return []

    texts = [x.get("search_text") or x["text"] for x in chunks]
    dense = embedding_model().encode(
        texts,
        batch_size=16,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    points = []
    rows = []
    for chunk, vector in zip(chunks, dense):
        point_id = stable_point_id(video["video_id"], chunk["chunk_index"])
        payload = {
            "video_id": video["video_id"],
            "title": video["title"],
            "url": video["url"],
            "published_at": video.get("published_at"),
            "content_type": video.get("content_type", "video"),
            "chunk_index": chunk["chunk_index"],
            "start_ms": chunk["start_ms"],
            "end_ms": chunk["end_ms"],
            "segment_start": chunk["segment_start"],
            "segment_end": chunk["segment_end"],
            "text": chunk["text"],
            "search_text": chunk.get("search_text", chunk["text"]),
            "semantic": chunk.get("semantic", {}),
            "caption_segments": chunk.get('caption_segments', []),
        }
        points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    "dense": vector.tolist(),
                    "lexical": lexical_sparse(chunk["text"], query=False),
                },
                payload=payload,
            )
        )
        rows.append({
            "point_id": point_id,
            **chunk,
        })

    for i in range(0, len(points), 64):
        client().upsert(
            collection_name=settings.qdrant_collection,
            points=points[i:i+64],
            wait=True,
        )
    return rows


def hybrid_search(query: str, limit: int | None = None) -> list[dict[str, Any]]:
    ensure_collection()
    limit = limit or settings.fused_candidates
    q_dense = embedding_model().encode(
        query, normalize_embeddings=True
    ).tolist()
    q_sparse = lexical_sparse(query, query=True)

    result = client().query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            models.Prefetch(
                query=q_dense,
                using="dense",
                limit=settings.dense_candidates,
            ),
            models.Prefetch(
                query=q_sparse,
                using="lexical",
                limit=settings.sparse_candidates,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    ).points

    items = []
    for p in result:
        payload = dict(p.payload or {})
        payload["point_id"] = str(p.id)
        payload["fusion_score"] = float(p.score or 0.0)
        items.append(payload)
    return items


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    if not candidates:
        return []
    if not settings.reranker_enabled:
        out = []
        for rank, item in enumerate(candidates[:top_k]):
            # Rank-derived fallback used only when the cross-encoder is disabled.
            # The LLM evidence judge can still downgrade weak/irrelevant matches.
            score = max(0.46, 0.80 - rank * 0.025)
            out.append({
                **item,
                "rerank_logit": None,
                "rerank_score": score,
            })
        return out

    pairs = [(query, x.get("search_text") or (str(x.get("title", "")) + "\n" + x["text"])) for x in candidates]
    raw = reranker_model().predict(pairs, batch_size=16, show_progress_bar=False)
    raw = np.asarray(raw, dtype=float).reshape(-1)

    ranked = []
    for item, score in zip(candidates, raw):
        # mMARCO cross-encoder returns logits. Sigmoid gives a convenient 0..1
        # confidence-like number for evidence gating (not a calibrated probability).
        sig = 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, float(score)))))
        ranked.append({**item, "rerank_logit": float(score), "rerank_score": sig})
    ranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return ranked[:top_k]
