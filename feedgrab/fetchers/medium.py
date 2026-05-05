# -*- coding: utf-8 -*-
"""
Medium fetcher.

Strategy (single article):
    Tier 0  Jina Reader (https://r.jina.ai/<URL>)        — primary path
    Tier 1  JSON-LD articleBody from raw HTML            — fast structured data
    Tier 2  Stealth Playwright fallback                  — last resort
    Member-only graceful degrade preserves preview from RSS / Jina output.

Strategy (user / publication):
    GET https://medium.com/feed/@<username>              — user RSS
    GET https://medium.com/feed/<publication-slug>       — publication RSS
    Then refetch each entry's URL via the single-article tier chain.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

import feedparser

from feedgrab.config import get_user_agent
from feedgrab.utils import http_client
from feedgrab.utils.jsonld import extract_jsonld_article


_MEDIUM_DOMAINS = ("medium.com",)
_MEMBER_ONLY_MARKERS = (
    "member-only story",
    "members-only story",
    "this is a member-only story",
    "read the full story with a medium membership",
    "read the full story",
)


# =============================================================================
# URL helpers
# =============================================================================

def is_medium_url(url: str) -> bool:
    """Whether *url* points to medium.com or a *.medium.com subdomain."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc == "medium.com":
        return True
    if netloc.endswith(".medium.com"):
        return True
    return False


def parse_medium_url(url: str) -> Tuple[str, str]:
    """Classify a Medium URL.

    Returns:
        (kind, ident) where kind is one of:
          - "article"  → ident is the canonical article URL
          - "user"     → ident is "@username"
          - "publication" → ident is "<slug>"
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")

    # subdomain.medium.com/<slug> → article (subdomain = username)
    if netloc.endswith(".medium.com") and netloc != "medium.com":
        if path:
            return "article", url
        # bare subdomain ≈ user main page; treat as user feed
        username = netloc.split(".medium.com", 1)[0]
        return "user", f"@{username}"

    # medium.com/...
    if not path:
        raise ValueError(f"无效的 Medium URL: {url}")

    parts = [p for p in path.split("/") if p]
    first = parts[0]

    # /@username — user main page
    if first.startswith("@") and len(parts) == 1:
        return "user", first

    # /@username/slug-hash — article
    if first.startswith("@") and len(parts) >= 2:
        return "article", url

    # /tag/<slug>, /search?q=, etc. — treat as generic article URL (fall through)
    if first in {"tag", "search", "topic", "topics", "m"}:
        # publication routes don't use these reserved prefixes
        return "article", url

    # /<publication>/<slug> — article in publication
    if len(parts) >= 2:
        return "article", url

    # /<publication> — publication main page
    return "publication", first


# =============================================================================
# Single-article tier chain
# =============================================================================

def _is_member_only(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(marker in lower for marker in _MEMBER_ONLY_MARKERS)


def _fetch_jina(url: str) -> Optional[Dict[str, Any]]:
    """Tier 0 — Jina Reader. Returns dict with title/content or None."""
    try:
        from feedgrab.fetchers.jina import fetch_via_jina
        result = fetch_via_jina(url)
        if not result or not result.get("content"):
            return None
        return result
    except Exception as exc:
        logger.warning(f"[Medium] Jina 抓取失败: {exc}")
        return None


def _fetch_jsonld(url: str) -> Optional[Dict[str, Any]]:
    """Tier 1 — fetch raw HTML and extract Schema.org articleBody."""
    try:
        headers = {
            "User-Agent": get_user_agent(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = http_client.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return None
        article = extract_jsonld_article(resp.text)
        if not article:
            return None
        return {
            "title": article.get("headline", ""),
            "content": article.get("articleBody", ""),
            "url": url,
            "author": article.get("author", ""),
            "published": article.get("datePublished", ""),
            "image": article.get("image", ""),
        }
    except Exception as exc:
        logger.warning(f"[Medium] JSON-LD 抓取失败: {exc}")
        return None


async def _fetch_browser(url: str) -> Optional[Dict[str, Any]]:
    """Tier 2 — patchright stealth Playwright fallback."""
    try:
        from feedgrab.fetchers.browser import fetch_via_browser
    except Exception:
        return None
    try:
        result = await fetch_via_browser(url)
        if not result or not result.get("content"):
            return None
        return result
    except Exception as exc:
        logger.warning(f"[Medium] Browser 抓取失败: {exc}")
        return None


def _extract_author_from_url(url: str) -> str:
    """Best-effort author handle from a Medium article URL."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    # subdomain.medium.com/<slug>
    if netloc.endswith(".medium.com") and netloc != "medium.com":
        return "@" + netloc.split(".medium.com", 1)[0]

    parts = [p for p in parsed.path.split("/") if p]
    if parts and parts[0].startswith("@"):
        return parts[0]
    if len(parts) >= 2:
        # publication article — no author handle in URL
        return ""
    return ""


def _strip_jina_chrome(content: str) -> str:
    """Remove Medium-specific noise from Jina Reader output."""
    if not content:
        return ""
    lines = content.split("\n")
    cleaned: List[str] = []
    for ln in lines:
        s = ln.strip()
        # Skip Medium standard navigation labels
        if s in {"Sign up", "Sign in", "Sitemap", "Open in app", "Write", "More from Medium"}:
            continue
        cleaned.append(ln)
    text = "\n".join(cleaned)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# =============================================================================
# Public API
# =============================================================================

async def fetch_medium(url: str) -> Dict[str, Any]:
    """Fetch a single Medium article through the tier chain.

    Returns a dict that schema.from_medium can convert to UnifiedContent.
    """
    from feedgrab.config import (
        medium_use_jina,
        medium_use_browser_fallback,
    )

    kind, ident = parse_medium_url(url)
    if kind == "user":
        raise RuntimeError(
            f"Medium 用户主页请使用批量子命令：feedgrab medium-user {ident} --limit N"
        )
    if kind == "publication":
        raise RuntimeError(
            f"Medium 出版物主页请使用批量子命令：feedgrab medium-pub {ident} --limit N"
        )

    article_url = ident

    # Tier 0 — Jina Reader
    result: Optional[Dict[str, Any]] = None
    if medium_use_jina():
        result = _fetch_jina(article_url)

    # Tier 1 — JSON-LD
    if not result:
        result = _fetch_jsonld(article_url)

    # Tier 2 — Browser fallback
    if not result and medium_use_browser_fallback():
        result = await _fetch_browser(article_url)

    if not result:
        raise RuntimeError(f"Medium 抓取全部 Tier 失败: {article_url}")

    title = (result.get("title") or "").strip() or "Untitled"
    content = _strip_jina_chrome(result.get("content") or "")
    is_member_only = _is_member_only(content)

    # Author best-effort
    author_handle = result.get("author") or _extract_author_from_url(article_url)

    return {
        "url": article_url,
        "title": title,
        "content": content,
        "author": author_handle or "medium",
        "author_name": result.get("author") or author_handle,
        "published": result.get("published", ""),
        "image": result.get("image", ""),
        "is_member_only": is_member_only,
        "tags": [],
    }


# =============================================================================
# RSS-based batch helpers (user / publication)
# =============================================================================

def _rss_url_for_user(handle: str) -> str:
    """Build the RSS endpoint for a Medium user (@username)."""
    h = handle.strip()
    if not h.startswith("@"):
        h = "@" + h
    return f"https://medium.com/feed/{h}"


def _rss_url_for_publication(slug: str) -> str:
    return f"https://medium.com/feed/{slug.strip().strip('/')}"


def _parse_feed(url: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch and parse Medium RSS, returning a list of entry dicts."""
    headers = {
        "User-Agent": get_user_agent(),
        "Accept": "application/rss+xml, application/xml, text/xml",
    }
    try:
        resp = http_client.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"RSS HTTP {resp.status_code}")
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        raise RuntimeError(f"Medium RSS 抓取失败 {url}: {exc}")

    entries: List[Dict[str, Any]] = []
    for entry in feed.entries[:limit]:
        link = entry.get("link", "")
        if not link:
            continue
        entries.append({
            "title": entry.get("title", ""),
            "url": link,
            "author": entry.get("author", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })
    return entries


async def fetch_medium_user(handle: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch a Medium user's recent articles via RSS + tier chain."""
    rss_url = _rss_url_for_user(handle)
    logger.info(f"[Medium] 用户 RSS: {rss_url}")
    entries = _parse_feed(rss_url, limit)
    return await _hydrate_entries(entries)


async def fetch_medium_publication(slug: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch a Medium publication's recent articles via RSS + tier chain."""
    rss_url = _rss_url_for_publication(slug)
    logger.info(f"[Medium] 出版物 RSS: {rss_url}")
    entries = _parse_feed(rss_url, limit)
    return await _hydrate_entries(entries)


async def _hydrate_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-fetch each RSS entry through the single-article tier chain."""
    import asyncio
    from feedgrab.config import medium_user_delay

    results: List[Dict[str, Any]] = []
    delay = medium_user_delay()
    for idx, entry in enumerate(entries, 1):
        link = entry.get("url")
        if not link:
            continue
        try:
            data = await fetch_medium(link)
        except Exception as exc:
            logger.warning(f"[Medium] 第 {idx} 篇 ({link}) 抓取失败，使用 RSS 摘要: {exc}")
            # Graceful degrade: keep RSS summary so user gets *something*
            data = {
                "url": link,
                "title": entry.get("title", "Untitled"),
                "content": _strip_jina_chrome(entry.get("summary", "")),
                "author": entry.get("author", "") or "medium",
                "author_name": entry.get("author", ""),
                "published": entry.get("published", ""),
                "image": "",
                "is_member_only": False,
                "tags": [],
            }
        results.append(data)
        if idx < len(entries) and delay > 0:
            await asyncio.sleep(delay)
    return results
