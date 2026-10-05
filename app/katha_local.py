from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yt_dlp

from .config import settings
from .youtube import fetch_captions


SPEAKERS: dict[str, dict[str, str]] = {
    "indresh_ji": {
        "speaker": "Indresh Ji Maharaj",
        "corpus_type": "katha",
    },
    "rajendra_das_ji": {
        "speaker": "Rajendra Das Ji Maharaj",
        "corpus_type": "katha",
    },
}

SPEAKER_ALIASES = {
    "indresh": "indresh_ji",
    "indresh_ji": "indresh_ji",
    "indresh-ji": "indresh_ji",
    "rajendra": "rajendra_das_ji",
    "rajendra_das": "rajendra_das_ji",
    "rajendra_das_ji": "rajendra_das_ji",
    "rajendra-das-ji": "rajendra_das_ji",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_speaker(value: str) -> str:
    key = re.sub(r"\s+", "_", value.strip().lower())
    key = SPEAKER_ALIASES.get(key, key)
    if key not in SPEAKERS:
        allowed = ", ".join(sorted(SPEAKERS))
        raise ValueError(f"Unknown speaker '{value}'. Allowed: {allowed}")
    return key


def katha_root() -> Path:
    return Path(settings.data_dir) / "katha"


def speaker_root(speaker_key: str) -> Path:
    key = normalize_speaker(speaker_key)
    root = katha_root() / key
    for child in (
        "videos",
        "transcripts",
        "segments",
        "summaries",
        "taxonomy",
        "tmp",
    ):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def _ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    if settings.ytdlp_cookies_from_browser.strip():
        opts["cookiesfrombrowser"] = (
            settings.ytdlp_cookies_from_browser.strip(),
            None,
            None,
            None,
        )
    return opts


def extract_video_metadata(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False) or {}

    video_id = str(info.get("id") or "").strip()
    if not video_id:
        raise RuntimeError("Could not determine YouTube video ID")

    webpage_url = (
        info.get("webpage_url")
        or f"https://www.youtube.com/watch?v={video_id}"
    )

    return {
        "video_id": video_id,
        "title": info.get("title") or video_id,
        "source_url": webpage_url,
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id") or info.get("uploader_id"),
        "published_at": info.get("upload_date"),
        "duration_seconds": int(info["duration"]) if info.get("duration") else None,
        "description": info.get("description") or "",
        "playlist": info.get("playlist") or info.get("playlist_title"),
        "playlist_id": info.get("playlist_id"),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _catalog(root: Path) -> list[dict[str, Any]]:
    path = root / "catalog.json"
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        return []


def _save_catalog(root: Path, rows: list[dict[str, Any]]) -> None:
    rows = sorted(
        rows,
        key=lambda row: (
            str(row.get("published_at") or ""),
            str(row.get("video_id") or ""),
        ),
        reverse=True,
    )
    _write_json(root / "catalog.json", rows)


def add_video(
    *,
    speaker: str,
    url: str,
    series: str | None = None,
    event: str | None = None,
    day: str | None = None,
    location: str | None = None,
    katha_type: str | None = None,
    with_captions: bool = False,
) -> dict[str, Any]:
    speaker_key = normalize_speaker(speaker)
    root = speaker_root(speaker_key)
    base = extract_video_metadata(url)

    record = {
        **base,
        "speaker_key": speaker_key,
        "speaker": SPEAKERS[speaker_key]["speaker"],
        "corpus_type": "katha",
        "source_kind": "katha_interpretation",
        "series": series,
        "event": event,
        "day": day,
        "location": location,
        "katha_type": katha_type,
        "status": "metadata_saved",
        "transcript_status": "not_requested",
        "added_at": utcnow(),
    }

    video_dir = root / "videos" / record["video_id"]
    video_dir.mkdir(parents=True, exist_ok=True)

    transcript_path = root / "transcripts" / f'{record["video_id"]}.json'

    if with_captions:
        caption_video = {
            "video_id": record["video_id"],
            "title": record["title"],
            "url": record["source_url"],
            "channel": record.get("channel"),
            "published_at": record.get("published_at"),
            "duration_seconds": record.get("duration_seconds"),
            "content_type": "video",
        }
        segments, source = fetch_captions(caption_video)
        if segments:
            transcript_doc = {
                "video_id": record["video_id"],
                "speaker_key": speaker_key,
                "speaker": record["speaker"],
                "source_url": record["source_url"],
                "transcript_source": source,
                "segments": segments,
            }
            _write_json(transcript_path, transcript_doc)
            record["transcript_status"] = "caption_saved"
            record["transcript_source"] = source
            record["transcript_path"] = str(transcript_path)
        else:
            record["transcript_status"] = "caption_unavailable"

    _write_json(video_dir / "metadata.json", record)

    rows = [
        row for row in _catalog(root)
        if row.get("video_id") != record["video_id"]
    ]
    rows.append(record)
    _save_catalog(root, rows)

    return record


def list_videos(speaker: str) -> list[dict[str, Any]]:
    return _catalog(speaker_root(speaker))


def stats() -> dict[str, Any]:
    result: dict[str, Any] = {"root": str(katha_root()), "speakers": {}}
    for speaker_key in SPEAKERS:
        root = speaker_root(speaker_key)
        rows = _catalog(root)
        result["speakers"][speaker_key] = {
            "speaker": SPEAKERS[speaker_key]["speaker"],
            "videos": len(rows),
            "captions_saved": sum(
                1 for row in rows
                if row.get("transcript_status") == "caption_saved"
            ),
            "folder": str(root),
        }
    return result
