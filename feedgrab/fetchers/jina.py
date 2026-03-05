# -*- coding: utf-8 -*-
"""
Jina Reader — universal fallback for content extraction.

Uses https://r.jina.ai/{url} to extract markdown from any web page.
Free, no API key required, handles JS rendering and anti-scraping.
"""

import requests
from loguru import logger


JINA_BASE = "https://r.jina.ai"
TIMEOUT = 30

HEADERS = {
    "Accept": "text/markdown",
    "User-Agent": "feedgrab/0.1",
}

# Jina Reader injects these metadata lines into the markdown output
_JINA_META_PREFIXES = ("URL Source:", "Published Time:", "Markdown Content:")


def fetch_via_jina(url: str) -> dict:
    """
    Fetch any URL via Jina Reader and return structured data.

    Returns:
        dict with keys: title, content, url, author (best-effort)
    """
    jina_url = f"{JINA_BASE}/{url}"
    logger.info(f"Jina fetch: {url}")

    try:
        resp = requests.get(jina_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        text = resp.text

        # Jina returns markdown; first line is usually the title
        lines = text.strip().split("\n")
        title = ""
        content_lines = []

        for line in lines:
            stripped = line.strip()
            # Skip Jina metadata prefix lines
            if any(stripped.startswith(p) for p in _JINA_META_PREFIXES):
                continue
            if not title and stripped:
                # First non-empty line as title, strip markdown heading
                title = line.lstrip("#").strip()
            else:
                content_lines.append(line)

        content = "\n".join(content_lines).strip()

        return {
            "title": title[:200],
            "content": content,
            "url": url,
            "author": "",
        }

    except requests.Timeout:
        logger.error(f"Jina timeout: {url}")
        raise
    except requests.RequestException as e:
        logger.error(f"Jina fetch failed: {url} — {e}")
        raise


def fetch_via_jina_text(url: str) -> str:
    """Fetch URL via Jina Reader in plain text mode (no markdown formatting).

    Text mode preserves all visible text including inline link content
    (cashtags, @mentions) that Jina's markdown renderer may drop.

    Returns:
        Plain text content string.
    """
    jina_url = f"{JINA_BASE}/{url}"
    logger.info(f"Jina fetch (text mode): {url}")

    headers = {**HEADERS, "X-Return-Format": "text"}
    try:
        resp = requests.get(jina_url, headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text.strip()
    except requests.RequestException as e:
        logger.warning(f"Jina text-mode fetch failed: {url} — {e}")
        return ""
