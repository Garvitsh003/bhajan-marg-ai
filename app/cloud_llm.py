import os
from functools import lru_cache


def _provider_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")


@lru_cache(maxsize=1)
def _client():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    from google import genai

    return genai.Client(api_key=api_key)


def gemini_chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
    max_output_tokens: int | None = None,
    timeout: int = 300,
) -> str:
    """Gemini adapter with the same conceptual interface as ollama_chat.

    timeout is accepted for call-site compatibility. The Google GenAI SDK
    manages its own HTTP transport timeouts.
    """
    del timeout

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
    }

    if system_parts:
        config_kwargs["system_instruction"] = "\n\n".join(system_parts)

    if json_mode:
        config_kwargs["response_mime_type"] = "application/json"

    response = _client().models.generate_content(
        model=_provider_model(),
        contents=prompt,
        config=types.GenerateContentConfig(**config_kwargs),
    )

    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("Gemini returned an empty response")

    return text.strip()
