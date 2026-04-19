# -*- coding: utf-8 -*-
"""
Ximalaya (喜马拉雅) single-track fetcher.

Uses Ximalaya's public Web revision APIs (no auth needed for free tracks):

1. ``GET /revision/track/v2/audio?ptype=1&trackId={id}``
       → ``data.src`` (m4a CDN URL) + ``canPlay``
2. ``GET /revision/track/simple?trackId={id}``
       → track metadata + album + host (podcaster)

Paid tracks return ``canPlay=false`` with no playable ``src``. In that
case we still output metadata and emit a WARN log — users can subscribe
and re-run.

Supported URL shapes:
    https://www.ximalaya.com/sound/{track_id}
    https://www.ximalaya.com/{category}/{album_id}/{track_id}
    https://m.ximalaya.com/sound/{track_id}
"""

import re
from typing import Any, Dict, Optional

import requests
from loguru import logger

from feedgrab.config import get_stealth_headers, ximalaya_whisper
from feedgrab.utils import http_client
from feedgrab.utils.transcribe import format_transcript, groq_transcribe_url


_API_AUDIO = "https://www.ximalaya.com/revision/track/v2/audio"
_API_SIMPLE = "https://www.ximalaya.com/revision/track/simple"
_XMLY_REFERER = "https://www.ximalaya.com/"
_HTTP_TIMEOUT = 15


_TRACK_ID_PATTERNS = (
    # /sound/123456 or /sound/123456?x=y
    re.compile(r"/sound/(\d+)"),
    # /shangye/393603/7843596 → trailing digit group is track_id
    re.compile(r"/\d+/(\d+)(?:[/?#]|$)"),
)


def _extract_track_id(url: str) -> str:
    """Pull numeric track_id from a Ximalaya URL."""
    for pat in _TRACK_ID_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    raise ValueError(f"Cannot extract track_id from URL: {url}")


def _api_get(api_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Call Ximalaya revision API; raise on non-zero ``ret``."""
    resp = http_client.get(
        api_url,
        params=params,
        headers={**get_stealth_headers(), "Referer": _XMLY_REFERER},
        timeout=_HTTP_TIMEOUT,
    )
    http_client.raise_for_status(resp)
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError(f"[Ximalaya] unexpected response: {str(data)[:200]}")
    if data.get("ret") not in (0, 200, None):
        raise ValueError(f"[Ximalaya] API error: ret={data.get('ret')} msg={data.get('msg')!r}")
    return data.get("data") or {}


def _format_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    if not seconds:
        return ""
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def fetch_ximalaya(url: str) -> Dict[str, Any]:
    """Fetch a Ximalaya track and return structured data.

    Returns dict compatible with ``from_ximalaya()``:
        {title, track_id, album_name, album_id, author, duration,
         duration_seconds, published, cover_image, audio_url, can_play,
         transcript, has_transcript, url, description}
    """
    track_id = _extract_track_id(url)
    logger.info(f"[Ximalaya] Tier 1 — Web API: track_id={track_id}")

    # Step 1: audio URL + canPlay
    try:
        audio_data = _api_get(_API_AUDIO, {"ptype": 1, "trackId": track_id})
    except (requests.RequestException, ValueError) as e:
        raise RuntimeError(f"[Ximalaya] audio API failed: {e}") from e

    audio_url = (audio_data.get("src") or "").strip()
    can_play = bool(audio_data.get("canPlay", True))
    is_sample = bool(audio_data.get("albumIsSample", False))

    if not can_play or not audio_url:
        logger.warning(
            f"[Ximalaya] track {track_id} is not playable "
            f"(canPlay={can_play}, src={'yes' if audio_url else 'no'}). "
            "Likely paid content — returning metadata only."
        )

    # Step 2: metadata
    try:
        meta_data = _api_get(_API_SIMPLE, {"trackId": track_id})
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"[Ximalaya] simple API failed ({e}), using minimal metadata")
        meta_data = {}

    track_info = meta_data.get("trackInfo") or {}
    album_info = meta_data.get("albumInfo") or {}
    anchor_info = meta_data.get("anchorInfo") or meta_data.get("userInfo") or {}

    title = (track_info.get("title") or "").strip()
    duration = int(track_info.get("duration") or 0)
    published = (track_info.get("lastUpdate") or track_info.get("createTimeAsString") or "").strip()
    cover = (track_info.get("coverPath") or track_info.get("coverLarge") or "").strip()
    if cover and cover.startswith("//"):
        cover = "https:" + cover

    album_name = (album_info.get("title") or album_info.get("albumName") or "").strip()
    album_id = str(album_info.get("albumId") or album_info.get("id") or "").strip()

    author = (
        anchor_info.get("anchorName")
        or anchor_info.get("nickName")
        or album_info.get("authorName")
        or ""
    ).strip()

    description = (track_info.get("richIntro") or track_info.get("intro") or "").strip()

    logger.info(
        f"[Ximalaya] title={title[:40]!r} album={album_name[:30]!r} "
        f"author={author!r} duration={_format_duration(duration)} "
        f"can_play={can_play}"
    )

    # Step 3: optional Whisper transcription (only if playable)
    transcript = ""
    has_transcript = False
    if audio_url and can_play and ximalaya_whisper():
        logger.info(f"[Ximalaya] Tier 2 — Whisper: {audio_url[:80]}...")
        snippets = groq_transcribe_url(audio_url, referer=_XMLY_REFERER)
        if snippets:
            transcript = format_transcript(snippets, description=description)
            has_transcript = bool(transcript)
            logger.info(
                f"[Ximalaya] transcript: {len(transcript)} chars, {len(snippets)} snippets"
            )
        else:
            logger.warning("[Ximalaya] Whisper returned empty (no GROQ_API_KEY or error)")

    return {
        "title": title,
        "track_id": track_id,
        "album_name": album_name,
        "album_id": album_id,
        "author": author,
        "description": description,
        "duration_seconds": duration,
        "duration": _format_duration(duration),
        "published": published,
        "cover_image": cover,
        "audio_url": audio_url,
        "can_play": can_play,
        "is_sample": is_sample,
        "transcript": transcript,
        "has_transcript": has_transcript,
        "url": f"https://www.ximalaya.com/sound/{track_id}",
        "platform": "ximalaya",
    }
