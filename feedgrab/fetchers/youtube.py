# -*- coding: utf-8 -*-
"""
YouTube video fetcher — API-first content extraction:

1. YouTube Data API v3 for metadata (title/author/duration/views/tags/thumbnail)
2. yt-dlp auto-subtitles (skip if API says no captions)
3. yt-dlp audio + Groq Whisper transcription (for non-subtitled videos)
4. API description fallback (no Jina needed)

Requires: yt-dlp installed (pip install yt-dlp)
Optional: YOUTUBE_API_KEY (rich metadata), GROQ_API_KEY (Whisper transcription)
"""

import re
import os
import shutil
import subprocess
import tempfile
from loguru import logger
from typing import Dict, Any


def _js_runtime_args() -> list:
    """Detect available JS runtime for yt-dlp (needed for YouTube extraction).

    yt-dlp only enables deno by default. If node/bun is installed but not deno,
    we must explicitly pass --js-runtimes to enable it.
    """
    for name, cmd in [("deno", "deno"), ("node", "node"), ("bun", "bun")]:
        if shutil.which(cmd):
            return ["--js-runtimes", name, "--remote-components", "ejs:github"]
    return []


def _extract_video_id(url: str) -> str:
    """Extract video ID from YouTube URL."""
    match = re.search(r'(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else ""


def _get_subtitles_via_ytdlp(url: str, lang: str = "en") -> str:
    """
    Download auto-generated subtitles using yt-dlp.
    Returns subtitle text, or empty string if unavailable.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "sub")

        cmd = [
            "yt-dlp",
            *_js_runtime_args(),
            "--write-auto-sub",
            "--write-sub",
            "--sub-lang", lang,
            "--sub-format", "srt",
            "--skip-download",
            "-o", output_path,
            url,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            logger.warning("yt-dlp not found. Install with: brew install yt-dlp")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp subtitle download timed out")
            return ""

        for ext in [f".{lang}.srt", f".{lang}.vtt"]:
            sub_file = output_path + ext
            if os.path.exists(sub_file):
                return _parse_srt(sub_file)

    return ""


def _parse_srt(filepath: str) -> str:
    """Parse SRT file into clean text (strip timestamps and sequence numbers)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    text_lines = []
    seen = set()

    for line in lines:
        line = line.strip()
        if not line or line.isdigit() or '-->' in line:
            continue
        if line.startswith('[') and line.endswith(']'):
            continue
        if line not in seen:
            seen.add(line)
            text_lines.append(line)

    return " ".join(text_lines)


def _transcribe_via_whisper(url: str) -> str:
    """
    Download audio with yt-dlp and transcribe via Groq Whisper API.

    Requires: GROQ_API_KEY env var + yt-dlp + ffmpeg installed.
    Groq Whisper limit: 25MB audio file.
    Returns transcript text, or empty string if unavailable.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        logger.info("GROQ_API_KEY not set, skipping Whisper transcription")
        return ""

    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "audio.%(ext)s")

        cmd = [
            "yt-dlp",
            *_js_runtime_args(),
            "-x",
            "--audio-format", "m4a",
            "--audio-quality", "5",
            "-o", output_template,
            "--no-playlist",
            url,
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except FileNotFoundError:
            logger.warning("yt-dlp not found for audio download")
            return ""
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp audio download timed out")
            return ""

        # Find the downloaded audio file
        audio_path = os.path.join(tmpdir, "audio.m4a")
        if not os.path.exists(audio_path):
            for f in os.listdir(tmpdir):
                if f.startswith("audio."):
                    audio_path = os.path.join(tmpdir, f)
                    break
            else:
                logger.warning("No audio file downloaded")
                return ""

        file_size = os.path.getsize(audio_path)
        if file_size > 25 * 1024 * 1024:
            logger.warning(f"Audio file too large ({file_size // 1024 // 1024}MB > 25MB limit)")
            return ""

        logger.info(f"Transcribing {file_size // 1024}KB audio via Groq Whisper...")

        from feedgrab.utils import http_client
        try:
            with open(audio_path, "rb") as f:
                response = http_client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (os.path.basename(audio_path), f, "audio/mp4")},
                    data={"model": "whisper-large-v3", "response_format": "text"},
                    timeout=120,
                )

            if response.status_code == 200:
                transcript = response.text.strip()
                logger.info(f"Whisper transcript: {len(transcript)} chars")
                return transcript
            else:
                logger.warning(f"Groq Whisper API error: {response.status_code} {response.text[:200]}")
                return ""
        except Exception as e:
            logger.warning(f"Whisper transcription failed: {e}")
            return ""


async def fetch_youtube(url: str, sub_lang: str = "en") -> Dict[str, Any]:
    """
    Fetch YouTube video content with API-first strategy.

    Strategy:
    1. YouTube API → complete metadata (1 quota unit, if API key configured)
    2. yt-dlp auto-subtitles (skip if API says no captions)
    3. yt-dlp audio + Groq Whisper (for non-subtitled videos)
    4. API description / Jina fallback (last resort)

    Args:
        url: YouTube video URL
        sub_lang: Subtitle language code (default: "en")

    Returns:
        Dict with full video metadata + transcript content.
    """
    logger.info(f"Fetching YouTube: {url}")
    video_id = _extract_video_id(url)

    # Step 1: Try YouTube API for metadata (1 quota unit)
    api_meta = None
    has_caption_hint = None
    if os.getenv("YOUTUBE_API_KEY", "").strip():
        try:
            from feedgrab.fetchers.youtube_search import get_single_video
            api_meta = get_single_video(video_id) if video_id else None
            if api_meta:
                has_caption_hint = api_meta.get("has_caption")
                logger.info(
                    f"[YouTube] API metadata OK: {api_meta['title'][:60]} "
                    f"(caption={has_caption_hint})"
                )
        except Exception as e:
            logger.warning(f"[YouTube] API metadata failed ({e}), falling back")

    # Step 2: Extract subtitles — skip if API says no captions
    transcript = ""
    if has_caption_hint is not False:
        # Try multiple language codes: YouTube auto-captions use varied codes
        # e.g. zh-Hant (Traditional), zh-Hans (Simplified), en-US, en
        langs_to_try = [sub_lang, "zh-CN", "zh-Hans", "zh-Hant", "zh", "en", "en-US"]
        # Deduplicate while preserving order
        seen = set()
        langs_to_try = [l for l in langs_to_try if l not in seen and not seen.add(l)]

        for lang in langs_to_try:
            logger.info(f"Extracting subtitles ({lang})...")
            transcript = _get_subtitles_via_ytdlp(url, lang=lang)
            if transcript:
                break

    # Step 3: No subtitles? Try Whisper transcription
    if not transcript:
        logger.info("No subtitles available, trying Whisper transcription...")
        transcript = _transcribe_via_whisper(url)

    # Determine content
    has_transcript = bool(transcript)
    if has_transcript:
        logger.info(f"Got transcript: {len(transcript)} chars")
        content = transcript
    elif api_meta and api_meta.get("description"):
        logger.info("No transcript, using API description")
        content = api_meta["description"]
    else:
        # Last resort: Jina
        logger.info("No transcript or API, falling back to Jina")
        from feedgrab.fetchers.jina import fetch_via_jina
        jina_data = fetch_via_jina(url)
        content = jina_data.get("content", "")

    # Build result — prefer API metadata when available
    if api_meta:
        return {
            "title": api_meta["title"],
            "description": content,
            "author": api_meta["channel_title"],
            "url": url,
            "video_id": video_id,
            "has_transcript": has_transcript,
            "platform": "youtube",
            "channel_id": api_meta["channel_id"],
            "published_at": api_meta["published_at"],
            "duration": api_meta["duration"],
            "duration_seconds": api_meta["duration_seconds"],
            "view_count": api_meta["view_count"],
            "like_count": api_meta["like_count"],
            "comment_count": api_meta["comment_count"],
            "tags": api_meta["tags"],
            "category_id": api_meta["category_id"],
            "definition": api_meta["definition"],
            "has_caption": api_meta["has_caption"],
            "thumbnail": api_meta["thumbnail"],
        }
    else:
        # Fallback: minimal metadata from Jina
        from feedgrab.fetchers.jina import fetch_via_jina
        jina_data = fetch_via_jina(url) if not content else {"title": "", "author": ""}
        return {
            "title": jina_data.get("title", "") or f"YouTube Video {video_id}",
            "description": content,
            "author": jina_data.get("author", ""),
            "url": url,
            "video_id": video_id,
            "has_transcript": has_transcript,
            "platform": "youtube",
        }
