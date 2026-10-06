"""V1.5.1 corpus understanding and temporal semantic map.

The corpus is analyzed offline from the already-saved transcripts. Generated
metadata is retrieval-only: the transcript remains the sole source of answer
evidence.

Artifacts live under data/corpus_intelligence/<video_id>.json and are not
committed to git.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from .config import settings
from .llm import parse_json

log = logging.getLogger(__name__)

ARTIFACT_VERSION = 1
DEFAULT_GROUP_SIZE = 8
BUCKET_SECONDS = 10


def artifact_path(video_id: str) -> Path:
    root = Path(getattr(settings, "corpus_intelligence_dir", "./data/corpus_intelligence"))
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{video_id}.json"


def load_artifact(video_id: str) -> dict[str, Any] | None:
    path = artifact_path(video_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        log.exception("Failed reading corpus intelligence artifact for %s", video_id)
        return None


def save_artifact(video_id: str, artifact: dict[str, Any]) -> str:
    path = artifact_path(video_id)
    path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path)


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


def _clean_json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _group_segments(segments: list[dict[str, Any]], group_size: int) -> list[list[dict[str, Any]]]:
    return [
        segments[i : i + group_size]
        for i in range(0, len(segments), group_size)
    ]


def _normalize_segment(segment: dict[str, Any]) -> dict[str, Any]:
    return {
        "segment_id": int(segment.get("segment_id", 0)),
        "start_ms": int(segment.get("start_ms", 0)),
        "end_ms": int(segment.get("end_ms", 0)),
        "text": " ".join(str(segment.get("text", "")).split()),
    }


def _bucketize_sections(
    sections: list[dict[str, Any]],
    *,
    duration_ms: int,
) -> list[dict[str, Any]]:
    """Expand semantic ranges into a cheap 10-second addressable index.

    We deliberately do not call an LLM once per 10-second bucket. A semantic
    section is assigned to all buckets it overlaps. Exact evidence still comes
    from the original caption segments/chunks.
    """
    if duration_ms <= 0:
        return []

    buckets: dict[int, dict[str, Any]] = {}
    bucket_count = (duration_ms + BUCKET_SECONDS * 1000 - 1) // (BUCKET_SECONDS * 1000)

    for section in sections:
        start = max(0, int(section.get("start_ms", 0)))
        end = max(start, int(section.get("end_ms", start)))
        start_bucket = start // (BUCKET_SECONDS * 1000)
        end_bucket = min(bucket_count - 1, max(start_bucket, (max(start, end - 1)) // (BUCKET_SECONDS * 1000)))

        topics = _clean_list(section.get("topics"), 8)
        situations = _clean_list(section.get("situations"), 6)
        intents = _clean_list(section.get("intents"), 6)
        concepts = _clean_list(section.get("concepts"), 10)
        summary = " ".join(str(section.get("summary", "")).split()).strip()

        for bucket in range(start_bucket, end_bucket + 1):
            row = buckets.setdefault(
                bucket,
                {
                    "start_ms": bucket * BUCKET_SECONDS * 1000,
                    "end_ms": min(duration_ms, (bucket + 1) * BUCKET_SECONDS * 1000),
                    "topics": [],
                    "situations": [],
                    "intents": [],
                    "concepts": [],
                    "summaries": [],
                },
            )
            for key, values in (
                ("topics", topics),
                ("situations", situations),
                ("intents", intents),
                ("concepts", concepts),
            ):
                for value in values:
                    if value not in row[key]:
                        row[key].append(value)
            if summary and summary not in row["summaries"]:
                row["summaries"].append(summary)

    return [
        {
            **row,
            "summary": " ".join(row.pop("summaries"))[:600],
        }
        for _, row in sorted(buckets.items())
    ]


def make_search_text(
    *,
    title: str,
    understanding: dict[str, Any] | None,
    temporal: dict[str, Any] | None,
    transcript_text: str,
) -> str:
    """Build retrieval-only text while keeping transcript evidence separate."""
    understanding = understanding or {}
    temporal = temporal or {}

    parts = [
        title,
        *(_clean_list(understanding.get("topics"), 12)),
        *(_clean_list(understanding.get("situations"), 10)),
        *(_clean_list(understanding.get("intents"), 10)),
        *(_clean_list(understanding.get("concepts"), 12)),
        *(_clean_list(understanding.get("questions_answered"), 10)),
        *(_clean_list(temporal.get("topics"), 8)),
        *(_clean_list(temporal.get("situations"), 6)),
        *(_clean_list(temporal.get("intents"), 6)),
        *(_clean_list(temporal.get("concepts"), 10)),
        transcript_text,
    ]
    return "\n".join(x for x in parts if x).strip()


def _prompt_for_group(
    *,
    title: str,
    video_metadata: dict[str, Any],
    group: list[dict[str, Any]],
) -> str:
    rows = []
    for i, segment in enumerate(group):
        rows.append(
            f"[SEGMENT {i}] {segment['start_ms']/1000:.1f}s-{segment['end_ms']/1000:.1f}s\n"
            f"{segment['text'][:1800]}"
        )

    return f"""You are building retrieval metadata for the Bhajan Marg transcript corpus.

VIDEO TITLE:
{title}

VIDEO METADATA:
{json.dumps(video_metadata, ensure_ascii=False)}

TRANSCRIPT SEGMENTS:
{chr(10).join(rows)}

Understand what is actually being discussed in these transcript segments.
This is indexing metadata only. Do not answer the user and do not invent
teachings that are not supported by the supplied text.

For every segment, return:
- topics: concrete subjects discussed
- situations: user situations/problems addressed
- intents: questions or goals being addressed
- concepts: important semantic concepts
- summary: a short factual description of what this segment discusses

Also return a group-level list of the strongest topics/situations/intents/concepts.

Keep wording useful for retrieval in Hindi and English where natural. Preserve
negation and qualifications. Do not turn a speaker's statement into scripture
or an authoritative claim beyond the transcript.

Return JSON only:
{{
  "group": {{
    "topics": [],
    "situations": [],
    "intents": [],
    "concepts": []
  }},
  "segments": [
    {{
      "segment_index": 0,
      "topics": [],
      "situations": [],
      "intents": [],
      "concepts": [],
      "summary": ""
    }}
  ]
}}
"""


def build_video_artifact(
    video: dict[str, Any],
    segments: list[dict[str, Any]],
    *,
    llm_call: Callable[..., str],
    group_size: int = DEFAULT_GROUP_SIZE,
    force: bool = False,
) -> dict[str, Any]:
    """Analyze a transcript in cached groups and create its semantic map."""
    video_id = str(video["video_id"])
    existing = load_artifact(video_id)
    if existing and not force and existing.get("transcript_hash") == video.get("transcript_hash"):
        return existing

    normalized = [_normalize_segment(x) for x in segments if str(x.get("text", "")).strip()]
    if not normalized:
        raise ValueError(f"No transcript segments for {video_id}")

    duration_ms = max(int(x["end_ms"]) for x in normalized)
    section_rows: list[dict[str, Any]] = []
    video_topics: list[str] = []
    video_situations: list[str] = []
    video_intents: list[str] = []
    video_concepts: list[str] = []
    questions_answered: list[str] = []

    for group_index, group in enumerate(_group_segments(normalized, group_size)):
        prompt = _prompt_for_group(
            title=str(video.get("title", "")),
            video_metadata={
                "video_id": video_id,
                "channel": video.get("channel"),
                "published_at": video.get("published_at"),
                "content_type": video.get("content_type", "video"),
            },
            group=group,
        )
        raw = llm_call(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            num_predict=1800,
        )
        data = _clean_json_object(parse_json(raw, {}))
        group_meta = _clean_json_object(data.get("group"))

        for target, key in (
            (video_topics, "topics"),
            (video_situations, "situations"),
            (video_intents, "intents"),
            (video_concepts, "concepts"),
        ):
            for value in _clean_list(group_meta.get(key)):
                if value not in target:
                    target.append(value)

        rows = data.get("segments") if isinstance(data.get("segments"), list) else []
        for local_index, segment in enumerate(group):
            meta = next(
                (
                    item for item in rows
                    if isinstance(item, dict)
                    and int(item.get("segment_index", -1)) == local_index
                ),
                {},
            )
            section_rows.append({
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
                "topics": _clean_list(meta.get("topics"), 8),
                "situations": _clean_list(meta.get("situations"), 6),
                "intents": _clean_list(meta.get("intents"), 6),
                "concepts": _clean_list(meta.get("concepts"), 10),
                "summary": " ".join(str(meta.get("summary", "")).split()).strip()[:600],
            })
        log.info("corpus-understanding video=%s group=%d", video_id, group_index + 1)

    # De-duplicate the global lists before writing the artifact.
    video_topics = _clean_list(video_topics, 30)
    video_situations = _clean_list(video_situations, 30)
    video_intents = _clean_list(video_intents, 30)
    video_concepts = _clean_list(video_concepts, 40)

    # Questions answered are derived from the intent/situation map rather than
    # being invented as a second answer-generating call.
    questions_answered = [
        f"{situation}: {intent}"
        for situation in video_situations[:12]
        for intent in video_intents[:6]
    ][:30]

    temporal_buckets = _bucketize_sections(section_rows, duration_ms=duration_ms)

    artifact = {
        "version": ARTIFACT_VERSION,
        "video_id": video_id,
        "title": video.get("title", ""),
        "url": video.get("url", ""),
        "transcript_hash": video.get("transcript_hash"),
        "understanding": {
            "topics": video_topics,
            "situations": video_situations,
            "intents": video_intents,
            "concepts": video_concepts,
            "questions_answered": questions_answered,
        },
        "semantic_sections": section_rows,
        "temporal_buckets": temporal_buckets,
    }
    save_artifact(video_id, artifact)
    return artifact
