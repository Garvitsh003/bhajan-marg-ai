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
