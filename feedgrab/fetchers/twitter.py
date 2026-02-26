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

# Sentence-ending punctuation for smart title truncation
_SENTENCE_ENDS = set("。！？.!?")


def _clean_title(text: str, max_len: int = 50) -> str:
    """Clean and smart-truncate text for use as a title.

    - Strip newlines, tabs, control chars; collapse whitespace
    - If within max_len, return as-is
    - Otherwise prefer cutting at last sentence-ending punctuation
    """
    # Remove newlines, tabs, control chars; collapse whitespace
    text = re.sub(r'[\r\n\t]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_len:
        return text
    # Look for last sentence-ending punctuation within max_len
    candidate = text[:max_len]
    for i in range(len(candidate) - 1, max_len // 3 - 1, -1):
        if candidate[i] in _SENTENCE_ENDS:
            return candidate[:i + 1]
    return candidate


def _extract_author(url: str) -> str:
    """Extract @username from tweet URL."""
    match = re.search(r'x\.com/(\w+)/status', url)
    return f"@{match.group(1)}" if match else ""


def _clean_jina_twitter_title(raw_title: str) -> tuple[str, str]:
    """Extract clean title and author display name from Jina page title.

    Jina returns page titles like:
      'Title: 鱼总聊AI on X: "OpenClaw新手完整学习路径-更适合新手食用的学习+使用教程" / X'
      '鱼总聊AI on X: "OpenClaw新手完整学习路径" / X'

    Returns:
        (clean_title, author_name) — e.g. ("OpenClaw新手...", "鱼总聊AI")
    """
    title = raw_title.strip()
    # Strip "Title: " prefix
    if title.lower().startswith("title:"):
        title = title[6:].strip()

    # Try to match pattern: {author} on X: "{actual_title}" / X
    m = re.match(r'(.+?)\s+on\s+X[:\s]*["\u201c](.+?)["\u201d]\s*/\s*X$', title)
    if m:
        return m.group(2).strip(), m.group(1).strip()

    # Fallback: strip trailing " / X" or " - X"
    title = re.sub(r'\s*[/\-]\s*X\s*$', '', title)
    # Strip leading "Title: "
    title = re.sub(r'^Title:\s*', '', title, flags=re.IGNORECASE)
    return title.strip(), ""


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

        # Build result with thread data + metrics from root tweet
        # For Twitter Articles, prefer article title over tweet text (which is just a t.co link)
        article = root.get("article") or {}
        title = article.get("title") or root.get("text", "")
        title = _clean_title(title)

        return {
            "text": _join_thread_text(tweets),
            "author": f"@{author}" if author else "",
            "author_name": thread.get("author_name", root.get("author_name", "")),
            "url": url,
            "title": title,
            "platform": "twitter",
            "thread_tweets": tweets,
            "has_thread": len(tweets) > 1,
            "article_data": article,
            "likes": root.get("likes", 0),
            "retweets": root.get("retweets", 0),
            "replies": root.get("replies", 0),
            "bookmarks": root.get("bookmarks", 0),
            "views": root.get("views", "0"),
            "created_at": root.get("created_at", ""),
            "images": [img for t in tweets for img in t.get("images", [])],
            "videos": [v for t in tweets for v in t.get("videos", [])],
            "hashtags": list(dict.fromkeys(
                tag for t in tweets for tag in t.get("hashtags", [])
            )),
            "author_replies": thread.get("author_replies", []),
            "comments": thread.get("comments", []),
        }

    # Fallback: single tweet via TweetDetail
    response = fetch_tweet_detail(tweet_id, cookies)
    if response:
        entries = parse_tweet_entries(response)
        for entry in entries:
            tweet_data = extract_tweet_data(entry)
            if tweet_data and tweet_data.get("id") == tweet_id:
                article = tweet_data.get("article") or {}
                title = article.get("title") or tweet_data.get("text", "")
                title = _clean_title(title)

                return {
                    "text": tweet_data.get("text", ""),
                    "author": f"@{tweet_data.get('author', '')}",
                    "author_name": tweet_data.get("author_name", ""),
                    "url": url,
                    "title": title,
                    "platform": "twitter",
                    "thread_tweets": [tweet_data],
                    "has_thread": False,
                    "article_data": article,
                    "likes": tweet_data.get("likes", 0),
                    "retweets": tweet_data.get("retweets", 0),
                    "replies": tweet_data.get("replies", 0),
                    "bookmarks": tweet_data.get("bookmarks", 0),
                    "views": tweet_data.get("views", "0"),
                    "created_at": tweet_data.get("created_at", ""),
                    "images": tweet_data.get("images", []),
                    "videos": tweet_data.get("videos", []),
                    "hashtags": tweet_data.get("hashtags", []),
                }

    raise RuntimeError("GraphQL returned no usable data")


def _join_thread_text(tweets: list) -> str:
    """Join thread tweets into a single text with numbering.

    First tweet (main post) has no prefix; subsequent tweets numbered [1/N]...[N/N].
    """
    if len(tweets) == 1:
        return tweets[0].get("text", "")

    parts = []
    rest_count = len(tweets) - 1
    for i, tweet in enumerate(tweets):
        text = tweet.get("text", "").strip()
        if not text:
            continue
        if i == 0:
            parts.append(text)
        else:
            parts.append(f"[{i}/{rest_count}] {text}")
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
                    # Check if this is a Twitter Article that needs Jina for full body
                    # Primary signal: article_data with has_content flag (from GraphQL)
                    # Secondary signal: text is short stub with t.co link
                    article_data = data.get("article_data") or {}
                    has_article = article_data.get("has_content", False)
                    text = data["text"].strip()
                    text_is_stub = (
                        "https://t.co/" in text or text.startswith("http")
                    ) and len(text) < 200
                    # For multi-tweet threads, check first tweet individually
                    if not text_is_stub and data.get("thread_tweets"):
                        first_text = (data["thread_tweets"][0].get("text") or "").strip()
                        text_is_stub = (
                            len(first_text) < 200
                            and ("https://t.co/" in first_text or first_text.startswith("http"))
                        )
                    is_article_stub = has_article or text_is_stub
                    if is_article_stub:
                        logger.info("[Twitter] Article detected — fetching body via Jina")
                        jina_content = ""
                        for attempt in range(2):
                            try:
                                jina_data = fetch_via_jina(url)
                                jina_content = jina_data.get("content", "")
                                if jina_content and len(jina_content.strip()) > 200:
                                    break
                                if attempt == 0:
                                    logger.info("[Twitter] Jina returned short content, retrying...")
                                    import time; time.sleep(2)
                            except Exception as je:
                                if attempt == 0:
                                    logger.info(f"[Twitter] Jina attempt 1 failed ({je}), retrying...")
                                    import time; time.sleep(2)
                                else:
                                    logger.warning(f"[Twitter] Jina retry also failed ({je})")
                        if jina_content and len(jina_content.strip()) > 200:
                            # Normalize nested image links [![alt](img)](link) → ![image](img)
                            jina_content = re.sub(
                                r'\[!\[[^\]]*\]\(([^)]+)\)\]\([^)]+\)',
                                r'![image](\1)',
                                jina_content,
                            )
                            data["text"] = jina_content
                            # Update thread_tweets content too for schema
                            if data.get("thread_tweets"):
                                data["thread_tweets"][0]["text"] = jina_content
                            logger.info("[Twitter] Article body fetched successfully")
                        else:
                            logger.warning("[Twitter] Jina article body too short after retries, keeping original")
                    return data
                logger.warning("[Twitter] GraphQL returned empty content")
            else:
                logger.warning(
                    "\n"
                    "+--------------------------------------------------+\n"
                    "|  Twitter Cookie 未配置 - 无法获取完整数据        |\n"
                    "+--------------------------------------------------+\n"
                    "|  缺少 cookie 将导致:                             |\n"
                    "|  - 无法获取 likes/views/bookmarks 等指标         |\n"
                    "|  - 无法获取作者回帖和评论                        |\n"
                    "|  - 仅能获取基础正文内容                          |\n"
                    "+--------------------------------------------------+\n"
                    "|  配置方法 (任选其一):                            |\n"
                    "|  1. feedgrab login twitter                       |\n"
                    "|  2. .env 设置 X_AUTH_TOKEN + X_CT0               |\n"
                    "|  3. 手动写入 sessions/x.json                     |\n"
                    "+--------------------------------------------------+"
                )
        except Exception as e:
            err_msg = str(e)
            if "401" in err_msg or "403" in err_msg or "unauthorized" in err_msg.lower():
                logger.warning(
                    "[Twitter] Cookie expired! Run: feedgrab login twitter\n"
                    "  Falling back to limited mode (no metrics)..."
                )
            else:
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
            clean_title, jina_author_name = _clean_jina_twitter_title(title)
            return {
                "text": content,
                "author": author,
                "author_name": jina_author_name,
                "url": url,
                "title": clean_title,
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
