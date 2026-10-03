import logging
import re
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_ROMAN_HINDI_HINTS = {
    "aap", "ap", "ka", "ki", "ke", "kya", "kaise", "kyun", "kyu", "mera",
    "meri", "mere", "mann", "man", "dil", "bhagwan", "bhagwaan", "naam",
    "jap", "krodh", "gussa", "bhakti", "satsang", "karma", "karm", "mujhe",
    "mujh", "hum", "hume", "hame", "nahi", "nahin", "hai", "hain", "ho",
    "karu", "karun", "kare", "karen", "chahiye", "prem", "radha", "krishna",
    "maharaj", "ji",
}


def resolve_language(question: str, preference: str) -> str:
    requested = (preference or "auto").strip().lower()
    if requested in {"hi", "hinglish", "en"}:
        return requested

    text = (question or "").strip()
    if not text:
        return "hi"

    devanagari = len(_DEVANAGARI_RE.findall(text))
    letters = sum(ch.isalpha() for ch in text)
    if devanagari >= 3 and devanagari / max(letters, 1) >= 0.20:
        return "hi"

    words = {
        re.sub(r"[^a-z]", "", token.lower())
        for token in re.findall(r"[A-Za-z']+", text)
    }
    hint_count = len(words & _ROMAN_HINDI_HINTS)
    if hint_count >= 2:
        return "hinglish"

    return "en"


def _protect_quotes(answer: str, quotes: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    protected = answer
    mapping: dict[str, str] = {}

    # Longest-first prevents a shorter quote from replacing text inside a
    # longer verified quote.
    verified = sorted(
        {
            str(item.get("text", "")).strip()
            for item in (quotes or [])
            if str(item.get("text", "")).strip()
        },
        key=len,
        reverse=True,
    )

    for index, quote in enumerate(verified):
        token = f"[[[SOURCE_QUOTE_{index}]]]"
        if quote in protected:
            protected = protected.replace(quote, token)
            mapping[token] = quote

    return protected, mapping


def render_answer_language(
    *,
    answer: str,
    question: str,
    preference: str,
    quotes: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Translate presentation prose without changing verified source quotes.

    Retrieval, evidence selection and quote extraction already happened before
    this function. If translation fails or a quote placeholder is damaged, the
    original grounded Hindi answer is returned rather than risking fidelity.
    """
    target = resolve_language(question, preference)
    if target == "hi" or not answer.strip():
        return answer, "hi"

    # Production uses Gemini. Keep local/offline behavior conservative rather
    # than adding a second unverified rewriting path.
    if settings.llm_provider.lower() != "gemini":
        return answer, "hi"

    protected, quote_map = _protect_quotes(answer, quotes or [])

    if target == "en":
        target_instruction = (
            "Write natural, concise English. Preserve important Hindi spiritual "
            "terms such as naam-jap, satsang, bhajan, seva or sharanagati when "
            "they are useful, with a brief English gloss only when needed."
        )
    else:
        target_instruction = (
            "Write natural Hinglish in Latin script: simple Hindi expressed in "
            "Roman letters with ordinary English where helpful. Do not make it "
            "slangy or overly casual."
        )

    system = f"""You are only a language renderer for a grounded spiritual QA system.

The source answer has already been fact-checked against retrieved satsang evidence.
Translate/rewrite its presentation into the requested language and NOTHING ELSE.

Rules:
1. Do not add facts, practices, promises, explanations, psychology, theology, or advice.
2. Do not remove caveats, uncertainty, source labels, or the distinction between direct teaching and AI explanation.
3. Tokens like [[[SOURCE_QUOTE_0]]] are immutable verified transcript quotes. Copy every such token EXACTLY and in the same place. Never translate text inside those placeholders.
3b. If the answer contains another clearly quoted transcript span that was not replaced by a placeholder, preserve that quoted Hindi text rather than paraphrasing it.
4. Keep the same section order and roughly the same length.
5. Preserve markdown/plain-text structure and emojis when present.
6. Do not claim to be Premanand Ji.
7. {target_instruction}

Return only the rendered answer."""

    try:
        from .cloud_llm import gemini_chat

        rendered = gemini_chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": protected},
            ],
            temperature=0.0,
            max_output_tokens=1200,
            timeout=int(settings.llm_timeout_seconds),
        ).strip()
    except Exception:
        log.exception("Answer language rendering failed; returning grounded Hindi")
        return answer, "hi"

    # Every protected source quote must survive byte-for-byte.
    for token, original in quote_map.items():
        if token not in rendered:
            log.warning("Language renderer altered quote placeholder; using original answer")
            return answer, "hi"
        rendered = rendered.replace(token, original)

    # Avoid exposing any orphaned placeholder-like tokens.
    if "[[[SOURCE_QUOTE_" in rendered:
        log.warning("Language renderer left an unknown quote placeholder")
        return answer, "hi"

    return rendered, target
