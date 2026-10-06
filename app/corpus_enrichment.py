"""Apply offline corpus-intelligence metadata to transcript chunks.

Generated semantic metadata is retrieval-only. The original transcript
chunk remains the sole answer evidence.
"""

from __future__ import annotations

from typing import Any

from .corpus_intelligence import load_artifact, make_search_text\nfrom .semantic_normalizer import normalize_artifact


def _clean_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []

    out: list[str] = []
    seen: set[str] = set()

    for item in value:
        if not isinstance(item, str):
            continue

        text = " ".join(item.split()).strip()
        if not text:
            continue

        key = text.casefold()
        if key in seen:
            continue

        seen.add(key)
        out.append(text)

        if len(out) >= limit:
            break

    return out


def _overlaps(
    chunk_start: int,
    chunk_end: int,
    section_start: int,
    section_end: int,
) -> bool:
    return chunk_start < section_end and chunk_end > section_start


def _merge_semantic_sections(
    sections: list[dict[str, Any]],
    chunk_start: int,
    chunk_end: int,
) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "topics": [],
        "situations": [],
        "intents": [],
        "concepts": [],
        "summaries": [],
    }

    for section in sections:
        start = int(section.get("start_ms", 0))
        end = int(section.get("end_ms", start))

        if not _overlaps(chunk_start, chunk_end, start, end):
            continue

        for key, limit in (
            ("topics", 12),
            ("situations", 10),
            ("intents", 10),
            ("concepts", 12),
        ):
            for value in _clean_list(section.get(key), limit):
                if value not in merged[key]:
                    merged[key].append(value)

        summary = " ".join(str(section.get("summary", "")).split()).strip()
        if summary and summary not in merged["summaries"]:
            merged["summaries"].append(summary)

    return {
        "topics": merged["topics"],
        "situations": merged["situations"],
        "intents": merged["intents"],
        "concepts": merged["concepts"],
        "summary": " ".join(merged["summaries"])[:600],
    }


def enrich_chunks(
    video: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich chunks with retrieval metadata while preserving exact evidence."""

    artifact = load_artifact(str(video["video_id"]))\n\n    if artifact:\n        artifact = normalize_artifact(artifact)

    # Intelligence is optional. If no artifact exists, return the original
    # chunks untouched rather than making ingestion fail.
    if not artifact:
        return chunks

    sections = artifact.get("temporal_buckets") or artifact.get("semantic_sections") or []
    understanding = artifact.get("understanding") or {}

    result: list[dict[str, Any]] = []

    for chunk in chunks:
        enriched = dict(chunk)

        semantic = _merge_semantic_sections(
            sections,
            int(chunk.get("start_ms", 0)),
            int(chunk.get("end_ms", 0)),
        )

        # Add video-level understanding as additional retrieval metadata.
        for key, limit in (
            ("topics", 12),
            ("situations", 10),
            ("intents", 10),
            ("concepts", 12),
        ):
            values = _clean_list(understanding.get(key), limit)

            for value in values:
                if value not in semantic[key]:
                    semantic[key].append(value)

        transcript_text = str(chunk.get("text", ""))

        enriched["semantic"] = semantic
        enriched["search_text"] = make_search_text(
            title=str(video.get("title", "")),
            understanding=understanding,
            temporal=semantic,
            transcript_text=transcript_text,
        )

        # Critical invariant: exact transcript evidence is never modified.
        enriched["text"] = chunk["text"]

        result.append(enriched)

    return result
