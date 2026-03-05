# -*- coding: utf-8 -*-
"""
Sogou WeChat article search — search WeChat public account articles by keyword.

Uses Sogou's WeChat search (weixin.sogou.com) to discover articles,
then fetches each article's full content via the existing wechat.py fetcher.

Provides:
    - feedgrab mpweixin-so <keyword>          (search and fetch articles)

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


async def _resolve_sogou_redirect(page, sogou_url: str) -> Optional[str]:
    """Follow Sogou redirect via an existing Playwright page to get the real URL.

    Reuses a shared page instance (which already visited the search page,
    so the context has proper Sogou cookies and referer).
    Returns the final WeChat URL or None if resolution fails.
    """
    try:
        # Open redirect in a new tab to preserve search page state
        new_page = await page.context.new_page()
        try:
            await new_page.goto(sogou_url, wait_until="domcontentloaded", timeout=20000)
            # Wait for redirect chain to complete
            await new_page.wait_for_timeout(4000)
            final_url = new_page.url

            if "mp.weixin.qq.com" in final_url:
                logger.debug(f"[WeChat-Search] Redirect resolved via URL: {final_url[:80]}")
                return final_url

            # Check for antispider — try to solve it by waiting longer
            if "antispider" in final_url:
                logger.debug("[WeChat-Search] Hit antispider, waiting for manual/auto resolve...")
                try:
                    await new_page.wait_for_url("**/mp.weixin.qq.com/**", timeout=10000)
                    final_url = new_page.url
                    if "mp.weixin.qq.com" in final_url:
                        logger.debug(f"[WeChat-Search] Antispider resolved: {final_url[:80]}")
                        return final_url
                except Exception:
                    pass

            # Try extracting from page content (JS redirect may embed the URL)
            content = await new_page.content()
            wx_m = re.search(r'(https?://mp\.weixin\.qq\.com/s[^\s"\'<>]+)', content)
            if wx_m:
                resolved = wx_m.group(1)
                logger.debug(f"[WeChat-Search] Redirect resolved via content: {resolved[:80]}")
                return resolved

            logger.debug(f"[WeChat-Search] Redirect landed on: {final_url[:80]}")
        finally:
            await new_page.close()
    except Exception as e:
        logger.debug(f"[WeChat-Search] Browser redirect failed: {e}")

    return None


def _save_search_item(item: Dict[str, Any], keyword: str):
    """Save a search result item as Markdown even without full article content.

    Uses search metadata (title, summary, author, publish_date, thumbnail)
    to create a minimal but informative document.
    """
    from feedgrab.schema import from_wechat
    from feedgrab.utils.storage import save_to_markdown

    # Build a pseudo article_data from search metadata
    article_data = {
        "title": item.get("title", ""),
        "author": item.get("author", ""),
        "url": item.get("wechat_url", item.get("sogou_url", "")),
        "content": item.get("summary", ""),
        "publish_date": item.get("publish_date", ""),
        "thumbnail": item.get("thumbnail", ""),
        "summary": item.get("summary", ""),
        "search_keyword": keyword,
    }

    content = from_wechat(article_data)
    content.category = "search"
    save_to_markdown(content)
    logger.info(f"[WeChat-Search] Saved (metadata only): {item.get('title', '')[:50]}")


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

    if not fetch_content:
        return {
            "keyword": keyword,
            "total": len(results),
            "fetched": len(results),
            "skipped": 0,
            "failed": 0,
            "articles": results,
        }

    # Launch ONE shared browser for all redirect resolutions
    browser = None
    context = None
    page = None
    pw = None
    try:
        from playwright.async_api import async_playwright
        from feedgrab.config import get_user_agent

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=get_user_agent())
        page = await context.new_page()

        # Navigate to the search page first to establish Sogou cookies
        # This is critical: redirect links only work with proper cookies/referer
        encoded = urllib.parse.quote(keyword)
        search_url = f"https://weixin.sogou.com/weixin?type=2&query={encoded}&ie=utf8&page=1"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        logger.info("[WeChat-Search] Browser launched, search page cookies acquired")
    except ImportError:
        logger.warning("[WeChat-Search] Playwright not installed, will save metadata only")
    except Exception as e:
        logger.warning(f"[WeChat-Search] Browser launch failed: {e}, will save metadata only")

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

        # Resolve Sogou redirect to get real WeChat URL
        wx_url = None
        if page:
            wx_url = await _resolve_sogou_redirect(page, sogou_url)

        if wx_url:
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
                if item.get("thumbnail"):
                    article_data["thumbnail"] = item["thumbnail"]
                if item.get("summary"):
                    article_data["summary"] = item["summary"]
                article_data["search_keyword"] = keyword

                content = from_wechat(article_data)
                content.category = "search"
                save_to_markdown(content)

                # Register in dedup index
                add_item(item_id, wx_url, index)

                articles.append(item)
                fetched += 1
                logger.info(f"[WeChat-Search] Saved: {title[:50]}")

            except Exception as e:
                logger.warning(f"[WeChat-Search] Fetch failed: {title[:40]} — {e}")
                # Save search metadata as fallback
                _save_search_item(item, keyword)
                articles.append(item)
                failed += 1
        else:
            logger.warning(f"[WeChat-Search] Could not resolve URL for: {title[:40]}")
            # Save search metadata even without full content
            _save_search_item(item, keyword)
            articles.append(item)
            failed += 1

        # Rate limit
        if i < len(results) - 1:
            time.sleep(delay)

    # Cleanup browser
    if context:
        await context.close()
    if browser:
        await browser.close()
    if pw:
        await pw.stop()

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
