# -*- coding: utf-8 -*-
"""
Twitter/X keyword search — discover tweets by keyword with engagement ranking.

Usage:
    feedgrab x-so "openclaw"
    feedgrab x-so openclaw --days 3 --lang en --min-faves 100 --sort top
    feedgrab x-so '"openclaw" lang:zh since:2026-03-06 min_faves:50' --raw

Architecture:
    1. Build Twitter search query from keyword + config defaults + CLI overrides
    2. Call SearchTimeline GraphQL endpoint directly (no browser needed)
    3. Paginate via cursor until max_results reached
    4. extract_tweet_data() on each entry → views-ranked summary table
    5. Optionally save individual tweet .md files (X_SEARCH_SAVE_TWEETS=true)

Output:
    X/search/{days}day_{sort_label}/{keyword}_{date}.md    ← summary table (always)
    X/search/{days}day_{sort_label}/{keyword}_{date}.csv   ← CSV table (always)
    X/search/{days}day_{sort_label}/{keyword}/{tweet}.md   ← individual tweets (optional)
"""

import csv
import os
import re
import time
import urllib.parse
from datetime import date, timedelta, datetime
from pathlib import Path
from loguru import logger
from typing import Dict, Any, List

from feedgrab.config import (
    parse_twitter_date_local,
)
from feedgrab.fetchers.twitter_graphql import (
    extract_tweet_data,
    fetch_search_timeline_page,
    parse_search_entries,
)
from feedgrab.fetchers.twitter_cookies import load_twitter_cookies
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
    """Generate summary Markdown table + CSV, sorted by views.

    MD: 内容摘要 is a hyperlink (no separate link column).
    CSV: has explicit link column with plain URL.
    """
    sort_label_zh = "最新" if sort == "live" else "热门"
    date_str = datetime.now().strftime("%Y-%m-%d")

    # --- Markdown ---
    lines = [
        "---",
        f'title: "X 搜索：{keyword}"',
        f"query: '{query}'",
        f'search_tab: "{sort_label_zh}"',
        f"total: {len(tweets)}",
        f"created: {date_str}",
        "cssclasses: wide",
        "---",
        "",
    ]

    if not tweets:
        lines.append("*No results found.*")
    else:
        lines.append(
            "| # | 作者👨🏻‍💻 | 内容摘要💻 | 日期🗓 | 点赞👍 | 转帖🔄 | 回复💬 | 查看👁 | 收藏📌 |"
        )
        lines.append(
            "|:---:|------|----------|:---:|:---:|:---:|:---:|:---:|:------:|"
        )

        for i, td in enumerate(tweets, 1):
            author = td.get("author", "")
            if author and not author.startswith("@"):
                author = f"@{author}"
            summary = _clean_title(td.get("text", ""), max_len=40)
            summary = summary.replace("|", "\\|")
            # Escape brackets for markdown link
            summary = summary.replace("[", "\\[").replace("]", "\\]")
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

            # Summary as hyperlink (no separate link column)
            summary_link = f"[{summary}]({tweet_url})"

            lines.append(
                f"| {i} | {author} | {summary_link} "
                f"| {date_short} | {likes} | {retweets} | {replies_count} "
                f"| {views} | {bookmarks} |"
            )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[X-SO] Summary table saved: {output_path}")

    # --- CSV ---
    csv_path = output_path.with_suffix(".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "#", "作者", "内容摘要", "日期", "点赞", "转帖",
            "回复", "查看", "收藏", "链接",
        ])
        for i, td in enumerate(tweets, 1):
            author = td.get("author", "")
            if author and not author.startswith("@"):
                author = f"@{author}"
            summary = _clean_title(td.get("text", ""), max_len=80)
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
            writer.writerow([
                i, author, summary, date_short, likes, retweets,
                replies_count, views, bookmarks, tweet_url,
            ])
    logger.info(f"[X-SO] CSV table saved: {csv_path}")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def search_twitter_keyword(
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

    Uses SearchTimeline GraphQL endpoint directly (no browser needed).

    Returns:
        dict with: total, saved, query, output_path
    """
    # Build query
    query = build_search_query(
        keyword, lang=lang, days=days, min_faves=min_faves,
        min_retweets=min_retweets, exclude_retweets=exclude_retweets,
        raw=raw,
    )
    search_url = build_search_url(query, sort=sort)
    logger.info(f"[X-SO] Query: {query}")
    logger.info(f"[X-SO] URL: {search_url}")

    # Load cookies (supports multi-account rotation)
    cookies = load_twitter_cookies()
    if not cookies:
        raise RuntimeError(
            "未找到 Twitter Cookie，请先运行: feedgrab login twitter"
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

    # Map sort to GraphQL product parameter
    product = "Latest" if sort == "live" else "Top"

    # GraphQL pagination loop
    all_entries = []
    cursor = None
    max_pages = max_results // 20 + 5  # ~20 entries per page

    for page in range(max_pages):
        response = fetch_search_timeline_page(
            raw_query=query,
            cookies=cookies,
            cursor=cursor,
            count=20,
            product=product,
        )

        # Retry once (cookie may have rotated after 429)
        if not response:
            cookies = load_twitter_cookies()
            if not cookies:
                logger.warning("[X-SO] No available cookies after retry")
                break
            time.sleep(3)
            response = fetch_search_timeline_page(
                raw_query=query, cookies=cookies,
                cursor=cursor, count=20, product=product,
            )
            if not response:
                logger.warning("[X-SO] GraphQL request failed after retry, stopping")
                break

        entries, cursors = parse_search_entries(response)
        if not entries:
            logger.info(f"[X-SO] No more entries at page {page + 1}")
            break

        all_entries.extend(entries)
        logger.info(
            f"[X-SO] Page {page + 1}: +{len(entries)} entries "
            f"(total: {len(all_entries)})"
        )

        if len(all_entries) >= max_results:
            break

        cursor = cursors.get("bottom")
        if not cursor:
            break

    logger.info(f"[X-SO] Total collected: {len(all_entries)} raw entries")

    # Process entries
    tweets = []
    for entry in all_entries:
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

    # Sort by views (descending)
    tweets.sort(key=lambda td: int(td.get("views", 0) or 0), reverse=True)

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
        "csv_path": str(summary_path.with_suffix(".csv")),
    }
