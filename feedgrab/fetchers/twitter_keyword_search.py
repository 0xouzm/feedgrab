# -*- coding: utf-8 -*-
"""
Twitter/X keyword search — discover tweets by keyword with engagement ranking.

Usage:
    feedgrab x-so "openclaw"
    feedgrab x-so openclaw --days 3 --lang en --min-faves 100 --sort top
    feedgrab x-so '"openclaw" lang:zh since:2026-03-06 min_faves:50' --raw

Architecture:
    1. Build Twitter search query from keyword + config defaults + CLI overrides
    2. Launch Playwright browser, load Twitter session
    3. Register SearchResponseCollector (reused from twitter_search_tweets.py)
    4. Navigate to search URL, auto-scroll to collect GraphQL responses
    5. extract_tweet_data() on each entry → engagement-ranked summary table
    6. Optionally save individual tweet .md files (X_SEARCH_SAVE_TWEETS=true)

Output:
    X/search/{days}day_{sort_label}/{keyword}_{date}.md    ← summary table (always)
    X/search/{days}day_{sort_label}/{keyword}/{tweet}.md   ← individual tweets (optional)
"""

import asyncio
import os
import re
import urllib.parse
from datetime import date, timedelta, datetime
from pathlib import Path
from loguru import logger
from typing import Dict, Any, List

from feedgrab.config import (
    get_session_dir,
    get_user_agent,
    parse_twitter_date_local,
)
from feedgrab.fetchers.twitter_search_tweets import (
    SearchResponseCollector,
    _scroll_and_collect_search,
)
from feedgrab.fetchers.twitter_graphql import extract_tweet_data
from feedgrab.fetchers.twitter import _clean_title


# ---------------------------------------------------------------------------
# Query building
# ---------------------------------------------------------------------------

def build_search_query(
    keyword: str,
    lang: str = "",
    days: int = 1,
    min_faves: int = 0,
    min_retweets: int = 0,
    exclude_retweets: bool = True,
    raw: bool = False,
) -> str:
    """Build Twitter search query string from keyword and filter parameters.

    When raw=False, auto-wraps keyword in quotes for exact phrase match
    and appends configured operators (lang, since, min_faves, etc.).
    When raw=True, uses keyword as-is (user controls full query).
    """
    if raw:
        return keyword

    # Auto-wrap keyword in quotes for exact match if not already quoted
    kw = keyword.strip()
    if not (kw.startswith('"') and kw.endswith('"')):
        kw = f'"{kw}"'

    parts = [kw]
    if lang:
        parts.append(f"lang:{lang}")
    if days > 0:
        since_date = (date.today() - timedelta(days=days)).isoformat()
        parts.append(f"since:{since_date}")
    if min_faves > 0:
        parts.append(f"min_faves:{min_faves}")
    if min_retweets > 0:
        parts.append(f"min_retweets:{min_retweets}")
    if exclude_retweets:
        parts.append("-is:retweet")

    return " ".join(parts)


def build_search_url(query: str, sort: str = "live") -> str:
    """Build Twitter search URL with sort parameter.

    sort='live' → Latest tab (&f=live)
    sort='top'  → Top tab (no &f= parameter, X.com default)
    """
    encoded = urllib.parse.quote(query)
    url = f"https://x.com/search?q={encoded}&src=typed_query"
    if sort == "live":
        url += "&f=live"
    return url


# ---------------------------------------------------------------------------
# Engagement scoring
# ---------------------------------------------------------------------------

def _engagement_score(tweet_data: dict) -> int:
    """Calculate engagement score for sorting.

    Formula: likes*3 + retweets*2 + bookmarks*2 + replies
    """
    likes = int(tweet_data.get("likes", 0) or 0)
    retweets = int(tweet_data.get("retweets", 0) or 0)
    bookmarks = int(tweet_data.get("bookmarks", 0) or 0)
    replies = int(tweet_data.get("replies", 0) or 0)
    return likes * 3 + retweets * 2 + bookmarks * 2 + replies


# ---------------------------------------------------------------------------
# Summary table generation
# ---------------------------------------------------------------------------

def _sanitize_for_dirname(name: str) -> str:
    """Clean a string for use as a directory/file name."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name)
    return name.strip('. ')[:50]


def _resolve_output_base() -> Path:
    """Resolve the base output directory (OBSIDIAN_VAULT > OUTPUT_DIR > output)."""
    vault = os.getenv("OBSIDIAN_VAULT", "").strip()
    output_dir = os.getenv("OUTPUT_DIR", "").strip()
    return Path(vault or output_dir or "output")


def _generate_summary_table(
    keyword: str,
    query: str,
    sort: str,
    days: int,
    tweets: List[dict],
    output_path: Path,
) -> None:
    """Generate a summary Markdown table sorted by engagement score.

    Writes directly to output_path (not via save_to_markdown).
    """
    sort_label_zh = "最新" if sort == "live" else "热门"
    date_str = datetime.now().strftime("%Y-%m-%d")

    # YAML front matter
    lines = [
        "---",
        f'title: "X 搜索：{keyword}"',
        f"query: '{query}'",
        f'search_tab: "{sort_label_zh}"',
        f"total: {len(tweets)}",
        f"created: {date_str}",
        "---",
        "",
    ]

    if not tweets:
        lines.append("*No results found.*")
    else:
        # Table header
        lines.append(
            "| # | 作者 | 内容摘要 | 👍 | 🔄 | 💬 | 👁 | 📌 | 日期 | 链接 |"
        )
        lines.append(
            "|---|------|----------|---:|---:|---:|---:|---:|------|------|"
        )

        # Table rows (already sorted by caller)
        for i, td in enumerate(tweets, 1):
            author = td.get("author", "")
            if author and not author.startswith("@"):
                author = f"@{author}"
            summary = _clean_title(td.get("text", ""), max_len=40)
            # Escape pipe chars in summary for table
            summary = summary.replace("|", "\\|")
            likes = int(td.get("likes", 0) or 0)
            retweets = int(td.get("retweets", 0) or 0)
            replies_count = int(td.get("replies", 0) or 0)
            views = int(td.get("views", 0) or 0)
            bookmarks = int(td.get("bookmarks", 0) or 0)
            created_at = td.get("created_at", "")
            date_short = parse_twitter_date_local(created_at, "%m-%d")

            tweet_id = td.get("id", "")
            tweet_author = td.get("author", "")
            tweet_url = f"https://x.com/{tweet_author}/status/{tweet_id}"

            lines.append(
                f"| {i} | {author} | {summary} "
                f"| {likes} | {retweets} | {replies_count} "
                f"| {views} | {bookmarks} | {date_short} "
                f"| [→]({tweet_url}) |"
            )

    # Write file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[X-SO] Summary table saved: {output_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def search_twitter_keyword(
    keyword: str,
    lang: str = "",
    days: int = 1,
    min_faves: int = 0,
    min_retweets: int = 0,
    sort: str = "live",
    exclude_retweets: bool = True,
    max_results: int = 100,
    scroll_delay: float = 2.0,
    save_tweets: bool = False,
    raw: bool = False,
) -> dict:
    """Search Twitter for tweets matching a keyword and generate engagement-ranked output.

    Returns:
        dict with: total, saved, query, output_path
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright 未安装。运行: "
            'pip install "feedgrab[browser]" && playwright install chromium'
        )

    # Build query
    query = build_search_query(
        keyword, lang=lang, days=days, min_faves=min_faves,
        min_retweets=min_retweets, exclude_retweets=exclude_retweets,
        raw=raw,
    )
    search_url = build_search_url(query, sort=sort)
    logger.info(f"[X-SO] Query: {query}")
    logger.info(f"[X-SO] URL: {search_url}")

    # Check session
    session_dir = get_session_dir()
    session_path = session_dir / "twitter.json"
    if not session_path.exists():
        raise RuntimeError(
            "未找到 Twitter session 文件，请先运行: feedgrab login twitter"
        )

    # Resolve output paths
    base_dir = _resolve_output_base()
    sort_label = "new" if sort == "live" else "hot"
    effective_days = days if not raw else 0
    subdir = f"search/{effective_days}day_{sort_label}"
    safe_keyword = _sanitize_for_dirname(keyword)
    date_str = datetime.now().strftime("%Y-%m-%d")
    summary_dir = base_dir / "X" / subdir
    summary_path = summary_dir / f"{safe_keyword}_{date_str}.md"

    # Launch browser
    collector = SearchResponseCollector()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=get_user_agent(),
            storage_state=str(session_path),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()
        page.on("response", collector.handle_response)

        try:
            # Warm up session
            logger.info("[X-SO] Warming up session...")
            try:
                await page.goto(
                    "https://x.com/home",
                    wait_until="domcontentloaded",
                    timeout=20000,
                )
                await asyncio.sleep(3)
            except Exception as e:
                logger.warning(f"[X-SO] Warm-up navigation error: {e}, continuing")

            # Navigate to search
            logger.info(f"[X-SO] Navigating to search page...")
            try:
                await page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
            except Exception as e:
                raise RuntimeError(f"搜索页面导航失败: {e}")

            # Wait for results or empty state
            try:
                await page.wait_for_selector(
                    '[data-testid="tweet"], '
                    '[data-testid="empty_state_header_text"]',
                    timeout=15000,
                )
            except Exception:
                logger.info("[X-SO] Page load timeout, attempting to continue")

            # Check empty results
            empty_state = await page.query_selector(
                '[data-testid="empty_state_header_text"]'
            )
            if empty_state:
                logger.info("[X-SO] No search results")
                await context.close()
                await browser.close()
                return {
                    "total": 0, "saved": 0,
                    "query": query, "output_path": "",
                }

            # Wait for initial GraphQL response
            await asyncio.sleep(2)
            initial_count = len(collector.entries)
            logger.info(f"[X-SO] Initial load captured {initial_count} entries")

            # Scroll to load more
            max_scrolls = max_results // 5 + 20
            await _scroll_and_collect_search(
                page, collector,
                max_scrolls=max_scrolls,
                scroll_delay_min=scroll_delay * 0.75,
                scroll_delay_max=scroll_delay * 1.5,
            )

            logger.info(
                f"[X-SO] Total captured: {len(collector.entries)} raw entries"
            )

        finally:
            await context.close()
            await browser.close()

    # Process entries
    tweets = []
    for entry in collector.entries:
        td = extract_tweet_data(entry)
        if not td:
            continue
        # Skip entries without an id
        if not td.get("id"):
            continue
        tweets.append(td)

    # Truncate to max_results
    tweets = tweets[:max_results]
    logger.info(f"[X-SO] Extracted {len(tweets)} tweets")

    # Sort by engagement score
    tweets.sort(key=_engagement_score, reverse=True)

    # Generate summary table
    _generate_summary_table(keyword, query, sort, effective_days, tweets, summary_path)

    # Optional: save individual tweets
    saved = 0
    if save_tweets and tweets:
        from feedgrab.fetchers.twitter_bookmarks import (
            _classify_tweet,
            _build_single_tweet_data,
        )
        from feedgrab.schema import from_twitter
        from feedgrab.utils.storage import save_to_markdown
        from feedgrab.utils.dedup import (
            load_index, save_index, has_item, add_item, item_id_from_url,
        )

        dedup_index = load_index(platform="X")
        tweet_subdir = f"{subdir}/{safe_keyword}"

        for td in tweets:
            tweet_id = td.get("id", "")
            author = td.get("author", "")
            tweet_url = f"https://x.com/{author}/status/{tweet_id}"
            item_id = item_id_from_url(tweet_url)

            if has_item(item_id, dedup_index):
                continue

            try:
                data = _build_single_tweet_data(td, tweet_url)
                content = from_twitter(data)
                content.category = tweet_subdir
                save_to_markdown(content)
                add_item(item_id, tweet_url, dedup_index)
                saved += 1
            except Exception as e:
                logger.warning(f"[X-SO] Failed to save tweet {tweet_id}: {e}")

        save_index(dedup_index, platform="X")
        logger.info(f"[X-SO] Saved {saved} individual tweet files")

    return {
        "total": len(tweets),
        "saved": saved,
        "query": query,
        "output_path": str(summary_path),
    }
