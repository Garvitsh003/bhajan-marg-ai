import html
import math
import re
import unicodedata
from collections import Counter
from typing import Iterable

import mmh3
import regex as uregex
from qdrant_client import models


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = html.unescape(text or "")
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = unicodedata.normalize("NFC", text)
    return _WS_RE.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    text = normalize_text(text).lower()
    # Unicode letters + combining marks + digits. Works with Devanagari and Latin.
    return uregex.findall(r"[\p{L}\p{M}\p{N}]+", text)


def lexical_sparse(text: str, query: bool = False) -> models.SparseVector:
    toks = tokens(text)
    if not toks:
        return models.SparseVector(indices=[], values=[])

    features = list(toks)
    features += [f"{a}::{b}" for a, b in zip(toks, toks[1:])]

    counts = Counter(features)
    pairs = []
    for feature, count in counts.items():
        idx = mmh3.hash(feature, signed=False)
        value = 1.0 if query else 1.0 + math.log(count)
        pairs.append((idx, value))
    pairs.sort(key=lambda x: x[0])
    return models.SparseVector(
        indices=[p[0] for p in pairs],
        values=[p[1] for p in pairs],
    )


def merge_rolling_caption(previous: str, current: str) -> str:
    prev = tokens(previous)
    curr = tokens(current)
    if not curr:
        return ""
    max_overlap = min(len(prev), len(curr), 20)
    overlap = 0
    for n in range(max_overlap, 0, -1):
        if prev[-n:] == curr[:n]:
            overlap = n
            break
    if overlap == 0:
        return normalize_text(current)
    # A token count is not a whitespace-word count: क्या-क्या has two
    # tokens but one whitespace word. Slice at the actual token offset.
    normalized = normalize_text(current)
    spans = list(uregex.finditer(r"[\p{L}\p{M}\p{N}]+", normalized))
    return normalized[spans[overlap - 1].end():].lstrip(" \t\r\n।॥.!?,;:")


def ms_to_clock(ms: int) -> str:
    total = max(0, ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def youtube_at(video_id: str, start_ms: int) -> str:
    return f"https://www.youtube.com/watch?v={video_id}&t={max(0,start_ms//1000)}s"
