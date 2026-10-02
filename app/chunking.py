from typing import Any

from .text import normalize_text


def chunk_transcript(
    segments: list[dict[str, Any]],
    target_chars: int = 850,
    min_seconds: int = 28,
    max_seconds: int = 85,
    overlap_segments: int = 2,
) -> list[dict[str, Any]]:
    if not segments:
        return []

    chunks = []
    buf: list[dict] = []

    def emit():
        nonlocal buf
        if not buf:
            return
        text = normalize_text(" ".join(x["text"] for x in buf))
        if text:
            chunks.append({
                "chunk_index": len(chunks),
                "start_ms": buf[0]["start_ms"],
                "end_ms": buf[-1]["end_ms"],
                "segment_start": buf[0]["segment_id"],
                "segment_end": buf[-1]["segment_id"],
                "text": text,
                "caption_segments": [{k:s[k] for k in ('start_ms','end_ms','text')} for s in buf],
            })
        buf = buf[-overlap_segments:] if overlap_segments else []

    for seg in segments:
        buf.append(seg)
        chars = sum(len(x["text"]) + 1 for x in buf)
        seconds = (buf[-1]["end_ms"] - buf[0]["start_ms"]) / 1000
        enough = seconds >= min_seconds and chars >= target_chars
        too_long = seconds >= max_seconds
        natural_break = seg["text"].rstrip().endswith(("।", "?", "!", ".", "॥"))

        if too_long or (enough and natural_break) or chars >= int(target_chars * 1.45):
            emit()

    if buf:
        # Avoid emitting a pure-overlap tail identical to prior ending.
        tail = normalize_text(" ".join(x["text"] for x in buf))
        if tail and (not chunks or tail != chunks[-1]["text"]):
            chunks.append({
                "chunk_index": len(chunks),
                "start_ms": buf[0]["start_ms"],
                "end_ms": buf[-1]["end_ms"],
                "segment_start": buf[0]["segment_id"],
                "segment_end": buf[-1]["segment_id"],
                "text": tail,
                "caption_segments": [{k:s[k] for k in ('start_ms','end_ms','text')} for s in buf],
            })
    return chunks
