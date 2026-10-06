"""Attach persisted corpus intelligence to transcript chunks.

This module never changes transcript evidence. It only adds retrieval metadata
and a semantic search_text field to each chunk when an artifact exists.
"""
from __future__ import annotations

from typing import Any

from .corpus_intelligence import load_artifact, make_search_text


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def enrich_chunks(
    video: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    artifact = load_artifact(str(video["video_id"]))
    if not artifact:
        return chunks

    understanding = artifact.get("understanding") or {}
    sections = artifact.get("semantic_sections") or []

    output: list[dict[str, Any]] = []
    for chunk in chunks:
        start = int(chunk.get("start_ms", 0))
        end = int(chunk.get("end_ms", start))

        topics: list[str] = []
        situations: list[str] = []
        intents: list[str] = []
        concepts: list[str] = []
        summaries: list[str] = []

        for section in sections:
            if not isinstance(section, dict):
                continue
            if not _overlap(
                start,
                max(end, start + 1),
                int(section.get("start_ms", 0)),
                int(section.get("end_ms", 0)),
            ):
                continue
            for target, key in (
                (topics, "topics"),
                (situations, "situations"),
                (intents, "intents"),
                (concepts, "concepts"),
            ):
                for value in section.get(key) or []:
                    if isinstance(value, str) and value not in target:
                        target.append(value)
            summary = str(section.get("summary", "")).strip()
            if summary and summary not in summaries:
                summaries.append(summary)

        semantic = {
            "topics": topics[:12] or list(understanding.get("topics") or [])[:8],
            "situations": situations[:8] or list(understanding.get("situations") or [])[:6],
            "intents": intents[:8] or list(understanding.get("intents") or [])[:6],
            "concepts": concepts[:12] or list(understanding.get("concepts") or [])[:10],
            "summaries": summaries[:3],
        }

        enriched = {
            **chunk,
            "semantic": semantic,
        }
        enriched["search_text"] = make_search_text(
            title=str(video.get("title", "")),
            understanding=understanding,
            temporal=semantic,
            transcript_text=str(chunk.get("text", "")),
        )
        output.append(enriched)

    return output
