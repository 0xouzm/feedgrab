# -*- coding: utf-8 -*-
"""
X/Twitter fetcher — four-tier fallback:

0. GraphQL API (complete thread + media, requires cookie auth)
1. X oEmbed API (fast, reliable for individual tweets, no login needed)
2. Jina Reader (handles non-tweet X pages like profiles)
3. Playwright + saved session (handles login-required content)

Install browser tier: pip install "feedgrab[browser]" && playwright install chromium
Save X session:       feedgrab login twitter
"""

import os
import re
import requests
from loguru import logger
from typing import Dict, Any

from feedgrab.fetchers.jina import fetch_via_jina


OEMBED_URL = "https://publish.twitter.com/oembed"


def _extract_author(url: str) -> str:
    """Extract @username from tweet URL."""
    match = re.search(r'x\.com/(\w+)/status', url)
    return f"@{match.group(1)}" if match else ""


def _extract_tweet_id(url: str) -> str:
    """Extract numeric tweet ID from URL."""
    match = re.search(r'x\.com/\w+/status/(\d+)', url)
    return match.group(1) if match else ""


def _is_tweet_url(url: str) -> bool:
    """Check if this is a direct tweet/status URL (vs profile or other X page)."""
    return bool(re.search(r'x\.com/\w+/status/\d+', url))


def _is_graphql_enabled() -> bool:
    """Check if GraphQL tier is enabled via env config."""
    return os.getenv("X_GRAPHQL_ENABLED", "true").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Tier 0: GraphQL API (new — ported from baoyu)
# ---------------------------------------------------------------------------

async def _fetch_via_graphql(url: str, tweet_id: str) -> Dict[str, Any]:
    """
    Fetch tweet/thread via X's private GraphQL API.

    Returns complete thread data with media, quoted tweets, etc.
    Requires valid auth cookies (loaded automatically from 4 sources).
    """
    from feedgrab.fetchers.twitter_cookies import load_twitter_cookies, has_required_cookies
    from feedgrab.fetchers.twitter_thread import fetch_tweet_thread
    from feedgrab.fetchers.twitter_graphql import fetch_tweet_detail, extract_tweet_data, parse_tweet_entries

    cookies = load_twitter_cookies()
    if not has_required_cookies(cookies):
        raise RuntimeError("No valid Twitter cookies for GraphQL")

    # Try thread fetch first (gets complete author self-reply chain)
    thread = fetch_tweet_thread(tweet_id, cookies)

    if thread and thread.get("tweets"):
        tweets = thread["tweets"]
        root = thread.get("root_tweet", tweets[0])
        author = thread.get("author", "")

        # Build result with thread data
        return {
            "text": _join_thread_text(tweets),
            "author": f"@{author}" if author else "",
            "url": url,
            "title": root.get("text", "")[:100],
            "platform": "twitter",
            "thread_tweets": tweets,
            "has_thread": len(tweets) > 1,
        }

    # Fallback: single tweet via TweetDetail
    response = fetch_tweet_detail(tweet_id, cookies)
    if response:
        entries = parse_tweet_entries(response)
        for entry in entries:
            tweet_data = extract_tweet_data(entry)
            if tweet_data and tweet_data.get("id") == tweet_id:
                return {
                    "text": tweet_data.get("text", ""),
                    "author": f"@{tweet_data.get('author', '')}",
                    "url": url,
                    "title": tweet_data.get("text", "")[:100],
                    "platform": "twitter",
                    "thread_tweets": [tweet_data],
                    "has_thread": False,
                }

    raise RuntimeError("GraphQL returned no usable data")


def _join_thread_text(tweets: list) -> str:
    """Join thread tweets into a single text with numbering."""
    if len(tweets) == 1:
        return tweets[0].get("text", "")

    parts = []
    for i, tweet in enumerate(tweets, 1):
        text = tweet.get("text", "").strip()
        if text:
            parts.append(f"[{i}/{len(tweets)}] {text}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tier 1: oEmbed API (original)
# ---------------------------------------------------------------------------

def _fetch_via_oembed(url: str) -> Dict[str, Any]:
    """
    Fetch tweet text via X's oEmbed API.
    Free, reliable, no auth needed. Works for public tweets.
    Note: oEmbed requires twitter.com URLs (not x.com).
    """
    oembed_query_url = url.replace("x.com", "twitter.com")
    resp = requests.get(
        OEMBED_URL,
        params={"url": oembed_query_url, "omit_script": "true"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    html = data.get("html", "")
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text).strip()

    return {
        "text": text,
        "author": data.get("author_name", ""),
        "author_url": data.get("author_url", ""),
        "title": text[:100] if text else "",
    }


# ---------------------------------------------------------------------------
# Tier 3: Playwright (original)
# ---------------------------------------------------------------------------

async def _fetch_via_playwright(url: str) -> Dict[str, Any]:
    """
    Fetch tweet via Playwright with X-specific DOM selectors.
    Uses saved login session if available (~/.feedgrab/sessions/twitter.json).
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed. Run:\n"
            '  pip install "feedgrab[browser]"\n'
            "  playwright install chromium"
        )

    from feedgrab.fetchers.browser import get_session_path
    from pathlib import Path

    session_path = get_session_path("twitter")
    has_session = Path(session_path).exists()
    if has_session:
        logger.info(f"Using saved X session: {session_path}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )

        context_kwargs = {}
        if has_session:
            context_kwargs["storage_state"] = session_path

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            **context_kwargs,
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            try:
                await page.wait_for_selector(
                    '[data-testid="tweetText"]', timeout=10_000
                )
            except Exception:
                pass

            tweet_text = await page.evaluate("""() => {
                const tweetEl = document.querySelector('[data-testid="tweetText"]');
                if (tweetEl) return tweetEl.innerText;
                const article = document.querySelector('article');
                if (article) return article.innerText;
                const main = document.querySelector('main');
                if (main) return main.innerText;
                return '';
            }""")

            title = await page.title()

            return {
                "text": (tweet_text or "").strip(),
                "title": (title or "").strip()[:200],
            }
        finally:
            await context.close()
            await browser.close()


# ---------------------------------------------------------------------------
# Main dispatcher — four-tier fallback
# ---------------------------------------------------------------------------

async def fetch_twitter(url: str) -> Dict[str, Any]:
    """
    Fetch a tweet or X post with four-tier fallback.

    Tier 0: GraphQL API (needs cookie, most complete — thread + media)
    Tier 1: oEmbed API (free, no auth, single tweet text only)
    Tier 2: Jina Reader (no auth, handles profiles/non-tweet pages)
    Tier 3: Playwright browser (last resort, handles login-required content)

    Logic:
        - Has cookies + is tweet URL → try Tier 0 first (GraphQL)
        - No cookies → skip Tier 0, go straight to Tier 1
        - GraphQL fails → auto-degrade to Tier 1/2/3

    Args:
        url: Tweet URL (x.com or twitter.com)

    Returns:
        Dict with: text, author, url, title, platform,
        and optionally: thread_tweets, has_thread (from Tier 0)
    """
    url = url.replace("twitter.com", "x.com")
    author = _extract_author(url)
    tweet_id = _extract_tweet_id(url)

    # Tier 0: GraphQL (needs cookie auth, most complete)
    if tweet_id and _is_graphql_enabled():
        try:
            from feedgrab.fetchers.twitter_cookies import load_twitter_cookies, has_required_cookies
            cookies = load_twitter_cookies()
            if has_required_cookies(cookies):
                logger.info(f"[Twitter] Tier 0 — GraphQL: {url}")
                data = await _fetch_via_graphql(url, tweet_id)
                if data and data.get("text"):
                    return data
                logger.warning("[Twitter] GraphQL returned empty content")
        except Exception as e:
            logger.warning(f"[Twitter] GraphQL failed ({e}), falling back")

    # Tier 1: oEmbed API (best for individual tweets, no auth)
    if _is_tweet_url(url):
        try:
            logger.info(f"[Twitter] Tier 1 — oEmbed: {url}")
            data = _fetch_via_oembed(url)
            text = (data.get("text") or "").strip()
            thin_oembed = (
                len(text) <= 20
                or text.lower().startswith("https://t.co/")
                or ("&mdash;" in text and text.count("https://t.co/") >= 1)
            )
            if not thin_oembed:
                return {
                    "text": text,
                    "author": author or data.get("author", ""),
                    "url": url,
                    "title": data.get("title", ""),
                    "platform": "twitter",
                }
            logger.warning("[Twitter] oEmbed returned thin content")
        except Exception as e:
            logger.warning(f"[Twitter] oEmbed failed ({e})")

    # Tier 2: Jina Reader (handles profiles, threads, non-tweet pages)
    try:
        logger.info(f"[Twitter] Tier 2 — Jina: {url}")
        data = fetch_via_jina(url)
        content = data.get("content", "")
        title = data.get("title", "")
        jina_ok = (
            content
            and len(content.strip()) > 100
            and "not yet fully loaded" not in content.lower()
            and title.lower() not in ("x", "title: x", "")
        )
        if jina_ok:
            return {
                "text": content,
                "author": author,
                "url": url,
                "title": title,
                "platform": "twitter",
            }
        logger.warning("[Twitter] Jina returned unusable content")
    except Exception as e:
        logger.warning(f"[Twitter] Jina failed ({e})")

    # Tier 3: Playwright + session with X-specific extraction
    try:
        logger.info(f"[Twitter] Tier 3 — Playwright: {url}")
        data = await _fetch_via_playwright(url)
        content = data.get("text", "")
        if content and len(content.strip()) > 20:
            return {
                "text": content,
                "author": author,
                "url": url,
                "title": data.get("title", ""),
                "platform": "twitter",
            }
        logger.warning("[Twitter] Playwright returned empty content")
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[Twitter] All methods failed: {e}")

    raise RuntimeError(
        f"❌ All Twitter fetch methods failed for: {url}\n"
        f"   Try: feedgrab login twitter (to save session for browser fallback)\n"
        f"   Then retry: feedgrab {url}"
    )
