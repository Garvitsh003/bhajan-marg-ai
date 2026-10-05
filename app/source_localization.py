from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .cloud_llm import gemini_chat


def _youtube_url(
    *,
    video_id: str | None,
    url: str | None,
    start_ms: int | None,
    target_language: str,
) -> str:
    base = (url or "").strip()
    if not base and video_id:
        base = f"https://www.youtube.com/watch?v={video_id}"

    if not base:
        return ""

    try:
        parsed = urlparse(base)
        host = parsed.hostname or ""

        if host == "youtu.be":
            vid = parsed.path.strip("/") or (video_id or "")
            base = f"https://www.youtube.com/watch?v={vid}"
            parsed = urlparse(base)

        if (parsed.hostname or "") not in {
            "youtube.com",
            "www.youtube.com",
            "m.youtube.com",
        }:
            return base

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))

        if video_id:
            query["v"] = video_id

        seconds = max(0, int((start_ms or 0) / 1000))
        if seconds:
            query["t"] = f"{seconds}s"

        # The user-facing rule is English query -> English-caption-preferred
        # link; Hindi/Hinglish -> Hindi-caption-preferred link. This does not
        # claim the audio itself is translated.
        if target_language == "en":
            query["hl"] = "en"
            query["cc_lang_pref"] = "en"
        else:
            query["hl"] = "hi"
            query["cc_lang_pref"] = "hi"

        query["cc_load_policy"] = "1"

        return urlunparse(
            parsed._replace(query=urlencode(query))
        )
    except Exception:
        return base


@lru_cache(maxsize=4096)
def _render_text(
    title: str,
    excerpt: str,
    target_language: str,
) -> tuple[str, str]:
    if target_language == "hi":
        return title, excerpt

    if target_language == "en":
        instruction = (
            "Translate the title and transcript excerpt into faithful natural English. "
            "Do not add explanation or spiritual interpretation. Preserve names and "
            "important Sanskrit/Hindi spiritual terms when translation would distort them."
        )
    else:
        instruction = (
            "Render the title and transcript excerpt into clear Hinglish in Latin script. "
            "Do not add explanation or spiritual interpretation. Preserve meaning exactly."
        )

    prompt = f"""
You are localizing a source card for a grounded satsang search product.

{instruction}

The transcript excerpt below is canonical evidence. Your localized text is only
for display convenience and must never be represented as the exact original quote.

TITLE:
{title}

TRANSCRIPT EXCERPT:
{excerpt}

Return JSON only:
{{
  "title": "...",
  "excerpt": "..."
}}
"""

    raw = gemini_chat(
        [{"role": "user", "content": prompt}],
        temperature=0.0,
        json_mode=True,
        max_output_tokens=700,
    )

    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {}

    out_title = str(parsed.get("title") or title).strip()
    out_excerpt = str(parsed.get("excerpt") or excerpt).strip()
    return out_title, out_excerpt


def localize_source(
    source: dict[str, Any],
    target_language: str,
) -> dict[str, Any]:
    target = target_language if target_language in {"hi", "hinglish", "en"} else "hi"

    title = str(
        source.get("video_title")
        or source.get("title")
        or "Bhajan Marg satsang"
    ).strip()

    exact_excerpt = str(
        source.get("transcript_excerpt")
        or source.get("text")
        or ""
    ).strip()

    if target == "hi":
        display_title = title
        display_excerpt = exact_excerpt
        label = "मूल हिन्दी स्रोत"
        is_translation = False
    else:
        display_title, display_excerpt = _render_text(
            title,
            exact_excerpt,
            target,
        )
        is_translation = True
        label = (
            "English translation of source caption"
            if target == "en"
            else "Hinglish rendering of source caption"
        )

    start_ms = (
        source.get("answer_start_ms")
        if source.get("answer_start_ms") is not None
        else source.get("timestamp_start_ms")
        if source.get("timestamp_start_ms") is not None
        else source.get("start_ms")
    )

    display_url = _youtube_url(
        video_id=source.get("video_id"),
        url=source.get("answer_url") or source.get("url"),
        start_ms=start_ms,
        target_language=target,
    )

    return {
        "target_language": target,
        "display_title": display_title,
        "display_excerpt": display_excerpt,
        "display_url": display_url,
        "display_label": label,
        "is_translation": is_translation,
        "exact_transcript_excerpt": exact_excerpt,
        "caption_preference": "en" if target == "en" else "hi",
    }
