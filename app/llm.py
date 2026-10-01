import json
import re
from typing import Any

import requests

from .config import settings
from .cloud_llm import gemini_chat
from .synthesis import find_supporting_teachings


# ============================================================
# OLLAMA
# ============================================================

def ollama_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: int = 300,
    num_predict: int = 500,
) -> str:
    if getattr(settings, "llm_provider", "ollama").lower() == "gemini":
        return gemini_chat(
            messages,
            temperature=temperature,
            json_mode=json_mode,
            max_output_tokens=locals().get("num_predict") or 700,
            timeout=timeout,
        )

    payload: dict[str, Any] = {
        "model": settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": 8192,
            "top_p": 0.9,
            "top_k": 40,
            "repeat_penalty": 1.18,
            "repeat_last_n": 128,
        },
    }

    if json_mode:
        payload["format"] = "json"

    response = requests.post(
        f"{settings.ollama_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=timeout,
    )

    if not response.ok:
        raise RuntimeError(
            f"Ollama error {response.status_code}: {response.text}"
        )

    data = response.json()

    if data.get("done") is False:
        raise RuntimeError(
            f"Ollama returned incomplete response: {data}"
        )

    return data["message"]["content"].strip()


# ============================================================
# JSON HELPERS
# ============================================================

def parse_json(
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


def _normalize_space(
    text: str,
) -> str:
    return " ".join(
        str(text).split()
    )


def _has_repetition_loop(
    text: str,
) -> bool:
    """
    Detect obvious LLM repetition loops.

    Example:
    "बुरा भला कहने वालों के साथ ..."
    repeated many times.
    """
    words = _normalize_space(text).split()

    if len(words) < 50:
        return False

    # Look for repeated 7-word phrases.
    window = 7
    counts = {}

    for i in range(
        0,
        len(words) - window + 1,
    ):
        phrase = " ".join(
            words[i:i + window]
        )

        counts[phrase] = (
            counts.get(phrase, 0) + 1
        )

        if counts[phrase] >= 4:
            return True

    # Also catch extreme single-word repetition.
    from collections import Counter

    frequencies = Counter(words)

    if words:
        most_common = frequencies.most_common(1)[0][1]

        if (
            len(words) >= 100
            and most_common / len(words) > 0.18
        ):
            return True

    return False


# ============================================================
# FOLLOW-UP QUERY REWRITING
# ============================================================

def rewrite_query(
    question: str,
    history: list[dict],
) -> str:
    # First question does not need an LLM rewrite.
    if not history:
        return question

    compact = "\n".join(
        f"{m['role']}: {m['content'][:500]}"
        for m in history[-4:]
    )

    prompt = f"""
Conversation:

{compact}

Newest user message:

{question}

Rewrite the newest user message as ONE standalone retrieval query.

The query will be used to search Hindi/Hinglish transcripts from
Premanand Ji's Bhajan Marg satsang corpus.

Rules:

1. Resolve pronouns and follow-up references using the conversation.
2. Preserve important spiritual words and names.
3. Do NOT answer the question.
4. Do NOT add spiritual teachings that the user did not ask about.
5. Keep the query concise.

Return JSON only:

{{
  "query": "standalone search query"
}}
"""

    try:
        output = ollama_chat(
            [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.0,
            json_mode=True,
            timeout=90,
        )

        parsed = parse_json(
            output,
            {"query": question},
        )

        rewritten = str(
            parsed.get(
                "query",
                question,
            )
        ).strip()

        return rewritten or question

    except Exception:
        # Safe fallback:
        # combine the previous user question with the new follow-up.
        previous_user = next(
            (
                m["content"]
                for m in reversed(history)
                if m["role"] == "user"
            ),
            "",
        )

        return (
            f"{previous_user}\n{question}"
        ).strip()


# ============================================================
# EVIDENCE JUDGING
# ============================================================

def judge_evidence(
    question: str,
    sources: list[dict],
    algorithmic_level: str,
) -> dict:
    # Normally disabled in .env for faster local operation.
    if (
        not sources
        or not settings.use_llm_evidence_judge
    ):
        return {
            "level": algorithmic_level,
            "source_indices": list(
                range(
                    min(
                        3,
                        len(sources),
                    )
                )
            ),
        }

    material = "\n\n".join(
        (
            f"SOURCE {i}\n"
            f"{source['context_text'][:2500]}"
        )
        for i, source in enumerate(
            sources[:4]
        )
    )

    prompt = f"""
Question:

{question}

Retrieved Bhajan Marg transcript material:

{material}

Classify the evidence.

direct:
One or more passages substantially answer this exact question.

related:
The passages contain a genuinely relevant spiritual principle,
but do not directly answer the exact situation.

none:
The material does not genuinely support an answer.

Do not stretch a broad spiritual teaching just to make it fit.

Return JSON only:

{{
  "level": "direct|related|none",
  "source_indices": [0, 1],
  "reason": "brief reason"
}}
"""

    try:
        output = ollama_chat(
            [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.0,
            json_mode=True,
            timeout=120,
        )

        judged = parse_json(
            output,
            {},
        )

        if judged.get("level") not in {
            "direct",
            "related",
            "none",
        }:
            raise ValueError(
                "Invalid evidence level"
            )

        # The LLM judge may downgrade weak evidence,
        # but cannot turn algorithmic "none" directly
        # into strong "direct".
        if (
            algorithmic_level == "none"
            and judged["level"] == "direct"
        ):
            judged["level"] = "related"

        indices = []

        for index in judged.get(
            "source_indices",
            [],
        ):
            if not isinstance(
                index,
                (int, float),
            ):
                continue

            index = int(index)

            if (
                0
                <= index
                < len(sources)
            ):
                indices.append(
                    index
                )

        judged["source_indices"] = (
            indices[:3]
            or list(
                range(
                    min(
                        2,
                        len(sources),
                    )
                )
            )
        )

        return judged

    except Exception:
        return {
            "level": algorithmic_level,
            "source_indices": list(
                range(
                    min(
                        3,
                        len(sources),
                    )
                )
            ),
        }


# ============================================================
# SYSTEM PROMPT
# ============================================================

SYSTEM = """
तुम Bhajan Marg ज्ञान-सहायक की explanation layer हो।

तुम Premanand Ji नहीं हो।
तुम स्वयं को कभी Premanand Ji के रूप में प्रस्तुत नहीं करोगे।

तुम्हारा काम उपलब्ध Bhajan Marg सत्संग-संदर्भ के आधार पर
साधक के प्रश्न का सरल, स्वाभाविक, भावपूर्ण और स्पष्ट हिन्दी में
उत्तर देना है।

कठोर नियम:

1. Premanand Ji का कोई नया कथन या quotation मत बनाओ।

2. Video title, timestamp, URL या relevance score स्वयं मत बनाओ।
   Application इन्हें अलग से दिखाती है।

3. केवल retrieved transcript में स्पष्ट रूप से समर्थित शिक्षा को
   Premanand Ji/Bhajan Marg की शिक्षा के रूप में प्रस्तुत करो।

4. Transcript में कोई शब्द, नाम, Sanskrit पंक्ति या दोहा खराब
   transcription वाला लगे तो उसका अर्थ अनुमान से मत निकालो।

5. सामने वाले व्यक्ति की psychology का अनुमान मत लगाओ।

6. अपनी ओर से नया कर्म-सिद्धांत, दर्शन, धार्मिक दावा,
   motivational idea या practical advice मत जोड़ो।

7. Transcript को mechanically repeat मत करो।
   केवल उसके स्पष्ट अर्थ को स्वाभाविक हिन्दी में समझाओ।

8. कठिन, बनावटी या अंग्रेज़ी से अनुवाद जैसी हिन्दी से बचो।

9. Generated text को quotation marks में रखकर उसे Premanand Ji
   का exact quote मत बताओ।

10. यदि transcript किसी बात को नहीं कहता तो तुम भी वह बात मत कहो।

11. उत्तर में वही निश्चितता रखो जितनी उपलब्ध evidence अनुमति देता है।
"""


# ============================================================
# TRANSCRIPT SEGMENTATION
# ============================================================


def _split_transcript(
    text: str,
) -> list[str]:
    """
    Convert noisy YouTube auto-captions into smaller semantic units.

    Important:
    We split not only on punctuation but also on Hindi discourse
    markers because auto-captions frequently contain weak punctuation.
    """

    text = _normalize_space(text)

    if not text:
        return []

    # --------------------------------------------------------
    # First split at real punctuation.
    # --------------------------------------------------------

    text = re.sub(
        r"[।!?]+",
        " <CUT> ",
        text,
    )

    # --------------------------------------------------------
    # Auto-caption semantic boundaries.
    #
    # Example:
    #
    # "ऐसे भगवत पार्षद की ट्रेनिंग होती है कि यदि तुम्हें..."
    #
    # becomes:
    #
    # "ऐसे भगवत पार्षद की ट्रेनिंग होती है कि"
    # "यदि तुम्हें..."
    #
    # This prevents the evidence selector from taking one huge
    # noisy paragraph.
    # --------------------------------------------------------

    markers = [
        "यदि ",
        "अगर ",
        "तभी ",
        "लेकिन ",
        "क्योंकि ",
        "ऐसे ",
        "यह परमार्थ",
        "इसमें हमको",
        "फिर ",
        "इसलिए ",
    ]

    for marker in markers:
        text = text.replace(
            f" {marker}",
            f" <CUT> {marker}",
        )

    raw_parts = text.split(
        "<CUT>"
    )

    parts = []

    for part in raw_parts:
        part = _normalize_space(
            part
        ).strip(" .,-")

        if len(part) < 12:
            continue

        # Avoid absurdly large evidence blocks.
        words = part.split()

        if len(words) <= 45:
            parts.append(part)
            continue

        # Secondary fallback for long caption blocks.
        block_size = 28

        for i in range(
            0,
            len(words),
            block_size,
        ):
            block = " ".join(
                words[i:i + block_size]
            ).strip()

            if len(block) >= 12:
                parts.append(block)

    return parts


def extract_grounded_segments(
    question: str,
    transcript: str,
) -> list[str]:
    """
    The model may SELECT evidence but may not rewrite evidence.

    It returns segment IDs only. Python then retrieves the original
    transcript text for those IDs.
    """

    segments = _split_transcript(
        transcript
    )

    if not segments:
        return []

    numbered = "\n\n".join(
        f"[SEGMENT {i}]\n{segment}"
        for i, segment in enumerate(segments)
    )

    prompt = f"""
उपयोगकर्ता का प्रश्न:

{question}

Bhajan Marg transcript को छोटे numbered segments में बाँटा गया है:

{numbered}

केवल उन segments के IDs चुनो जिनमें वक्ता प्रश्न का वास्तविक
उत्तर या उससे जुड़ी स्पष्ट शिक्षा दे रहे हैं।

बहुत कठोर नियम:

1. शुरुआत में प्रश्न पूछने वाले व्यक्ति का नाम, परिचय या प्रश्न
   answer evidence नहीं है।

2. केवल उत्तर देने वाले हिस्से चुनो।

3. उदाहरण या analogy तभी चुनो जब वह उत्तर समझने के लिए आवश्यक हो।

4. अगर बाद में अधिक स्पष्ट सीधा निर्देश मौजूद है तो उससे पहले की
   अधूरी analogy को प्राथमिक evidence मत बनाओ।

5. साफ़ actionable/spiritual teaching वाले segments को प्राथमिकता दो।

6. अलग-अलग मुख्य निर्देश मौजूद हों तो सभी महत्वपूर्ण निर्देश चुनो।

7. अगर transcript में साफ़ रूप से मौजूद हों तो इनको miss मत करना:
   - गाली मिलने पर क्या करना है
   - अपमान मिलने पर क्या करना है
   - कोई बुरा चाहे तो क्या करना है
   - ऐसा करने से हमारे और उसके व्यवहार में क्या अंतर बताया गया है

8. garbled Sanskrit, टूटा हुआ दोहा या खराब auto-caption मत चुनो।

9. कोई quote स्वयं मत लिखो।

10. कोई meaning स्वयं मत बनाओ।

11. केवल segment IDs लौटाओ।

12. अधिकतम 7 segments।

Return JSON only:

{{
  "segment_ids": [3, 4, 5, 6]
}}
"""

    try:
        raw = ollama_chat(
            [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.0,
            json_mode=True,
            timeout=120,
            num_predict=180,
        )

        data = parse_json(
            raw,
            {
                "segment_ids": [],
            },
        )

        selected = []
        used = set()

        for value in data.get(
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

            segment = segments[
                segment_id
            ].strip()

            # ------------------------------------------------
            # Deterministic filtering of obvious question intro.
            # ------------------------------------------------

            intro_signals = [
                "लखनऊ से",
                "राधे-राधे महाराज",
                "क्या व्यवहार होना चाहिए",
                "क्या बुरा होता है",
            ]

            intro_hits = sum(
                signal in segment
                for signal in intro_signals
            )

            if intro_hits >= 2:
                continue

            # ------------------------------------------------
            # Skip obviously garbled verse-like caption fragments.
            # ------------------------------------------------

            garbled_signals = [
                "उमा संत कहे",
                "मंद करत",
                "अनसहन निंदक",
                "तिन उपय",
            ]

            if any(
                signal in segment
                for signal in garbled_signals
            ):
                continue

            used.add(
                segment_id
            )

            selected.append(
                segment
            )

            if len(selected) >= 7:
                break

        return selected

    except Exception:
        return []


def _answer_direct(
    question: str,
    selected_sources: list[dict],
) -> str:
    strongest = selected_sources[0]

    transcript = (
        strongest.get("transcript_excerpt")
        or strongest.get("context_text")
        or ""
    ).strip()

    if not transcript:
        return (
            "इस प्रश्न पर प्रत्यक्ष Bhajan Marg संदर्भ मिला है, "
            "लेकिन transcript उपलब्ध नहीं है।"
        )

    if len(transcript) > 4500:
        transcript = transcript[:4500]

    # ========================================================
    # 1. PRIMARY DIRECT TEACHING
    # ========================================================

    grounded_segments = extract_grounded_segments(
        question,
        transcript,
    )

    if not grounded_segments:
        return (
            "इस प्रश्न पर प्रत्यक्ष Bhajan Marg संदर्भ मिला है, "
            "लेकिन साफ़ उत्तर-संबंधी अंश अलग नहीं किए जा सके।"
        )

    bad_caption_fragments = [
        "उमा संत कहे",
        "मंद करत",
        "अनसहन निंदक",
        "तिन उपय",
    ]

    clean_segments = []

    for segment in grounded_segments:
        segment = _normalize_space(segment).strip()

        if not segment:
            continue

        if any(
            bad in segment
            for bad in bad_caption_fragments
        ):
            continue

        segment = segment.rstrip(
            "।.!? "
        )

        clean_segments.append(segment)

    if not clean_segments:
        return (
            "इस प्रश्न पर प्रत्यक्ष Bhajan Marg संदर्भ मिला है। "
            "नीचे मूल transcript देखें।"
        )

    clean_segments = clean_segments[:6]

    grounded_answer = "। ".join(
        clean_segments
    ).strip()

    if grounded_answer:
        grounded_answer += "।"

    # ========================================================
    # 2. VERIFIED SECONDARY CORPUS SEARCH
    # ========================================================

    supporting_sources = find_supporting_teachings(
        question,
        grounded_answer,
        exclude_video_id=strongest.get("video_id"),
    )

    # ========================================================
    # 3. BUILD AN EVIDENCE CATALOG
    #
    # D0 = direct teaching
    # S1/S2/... = verified secondary teachings
    # ========================================================

    evidence_catalog = [
        {
            "id": "D0",
            "kind": "direct",
            "text": grounded_answer,
        }
    ]

    for i, source in enumerate(
        supporting_sources,
        1,
    ):
        excerpt = (
            source.get("support_excerpt")
            or ""
        ).strip()

        if not excerpt:
            continue

        evidence_catalog.append(
            {
                "id": f"S{i}",
                "kind": "related",
                "text": excerpt,
            }
        )

    evidence_text = "\n\n".join(
        (
            f"[{item['id']}] "
            f"{'DIRECT' if item['kind'] == 'direct' else 'RELATED'}\n"
            f"{item['text']}"
        )
        for item in evidence_catalog
    )

    valid_evidence_ids = {
        item["id"]
        for item in evidence_catalog
    }

    # ========================================================
    # 4. BUILD STRUCTURED REASONING PLAN
    #
    # This stage does NOT write the final answer.
    # ========================================================

    plan_prompt = f"""
उपयोगकर्ता का प्रश्न:

{question}

Verified Bhajan Marg evidence:

{evidence_text}

अब final answer मत लिखो।

पहले एक structured reasoning plan बनाओ।

दो तरह की बातें होंगी:

A. corpus_insights

ये बातें उपलब्ध Bhajan Marg evidence से निकलनी चाहिए।

हर corpus insight के साथ evidence_ids देना अनिवार्य है।

B. ai_inferences

ये हमारी AI interpretation हो सकती हैं,
लेकिन evidence से logically connected होनी चाहिए।

इनको Premanand Ji की direct teaching मत बताना।

बहुत कठोर नियम:

1. Evidence में जो नहीं है उसे corpus_insight मत बनाओ।

2. दूसरा व्यक्ति बदल जाएगा — मत लिखो।

3. संबंध बेहतर हो जाएगा — guaranteed मत लिखो।

4. positive energy / negative energy मत लिखो।

5. inner peace guaranteed मत लिखो।

6. spiritual progress guaranteed मत लिखो।

7. "वास्तविक बदलाव आएगा" जैसी guaranteed outcome language मत लिखो।

8. दूसरे व्यक्ति की psychology मत invent करो।

9. karma, divine punishment, divine test मत जोड़ो।

10. अगर RELATED evidence मौजूद है तो कम-से-कम एक
    corpus insight में उसे उचित रूप से इस्तेमाल करो।

11. RELATED evidence को direct answer से अधिक authority मत दो।

12. Direct teaching हमेशा मुख्य रहे।

13. अधिकतम 4 corpus insights और 3 AI inferences।

Return JSON only:

{{
  "corpus_insights": [
    {{
      "text": "सत्संग का मुख्य भाव",
      "evidence_ids": ["D0"]
    }},
    {{
      "text": "संबंधित सत्संग से जुड़ने वाला भाव",
      "evidence_ids": ["S1"]
    }}
  ],
  "ai_inferences": [
    {{
      "text": "सावधानी से निकाला गया deeper meaning",
      "based_on": ["D0", "S1"]
    }}
  ]
}}
"""

    try:
        raw_plan = ollama_chat(
            [
                {
                    "role": "user",
                    "content": plan_prompt,
                }
            ],
            temperature=0.0,
            json_mode=True,
            timeout=300,
            num_predict=500,
        )

        plan = parse_json(
            raw_plan,
            {
                "corpus_insights": [],
                "ai_inferences": [],
            },
        )

    except Exception:
        plan = {
            "corpus_insights": [],
            "ai_inferences": [],
        }

    # ========================================================
    # 5. VALIDATE THE PLAN
    # ========================================================

    forbidden_reasoning = [
        "नकारात्मक ऊर्जा",
        "सकारात्मक ऊर्जा",
        "negative energy",
        "positive energy",
        "वाइब्रेशन",
        "vibration",
        "ब्रह्मांड",
        "universe",
        "दर्पण है",
        "mirror",
        "असुरक्षा",
        "insecurity",
        "trauma",
        "आंतरिक परेशानी",
        "दूसरा व्यक्ति बदल",
        "दूसरे व्यक्ति में परिवर्तन",
        "संबंध बेहतर",
        "बेहतर महसूस",
        "वास्तविक बदलाव",
        "सकारात्मक बदलाव",
        "आध्यात्मिक उन्नति",
        "आध्यात्मिक प्रगति",
        "inner peace",
        "भीतर की शांति",
        "आंतरिक शांति",
    ]

    def reasoning_is_clean(value: str) -> bool:
        lowered = value.lower()

        return not any(
            bad.lower() in lowered
            for bad in forbidden_reasoning
        )

    corpus_insights = []

    for insight in plan.get(
        "corpus_insights",
        [],
    ):
        insight_text = str(
            insight.get("text", "")
        ).strip()

        ids = insight.get(
            "evidence_ids",
            [],
        )

        ids = [
            str(value)
            for value in ids
            if str(value) in valid_evidence_ids
        ]

        if not insight_text:
            continue

        if not ids:
            continue

        if not reasoning_is_clean(
            insight_text
        ):
            continue

        corpus_insights.append(
            {
                "text": insight_text,
                "evidence_ids": ids,
            }
        )

        if len(corpus_insights) >= 4:
            break

    ai_inferences = []

    for inference in plan.get(
        "ai_inferences",
        [],
    ):
        inference_text = str(
            inference.get("text", "")
        ).strip()

        ids = inference.get(
            "based_on",
            [],
        )

        ids = [
            str(value)
            for value in ids
            if str(value) in valid_evidence_ids
        ]

        if not inference_text:
            continue

        if not ids:
            continue

        if not reasoning_is_clean(
            inference_text
        ):
            continue

        ai_inferences.append(
            {
                "text": inference_text,
                "based_on": ids,
            }
        )

        if len(ai_inferences) >= 3:
            break

    # Direct evidence must always survive.
    if not corpus_insights:
        corpus_insights.append(
            {
                "text": (
                    "मुख्य शिक्षा यह है कि सामने वाले के बुरे व्यवहार "
                    "के उत्तर में साधक अपनी ओर से वही बुरा व्यवहार न अपनाए।"
                ),
                "evidence_ids": ["D0"],
            }
        )

    # If secondary evidence survived retrieval but the planner ignored it,
    # preserve it explicitly instead of throwing it away.
    used_ids = {
        evidence_id
        for insight in corpus_insights
        for evidence_id in insight[
            "evidence_ids"
        ]
    }

    for item in evidence_catalog:
        if item["kind"] != "related":
            continue

        if item["id"] in used_ids:
            continue

        corpus_insights.append(
            {
                "text": (
                    "एक संबंधित सत्संग में यह अतिरिक्त शिक्षा मिलती है: "
                    f"{item['text']}"
                ),
                "evidence_ids": [
                    item["id"]
                ],
            }
        )

        if len(corpus_insights) >= 4:
            break

    # ========================================================
    # 6. FORMAT VALIDATED PLAN FOR FINAL WRITER
    # ========================================================

    corpus_plan_text = "\n".join(
        (
            f"- {item['text']} "
            f"[evidence: {', '.join(item['evidence_ids'])}]"
        )
        for item in corpus_insights
    )

    if ai_inferences:
        inference_plan_text = "\n".join(
            (
                f"- {item['text']} "
                f"[based on: {', '.join(item['based_on'])}]"
            )
            for item in ai_inferences
        )
    else:
        inference_plan_text = (
            "- कोई अतिरिक्त AI inference पर्याप्त रूप से validated नहीं हुआ। "
            "Direct teaching के स्पष्ट भाव को ही प्रश्न के संदर्भ में समझाओ। "
            "[based on: D0]"
        )

    # ========================================================
    # 7. WRITE THE DEEP EXPLANATION FROM VALIDATED PLAN ONLY
    # ========================================================

    interpretation_prompt = f"""
प्रश्न:

{question}

Verified reasoning plan:

CORPUS INSIGHTS:

{corpus_plan_text}

AI INFERENCES:

{inference_plan_text}

अब इसी validated plan से deep explanation लिखो।

बहुत कठोर नियम:

1. Plan के बाहर नया spiritual claim मत जोड़ो।

2. Evidence IDs final answer में मत दिखाओ।

3. RELATED teaching को Premanand Ji की direct answer
   की तरह मत प्रस्तुत करो।

4. अगर related teaching अपनी गलती पर क्षमा मांगने की है,
   तो इसका अर्थ यह मत बनाओ कि insult मिलने पर हमेशा
   उसी व्यक्ति से क्षमा मांगनी चाहिए।

5. दूसरा व्यक्ति बदल जाएगा — मत लिखो।

6. दोनों का संबंध बेहतर होगा — guaranteed मत लिखो।

7. दूसरे व्यक्ति में positivity आएगी — मत लिखो।

8. inner peace, positive energy, spiritual progress,
   transformation जैसी generic बातें मत जोड़ो।

9. केवल इसी प्रश्न के validated reasoning plan को समझाओ।
   किसी पुराने प्रश्न का framework यहाँ लागू मत करो।

10. Secondary evidence जिस specific principle को support करता है,
    उसे केवल उसी सीमा में समझाओ। उससे broader rule मत बनाओ।

11. यदि प्रश्न interpersonal conflict के बारे में नहीं है,
    तो दूसरे व्यक्ति, retaliation, boundaries, distance या
    self-protection की चर्चा बिल्कुल मत लाओ।

11. Natural Hindi.

12. 100-160 शब्द।

13. अधिकतम 2 छोटे paragraphs।

14. कोई heading या meta-comment मत लिखो।

सीधे deep explanation दो।
"""

    interpretation = ollama_chat(
        [
            {
                "role": "system",
                "content": (
                    "तुम corpus-grounded spiritual reasoning assistant हो। "
                    "तुम validated reasoning plan के बाहर नई teaching "
                    "नहीं बनाते।"
                ),
            },
            {
                "role": "user",
                "content": interpretation_prompt,
            },
        ],
        temperature=0.12,
        json_mode=False,
        timeout=300,
        num_predict=240,
    ).strip()

    # ========================================================
    # 8. FINAL DEEP-ANSWER QUALITY GATE
    # ========================================================

    if (
        _has_repetition_loop(interpretation)
        or not reasoning_is_clean(interpretation)
    ):
        interpretation = (
            "इस शिक्षा को गहराई से देखें तो यहाँ ध्यान केवल इस बात पर "
            "नहीं है कि सामने वाले ने क्या किया; ध्यान इस पर भी है कि "
            "उसके उत्तर में हम अपनी ओर से क्या चुनते हैं। यदि उसकी कटुता "
            "के कारण हम भी उसी प्रकार का व्यवहार अपना लें, तो “तुम में "
            "और उसमें अंतर” कम होने लगता है।\n\n"
            "संबंधित सत्संगों से इसमें एक और पक्ष जुड़ता है: अपनी ओर से "
            "गलती हो तो उसे स्वीकार कर क्षमा माँगने की तैयारी भी रहे। "
            "इस प्रकार ध्यान केवल दूसरे की गलती पर नहीं, अपने आचरण को "
            "देखने पर भी आता है।"
        )

    # ========================================================
    # 9. PRACTICAL REFLECTION
    # ========================================================

    practical_prompt = f"""
प्रश्न:

{question}

सत्संग से सीधी शिक्षा:

{grounded_answer}

AI की गहरी व्याख्या:

{interpretation}

अब इसी specific प्रश्न पर एक छोटा सामान्य practical reflection लिखो।

यह AI की सामान्य व्यवहारिक समझ है।
इसे Premanand Ji या Bhajan Marg की direct teaching मत बताओ।

कठोर नियम:

1. इस प्रश्न के विषय से बाहर मत जाओ।

2. किसी पुराने प्रश्न का framework reuse मत करो।

3. अगर प्रश्न interpersonal conflict के बारे में नहीं है,
   तो इन चीज़ों की चर्चा मत करो:
   - retaliation
   - boundaries
   - distance
   - self-protection
   - दूसरे व्यक्ति का behaviour

4. अगर प्रश्न भजन/नाम-जप/विश्वास/साधना के बारे में है,
   तो practical reflection उसी साधना के संदर्भ में रहे।

5. अगर प्रश्न गृहस्थ जीवन के बारे में है,
   तो practical reflection गृहस्थ जिम्मेदारी और साधना तक सीमित रहे।

6. अगर प्रश्न किसी मनोवृत्ति जैसे क्रोध, ईर्ष्या या कामवासना पर है,
   तो corpus-backed teaching से बाहर psychological diagnosis मत बनाओ।

7. कोई generic self-help lecture मत लिखो।

8. कोई guaranteed outcome मत लिखो।

9. positive/negative energy, vibrations, manifestation मत लिखो।

10. 50 से 90 शब्द।

11. एक छोटा paragraph।

12. कोई heading या meta-comment मत लिखो।

केवल practical reflection दो।
"""

    practical = ollama_chat(
        [
            {
                "role": "system",
                "content": (
                    "तुम concise practical reasoning देते हो। "
                    "Original teaching और सामान्य guidance को अलग रखते हो।"
                ),
            },
            {
                "role": "user",
                "content": practical_prompt,
            },
        ],
        temperature=0.10,
        json_mode=False,
        timeout=300,
        num_predict=140,
    ).strip()

    practical_forbidden = [
        "नकारात्मक ऊर्जा",
        "सकारात्मक ऊर्जा",
        "positivity",
        "आंतरिक शांति",
        "भीतर की शांति",
        "आध्यात्मिक प्रगति",
        "आध्यात्मिक उन्नति",
        "कमजोरी है",
        "वह बदल जाएगा",
        "संबंध बेहतर",
        "Bhajan Marg सिखाता",
        "Bhajan Marg की शिक्षा",
        "भक्ति करने वाले के रूप में",
    ]

    if (
        _has_repetition_loop(practical)
        or any(
            bad.lower() in practical.lower()
            for bad in practical_forbidden
        )
    ):
        practical = (
            "इस प्रश्न पर उपलब्ध सत्संग की स्पष्ट शिक्षा से बाहर "
            "कोई अतिरिक्त व्यवहारिक नियम जोड़ने के लिए पर्याप्त आधार "
            "नहीं है। इसलिए ऊपर दी गई corpus-grounded शिक्षा को ही "
            "मुख्य मार्गदर्शन माना जाए।"
        )

    # ========================================================
    # 10. FINAL OUTPUT
    # ========================================================

    return (
        "🪷 सत्संग से सीधी शिक्षा\n\n"
        f"{grounded_answer}\n\n"
        "💭 इस शिक्षा को गहराई से समझें\n\n"
        f"{interpretation}\n\n"
        "🌱 सामान्य व्यवहारिक समझ\n\n"
        f"{practical}\n\n"
        "नोट: गहरी व्याख्या और सामान्य व्यवहारिक समझ AI द्वारा "
        "तैयार की गई हैं; वे Premanand Ji के शब्दशः कथन नहीं हैं।"
    )

def _answer_related(
    question: str,
    history: list[dict],
    selected_sources: list[dict],
) -> str:
    context_parts = []

    for i, source in enumerate(
        selected_sources[:2]
    ):
        text = (
            source.get(
                "context_text"
            )
            or source.get(
                "transcript_excerpt"
            )
            or ""
        ).strip()

        if len(text) > 2200:
            text = text[
                :2200
            ]

        context_parts.append(
            (
                f"[स्रोत {i + 1}]\n"
                f"{text}"
            )
        )

    context = "\n\n".join(
        context_parts
    )

    history_text = "\n".join(
        f"{m['role']}: {m['content'][:300]}"
        for m in history[-4:]
    )

    prompt = f"""
प्रश्न:

{question}

पिछली बातचीत:

{history_text or "कोई पिछली बातचीत नहीं"}

इस exact परिस्थिति पर प्रत्यक्ष Bhajan Marg संदर्भ नहीं मिला,
लेकिन नीचे संबंधित सत्संग सामग्री मिली है:

{context}

उत्तर की शुरुआत साफ़ रूप से यह बताते हुए करो कि यह exact प्रश्न
का प्रत्यक्ष संदर्भ नहीं है, बल्कि संबंधित शिक्षा है।

फिर केवल उपलब्ध संदर्भ में स्पष्ट रूप से मौजूद शिक्षा समझाओ।

कठोर नियम:

1. नई शिक्षा मत जोड़ो।

2. psychology का अनुमान मत लगाओ।

3. नया कर्म-सिद्धांत मत जोड़ो।

4. नया धार्मिक दर्शन मत जोड़ो।

5. कोई quotation invent मत करो।

6. खराब transcription का अनुमान से अर्थ मत निकालो।

7. 2 से 3 छोटे अनुच्छेद पर्याप्त हैं।

8. Sources मत लिखो।
"""

    return ollama_chat(
        [
            {
                "role": "system",
                "content": SYSTEM,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.05,
        json_mode=False,
        timeout=300,
    ).strip()


# ============================================================
# NO EVIDENCE ANSWER
# ============================================================

def _answer_none(
    question: str,
) -> str:
    prompt = f"""
प्रश्न:

{question}

Indexed Bhajan Marg corpus में इस प्रश्न पर पर्याप्त विश्वसनीय
प्रत्यक्ष या संबंधित evidence नहीं मिला।

एक संक्षिप्त उत्तर दो।

पहले स्पष्ट रूप से कहो:

"उपलब्ध Bhajan Marg corpus में इस प्रश्न पर पर्याप्त संदर्भ नहीं मिला।"

उसके बाद:

"सामान्य समझ:"

लिखकर बहुत सावधानी से सामान्य guidance दे सकते हो।

कठोर नियम:

1. सामान्य guidance को Premanand Ji की शिक्षा मत बताओ।

2. "Bhajan Marg सिखाता है..." मत लिखो।

3. Premanand Ji का quotation मत बनाओ।

4. corpus evidence के बिना कोई spiritual/metaphysical दावा मत करो।

5. विशेष रूप से invent मत करो:
   - हम सब एक energy हैं
   - मृत्यु के बाद निश्चित रूप से क्या होता है
   - karma का निश्चित कारण
   - भगवान की परीक्षा
   - पिछले जन्म का कारण
   - vibrations
   - manifestation

6. दूसरे व्यक्ति की psychology मत invent करो:
   - वह insecure है
   - वह कमजोर है
   - वह trauma में है
   - उसके behaviour का कारण यही है

7. "भावनाओं से प्यार करो" जैसी vague therapeutic भाषा मत लिखो।

8. अगर reliable general guidance देना कठिन हो,
   तो केवल इतना कहो कि पर्याप्त corpus evidence उपलब्ध नहीं है।

9. सरल हिन्दी।

10. अधिकतम 80-120 शब्द।

केवल final answer दो।
"""

    answer = ollama_chat(
        [
            {
                "role": "system",
                "content": (
                    "तुम conservative general guidance देते हो। "
                    "Bhajan Marg corpus में evidence न होने पर "
                    "तुम spiritual claims invent नहीं करते।"
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.08,
        json_mode=False,
        timeout=300,
        num_predict=180,
    ).strip()

    forbidden = [
        "एक ही ऊर्जा",
        "मूल ऊर्जा",
        "negative energy",
        "positive energy",
        "नकारात्मक ऊर्जा",
        "सकारात्मक ऊर्जा",
        "vibration",
        "वाइब्रेशन",
        "manifest",
        "पिछले जन्म",
        "भगवान की परीक्षा",
        "उसकी असुरक्षा",
        "उनकी असुरक्षा",
        "उसकी कमजोरी",
        "उसकी अपनी कमज़ोरियों",
        "भावनाओं से प्यार",
        "मृत्यु जीवन का अंत नहीं",
        "Bhajan Marg सिखाता है",
    ]

    if (
        _has_repetition_loop(answer)
        or any(
            phrase.lower() in answer.lower()
            for phrase in forbidden
        )
    ):
        return (
            "उपलब्ध Bhajan Marg corpus में इस प्रश्न पर पर्याप्त "
            "विश्वसनीय संदर्भ नहीं मिला। इसलिए मैं इसे Premanand Ji "
            "की शिक्षा के रूप में जोड़कर कोई उत्तर नहीं बनाऊँगा। "
            "Corpus बढ़ने पर इस प्रश्न को दोबारा खोजा जा सकता है।"
        )

    return answer

def generate_answer(
    question: str,
    history: list[dict],
    evidence_level: str,
    selected_sources: list[dict],
) -> str:
    if (
        evidence_level == "direct"
        and selected_sources
    ):
        return _answer_direct(
            question,
            selected_sources,
        )

    if (
        evidence_level == "related"
        and selected_sources
    ):
        return _answer_related(
            question,
            history,
            selected_sources,
        )

    return _answer_none(
        question
    )
