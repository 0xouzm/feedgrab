# -*- coding: utf-8 -*-
"""
Playwright browser fetcher — headless Chromium fallback for anti-scraping sites.

Used when Jina Reader fails (403/451/timeout). Supports persistent login
sessions via Playwright's storage_state for platforms requiring authentication.

Install: pip install "feedgrab[browser]" && playwright install chromium
"""

from loguru import logger
from pathlib import Path

from feedgrab.config import get_session_dir

SESSION_DIR = get_session_dir()
TIMEOUT_MS = 30_000


async def fetch_via_browser(url: str, storage_state: str = None) -> dict:
    """
    Fetch a URL using headless Chromium via Playwright.

    Args:
        url: Target URL to fetch.
        storage_state: Path to a Playwright storage state JSON file (cookies/localStorage).
                       If provided, the browser context will load this session.

    Returns:
        dict with keys: title, content, url, author
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            '  pip install "feedgrab[browser]"\n'
            "  playwright install chromium"
        )

    logger.info(f"Browser fetch: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context_kwargs = {}
        if storage_state and Path(storage_state).exists():
            context_kwargs["storage_state"] = storage_state
            logger.info(f"Using session: {storage_state}")

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            **context_kwargs,
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            is_xhs = "xiaohongshu.com" in url or "xhslink.com" in url

            if is_xhs:
                # XHS SPA needs the note container to render
                try:
                    await page.wait_for_selector("#noteContainer", timeout=8000)
                except Exception:
                    logger.warning("[XHS] #noteContainer not found within 8s, proceeding anyway")
                await page.wait_for_timeout(1000)

                data = await page.evaluate("""() => {
                    const title = document.querySelector('#detail-title');
                    const desc = document.querySelector('#detail-desc');
                    const author = document.querySelector('.author-wrapper .username')
                        || document.querySelector('.author-container .username');

                    // 正文（不含标签文本，标签单独提取）
                    let content = '';
                    if (desc) {
                        const clone = desc.cloneNode(true);
                        clone.querySelectorAll('a.tag').forEach(a => a.remove());
                        content = clone.innerText.trim();
                    }

                    // 话题标签
                    const tags = desc
                        ? Array.from(desc.querySelectorAll('a.tag'))
                            .map(a => a.innerText.trim().replace(/^#+/, ''))
                            .filter(Boolean)
                        : [];

                    // 笔记图片：只取非 duplicate 的 slide，按 data-index 排序
                    const images = Array.from(
                        document.querySelectorAll('.swiper-wrapper .swiper-slide:not(.swiper-slide-duplicate)')
                    ).sort((a, b) =>
                        (parseInt(a.dataset.swiperSlideIndex) || 0) -
                        (parseInt(b.dataset.swiperSlideIndex) || 0)
                    ).map(slide => {
                        const img = slide.querySelector('img');
                        return img ? (img.src || '') : '';
                    }).filter(src => src.startsWith('http'));

                    // 互动数据：点赞、收藏、评论
                    const counts = Array.from(
                        document.querySelectorAll('.engage-bar .count')
                    ).map(el => el.innerText.trim());

                    // 日期 + IP属地（如 "02-18 福建" 或 "编辑于 2025-08-16"）
                    const dateEl = document.querySelector('.bottom-container .date');

                    // 作者主页链接（去掉追踪参数）
                    let authorUrl = '';
                    const authorLink = document.querySelector('.author-wrapper a[href*="/user/profile/"]');
                    if (authorLink) {
                        try {
                            const u = new URL(authorLink.href);
                            authorUrl = u.origin + u.pathname;
                        } catch(e) {}
                    }

                    return {
                        title: title ? title.innerText.trim() : '',
                        content: content,
                        author: author ? author.innerText.trim().split('\\n')[0] : '',
                        authorUrl: authorUrl,
                        tags: tags,
                        images: images,
                        likes: parseInt(counts[0]) || 0,
                        collects: parseInt(counts[1]) || 0,
                        comments: parseInt(counts[2]) || 0,
                        date: dateEl ? dateEl.innerText.trim() : '',
                    };
                }""")

                result = {
                    "title": (data["title"] or "").strip()[:200],
                    "content": (data["content"] or "").strip(),
                    "url": page.url,
                    "author": (data["author"] or "").strip(),
                    "author_url": data.get("authorUrl", ""),
                    "tags": data.get("tags", []),
                    "images": data.get("images", []),
                    "likes": data.get("likes", 0),
                    "collects": data.get("collects", 0),
                    "comments": data.get("comments", 0),
                    "date": data.get("date", ""),
                }
            else:
                # Generic fallback for non-XHS pages
                await page.wait_for_timeout(2000)

                title = await page.title()
                content = await page.evaluate("""() => {
                    const el = document.querySelector('article')
                        || document.querySelector('main')
                        || document.querySelector('.content')
                        || document.body;
                    return el ? el.innerText : '';
                }""")

                result = {
                    "title": (title or "").strip()[:200],
                    "content": (content or "").strip(),
                    "url": page.url,
                    "author": "",
                }

            logger.info(f"Browser fetch OK: {result['title'][:60]}")
            return result

        finally:
            await context.close()
            await browser.close()


def get_session_path(platform: str) -> str:
    """Get the session file path for a platform."""
    return str(SESSION_DIR / f"{platform}.json")
