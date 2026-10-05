import os
import logging
import time
from functools import lru_cache
from .budget import remaining_timeout, request_id
from .config import settings

log = logging.getLogger(__name__)


def _provider_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


@lru_cache(maxsize=1)
def _client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai

    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(
        timeout=int(settings.llm_timeout_seconds * 1000),
        retry_options=types.HttpRetryOptions(attempts=1),
    ))


def gemini_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
    max_output_tokens: int | None = None,
    timeout: int = 300,
) -> str:
    """Bound the SDK transport timeout in milliseconds for every call."""
    seconds = remaining_timeout(min(timeout, settings.llm_timeout_seconds))

    from google.genai import types

    system_parts: list[str] = []
    conversation_parts: list[str] = []

    for message in messages:
        role = str(message.get("role", "user")).strip().lower()
        content = str(message.get("content", "")).strip()
        if not content:
            continue

        if role == "system":
            system_parts.append(content)
        else:
            label = "USER" if role == "user" else "ASSISTANT"
            conversation_parts.append(f"{label}:\n{content}")

    prompt = "\n\n".join(conversation_parts).strip()
    if not prompt:
        prompt = "USER:\n"

    config_kwargs = {
        "temperature": max(0.0, min(2.0, float(temperature))),
        "max_output_tokens": int(max_output_tokens or 700),
        "http_options": types.HttpOptions(timeout=max(1, int(seconds * 1000)),
            retry_options=types.HttpRetryOptions(attempts=1)),
    }

    if system_parts:
        config_kwargs["system_instruction"] = "\n\n".join(system_parts)

    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"

    started = time.monotonic()
    try:
        response = _client().models.generate_content(
            model=_provider_model(), contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    finally:
        log.info("request=%s phase=gemini elapsed_ms=%d", request_id.get(),
                 (time.monotonic() - started) * 1000)

    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")

    return text.strip()



def gemini_transcribe_audio(
    audio_bytes: bytes,
    *,
    mime_type: str,
    language: str = "auto",
    timeout: int = 60,
) -> str:
    """Transcribe tester voice feedback without summarizing or answering it."""
    if not audio_bytes:
        raise ValueError("Audio payload is empty")

    seconds = remaining_timeout(min(timeout, max(settings.llm_timeout_seconds, 60)))

    from google.genai import types

    target = {
        "hi": "The speaker is primarily using Hindi. Preserve natural Hindi wording.",
        "hinglish": (
            "The speaker may code-switch between Hindi and English (Hinglish). "
            "Preserve the code-switching faithfully instead of translating it."
        ),
        "en": "The speaker is primarily using English. Preserve their exact meaning.",
    }.get(language, "Detect the spoken language automatically and preserve it faithfully.")

    prompt = f"""Transcribe this user-testing voice feedback.

Rules:
- This is transcription only. Do not answer the speaker.
- Do not summarize, interpret, improve, or spiritualize what they said.
- Preserve named entities such as Maharaj Ji, Premanand Ji, Bhajan Marg and video references.
- Preserve complaints like "Maharaj Ji said this somewhere else" exactly in meaning.
- {target}
- If a word is genuinely inaudible, write [unclear] rather than guessing.
- Return only the transcript, with no preamble or quotation marks.
"""

    normalized_mime = (mime_type or "audio/webm").split(";", 1)[0].strip().lower()
    if not normalized_mime.startswith("audio/"):
        normalized_mime = "audio/webm"

    model = os.getenv("GEMINI_AUDIO_MODEL", _provider_model()).strip() or _provider_model()
    started = time.monotonic()
    try:
        response = _client().models.generate_content(
            model=model,
            contents=[
                prompt,
                types.Part.from_bytes(data=audio_bytes, mime_type=normalized_mime),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=1200,
                http_options=types.HttpOptions(
                    timeout=max(1, int(seconds * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            ),
        )
    finally:
        log.info(
            "request=%s phase=voice_transcription elapsed_ms=%d",
            request_id.get(),
            (time.monotonic() - started) * 1000,
        )

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise RuntimeError("Gemini returned an empty voice transcript")
    return text
