import json
import re
from typing import Any

import requests

from .config import settings
from .cloud_llm import gemini_chat
from .search_backend import hybrid_search, rerank


# ============================================================
# CONFIG
# ============================================================

SUPPORT_PREJUDGE_MIN_SCORE = 0.45

SUPPORT_MAX_CANDIDATES = 6

SUPPORT_MAX_SOURCES = 3

SUPPORT_TEXT_LIMIT = 1400

SUPPORT_MAX_EXCERPT_SEGMENTS = 3

# This threshold is applied AFTER exact supporting spans
# have been extracted.
SUPPORT_EXCERPT_MIN_SCORE = 0.50


# ============================================================
# HELPERS
# ============================================================

def _score(item: dict) -> float:
    return float(
        item.get(
            "rerank_score",
            0.0,
        )
    )


def _normalize_space(text: str) -> str:
    return " ".join(
        str(text).split()
    )


def _parse_json(
    text: str,
    fallback: dict,
) -> dict:
    try:
        return json.loads(text)

    except Exception:
        match = re.search(
            r"\{.*\}",
            text,
            re.S,
        )

        if not match:
            return fallback

        try:
            return json.loads(
                match.group(0)
            )

        except Exception:
            return fallback


def _build_excerpt(
    segments: list[str],
) -> str:
    cleaned = []

    for segment in segments:
        segment = _normalize_space(
            segment
        ).strip()

        segment = segment.rstrip(
            "।.!? "
        )

        if segment:
            cleaned.append(segment)

    if not cleaned:
        return ""

    return "। ".join(cleaned) + "।"


# ============================================================
# OLLAMA JSON
# ============================================================

def _ollama_json(
    prompt: str,
    *,
    num_predict: int = 600,
    timeout: int = 240,
) -> dict:
    if getattr(settings, "llm_provider", "ollama").lower() == "gemini":
        raw = gemini_chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
            json_mode=True,
            max_output_tokens=num_predict,
            timeout=timeout,
        )
        return _parse_json(raw, {})

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "stream": False,
        "format": "json",
        "keep_alive": "30m",
        "options": {
            "temperature": 0.0,
            "num_predict": num_predict,
            "num_ctx": 8192,
        },
    }

    try:
        response = requests.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json=payload,
            timeout=timeout,
        )

        if not response.ok:
            return {}

        data = response.json()

        raw = (
            data.get("message", {})
            .get("content", "")
        )

        return _parse_json(
            raw,
            {},
        )

    except Exception:
        return {}


# ============================================================
# SECONDARY TRANSCRIPT SEGMENTATION
# ============================================================

def _split_support_text(
    text: str,
) -> list[str]:
    text = _normalize_space(text)

    if not text:
        return []

    text = re.sub(
        r"[।!?]+",
        " <CUT> ",
        text,
    )

    markers = [
        "अगर ",
        "यदि ",
        "लेकिन ",
        "इसलिए ",
        "तो इसलिए ",
        "पर ",
        "क्योंकि ",
        "हम अपनी तरफ से ",
        "कोई ऐसा आचरण ",
        "उसके सामने ",
        "उसको जलाएंगे ",
        "तो इसलिए थोड़ा ",
        "थोड़ा सहनशील ",
        "अगर आपकी तरफ से गलती ",
        "आप हमें क्षमा ",
        "आवश्यकता पड़ने ",
    ]

    for marker in markers:
        text = text.replace(
            f" {marker}",
            f" <CUT> {marker}",
        )

    raw_parts = text.split(
        "<CUT>"
    )

    segments = []

    for part in raw_parts:
        part = _normalize_space(
            part
        ).strip(" .,-")

        if len(part) < 12:
            continue

        words = part.split()

        if len(words) <= 26:
            segments.append(
                part
            )
            continue

        # Fallback for long auto-caption runs.
        block_size = 18

        for i in range(
            0,
            len(words),
            block_size,
        ):
            block = " ".join(
                words[
                    i:
                    i + block_size
                ]
            ).strip()

            if len(block) >= 12:
                segments.append(
                    block
                )

    return segments


# ============================================================
# FIRST PASS:
# CHOOSE EXACT EVIDENCE FROM ONE CANDIDATE
# ============================================================

def _extract_candidate_evidence(
    question: str,
    direct_teaching: str,
    item: dict,
) -> dict | None:
    full_text = _normalize_space(
        item.get(
            "text",
            "",
        )
    )

    if len(full_text) > SUPPORT_TEXT_LIMIT:
        full_text = full_text[
            :SUPPORT_TEXT_LIMIT
        ]

    segments = _split_support_text(
        full_text
    )

    if not segments:
        return None

    numbered = "\n\n".join(
        f"[SEGMENT {i}]\n{segment}"
        for i, segment in enumerate(
            segments
        )
    )

    prompt = f"""
प्रश्न:

{question}

PRIMARY direct teaching:

{direct_teaching}

Secondary satsang candidate:

{numbered}

केवल वे exact segments चुनो जो PRIMARY teaching को
वास्तव में deepen या clarify करते हैं।

सबसे महत्वपूर्ण नियम:

1. केवल segment IDs लौटाओ।

2. कोई evidence स्वयं मत लिखो।

3. सबसे छोटा sufficient evidence चुनो।

4. एक relevant sentence के साथ unrelated sentence मत चुनो।

5. generic भगवान/भजन discussion मत चुनो।

6. केवल:
   "हम गलत कर्म नहीं करेंगे क्योंकि हम भक्त हैं"
   जैसी broad बात इस प्रश्न के लिए पर्याप्त नहीं है।

7. मृत्यु, शरीर, भाग्य, संसार, लक्ष्य आदि की broad बातें
   इस प्रश्न के लिए relevant नहीं हैं।

8. interpersonal behaviour को priority दो।

इस प्रश्न के लिए relevant adjacent principles:

- सहनशीलता
- क्षमा
- विनय
- नम्रता
- जलन/द्वेष न रखना
- सामने वाले की नकारात्मक प्रतिक्रिया की नकल न करना
- अपमान या विरोध में अपना आचरण संभालना

उदाहरण:

"थोड़ा सहनशील बनो"
→ useful

"गलती हुई तो क्षमा मांगो"
→ useful

"हम अपनी तरफ से किसी के प्रति जलन नहीं रखेंगे"
→ useful

"उसके सामने बहुत नम्र रहेंगे"
→ useful

"हम चाहे जहां हों हम प्रभु के पास हैं"
→ इस प्रश्न के लिए unrelated

Relation:

strong
= लगभग वही explicit response principle

useful
= adjacent लेकिन genuinely helpful principle

weak
= broad thematic overlap

unrelated
= अलग विषय

अगर साफ़ relevant evidence नहीं है:

{{
  "relation": "unrelated",
  "segment_ids": [],
  "reason": "..."
}}

अधिकतम {SUPPORT_MAX_EXCERPT_SEGMENTS} segments।

Return JSON only:

{{
  "relation": "strong|useful|weak|unrelated",
  "segment_ids": [2, 4],
  "reason": "..."
}}
"""

    parsed = _ollama_json(
        prompt,
        num_predict=300,
    )

    relation = str(
        parsed.get(
            "relation",
            "",
        )
    ).strip().lower()

    if relation not in {
        "strong",
        "useful",
        "weak",
        "unrelated",
    }:
        return None

    if relation not in {
        "strong",
        "useful",
    }:
        return None

    selected_segments = []
    selected_original_ids = []

    used = set()

    for value in parsed.get(
        "segment_ids",
        [],
    ):
        if not isinstance(
            value,
            (int, float),
        ):
            continue

        segment_id = int(value)

        if not (
            0
            <= segment_id
            < len(segments)
        ):
            continue

        if segment_id in used:
            continue

        used.add(
            segment_id
        )

        selected_original_ids.append(
            segment_id
        )

        selected_segments.append(
            segments[
                segment_id
            ]
        )

        if (
            len(selected_segments)
            >= SUPPORT_MAX_EXCERPT_SEGMENTS
        ):
            break

    if not selected_segments:
        return None

    return {
        "relation": relation,

        "reason": str(
            parsed.get(
                "reason",
                "",
            )
        ).strip(),

        "segment_ids": selected_original_ids,

        "segments": selected_segments,

        "excerpt": _build_excerpt(
            selected_segments
        ),

        "full_text": full_text,
    }


# ============================================================
# SECOND PASS:
# RERANK THE EXACT EXCERPTS THEMSELVES
# ============================================================

def _rerank_exact_excerpts(
    question: str,
    direct_teaching: str,
    extracted: list[dict],
) -> list[dict]:
    if not extracted:
        return []

    focused_query = (
        f"{question}\n\n"
        f"मुख्य शिक्षा:\n"
        f"{direct_teaching}"
    )

    rerank_input = []

    for item in extracted:
        candidate = dict(item)

        # Critical:
        # rerank exact excerpt, NOT original noisy chunk.
        candidate["text"] = item[
            "support_excerpt"
        ]

        rerank_input.append(
            candidate
        )

    try:
        reranked = rerank(
            focused_query,
            rerank_input,
            top_k=len(rerank_input),
        )

    except Exception:
        return []

    score_by_video = {}

    for item in reranked:
        video_id = str(
            item.get(
                "video_id",
                "",
            )
        )

        if not video_id:
            continue

        score_by_video[
            video_id
        ] = _score(item)

    surviving = []

    for item in extracted:
        video_id = str(
            item.get(
                "video_id",
                "",
            )
        )

        excerpt_score = float(
            score_by_video.get(
                video_id,
                0.0,
            )
        )

        item[
            "excerpt_relevance"
        ] = round(
            excerpt_score,
            4,
        )

        if (
            excerpt_score
            < SUPPORT_EXCERPT_MIN_SCORE
        ):
            continue

        surviving.append(
            item
        )

    return surviving


# ============================================================
# THIRD PASS:
# VALIDATE ONLY THE SELECTED EXACT SEGMENTS
# ============================================================

def _validate_exact_segments(
    question: str,
    direct_teaching: str,
    candidates: list[dict],
) -> dict[int, dict]:
    if not candidates:
        return {}

    blocks = []

    for i, candidate in enumerate(
        candidates
    ):
        segment_lines = []

        for local_id, segment in enumerate(
            candidate[
                "support_segments"
            ]
        ):
            segment_lines.append(
                f"[SEGMENT {local_id}] {segment}"
            )

        blocks.append(
            (
                f"[CANDIDATE {i}]\n"
                f"Original relation: "
                f"{candidate['support_relation']}\n"
                f"Exact excerpt rerank score: "
                f"{candidate['excerpt_relevance']}\n"
                + "\n".join(segment_lines)
            )
        )

    material = "\n\n".join(
        blocks
    )

    prompt = f"""
प्रश्न:

{question}

PRIMARY teaching:

{direct_teaching}

नीचे केवल छोटे exact supporting segments दिए गए हैं:

{material}

अब FINAL evidence validation करो।

Full video/chunk के बारे में मत सोचो।
केवल इन exact lines को judge करो।

हर candidate के लिए:

keep = true
केवल यदि कम-से-कम एक exact segment वास्तव में primary
teaching को deepen/clarify करता है।

keep_segment_ids:
Candidate के अंदर केवल वही local segment IDs रखो जो सच में useful हैं।

उदाहरण:

Candidate:
[SEGMENT 0] अगर आपकी तरफ से गलती हुई तो क्षमा मांगो
[SEGMENT 1] हम प्यार के द्वारा पशु को वश में कर सकते हैं

इस प्रश्न के लिए:
keep_segment_ids = [0]

क्योंकि पहला segment useful है,
दूसरा unnecessary analogy है।

दूसरा उदाहरण:

[SEGMENT 0] हम चाहे जहां हों हम प्रभु के पास हैं

इस प्रश्न के लिए:
keep = false

Strong relation तभी:
exact evidence लगभग उसी conflict-response principle पर हो।

Useful:
सहनशीलता, क्षमा, विनय, नम्रता,
द्वेष/जलन न रखना जैसी adjacent teaching।

गलत reason मत बनाओ।
Evidence में जो नहीं है उसे reason में मत लिखो।

Return JSON only:

{{
  "results": [
    {{
      "id": 0,
      "keep": true,
      "relation": "useful",
      "keep_segment_ids": [0],
      "reason": "यह exact line क्षमा की संबंधित शिक्षा देती है"
    }}
  ]
}}
"""

    parsed = _ollama_json(
        prompt,
        num_predict=450,
    )

    decisions = {}

    for result in parsed.get(
        "results",
        [],
    ):
        idx = result.get(
            "id"
        )

        if not isinstance(
            idx,
            int,
        ):
            continue

        if not (
            0
            <= idx
            < len(candidates)
        ):
            continue

        keep = bool(
            result.get(
                "keep",
                False,
            )
        )

        relation = str(
            result.get(
                "relation",
                "useful",
            )
        ).strip().lower()

        if relation not in {
            "strong",
            "useful",
        }:
            relation = "useful"

        valid_segment_ids = []

        max_segments = len(
            candidates[idx][
                "support_segments"
            ]
        )

        for value in result.get(
            "keep_segment_ids",
            [],
        ):
            if not isinstance(
                value,
                (int, float),
            ):
                continue

            value = int(value)

            if (
                0
                <= value
                < max_segments
                and value
                not in valid_segment_ids
            ):
                valid_segment_ids.append(
                    value
                )

        if (
            keep
            and not valid_segment_ids
        ):
            keep = False

        decisions[idx] = {
            "keep": keep,

            "relation": relation,

            "keep_segment_ids": (
                valid_segment_ids
            ),

            "reason": str(
                result.get(
                    "reason",
                    "",
                )
            ).strip(),
        }

    return decisions


# ============================================================
# PUBLIC SECONDARY SEARCH
# ============================================================

def find_supporting_teachings(
    question: str,
    direct_teaching: str,
    *,
    exclude_video_id: str | None = None,
) -> list[dict[str, Any]]:
    query = (
        f"{question}\n\n"
        f"मुख्य सत्संग शिक्षा:\n"
        f"{direct_teaching}"
    )

    # ========================================================
    # 1. FULL CORPUS SEARCH
    # ========================================================

    try:
        candidates = hybrid_search(
            query
        )

        ranked = rerank(
            query,
            candidates,
            top_k=20,
        )

    except Exception:
        return []

    # ========================================================
    # 2. BASIC CANDIDATE PRE-FILTER
    # ========================================================

    prelim = []

    seen_videos = set()

    for item in ranked:
        video_id = str(
            item.get(
                "video_id",
                "",
            )
        ).strip()

        if not video_id:
            continue

        if (
            exclude_video_id
            and video_id
            == exclude_video_id
        ):
            continue

        if video_id in seen_videos:
            continue

        initial_score = _score(
            item
        )

        if (
            initial_score
            < SUPPORT_PREJUDGE_MIN_SCORE
        ):
            continue

        text = _normalize_space(
            item.get(
                "text",
                "",
            )
        )

        if len(text) < 50:
            continue

        seen_videos.add(
            video_id
        )

        prelim.append(
            item
        )

        if (
            len(prelim)
            >= SUPPORT_MAX_CANDIDATES
        ):
            break

    if not prelim:
        return []

    # ========================================================
    # 3. EXACT EVIDENCE EXTRACTION
    # ========================================================

    extracted = []

    for item in prelim:
        evidence = (
            _extract_candidate_evidence(
                question,
                direct_teaching,
                item,
            )
        )

        if not evidence:
            continue

        extracted.append(
            {
                "video_id": item.get(
                    "video_id",
                    "",
                ),

                "title": item.get(
                    "title",
                    "",
                ),

                "published_at": item.get(
                    "published_at"
                ),

                "start_ms": item.get(
                    "start_ms",
                    0,
                ),

                "end_ms": item.get(
                    "end_ms",
                    0,
                ),

                # Original chunk for debug only.
                "text": evidence[
                    "full_text"
                ],

                "support_segments": evidence[
                    "segments"
                ],

                "support_excerpt": evidence[
                    "excerpt"
                ],

                # Chunk-level reranker score.
                "relevance": round(
                    _score(item),
                    4,
                ),

                "support_relation": evidence[
                    "relation"
                ],

                "support_reason": evidence[
                    "reason"
                ],

                "support_segment_ids": evidence[
                    "segment_ids"
                ],
            }
        )

    if not extracted:
        return []

    # ========================================================
    # 4. RERANK EXACT EXCERPTS
    # ========================================================

    extracted = _rerank_exact_excerpts(
        question,
        direct_teaching,
        extracted,
    )

    if not extracted:
        return []

    # ========================================================
    # 5. FINAL EXACT-SEGMENT VALIDATION
    # ========================================================

    validation = _validate_exact_segments(
        question,
        direct_teaching,
        extracted,
    )

    if not validation:
        return []

    accepted = []

    for i, item in enumerate(
        extracted
    ):
        decision = validation.get(
            i
        )

        if not decision:
            continue

        if not decision[
            "keep"
        ]:
            continue

        local_ids = decision[
            "keep_segment_ids"
        ]

        final_segments = [
            item[
                "support_segments"
            ][local_id]
            for local_id in local_ids
        ]

        final_excerpt = _build_excerpt(
            final_segments
        )

        if not final_excerpt:
            continue

        item[
            "support_segments"
        ] = final_segments

        item[
            "support_excerpt"
        ] = final_excerpt

        item[
            "support_relation"
        ] = decision[
            "relation"
        ]

        if decision.get(
            "reason"
        ):
            item[
                "support_reason"
            ] = decision[
                "reason"
            ]

        accepted.append(
            item
        )

    # ========================================================
    # 6. FINAL SORT
    # ========================================================

    relation_priority = {
        "strong": 2,
        "useful": 1,
    }

    accepted.sort(
        key=lambda item: (
            relation_priority.get(
                item.get(
                    "support_relation",
                    "",
                ),
                0,
            ),
            float(
                item.get(
                    "excerpt_relevance",
                    0.0,
                )
            ),
            float(
                item.get(
                    "relevance",
                    0.0,
                )
            ),
        ),
        reverse=True,
    )

    return accepted[
        :SUPPORT_MAX_SOURCES
    ]
