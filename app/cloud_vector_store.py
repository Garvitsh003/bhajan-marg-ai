import json
import os
import re
from functools import lru_cache
from typing import Any

from qdrant_client import QdrantClient, models

from .cloud_llm import gemini_chat
from .config import settings
from .budget import remaining_timeout


DENSE_VECTOR = "dense_vector"
SPARSE_VECTOR = "bm25_sparse_vector"


def _dense_model() -> str:
    return os.getenv(
        "QDRANT_DENSE_MODEL",
        "sentence-transformers/all-minilm-l6-v2",
    )


def _bm25_model() -> str:
    return os.getenv("QDRANT_BM25_MODEL", "qdrant/bm25")


def _collection() -> str:
    return os.getenv(
        "QDRANT_COLLECTION",
        getattr(settings, "qdrant_collection", "bhajan_marg_chunks_cloud_v1"),
    )


@lru_cache(maxsize=1)
def client() -> QdrantClient:
    url = os.getenv("QDRANT_URL", "").strip()
    api_key = os.getenv("QDRANT_API_KEY", "").strip()

    if not url:
        raise RuntimeError("QDRANT_URL is not configured")
    if not api_key:
        raise RuntimeError("QDRANT_API_KEY is not configured")

    return QdrantClient(
        url=url,
        api_key=api_key,
        cloud_inference=True,
        timeout=settings.qdrant_timeout_seconds,
    )


def ensure_collection():
    c = client()
    name = _collection()

    existing = {x.name for x in c.get_collections().collections}
    if name in existing:
        return

    c.create_collection(
        collection_name=name,
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


def hybrid_search(
    query: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    fused_limit = int(
        limit
        or getattr(settings, "fused_candidates", 50)
        or 50
    )

    dense_limit = int(
        getattr(settings, "dense_candidates", 40)
        or 40
    )
    sparse_limit = int(
        getattr(settings, "sparse_candidates", 40)
        or 40
    )

    result = client().query_points(
        collection_name=_collection(),
        prefetch=[
            models.Prefetch(
                query=models.Document(
                    text=query,
                    model=_dense_model(),
                ),
                using=DENSE_VECTOR,
                limit=dense_limit,
            ),
            models.Prefetch(
                query=models.Document(
                    text=query,
                    model=_bm25_model(),
                ),
                using=SPARSE_VECTOR,
                limit=sparse_limit,
            ),
        ],
        query=models.FusionQuery(
            fusion=models.Fusion.RRF,
        ),
        limit=fused_limit,
        with_payload=True,
        timeout=max(1, int(remaining_timeout(settings.qdrant_timeout_seconds))),
    ).points

    items: list[dict[str, Any]] = []

    for point in result:
        payload = dict(point.payload or {})
        payload["point_id"] = str(point.id)
        payload["fusion_score"] = float(point.score or 0.0)
        items.append(payload)

    return items


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}


def _fallback_rerank(
    candidates: list[dict],
    top_k: int,
) -> list[dict]:
    output = []

    for rank, item in enumerate(candidates[:top_k]):
        # Deliberately only a ranking fallback. The downstream semantic
        # evidence judge remains authoritative in cloud mode.
        score = max(0.20, 0.66 - rank * 0.025)
        output.append(
            {
                **item,
                "rerank_logit": None,
                "rerank_score": score,
            }
        )

    return output


def rerank(
    query: str,
    candidates: list[dict],
    top_k: int,
) -> list[dict]:
    if not candidates:
        return []

    # Cloud retrieval is intentionally high-recall.
    #
    # Important:
    # The best exact answer may appear well below rank 20 in
    # MiniLM + BM25 RRF search. Therefore Gemini must inspect
    # the wider retrieval pool rather than only the first few
    # embedding results.
    shortlist = candidates[
        : min(
            len(candidates),
            60,
        )
    ]

    blocks = []

    for i, item in enumerate(shortlist):
        title = " ".join(
            str(
                item.get(
                    "title",
                    "",
                )
            ).split()
        )

        semantic = item.get("semantic") or {}
        # Keep actual transcript evidence visible to the reranker. The semantic
        # search_text may be long, so it must not crowd the evidence out of the
        # bounded Gemini prompt.
        candidate_text = " ".join(str(item.get("text", "")).split())

        # 850 chars is enough to expose the semantic intent of
        # most transcript chunks while keeping the Gemini input
        # reasonably small even with ~60 candidates.
        if len(candidate_text) > 850:
            candidate_text = candidate_text[:850]

        blocks.append(
            f"[CANDIDATE {i}]\n"
            f"TITLE: {title}\n"
            f"SEMANTIC: {json.dumps(semantic, ensure_ascii=False)}\n"
            f"TEXT: {candidate_text}"
        )

    requested_results = min(
        len(shortlist),
        max(
            top_k * 2,
            12,
        ),
    )

    prompt = f"""
User question:

{query}

Below are Bhajan Marg transcript candidates retrieved using
dense + BM25 hybrid search.

{chr(10).join(blocks)}

Your job is semantic reranking.

Do NOT simply rank passages that discuss the same broad topic.

Prefer passages in this order:

1. The passage contains the same or nearly the same QUESTION
   and then gives an answer.

2. The passage directly gives a concrete answer to the user's
   exact question.

3. The passage gives a strongly applicable teaching even if
   wording differs.

4. Broad thematic discussion comes after direct answers.

Examples of what matters:

User:
"भगवान पर विश्वास कैसे बढ़ाएं?"

A passage saying:
"श्रद्धा विश्वास को दिन प्रतिदिन और दृढ़ बनाने के लिए
क्या करना चाहिए?"
followed by actual उपाय
is MORE relevant than a general passage merely discussing
"भगवान पर विश्वास".

Likewise:

User:
"बार-बार क्रोध आने पर क्या करें?"

A passage explicitly discussing क्रोध, उसका कारण या उसका उपाय
should outrank a general passage about spiritual practice.

Important rules:

- Judge meaning, not keyword count.
- Hindi auto-captions may contain recognition errors.
- Look for question → answer structure inside the transcript.
- Concrete उपाय should beat broad philosophy.
- Do not reward a candidate merely because its title sounds relevant.
- Do not invent missing context.

Score guide:

0.95-1.00
Exact or near-exact question answered directly.

0.85-0.94
Very strong direct answer.

0.65-0.84
Clearly useful and applicable teaching.

0.40-0.64
Related but indirect.

0.00-0.39
Weak or unrelated.

Return ONLY the best {requested_results} candidates.

Return JSON only:

{{
  "ranked": [
    {{
      "id": 12,
      "score": 0.98
    }},
    {{
      "id": 4,
      "score": 0.91
    }}
  ]
}}
"""


    try:
        raw = gemini_chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            max_output_tokens=1100,
        )
        parsed = _parse_json(raw)

        scores: dict[int, float] = {}
        for row in parsed.get("ranked", []):
            idx = row.get("id")
            score = row.get("score")
            if not isinstance(idx, int):
                continue
            try:
                score = float(score)
            except Exception:
                continue
            if 0 <= idx < len(shortlist):
                scores[idx] = max(0.0, min(1.0, score))

        if not scores:
            return _fallback_rerank(candidates, top_k)

        ranked = []
        for i, item in enumerate(shortlist):
            score = scores.get(i, max(0.15, 0.42 - i * 0.02))
            ranked.append(
                {
                    **item,
                    "rerank_logit": None,
                    "rerank_score": score,
                }
            )

        ranked.sort(
            key=lambda x: float(x.get("rerank_score", 0.0)),
            reverse=True,
        )
        return ranked[:top_k]

    except Exception:
        return _fallback_rerank(candidates, top_k)
