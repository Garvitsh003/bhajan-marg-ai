from __future__ import annotations

import os
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .product_db import configured as database_configured
from .product_db import connection


TRACE_CANDIDATE_LIMIT = 50


def version_snapshot() -> dict[str, str]:
    return {
        "corpus_version": os.getenv("CORPUS_VERSION", "Premanand Corpus V1.0"),
        "chunking_version": os.getenv("CHUNKING_VERSION", "chunking-v1"),
        "retrieval_version": os.getenv("RETRIEVAL_VERSION", "retrieval-v1.5"),
        "embedding_version": os.getenv(
            "EMBEDDING_VERSION",
            os.getenv("QDRANT_DENSE_MODEL", "sentence-transformers/all-minilm-l6-v2"),
        ),
        "reranker_version": os.getenv("RERANKER_VERSION", "gemini-semantic-reranker-v1"),
        "prompt_version": os.getenv("PROMPT_VERSION", "answer-policy-v1.5"),
        "model_version": os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    }


def _clean_candidate(item: dict[str, Any]) -> dict[str, Any]:
    keep = {
        "point_id",
        "video_id",
        "title",
        "url",
        "content_type",
        "published_at",
        "chunk_index",
        "start_ms",
        "end_ms",
        "text",
        "fusion_score",
        "rerank_score",
        "rerank_logit",
        "transcript_source",
        "content_family_id",
        "source_authority",
    }
    out = {
        key: value
        for key, value in item.items()
        if key in keep
    }
    if isinstance(out.get("text"), str) and len(out["text"]) > 4000:
        out["text"] = out["text"][:4000]
    return out


def record_chat_case(
    *,
    request_id: str,
    question: str,
    standalone_query: str,
    response_language: str,
    answer: str,
    evidence: dict[str, Any],
    generated: dict[str, Any],
    sources_shown: list[dict[str, Any]],
    elapsed_ms: int,
) -> str | None:
    if not database_configured():
        return None

    case_id = uuid.uuid4()
    raw_ranked = [
        _clean_candidate(item)
        for item in (evidence.get("raw_ranked") or [])[:TRACE_CANDIDATE_LIMIT]
    ]

    retrieval_trace = {
        "candidate_count": len(evidence.get("raw_ranked") or []),
        "top_candidates": raw_ranked,
        "selected_source_count": len(sources_shown),
        "judge_reason": evidence.get("reason"),
    }
    answer_trace = {
        "quotes": generated.get("quotes") or [],
        "claims": generated.get("claims") or [],
    }
    timing = {"total_elapsed_ms": int(elapsed_ms)}

    with connection() as conn:
        conn.execute(
            """
            INSERT INTO quality_cases(
                id, request_id, question, standalone_query, response_language,
                answer, evidence_level, evidence_reason, answer_status,
                extraction_status, interpretation_status, search_queries,
                retrieval_trace, sources_shown, answer_trace, versions, timing
            )
            VALUES(
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,%s
            )
            ON CONFLICT (request_id) DO UPDATE SET
                question=EXCLUDED.question,
                standalone_query=EXCLUDED.standalone_query,
                response_language=EXCLUDED.response_language,
                answer=EXCLUDED.answer,
                evidence_level=EXCLUDED.evidence_level,
                evidence_reason=EXCLUDED.evidence_reason,
                answer_status=EXCLUDED.answer_status,
                extraction_status=EXCLUDED.extraction_status,
                interpretation_status=EXCLUDED.interpretation_status,
                search_queries=EXCLUDED.search_queries,
                retrieval_trace=EXCLUDED.retrieval_trace,
                sources_shown=EXCLUDED.sources_shown,
                answer_trace=EXCLUDED.answer_trace,
                versions=EXCLUDED.versions,
                timing=EXCLUDED.timing,
                updated_at=NOW()
            RETURNING id
            """,
            (
                case_id,
                request_id,
                question,
                standalone_query,
                response_language,
                answer,
                evidence.get("level"),
                evidence.get("reason"),
                generated.get("answer_status"),
                generated.get("extraction_status"),
                generated.get("interpretation_status"),
                Jsonb(evidence.get("search_queries") or [standalone_query]),
                Jsonb(retrieval_trace),
                Jsonb(sources_shown),
                Jsonb(answer_trace),
                Jsonb(version_snapshot()),
                Jsonb(timing),
            ),
        )

    return str(case_id)


def attach_message(
    *,
    request_id: str | None,
    message_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    if not request_id or not database_configured():
        return

    with connection() as conn:
        conn.execute(
            """
            UPDATE quality_cases
            SET message_id=%s,
                conversation_id=%s,
                user_id=%s,
                updated_at=NOW()
            WHERE request_id=%s
            """,
            (message_id, conversation_id, user_id, request_id),
        )


def attach_feedback(
    *,
    request_id: str | None,
    feedback_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_id: str | None,
    rating: int,
    reason: str | None,
    comment: str | None,
    voice_transcript: str | None,
) -> None:
    if not request_id or not database_configured():
        return

    reason_category = {
        "answer_irrelevant": "generation",
        "wrong_source": "retrieval",
        "didnt_understand_me": "query_understanding",
        "incomplete": "generation",
        "unsupported_by_source": "citation",
        "discussed_elsewhere": "retrieval",
        "language_problem": "language",
    }.get(reason or "")

    with connection() as conn:
        conn.execute(
            """
            UPDATE quality_cases
            SET feedback_id=%s,
                user_id=COALESCE(%s,user_id),
                guest_id=COALESCE(%s,guest_id),
                feedback_rating=%s,
                feedback_reason=%s,
                feedback_comment=%s,
                voice_transcript=%s,
                failure_category=COALESCE(failure_category,%s),
                review_status=CASE
                    WHEN %s < 0 THEN 'needs_review'
                    ELSE review_status
                END,
                updated_at=NOW()
            WHERE request_id=%s
            """,
            (
                feedback_id,
                user_id,
                guest_id,
                rating,
                reason,
                comment,
                voice_transcript,
                reason_category,
                rating,
                request_id,
            ),
        )
