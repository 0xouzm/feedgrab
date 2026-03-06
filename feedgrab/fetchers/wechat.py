# -*- coding: utf-8 -*-
"""
WeChat article fetcher — two-tier fallback:

1. Jina Reader (fast, no deps)
2. Stealth browser with WeChat-specific extraction (rich HTML + full metadata)
"""

from loguru import logger
from typing import Dict, Any


async def fetch_wechat(url: str) -> Dict[str, Any]:
    """
    Fetch a WeChat public account article with fallback.

    Args:
        url: mp.weixin.qq.com article URL

    Returns:
        Dict with: title, content, author, url, platform,
                   cover_image, publish_date, summary, tags, original_url
    """
    # Tier 1: Jina Reader
    try:
        logger.info(f"[WeChat] Tier 1 — Jina: {url}")
        from feedgrab.fetchers.jina import fetch_via_jina

        data = fetch_via_jina(url)
        if data.get("content"):
            return {
                "title": data["title"],
                "content": data["content"],
                "author": data.get("author", ""),
                "url": url,
                "platform": "wechat",
                "cover_image": "",
                "publish_date": "",
                "summary": "",
                "tags": [],
                "original_url": "",
            }
        logger.warning("[WeChat] Jina returned empty content, falling back to browser")
    except Exception as e:
        logger.warning(f"[WeChat] Jina failed ({e}), falling back to browser")

    # Tier 2: Stealth browser with WeChat-specific extraction
    try:
        logger.info(f"[WeChat] Tier 2 — Browser (WeChat extract): {url}")
        from feedgrab.fetchers.browser import (
            get_async_playwright, stealth_launch, get_stealth_context_options,
            setup_resource_blocking, generate_referer,
            evaluate_wechat_article,
        )
        from feedgrab.fetchers.wechat_search import _html_to_markdown

        async_pw = get_async_playwright()
        async with async_pw() as p:
            browser = await stealth_launch(p, headless=True)
            context = await browser.new_context(**get_stealth_context_options())
            page = await context.new_page()
            await setup_resource_blocking(page)

            try:
                await page.goto(
                    url, wait_until="domcontentloaded", timeout=30_000,
                    referer=generate_referer(url),
                )
                result = await evaluate_wechat_article(
                    page, md_converter=_html_to_markdown,
                )
                logger.info(f"[WeChat] Browser OK: {result['title'][:60]}")
                return result
            finally:
                await context.close()
                await browser.close()

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"[WeChat] Browser fetch also failed: {e}")
        raise RuntimeError(
            f"All WeChat fetch methods failed.\n"
            f"   Last error: {e}"
        )
