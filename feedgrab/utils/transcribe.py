# -*- coding: utf-8 -*-
"""
Shared Whisper transcription utilities for audio/video fetchers.

Thin public wrapper around the internal Groq Whisper pipeline in
``feedgrab/fetchers/youtube.py`` (``_whisper_single`` / ``_whisper_chunked``
/ ``_segment_into_sentences`` / ``_parse_chapters`` /
``_format_transcript_markdown``). New fetchers (xiaoyuzhou, ximalaya,
bilibili subtitle fallback) import from here instead of touching
youtube.py internals directly.
"""

import os
import tempfile
from typing import Dict, List, Optional

import requests
from loguru import logger

from feedgrab.utils import http_client


# Groq single-call max upload size (free/dev tier is 100 MB; leave safety margin)
_WHISPER_SINGLE_MAX_MB = 95


def groq_transcribe_file(audio_path: str) -> List[Dict]:
    """Transcribe a local audio file via Groq Whisper.

    Automatically switches to ffmpeg-chunked mode for files ≥95 MB.

    Returns
    -------
    list[dict]
        Snippets ``[{text, start (float), duration (float)}]`` with
        segment-level timestamps, compatible with ``format_transcript()``.
        Empty list if ``GROQ_API_KEY`` unset or transcription fails.
    """
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        logger.info("[Whisper] GROQ_API_KEY not set, skipping transcription")
        return []

    if not os.path.exists(audio_path):
        logger.warning(f"[Whisper] audio file not found: {audio_path}")
        return []

    from feedgrab.config import groq_whisper_model, youtube_whisper_lang
    from feedgrab.fetchers.youtube import _whisper_single, _whisper_chunked

    model = groq_whisper_model()
    lang = youtube_whisper_lang()
    size_mb = os.path.getsize(audio_path) / 1024 / 1024

    if size_mb < _WHISPER_SINGLE_MAX_MB:
        return _whisper_single(audio_path, api_key, model, lang)

    logger.info(f"[Whisper] audio {size_mb:.1f} MB ≥ {_WHISPER_SINGLE_MAX_MB} MB, using chunked mode")
    with tempfile.TemporaryDirectory() as tmpdir:
        return _whisper_chunked(audio_path, tmpdir, api_key, model, lang)


def groq_transcribe_url(
    audio_url: str,
    referer: str = "",
    extension_hint: str = "",
) -> List[Dict]:
    """Download audio from URL then transcribe via Groq Whisper.

    Parameters
    ----------
    audio_url : str
        Direct CDN URL of the audio file (mp3 / m4a / aac).
    referer : str
        Optional Referer header (required by some CDNs: xhs, xmcdn, etc.).
    extension_hint : str
        File extension including dot (".m4a"), used when URL doesn't expose it.
        Auto-detected from URL if empty.

    Returns
    -------
    list[dict]
        Same format as ``groq_transcribe_file()``. Empty on download failure.
    """
    if not audio_url:
        return []
    if not os.getenv("GROQ_API_KEY", "").strip():
        logger.info("[Whisper] GROQ_API_KEY not set, skipping transcription")
        return []

    # Guess extension from URL if not provided
    suffix = extension_hint or _guess_audio_ext(audio_url)

    headers = {"Referer": referer} if referer else {}
    tmp_path: Optional[str] = None
    try:
        logger.info(f"[Whisper] downloading audio: {audio_url[:80]}...")
        resp = http_client.get(audio_url, headers=headers, timeout=600, stream=True)
        http_client.raise_for_status(resp)

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            tmp_path = f.name
            total = 0
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        logger.info(f"[Whisper] downloaded {total / 1024 / 1024:.1f} MB → {tmp_path}")

        return groq_transcribe_file(tmp_path)

    except requests.RequestException as e:
        logger.warning(f"[Whisper] audio download failed: {e}")
        return []
    except Exception as e:
        logger.warning(f"[Whisper] transcription pipeline error: {e}")
        return []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def format_transcript(snippets: List[Dict], description: str = "") -> str:
    """Render snippets into Markdown transcript with chapter support.

    Delegates to ``youtube._parse_chapters`` +
    ``youtube._segment_into_sentences`` + ``youtube._format_transcript_markdown``
    for consistent output across platforms.

    Parameters
    ----------
    snippets : list[dict]
        ``[{text, start, duration}]`` from ``groq_transcribe_*()`` or
        subtitle parsers.
    description : str
        Optional episode/video description; parsed for ``HH:MM:SS title``
        chapter markers and rendered as ``## Chapter [M:SS]`` headers.

    Returns
    -------
    str
        Markdown transcript with paragraph-grouped sentences and
        ``[HH:MM:SS → HH:MM:SS]`` timestamps. Empty string if no snippets.
    """
    if not snippets:
        return ""
    from feedgrab.fetchers.youtube import (
        _parse_chapters,
        _segment_into_sentences,
        _format_transcript_markdown,
    )
    chapters = _parse_chapters(description) if description else []
    sentences = _segment_into_sentences(snippets)
    return _format_transcript_markdown(sentences, chapters)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_audio_ext(url: str) -> str:
    """Guess audio extension from URL path, default to .m4a."""
    lower = url.lower().split("?", 1)[0]
    for ext in (".m4a", ".mp3", ".aac", ".ogg", ".wav", ".flac"):
        if lower.endswith(ext):
            return ext
    return ".m4a"


def subtitle_body_to_snippets(body: List[Dict]) -> List[Dict]:
    """Convert Bilibili-style subtitle body to Whisper-style snippets.

    Input: ``[{"from": 0.0, "to": 2.5, "content": "..."}, ...]``
    Output: ``[{"text": "...", "start": 0.0, "duration": 2.5}, ...]``
    """
    out: List[Dict] = []
    for item in body or []:
        text = (item.get("content") or "").strip()
        if not text:
            continue
        start = float(item.get("from", 0.0))
        end = float(item.get("to", start))
        duration = max(0.0, end - start)
        out.append({"text": text, "start": start, "duration": duration})
    return out
