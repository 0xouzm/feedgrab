# -*- coding: utf-8 -*-
"""
Xiaoyuzhou (小宇宙) podcast episode fetcher.

Strategy: fetch episode page HTML → extract ``<script id="__NEXT_DATA__">``
JSON → pull out title/podcast/shownotes/m4a URL from
``props.pageProps.episode``. Optionally transcribe the audio via Groq
Whisper (reusing the YouTube Whisper pipeline).

URL formats:
    https://www.xiaoyuzhoufm.com/episode/{episode_id}
    https://www.xiaoyuzhoufm.com/podcast/{podcast_id}/episode/{episode_id}

Zero-auth, no device token needed — the SSR JSON includes the audio
CDN URL directly.
"""

import html
import json
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from loguru import logger

from feedgrab.config import get_stealth_headers, xiaoyuzhou_whisper
from feedgrab.utils import http_client
from feedgrab.utils.transcribe import format_transcript, groq_transcribe_url


_PAGE_TIMEOUT = 20
_XYZ_REFERER = "https://www.xiaoyuzhoufm.com/"
_NEXT_DATA_RE = re.compile(
    r'<script\b[^>]*\bid="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_EPISODE_ID_RE = re.compile(r"/episode/([a-zA-Z0-9]+)")


def _extract_episode_id(url: str) -> str:
    m = _EPISODE_ID_RE.search(url)
    if not m:
        raise ValueError(f"Cannot extract episode_id from URL: {url}")
    return m.group(1)


def _extract_next_data(page_html: str) -> Optional[Dict[str, Any]]:
    """Pull ``__NEXT_DATA__`` JSON from page HTML."""
    if not page_html:
        return None
    m = _NEXT_DATA_RE.search(page_html)
    if not m:
        return None
    try:
        return json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError as e:
        logger.warning(f"[Xiaoyuzhou] __NEXT_DATA__ JSON parse failed: {e}")
        return None


def _shownotes_to_markdown(shownotes_html: str) -> str:
    """Convert shownotes HTML to Markdown via markdownify."""
    if not shownotes_html:
        return ""
    try:
        from markdownify import markdownify as md

        return md(
            shownotes_html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        ).strip()
    except ImportError:
        # Fallback: strip tags
        return re.sub(r"<[^>]+>", "", shownotes_html).strip()


def _format_duration(seconds: int) -> str:
    """Format duration in ``H:MM:SS`` or ``M:SS``."""
    if not seconds:
        return ""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


async def fetch_xiaoyuzhou(url: str) -> Dict[str, Any]:
    """Fetch a Xiaoyuzhou episode and return structured data.

    Returns dict compatible with ``from_xiaoyuzhou()``:
        {title, episode_id, podcast_name, podcast_id, author, shownotes,
         duration, duration_seconds, published, cover_image, audio_url,
         transcript, has_transcript, url}
    """
    episode_id = _extract_episode_id(url)
    logger.info(f"[Xiaoyuzhou] Tier 1 — SSR fetch: episode_id={episode_id}")

    # Normalize URL to canonical episode page (Xiaoyuzhou redirects anyway)
    canonical_url = f"https://www.xiaoyuzhoufm.com/episode/{episode_id}"

    try:
        resp = http_client.get(
            canonical_url,
            headers=get_stealth_headers(),
            timeout=_PAGE_TIMEOUT,
        )
        http_client.raise_for_status(resp)
        page_html = resp.text
    except requests.RequestException as e:
        raise RuntimeError(f"[Xiaoyuzhou] page fetch failed: {e}") from e

    next_data = _extract_next_data(page_html)
    if not next_data:
        raise RuntimeError(
            "[Xiaoyuzhou] __NEXT_DATA__ not found. Page structure may have changed."
        )

    try:
        episode = next_data["props"]["pageProps"]["episode"]
    except (KeyError, TypeError) as e:
        raise RuntimeError(
            f"[Xiaoyuzhou] pageProps.episode missing: {e}. "
            f"Keys present: {list(next_data.get('props', {}).get('pageProps', {}).keys())}"
        ) from e

    title = (episode.get("title") or "").strip()
    description = (episode.get("description") or "").strip()
    shownotes_html = episode.get("shownotes") or ""
    shownotes = _shownotes_to_markdown(shownotes_html)
    duration = int(episode.get("duration") or 0)
    published = (episode.get("pubDate") or "").strip()
    cover_image = ""
    img = episode.get("image")
    if isinstance(img, dict):
        cover_image = img.get("picUrl") or img.get("largePicUrl") or ""
    elif isinstance(img, str):
        cover_image = img

    media = episode.get("media") or {}
    source = media.get("source") or {}
    audio_url = (source.get("url") or "").strip()

    podcast = episode.get("podcast") or {}
    podcast_name = (podcast.get("title") or "").strip()
    podcast_id = (podcast.get("pid") or "").strip()
    author = (podcast.get("author") or "").strip()

    logger.info(
        f"[Xiaoyuzhou] title={title[:40]!r} podcast={podcast_name[:30]!r} "
        f"duration={_format_duration(duration)} audio={'yes' if audio_url else 'no'}"
    )

    # Optional: Whisper transcription
    transcript = ""
    has_transcript = False
    if audio_url and xiaoyuzhou_whisper():
        logger.info(f"[Xiaoyuzhou] Tier 2 — Whisper transcription: {audio_url[:80]}...")
        snippets = groq_transcribe_url(audio_url, referer=_XYZ_REFERER)
        if snippets:
            transcript = format_transcript(snippets, description=shownotes or description)
            has_transcript = bool(transcript)
            logger.info(
                f"[Xiaoyuzhou] transcript: {len(transcript)} chars, {len(snippets)} snippets"
            )
        else:
            logger.warning("[Xiaoyuzhou] Whisper returned empty (no GROQ_API_KEY or error)")

    return {
        "title": title,
        "episode_id": episode_id,
        "podcast_name": podcast_name,
        "podcast_id": podcast_id,
        "author": author,
        "description": description,
        "shownotes": shownotes,
        "duration_seconds": duration,
        "duration": _format_duration(duration),
        "published": published,
        "cover_image": cover_image,
        "audio_url": audio_url,
        "transcript": transcript,
        "has_transcript": has_transcript,
        "url": canonical_url,
        "platform": "xiaoyuzhou",
    }
