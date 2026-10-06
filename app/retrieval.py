import os
from typing import Any

from . import db
from .config import settings
from .llm import judge_evidence, expand_retrieval_queries
from .query_intent import understand_query, intent_to_queries
from .text import ms_to_clock, youtube_at
from .search_backend import hybrid_search, rerank


DOMINANT_DIRECT_THRESHOLD = 0.90
DOMINANT_MAX_GAP = 0.08

# Number of reranked candidates that the semantic evidence
# judge may inspect.
#
# This is deliberately larger than FINAL_SOURCES.
# We first judge a wider pool, then return only the best few.
EVIDENCE_JUDGE_MAX_CANDIDATES = 8


def _score(item: dict) -> float:
    return float(
        item.get(
            "rerank_score",
            0.0,
        )
    )


def _algorithmic_level(
    results: list[dict],
) -> str:
    if not results:
        return "none"

    top = _score(
        results[0]
    )

    if (
        top
        >= settings.strong_evidence_threshold
    ):
        return "direct"

    if (
        top
        >= settings.related_evidence_threshold
    ):
        return "related"

    return "none"


def _filter_for_selection(
    ranked: list[dict],
) -> list[dict]:
    """
    If retrieval has an exceptionally strong result, do not
    dilute it with much weaker passages.

    Example:
        0.9893 -> keep
        0.5586 -> remove
        0.4756 -> remove

    But:
        0.96 -> keep
        0.93 -> keep
    """

    if not ranked:
        return []

    top_score = _score(
        ranked[0]
    )

    if (
        top_score
        >= DOMINANT_DIRECT_THRESHOLD
    ):
        cutoff = (
            top_score
            - DOMINANT_MAX_GAP
        )

        strong = [
            item
            for item in ranked
            if _score(item) >= cutoff
        ]

        return (
            strong[:2]
            or ranked[:1]
        )

    return ranked


def retrieve(
    question: str,
) -> dict[str, Any]:
    # ---------------------------------------------------------
    # 1. Understand the user's situation before retrieval
    # ---------------------------------------------------------
    query_intent = understand_query(question)
    intent_queries = intent_to_queries(query_intent, question)
    language_queries = expand_retrieval_queries(question) or [question]

    retrieval_queries: list[str] = []
    seen_queries: set[str] = set()
    for value in [*intent_queries, *language_queries]:
        value = " ".join(str(value).split()).strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen_queries:
            continue
        seen_queries.add(key)
        retrieval_queries.append(value)

    retrieval_queries = retrieval_queries[:10] or [question]

    # ---------------------------------------------------------
    # 2. Search the indexed corpus
    # ---------------------------------------------------------

    # Search every safe language/spelling variant, then fuse by point id.
    # This raises recall for Roman Hindi / Hinglish without changing answer
    # semantics: the original standalone question remains authoritative for
    # reranking, evidence judging and answer generation.
    merged: dict[str, dict] = {}

    for query_index, retrieval_query in enumerate(retrieval_queries):
        results = hybrid_search(retrieval_query)

        for rank, item in enumerate(results):
            point_id = str(
                item.get("point_id")
                or f'{item.get("video_id")}:{item.get("chunk_index")}'
            )

            row = merged.get(point_id)

            if row is None:
                row = {
                    **item,
                    "matched_queries": [],
                    "query_variant_ranks": {},
                    "multi_query_rrf": 0.0,
                    "best_fusion_score": float(item.get("fusion_score", 0.0) or 0.0),
                }
                merged[point_id] = row

            # RRF over query variants gives exact Hindi/BM25 hits a fair chance
            # even when the original Roman query is weak.
            weight = 1.10 if query_index == 0 else 1.0
            row["multi_query_rrf"] += weight / (60.0 + rank + 1.0)
            row["best_fusion_score"] = max(
                float(row.get("best_fusion_score", 0.0) or 0.0),
                float(item.get("fusion_score", 0.0) or 0.0),
            )
            row["matched_queries"].append(retrieval_query)
            row["query_variant_ranks"][retrieval_query] = rank + 1

    candidates = sorted(
        merged.values(),
        key=lambda item: (
            float(item.get("multi_query_rrf", 0.0) or 0.0),
            float(item.get("best_fusion_score", 0.0) or 0.0),
        ),
        reverse=True,
    )[: max(int(getattr(settings, "fused_candidates", 50) or 50), 60)]

    # Rerank against the ORIGINAL standalone question. Query variants exist
    # only to improve recall and must not redefine what the user asked.
    full_ranked = rerank(
        question,
        candidates,
        top_k=max(
            settings.final_sources * 4,
            12,
        ),
    )

    # V1.5.1 recall recovery: if the normal pool is weak, search a much
    # wider slice of every semantic/language query before declaring none.
    recovery_trigger = (
        not full_ranked
        or _score(full_ranked[0]) < settings.recovery_trigger_threshold
    )

    if recovery_trigger:
        recovery_limit = max(
            int(getattr(settings, "recovery_candidates", 250)),
            int(getattr(settings, "fused_candidates", 50)),
        )
        for retrieval_query in retrieval_queries:
            results = hybrid_search(retrieval_query, limit=recovery_limit)
            for rank, item in enumerate(results):
                point_id = str(
                    item.get("point_id")
                    or f'{item.get("video_id")}:{item.get("chunk_index")}'
                )
                row = merged.get(point_id)
                if row is None:
                    row = {
                        **item,
                        "matched_queries": [],
                        "query_variant_ranks": {},
                        "multi_query_rrf": 0.0,
                        "best_fusion_score": float(item.get("fusion_score", 0.0) or 0.0),
                    }
                    merged[point_id] = row
                row["multi_query_rrf"] += 0.75 / (60.0 + rank + 1.0)
                row["best_fusion_score"] = max(
                    float(row.get("best_fusion_score", 0.0) or 0.0),
                    float(item.get("fusion_score", 0.0) or 0.0),
                )
                row["matched_queries"].append(retrieval_query)

        candidates = sorted(
            merged.values(),
            key=lambda item: (
                float(item.get("multi_query_rrf", 0.0) or 0.0),
                float(item.get("best_fusion_score", 0.0) or 0.0),
            ),
            reverse=True,
        )[:recovery_limit]

        full_ranked = rerank(
            question,
            candidates,
            top_k=max(settings.final_sources * 6, 20),
        )

    # ---------------------------------------------------------
    # 3. Remove weak passages when there is a dominant match
    # ---------------------------------------------------------

    ranked_for_selection = (
        _filter_for_selection(
            full_ranked
        )
    )

    # ---------------------------------------------------------
    # 4. Build evidence contexts
    # ---------------------------------------------------------

    selected: list[dict] = []

    per_video: dict[str, int] = {}

    for item in ranked_for_selection:
        video_id = item[
            "video_id"
        ]

        item_score = _score(
            item
        )

        # Prevent one video from filling the context
        # with duplicate chunks.
        if (
            per_video.get(
                video_id,
                0,
            )
            >= 2
        ):
            continue

        # Important:
        # When an exact/high-confidence passage is found,
        # use that exact passage only.
        #
        # Do NOT expand neighboring chunks because they may
        # introduce unrelated ideas into the answer.
        if (
            item_score
            >= DOMINANT_DIRECT_THRESHOLD
        ):
            context_text = (
                item["text"].strip()
            )

        elif os.getenv("APP_MODE", "local").lower() == "cloud":
            # Cloud mode has no persistent local chunk table on Render.
            context_text = item["text"].strip()

        else:
            neighbors = (
                db.get_neighbor_context(
                    video_id,
                    int(
                        item[
                            "chunk_index"
                        ]
                    ),
                    settings.context_neighbors,
                )
            )

            context_text = " ".join(
                chunk["text"]
                for chunk in neighbors
            ).strip()

            if not context_text:
                context_text = (
                    item["text"].strip()
                )

        selected.append(
            {
                **item,
                "context_text": context_text,
            }
        )

        per_video[video_id] = (
            per_video.get(
                video_id,
                0,
            )
            + 1
        )

        if (
            len(selected)
            >= EVIDENCE_JUDGE_MAX_CANDIDATES
        ):
            break

    # ---------------------------------------------------------
    # 5. Determine evidence quality
    # ---------------------------------------------------------

    algorithmic_level = (
        _algorithmic_level(
            selected
        )
    )

    judged = judge_evidence(
        question,
        selected,
        algorithmic_level,
    )

    level = judged[
        "level"
    ]

    raw_indices = judged.get(
        "source_indices"
    )

    # None means the judge did not provide source selection.
    # In that case we can safely fall back to the candidate pool.
    #
    # [] means the judge explicitly selected no evidence.
    # Preserve that decision.
    if raw_indices is None:
        indices = list(
            range(
                len(selected)
            )
        )
    else:
        indices = raw_indices

    usable = []

    for i in indices:
        if not isinstance(
            i,
            int,
        ):
            continue

        if not (
            0 <= i < len(selected)
        ):
            continue

        usable.append(
            selected[i]
        )

    # ---------------------------------------------------------
    # 6. Final evidence filtering
    # ---------------------------------------------------------

    # The reranker score is excellent for ordering candidates,
    # but it is not calibrated well enough to be the final
    # semantic truth for Hindi satsang questions.
    #
    # When the LLM evidence judge is enabled, trust its
    # direct / related / none decision and source_indices.
    #
    # Numeric thresholds remain useful as the fallback path
    # when semantic judging is disabled.

    if not usable:
        level = "none"

    elif settings.use_llm_evidence_judge:
        if level == "direct":
            top_score = _score(
                usable[0]
            )

            # Preserve our existing dominant-match behaviour.
            #
            # Example:
            # 0.9893 exact answer
            # should not be diluted by unrelated 0.50 passages.
            if (
                top_score
                >= DOMINANT_DIRECT_THRESHOLD
            ):
                cutoff = (
                    top_score
                    - DOMINANT_MAX_GAP
                )

                dominant_usable = [
                    source
                    for source in usable
                    if (
                        _score(source)
                        >= cutoff
                    )
                ]

                if dominant_usable:
                    usable = dominant_usable[
                        :2
                    ]
                else:
                    usable = usable[
                        :1
                    ]

            else:
                # Semantic judge has already decided these are
                # direct evidence. Do not delete them just
                # because the CrossEncoder score is below 0.72.
                usable = usable[
                    : settings.final_sources
                ]

        elif level == "related":
            # Critical:
            # Do NOT re-apply RELATED_EVIDENCE_THRESHOLD here.
            #
            # The semantic judge has already inspected the
            # actual transcript meaning.
            usable = usable[
                : settings.final_sources
            ]

        else:
            level = "none"
            usable = []

    else:
        # -----------------------------------------------------
        # Algorithmic fallback when semantic judge is disabled
        # -----------------------------------------------------

        if level == "direct":
            top_score = _score(
                usable[0]
            )

            if (
                top_score
                >= DOMINANT_DIRECT_THRESHOLD
            ):
                cutoff = (
                    top_score
                    - DOMINANT_MAX_GAP
                )

                usable = [
                    source
                    for source in usable
                    if (
                        _score(source)
                        >= cutoff
                    )
                ][:2]

            else:
                usable = [
                    source
                    for source in usable
                    if (
                        _score(source)
                        >= settings.strong_evidence_threshold
                    )
                ][: settings.final_sources]

        elif level == "related":
            usable = [
                source
                for source in usable
                if (
                    _score(source)
                    >= settings.related_evidence_threshold
                )
            ][: settings.final_sources]

        else:
            level = "none"
            usable = []

    # Never expose an impossible evidence state such as:
    #
    #     level = related
    #     sources = []
    #
    if not usable:
        level = "none"

    # ---------------------------------------------------------
    # 7. Build source cards
    # ---------------------------------------------------------

    cards: list[dict] = []

    seen: set[tuple] = set()

    for source in usable:
        key = (
            source["video_id"],
            source["chunk_index"],
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        cards.append(
            {
                "video_id": source[
                    "video_id"
                ],

                "title": source[
                    "title"
                ],

                "published_at": source.get(
                    "published_at"
                ),

                "start_ms": source[
                    "start_ms"
                ],

                "end_ms": source[
                    "end_ms"
                ],

                "start": ms_to_clock(
                    source["start_ms"]
                ),

                "end": ms_to_clock(
                    source["end_ms"]
                ),

                "url": youtube_at(
                    source["video_id"],
                    source["start_ms"],
                ),

                # Exact transcript text.
                # The LLM never generates this.
                "transcript_excerpt": source[
                    "text"
                ],

                "relevance": round(
                    _score(source),
                    4,
                ),

                # Context passed internally to answer generation.
                "context_text": source[
                    "context_text"
                ],
                'caption_segments':source.get('caption_segments', []),
            }
        )

    # ---------------------------------------------------------
    # 8. Return result
    # ---------------------------------------------------------

    return {
        "level": level,
        "reason": judged.get(
            "reason"
        ),
        "sources": cards,
        "search_queries": retrieval_queries,
        "query_intent": query_intent,

        # Preserve the entire reranker output for debugging.
        # Only final answer evidence is filtered.
        "raw_ranked": full_ranked,
    }
