# -*- coding: utf-8 -*-
"""
Sogou WeChat article search — search WeChat public account articles by keyword.

Uses Sogou's WeChat search (weixin.sogou.com) to discover articles,
then fetches each article's full content via browser and converts to Markdown.

Provides:
    - feedgrab mpweixin-so <keyword>

Data available from Sogou search results:
    - title, summary, author (公众号名), publish_time, thumbnail
    - NOT available: read count, likes, comments (WeChat internal only)

Sogou pagination: 10 results per page, up to ~10 pages (100 results).
"""

import math
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from loguru import logger
from typing import Dict, Any, List, Optional


# ---------------------------------------------------------------------------
# Sogou search (HTTP)
# ---------------------------------------------------------------------------

def _sogou_search(keyword: str, page: int = 1) -> List[Dict[str, Any]]:
    """Search WeChat articles via Sogou (one page, 10 results max).

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
        logger.warning(f"[mpweixin-so] Sogou request failed (page {page}): {e}")
        return []

    if "antispider" in html.lower() or "用户您好" in html:
        logger.warning("[mpweixin-so] Sogou triggered anti-bot verification")
        return []

    return _parse_sogou_results(html)


def _sogou_search_multi(keyword: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Fetch multiple pages from Sogou to reach max_results."""
    pages_needed = math.ceil(max_results / 10)
    all_results: List[Dict[str, Any]] = []

    for page_num in range(1, pages_needed + 1):
        if len(all_results) >= max_results:
            break
        logger.info(f"[mpweixin-so] Fetching search page {page_num}/{pages_needed}")
        page_results = _sogou_search(keyword, page=page_num)
        if not page_results:
            break
        all_results.extend(page_results)
        if page_num < pages_needed:
            time.sleep(1.5)  # Rate limit between pages

    return all_results[:max_results]


def _parse_sogou_results(html: str) -> List[Dict[str, Any]]:
    """Parse Sogou WeChat search results from HTML (single page)."""
    results = []

    li_blocks = re.findall(
        r'<li\s+id="sogou_vr_\d+_box_\d+"[^>]*>(.*?)</li>',
        html,
        re.DOTALL,
    )

    for block in li_blocks:
        item = {}

        # Title
        title_m = re.search(r'<h3>\s*<a[^>]*>(.*?)</a>\s*</h3>', block, re.DOTALL)
        if title_m:
            title = title_m.group(1)
            title = re.sub(r'<[^>]+>', '', title)
            title = re.sub(r'<!--.*?-->', '', title)
            title = title.replace("&ldquo;", "\u201c").replace("&rdquo;", "\u201d")
            title = title.replace("&mdash;", "\u2014").replace("&amp;", "&")
            item["title"] = title.strip()

        # Sogou redirect URL
        url_m = re.search(r'<h3>\s*<a[^>]*href="([^"]+)"', block)
        if url_m:
            sogou_url = url_m.group(1)
            if sogou_url.startswith("/"):
                sogou_url = f"https://weixin.sogou.com{sogou_url}"
            item["sogou_url"] = sogou_url

        # Summary
        summary_m = re.search(r'<p\s+class="txt-info"[^>]*>(.*?)</p>', block, re.DOTALL)
        if summary_m:
            summary = summary_m.group(1)
            summary = re.sub(r'<[^>]+>', '', summary)
            summary = re.sub(r'<!--.*?-->', '', summary)
            summary = summary.replace("&ldquo;", "\u201c").replace("&rdquo;", "\u201d")
            summary = summary.replace("&mdash;", "\u2014").replace("&amp;", "&")
            item["summary"] = summary.strip()

        # Author (公众号名)
        author_m = re.search(r'<span\s+class="all-time-y2">(.*?)</span>', block)
        if author_m:
            item["author"] = author_m.group(1).strip()

        # Publish timestamp
        time_m = re.search(r"timeConvert\('(\d+)'\)", block)
        if time_m:
            ts = int(time_m.group(1))
            item["timestamp"] = ts
            item["publish_date"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

        # Thumbnail
        thumb_m = re.search(r'<img\s+src="(//img01\.sogoucdn\.com[^"]+)"', block)
        if thumb_m:
            item["thumbnail"] = f"https:{thumb_m.group(1)}"

        if item.get("title") and item.get("sogou_url"):
            results.append(item)

    return results


# ---------------------------------------------------------------------------
# Sogou redirect resolution (browser)
# ---------------------------------------------------------------------------

async def _resolve_sogou_redirect(page, sogou_url: str) -> Optional[str]:
    """Follow Sogou redirect via a new tab in the existing browser context.

    The context already has Sogou cookies from visiting the search page.
    """
    try:
        new_page = await page.context.new_page()
        try:
            await new_page.goto(sogou_url, wait_until="domcontentloaded", timeout=20000)
            await new_page.wait_for_timeout(4000)
            final_url = new_page.url

            if "mp.weixin.qq.com" in final_url:
                logger.debug(f"[mpweixin-so] Redirect resolved: {final_url[:80]}")
                return final_url

            if "antispider" in final_url:
                logger.debug("[mpweixin-so] Hit antispider, waiting...")
                try:
                    await new_page.wait_for_url("**/mp.weixin.qq.com/**", timeout=10000)
                    final_url = new_page.url
                    if "mp.weixin.qq.com" in final_url:
                        return final_url
                except Exception:
                    pass

            content = await new_page.content()
            wx_m = re.search(r'(https?://mp\.weixin\.qq\.com/s[^\s"\'<>]+)', content)
            if wx_m:
                return wx_m.group(1)

            logger.debug(f"[mpweixin-so] Redirect landed on: {final_url[:80]}")
        finally:
            await new_page.close()
    except Exception as e:
        logger.debug(f"[mpweixin-so] Browser redirect failed: {e}")

    return None


# ---------------------------------------------------------------------------
# WeChat article HTML → Markdown conversion
# ---------------------------------------------------------------------------

_WECHAT_EXTRACT_JS = """
() => {
    const content = document.querySelector('#js_content');
    if (!content) return null;

    const title = (document.querySelector('#activity-name') || {}).innerText || '';
    const author = (document.querySelector('#js_name') || {}).innerText || '';

    // Extract rich content as simplified HTML
    const html = content.innerHTML;
    return { title: title.trim(), author: author.trim(), html: html };
}
"""


def _html_to_markdown(html: str) -> str:
    """Convert WeChat article HTML to Markdown.

    Handles: headings, paragraphs, bold, italic, images, links, lists, blockquotes.
    """
    if not html:
        return ""

    text = html

    # Remove script/style
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

    # Headings (h1-h4)
    for level in range(1, 5):
        tag = f'h{level}'
        prefix = '#' * level
        text = re.sub(
            rf'<{tag}[^>]*>(.*?)</{tag}>',
            lambda m, p=prefix: f'\n\n{p} {_strip_tags(m.group(1)).strip()}\n\n',
            text, flags=re.DOTALL | re.IGNORECASE,
        )

    # Blockquote
    text = re.sub(
        r'<blockquote[^>]*>(.*?)</blockquote>',
        lambda m: '\n' + '\n'.join(f'> {line}' for line in _strip_tags(m.group(1)).strip().split('\n') if line.strip()) + '\n',
        text, flags=re.DOTALL | re.IGNORECASE,
    )

    # Bold: <strong>, <b>
    text = re.sub(r'<(?:strong|b)[^>]*>(.*?)</(?:strong|b)>', r'**\1**', text, flags=re.DOTALL | re.IGNORECASE)
    # Italic: <em>, <i>
    text = re.sub(r'<(?:em|i)[^>]*>(.*?)</(?:em|i)>', r'*\1*', text, flags=re.DOTALL | re.IGNORECASE)

    # Images: data-src (lazy) or src
    def _img_replace(m):
        attrs = m.group(1)
        # WeChat uses data-src for lazy loading
        src_m = re.search(r'data-src="([^"]+)"', attrs)
        if not src_m:
            src_m = re.search(r'src="([^"]+)"', attrs)
        if not src_m:
            return ''
        src = src_m.group(1)
        # Skip tiny tracking pixels and SVG icons
        if 'wx_fmt=svg' in src or 'data:image' in src:
            return ''
        width_m = re.search(r'data-w="(\d+)"', attrs)
        if width_m and int(width_m.group(1)) < 20:
            return ''
        return f'\n\n![image]({src})\n\n'

    text = re.sub(r'<img([^>]*)/?>', _img_replace, text, flags=re.IGNORECASE)

    # Links
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
        lambda m: f'[{_strip_tags(m.group(2)).strip()}]({m.group(1)})' if m.group(1) and not m.group(1).startswith('javascript:') else _strip_tags(m.group(2)),
        text, flags=re.DOTALL | re.IGNORECASE,
    )

    # List items
    text = re.sub(r'<li[^>]*>(.*?)</li>', lambda m: f'\n- {_strip_tags(m.group(1)).strip()}', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'</?[ou]l[^>]*>', '', text, flags=re.IGNORECASE)

    # Horizontal rules
    text = re.sub(r'<hr[^>]*/?>','\n\n---\n\n', text, flags=re.IGNORECASE)

    # Line breaks
    text = re.sub(r'<br\s*/?>','\n', text, flags=re.IGNORECASE)

    # Paragraphs and sections → double newline
    text = re.sub(r'<(?:p|section|div)[^>]*>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</(?:p|section|div)>', '', text, flags=re.IGNORECASE)

    # Strip remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Decode HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&ldquo;', '\u201c')
    text = text.replace('&rdquo;', '\u201d')
    text = text.replace('&mdash;', '\u2014')
    text = text.replace('&ndash;', '\u2013')
    text = text.replace('&hellip;', '\u2026')

    # Clean up whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    return text


def _strip_tags(html: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r'<[^>]+>', '', html)


async def _fetch_wechat_article_via_browser(context, wx_url: str) -> Dict[str, Any]:
    """Fetch WeChat article content using the shared browser context.

    Extracts rich HTML from #js_content and converts to Markdown.
    Returns dict with: title, content, author, url.
    """
    new_page = await context.new_page()
    try:
        await new_page.goto(wx_url, wait_until="domcontentloaded", timeout=20000)
        await new_page.wait_for_timeout(2000)

        data = await new_page.evaluate(_WECHAT_EXTRACT_JS)
        if not data:
            # Fallback: grab raw text
            text = await new_page.evaluate("() => document.body.innerText")
            page_title = await new_page.title()
            return {
                "title": page_title or "",
                "content": (text or "").strip(),
                "author": "",
                "url": wx_url,
            }

        md_content = _html_to_markdown(data.get("html", ""))
        return {
            "title": data.get("title", ""),
            "content": md_content,
            "author": data.get("author", ""),
            "url": wx_url,
        }
    finally:
        await new_page.close()


# ---------------------------------------------------------------------------
# Save helpers
# ---------------------------------------------------------------------------

def _save_article(article_data: Dict[str, Any], item: Dict[str, Any], keyword: str):
    """Save a WeChat article as Markdown with full metadata."""
    from feedgrab.schema import from_wechat
    from feedgrab.utils.storage import save_to_markdown

    # Fallback title from search results when browser extraction failed
    if not article_data.get("title") and item.get("title"):
        article_data["title"] = item["title"]

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
    content.category = f"search_sogou/{keyword}"
    save_to_markdown(content)


def _save_search_item(item: Dict[str, Any], keyword: str):
    """Save search metadata only (when full content fetch fails)."""
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
    _save_article(article_data, item, keyword)
    logger.info(f"[mpweixin-so] Saved (metadata only): {item.get('title', '')[:50]}")


# ---------------------------------------------------------------------------
# Main search + fetch pipeline
# ---------------------------------------------------------------------------

async def search_wechat_articles(
    keyword: str,
    max_results: int = 10,
    fetch_content: bool = True,
    delay: float = 3.0,
) -> Dict[str, Any]:
    """Search and fetch WeChat articles via Sogou.

    Args:
        keyword: Search keyword
        max_results: Maximum number of results (up to 100, 10 per Sogou page)
        fetch_content: Whether to fetch full article content
        delay: Delay between fetching each article (seconds)

    Returns:
        Dict with: keyword, total, fetched, skipped, failed, articles
    """
    from feedgrab.utils.dedup import load_index, save_index, has_item, add_item, item_id_from_url

    logger.info(f"[mpweixin-so] Searching: {keyword} (max {max_results})")
    results = _sogou_search_multi(keyword, max_results=max_results)

    if not results:
        logger.warning("[mpweixin-so] No results found")
        return {
            "keyword": keyword,
            "total": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "articles": [],
        }

    logger.info(f"[mpweixin-so] Found {len(results)} results")

    if not fetch_content:
        return {
            "keyword": keyword,
            "total": len(results),
            "fetched": len(results),
            "skipped": 0,
            "failed": 0,
            "articles": results,
        }

    # Launch ONE shared browser for redirect resolution + article fetching
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

        # Visit search page to acquire Sogou cookies (required for redirect links)
        encoded = urllib.parse.quote(keyword)
        search_url = f"https://weixin.sogou.com/weixin?type=2&query={encoded}&ie=utf8&page=1"
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        logger.info("[mpweixin-so] Browser ready, Sogou cookies acquired")
    except ImportError:
        logger.warning("[mpweixin-so] Playwright not installed, will save metadata only")
    except Exception as e:
        logger.warning(f"[mpweixin-so] Browser launch failed: {e}, will save metadata only")

    index = load_index(platform="mpweixin")
    fetched = 0
    skipped = 0
    failed = 0
    articles = []

    for i, item in enumerate(results):
        title = item.get("title", "untitled")
        sogou_url = item.get("sogou_url", "")

        logger.info(f"[mpweixin-so] [{i+1}/{len(results)}] {title[:50]}")

        # Resolve Sogou redirect → real mp.weixin.qq.com URL
        wx_url = None
        if page:
            wx_url = await _resolve_sogou_redirect(page, sogou_url)

        if wx_url:
            item["wechat_url"] = wx_url

            item_id = item_id_from_url(wx_url)
            if has_item(item_id, index):
                logger.info(f"[mpweixin-so] Already fetched, skipping: {title[:40]}")
                skipped += 1
                continue

            # Fetch full article directly via our browser (rich Markdown)
            try:
                article_data = await _fetch_wechat_article_via_browser(context, wx_url)
                _save_article(article_data, item, keyword)

                add_item(item_id, wx_url, index)
                articles.append(item)
                fetched += 1
                logger.info(f"[mpweixin-so] Saved: {title[:50]}")
            except Exception as e:
                logger.warning(f"[mpweixin-so] Fetch failed: {title[:40]} — {e}")
                _save_search_item(item, keyword)
                articles.append(item)
                failed += 1
        else:
            logger.warning(f"[mpweixin-so] Could not resolve URL for: {title[:40]}")
            _save_search_item(item, keyword)
            articles.append(item)
            failed += 1

        if i < len(results) - 1:
            time.sleep(delay)

    # Cleanup
    if context:
        await context.close()
    if browser:
        await browser.close()
    if pw:
        await pw.stop()

    save_index(index, platform="mpweixin")

    return {
        "keyword": keyword,
        "total": len(results),
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "articles": articles,
    }
