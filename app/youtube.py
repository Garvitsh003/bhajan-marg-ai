import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import webvtt
import yt_dlp

from .config import settings
from .text import merge_rolling_caption, normalize_text


def _ydl_common() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "noplaylist": False,
    }
    # Browser-cookie extraction is intentionally optional. Example value: chrome.
    if settings.ytdlp_cookies_from_browser.strip():
        opts["cookiesfrombrowser"] = (
            settings.ytdlp_cookies_from_browser.strip(),
            None, None, None
        )
    return opts


def list_channel_videos(limit: int | None = None) -> list[dict[str, Any]]:
    opts = _ydl_common()
    opts.update({
        "extract_flat": "in_playlist",
        "skip_download": True,
        "playlistend": limit if limit and limit > 0 else None,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(settings.channel_url, download=False) or {}

    entries = info.get("entries") or []
    videos = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        vid = e["id"]
        videos.append({
            "video_id": vid,
            "title": e.get("title") or vid,
            "url": e.get("url") if str(e.get("url", "")).startswith("http")
                   else f"https://www.youtube.com/watch?v={vid}",
            "channel": e.get("channel") or e.get("uploader") or "Bhajan Marg",
            "published_at": e.get("upload_date"),
            "duration_seconds": int(e["duration"]) if e.get("duration") else None,
        })
    return videos


def enrich_video(video: dict[str, Any]) -> dict[str, Any]:
    opts = _ydl_common()
    opts.update({"skip_download": True, "noplaylist": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video["url"], download=False) or {}
    return {
        **video,
        "title": info.get("title") or video["title"],
        "channel": info.get("channel") or info.get("uploader") or video.get("channel"),
        "published_at": info.get("upload_date") or video.get("published_at"),
        "duration_seconds": int(info["duration"]) if info.get("duration") else video.get("duration_seconds"),
    }


def _parse_vtt(path: Path) -> list[dict[str, Any]]:
    raw = []
    previous_full = ""
    for cap in webvtt.read(str(path)):
        text = normalize_text(cap.text)
        if not text:
            continue
        # YouTube auto-captions often roll previous words into the next cue.
        delta = merge_rolling_caption(previous_full, text)
        previous_full = text
        if not delta:
            continue
        start_ms = _vtt_time_to_ms(cap.start)
        end_ms = _vtt_time_to_ms(cap.end)
        raw.append({
            "segment_id": len(raw),
            "start_ms": start_ms,
            "end_ms": end_ms,
            "raw_text": text,
            "text": delta,
        })
    return raw


def _vtt_time_to_ms(ts: str) -> int:
    h, m, s = ts.split(":")
    return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)


def fetch_captions(video: dict[str, Any]) -> tuple[list[dict], str] | tuple[None, None]:
    vid = video["video_id"]
    outdir = Path(settings.temp_dir) / vid
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(outdir / "%(id)s.%(ext)s")

    opts = _ydl_common()
    opts.update({
        "skip_download": True,
        "noplaylist": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [x.strip() for x in settings.subtitle_langs.split(",") if x.strip()],
        "subtitlesformat": "vtt",
        "outtmpl": outtmpl,
        "overwrites": True,
    })

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(video["url"], download=True)

    candidates = sorted(outdir.glob(f"{vid}*.vtt"))
    if not candidates:
        return None, None

    def preference(p: Path):
        n = p.name.lower()
        return (
            0 if ".hi" in n else 1 if ".en" in n else 2,
            len(n)
        )

    chosen = sorted(candidates, key=preference)[0]
    segments = _parse_vtt(chosen)
    return (segments, f"youtube_caption:{chosen.name}") if segments else (None, None)


def whisper_transcribe(video: dict[str, Any]) -> tuple[list[dict], str] | tuple[None, None]:
    if not settings.whisper_fallback:
        return None, None

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "WHISPER_FALLBACK=true but faster-whisper is not installed. "
            "Install requirements-whisper.txt"
        )

    vid = video["video_id"]
    outdir = Path(settings.temp_dir) / f"{vid}_audio"
    shutil.rmtree(outdir, ignore_errors=True)
    outdir.mkdir(parents=True, exist_ok=True)

    opts = _ydl_common()
    opts.update({
        "format": "bestaudio/best",
        "noplaylist": True,
        "outtmpl": str(outdir / f"{vid}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "64",
        }],
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video["url"]])

    audio = outdir / f"{vid}.mp3"
    if not audio.exists():
        return None, None

    model = WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )
    result, _ = model.transcribe(
        str(audio),
        language="hi",
        vad_filter=True,
        beam_size=5,
    )
    segments = []
    for seg in result:
        text = normalize_text(seg.text)
        if text:
            segments.append({
                "segment_id": len(segments),
                "start_ms": int(seg.start * 1000),
                "end_ms": int(seg.end * 1000),
                "raw_text": text,
                "text": text,
            })
    shutil.rmtree(outdir, ignore_errors=True)
    return (segments, "faster_whisper") if segments else (None, None)


def save_transcript(video: dict, segments: list[dict], source: str) -> tuple[str, str]:
    doc = {
        "video_id": video["video_id"],
        "title": video["title"],
        "url": video["url"],
        "channel": video.get("channel"),
        "published_at": video.get("published_at"),
        "transcript_source": source,
        "segments": segments,
    }
    serialized = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    path = Path(settings.transcript_dir) / f"{video['video_id']}.json"
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path), digest


def get_or_create_transcript(video: dict) -> tuple[list[dict], str, str, str]:
    segments, source = fetch_captions(video)
    if not segments:
        segments, source = whisper_transcribe(video)
    if not segments:
        raise RuntimeError("No usable captions/transcript found")
    path, digest = save_transcript(video, segments, source)
    return segments, source, path, digest
