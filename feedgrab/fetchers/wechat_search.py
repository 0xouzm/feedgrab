# -*- coding: utf-8 -*-
"""
Sogou WeChat article search — search WeChat public account articles by keyword.

Uses Sogou's WeChat search (weixin.sogou.com) to discover articles,
then fetches each article's full content via the existing wechat.py fetcher.

Provides:
    - feedgrab wechat-search <keyword>          (search and fetch articles)

Data available from Sogou search results:
    - title, summary, author (公众号名), publish_time, thumbnail
    - NOT available: read count, likes, comments (WeChat internal only)
"""

import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Dict, Any, List, Optional


def _sogou_search(keyword: str, page: int = 1, max_results: int = 10) -> List[Dict[str, Any]]:
    """Search WeChat articles via Sogou.

    Returns list of dicts with: title, summary, author, timestamp, sogou_url, thumbnail.
    """
    encoded = urllib.parse.quote(keyword)
    url = (
        f"https://weixin.sogou.com/weixin?"
        f"type=2&query={encoded}&ie=utf8&page={page}"
    )

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/132.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"[WeChat-Search] Sogou request failed: {e}")
        return []

    # Check for anti-bot page
    if "antispider" in html.lower() or "用户您好" in html:
        logger.warning("[WeChat-Search] Sogou triggered anti-bot verification")
        return []

    return _parse_sogou_results(html, max_results)


def _parse_sogou_results(html: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Parse Sogou WeChat search results from HTML."""
    results = []

    # Find all <li> blocks in the news-list
    li_blocks = re.findall(
        r'<li\s+id="sogou_vr_\d+_box_\d+"[^>]*>(.*?)</li>',
        html,
        re.DOTALL,
    )

    for block in li_blocks[:max_results]:
        item = {}

        # Title: <h3><a ...>title text</a></h3>
        title_m = re.search(
            r'<h3>\s*<a[^>]*>(.*?)</a>\s*</h3>',
            block,
            re.DOTALL,
        )
        if title_m:
            title = title_m.group(1)
            # Clean HTML tags and entities
            title = re.sub(r'<[^>]+>', '', title)
            title = re.sub(r'<!--.*?-->', '', title)
            title = title.replace("&ldquo;", "\u201c").replace("&rdquo;", "\u201d")
            title = title.replace("&mdash;", "\u2014").replace("&amp;", "&")
            item["title"] = title.strip()

        # Sogou redirect URL (from the title link)
        url_m = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"', block)
        if url_m:
            sogou_url = url_m.group(1)
            # Make absolute if relative
            if sogou_url.startswith("/"):
                sogou_url = f"https://weixin.sogou.com{sogou_url}"
            item["sogou_url"] = sogou_url

        # Summary: <p class="txt-info" ...>text</p>
        summary_m = re.search(
            r'<p\s+class="txt-info"[^>]*>(.*?)</p>',
            block,
            re.DOTALL,
        )
        if summary_m:
            summary = summary_m.group(1)
            summary = re.sub(r'<[^>]+>', '', summary)
            summary = re.sub(r'<!--.*?-->', '', summary)
            summary = summary.replace("&ldquo;", "\u201c").replace("&rdquo;", "\u201d")
            summary = summary.replace("&mdash;", "\u2014").replace("&amp;", "&")
            item["summary"] = summary.strip()

        # Author (公众号名): <span class="all-time-y2">name</span>
        author_m = re.search(
            r'<span\s+class="all-time-y2">(.*?)</span>',
            block,
        )
        if author_m:
            item["author"] = author_m.group(1).strip()

        # Publish timestamp: timeConvert('1234567890')
        time_m = re.search(r"timeConvert\('(\d+)'\)", block)
        if time_m:
            ts = int(time_m.group(1))
            item["timestamp"] = ts
            item["publish_date"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        # Thumbnail: <img src="...">
        thumb_m = re.search(
            r'<img\s+src="(//img01\.sogoucdn\.com[^"]+)"',
            block,
        )
        if thumb_m:
            item["thumbnail"] = f"https:{thumb_m.group(1)}"

        if item.get("title") and item.get("sogou_url"):
            results.append(item)

    return results


async def _resolve_sogou_redirect_via_browser(sogou_url: str) -> Optional[str]:
    """Follow Sogou redirect via Playwright to get the real mp.weixin.qq.com URL.

    Sogou uses encrypted redirect links that trigger anti-bot on direct HTTP.
    Browser automation is required to follow the redirect chain.
    Returns the final WeChat URL or None if resolution fails.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.debug("[WeChat-Search] Playwright not installed, cannot resolve redirect")
        return None

    from feedgrab.config import get_user_agent

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, channel="chrome")
            context = await browser.new_context(user_agent=get_user_agent())
            page = await context.new_page()

            try:
                await page.goto(sogou_url, wait_until="domcontentloaded", timeout=15000)
                # Wait briefly for redirect
                await page.wait_for_timeout(3000)
                final_url = page.url

                if "mp.weixin.qq.com" in final_url:
                    return final_url

                # Try extracting from page content
                content = await page.content()
                wx_m = re.search(r'(https?://mp\.weixin\.qq\.com/s[^\s"\'<>]+)', content)
                if wx_m:
                    return wx_m.group(1)

            finally:
                await context.close()
                await browser.close()
    except Exception as e:
        logger.debug(f"[WeChat-Search] Browser redirect resolution failed: {e}")

    return None


async def search_wechat_articles(
    keyword: str,
    max_results: int = 10,
    fetch_content: bool = True,
    delay: float = 3.0,
) -> Dict[str, Any]:
    """Search and optionally fetch WeChat articles.

    Args:
        keyword: Search keyword
        max_results: Maximum number of results
        fetch_content: Whether to fetch full article content
        delay: Delay between fetching each article (seconds)

    Returns:
        Dict with: keyword, total, fetched, skipped, failed, articles
    """
    from feedgrab.utils.dedup import load_index, save_index, has_item, add_item, item_id_from_url

    logger.info(f"[WeChat-Search] Searching: {keyword}")
    results = _sogou_search(keyword, max_results=max_results)

    if not results:
        logger.warning("[WeChat-Search] No results found")
        return {
            "keyword": keyword,
            "total": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "articles": [],
        }

    logger.info(f"[WeChat-Search] Found {len(results)} results")

    # Load dedup index
    index = load_index(platform="WeChat")
    fetched = 0
    skipped = 0
    failed = 0
    articles = []

    for i, item in enumerate(results):
        title = item.get("title", "untitled")
        sogou_url = item.get("sogou_url", "")

        logger.info(f"[WeChat-Search] [{i+1}/{len(results)}] {title[:50]}")

        if not fetch_content:
            articles.append(item)
            fetched += 1
            continue

        # Resolve Sogou redirect to get real WeChat URL
        wx_url = await _resolve_sogou_redirect_via_browser(sogou_url)
        if not wx_url:
            logger.warning(f"[WeChat-Search] Could not resolve WeChat URL for: {title[:40]}")
            # Still save search result metadata
            articles.append(item)
            failed += 1
            continue

        item["wechat_url"] = wx_url

        # Dedup check
        item_id = item_id_from_url(wx_url)
        if has_item(item_id, index):
            logger.info(f"[WeChat-Search] Already fetched, skipping: {title[:40]}")
            skipped += 1
            continue

        # Fetch full article content
        try:
            from feedgrab.fetchers.wechat import fetch_wechat
            from feedgrab.schema import from_wechat
            from feedgrab.utils.storage import save_to_markdown

            article_data = await fetch_wechat(wx_url)
            # Enrich with search metadata
            if item.get("author"):
                article_data["author"] = item["author"]
            if item.get("publish_date"):
                article_data["publish_date"] = item["publish_date"]

            content = from_wechat(article_data)
            content.category = "search"
            save_to_markdown(content)

            # Register in dedup index
            add_item(item_id, wx_url, index)

            articles.append(item)
            fetched += 1
            logger.info(f"[WeChat-Search] Saved: {title[:50]}")

        except Exception as e:
            logger.warning(f"[WeChat-Search] Failed to fetch: {title[:40]} — {e}")
            articles.append(item)
            failed += 1

        # Rate limit
        if i < len(results) - 1:
            time.sleep(delay)

    # Save dedup index
    save_index(index, platform="WeChat")

    return {
        "keyword": keyword,
        "total": len(results),
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "articles": articles,
    }
