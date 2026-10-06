"""V1.5.1 structured understanding of user questions."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .llm import ollama_chat

log = logging.getLogger(__name__)


def _list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        value = " ".join(item.split()).strip()
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        out.append(value)
        if len(out) >= limit:
            break
    return out


def understand_query(
    question: str,
    *,
    llm_call: Callable[..., str] = ollama_chat,
) -> dict[str, Any]:
    """Return retrieval intent only; never generate an answer."""
    prompt = f"""Understand this user question for retrieval against a Hindi Bhajan Marg transcript corpus.

USER QUESTION:
{question}

Extract only what is explicitly or strongly implied by the user's question.
Do not answer it. Do not add spiritual advice. Preserve negation, uncertainty,
people/entities, and the requested action.

Return JSON:
{{
  "language": "hi|hinglish|en|mixed|unknown",
  "domain": "",
  "situation": "",
  "intent": "",
  "entities": [],
  "emotions": [],
  "constraints": [],
  "concepts": [],
  "retrieval_phrases": []
}}

retrieval_phrases should contain concise Hindi/English phrases that express
the same situation and intent, not generic synonyms or advice.
"""
    try:
        data = llm_call(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            num_predict=700,
        )
        parsed = json.loads(data)
        if not isinstance(parsed, dict):
            raise ValueError("query intent is not an object")
    except Exception as exc:
        log.warning("query intent unavailable: %s", type(exc).__name__)
        return {
            "language": "unknown",
            "domain": "",
            "situation": "",
            "intent": "",
            "entities": [],
            "emotions": [],
            "constraints": [],
            "concepts": [],
            "retrieval_phrases": [question],
        }

    return {
        "language": str(parsed.get("language", "unknown")),
        "domain": str(parsed.get("domain", "")),
        "situation": str(parsed.get("situation", "")),
        "intent": str(parsed.get("intent", "")),
        "entities": _list(parsed.get("entities")),
        "emotions": _list(parsed.get("emotions")),
        "constraints": _list(parsed.get("constraints")),
        "concepts": _list(parsed.get("concepts")),
        "retrieval_phrases": _list(parsed.get("retrieval_phrases"), 8) or [question],
    }


def intent_to_queries(intent: dict[str, Any], original: str) -> list[str]:
    """Create a bounded semantic recall set without changing user meaning."""
    values: list[str] = [original]
    for key in ("situation", "intent"):
        value = str(intent.get(key, "")).strip()
        if value and value not in values:
            values.append(value)

    for value in _list(intent.get("retrieval_phrases"), 6):
        if value not in values:
            values.append(value)

    concepts = _list(intent.get("concepts"), 8)
    if concepts:
        values.append(" ".join(concepts))

    # Keep the expansion deliberately small. Broad synonym clouds reduce
    # precision and can pollute the retrieval pool.
    return values[:8]
