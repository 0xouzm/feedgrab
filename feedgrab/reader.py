# -*- coding: utf-8 -*-
"""
Universal Reader — routes any URL to the right fetcher.

The core dispatcher: give it a URL, get back structured content.
"""

import asyncio
from urllib.parse import urlparse
from loguru import logger
from typing import Dict, Any, Optional

from feedgrab.schema import (
    UnifiedContent, UnifiedInbox, SourceType,
    from_bilibili, from_twitter, from_wechat,
    from_xiaohongshu, from_youtube, from_rss, from_telegram,
)
from feedgrab.fetchers.jina import fetch_via_jina
from feedgrab.utils.url_validator import validate_url


class UniversalReader:
    """
    Routes URLs to platform-specific fetchers.
    Falls back to Jina Reader for unknown platforms.
    """

    def __init__(self, inbox: Optional[UnifiedInbox] = None):
        self.inbox = inbox

    def _detect_platform(self, url: str) -> str:
        """Detect platform from URL."""
        domain = urlparse(url).netloc.lower()
        path = urlparse(url).path.lower()

        if "mp.weixin.qq.com" in domain:
            return "wechat"
        if "x.com" in domain or "twitter.com" in domain:
            # Bookmark URLs: x.com/i/bookmarks or x.com/i/bookmarks/{folderId}
            if "/i/bookmarks" in path:
                return "twitter_bookmarks"
            return "twitter"
        if "youtube.com" in domain or "youtu.be" in domain:
            return "youtube"
        if "xiaohongshu.com" in domain or "xhslink.com" in domain:
            return "xhs"
        if "bilibili.com" in domain or "b23.tv" in domain:
            return "bilibili"
        if "xiaoyuzhoufm.com" in domain:
            return "podcast"
        if "podcasts.apple.com" in domain:
            return "podcast"
        if "t.me" in domain or "telegram.org" in domain:
            return "telegram"
        if url.endswith(".xml") or "/rss" in url or "/feed" in url or "/atom" in url:
            return "rss"
        return "generic"

    async def read(self, url: str) -> UnifiedContent:
        """
        Fetch content from any URL and return as UnifiedContent.

        The main entry point — give it a URL, get back structured content.
        """
        # Ensure URL has scheme
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        # SSRF protection: block private IPs, metadata endpoints, DNS rebinding
        validate_url(url)

        platform = self._detect_platform(url)
        logger.info(f"[{platform}] {url[:60]}...")

        # Bookmark batch mode: special flow, returns summary
        if platform == "twitter_bookmarks":
            return await self._read_bookmarks(url)

        try:
            content = await self._fetch(platform, url)

            # Save to inbox if configured
            if self.inbox:
                if self.inbox.add(content):
                    self.inbox.save()
                    logger.info(f"Saved to inbox: {content.title[:50]}")

            # Save to markdown output if configured
            from feedgrab.utils.storage import save_to_markdown
            if content.source_type == SourceType.TWITTER and not content.category:
                content.category = "status"
            save_to_markdown(content)

            # Register in global dedup index (single fetch: always save, never skip)
            try:
                from feedgrab.utils.dedup import load_index, save_index, add_item
                index = load_index()
                if content.id not in index:
                    add_item(content.id, content.url, index)
                    save_index(index)
            except Exception:
                pass

            return content

        except Exception as e:
            logger.error(f"[{platform}] Failed: {e}")
            raise

    async def _fetch(self, platform: str, url: str) -> UnifiedContent:
        """Dispatch to platform-specific fetcher."""

        if platform == "bilibili":
            from feedgrab.fetchers.bilibili import fetch_bilibili
            data = await fetch_bilibili(url)
            return from_bilibili(data)

        if platform == "twitter":
            from feedgrab.fetchers.twitter import fetch_twitter
            data = await fetch_twitter(url)
            return from_twitter(data)

        if platform == "wechat":
            from feedgrab.fetchers.wechat import fetch_wechat
            data = await fetch_wechat(url)
            return from_wechat(data)

        if platform == "xhs":
            from feedgrab.fetchers.xhs import fetch_xhs
            data = await fetch_xhs(url)
            return from_xiaohongshu(data)

        if platform == "youtube":
            from feedgrab.fetchers.youtube import fetch_youtube
            data = await fetch_youtube(url)
            return from_youtube(data)

        if platform == "rss":
            from feedgrab.fetchers.rss import fetch_rss
            articles = await fetch_rss(url, limit=1)
            if articles:
                return from_rss(articles[0])
            raise ValueError(f"No articles found in RSS feed: {url}")

        if platform == "telegram":
            from feedgrab.fetchers.telegram import fetch_telegram
            # Extract channel username from t.me URL
            path = urlparse(url).path.strip("/").split("/")[0]
            channel = path if path else url
            messages = await fetch_telegram(channel, limit=1)
            if messages:
                return from_telegram(messages[0], channel, channel)
            raise ValueError(f"No messages from Telegram channel: {url}")

        # Fallback: Jina Reader for any unknown URL
        logger.info(f"Using Jina fallback for: {url}")
        data = fetch_via_jina(url)
        return UnifiedContent(
            source_type=SourceType.MANUAL,
            source_name=urlparse(url).netloc,
            title=data["title"],
            content=data["content"],
            url=url,
        )

    async def _read_bookmarks(self, url: str) -> UnifiedContent:
        """Batch-fetch bookmarks, stream-save each tweet, return summary."""
        from feedgrab.config import x_bookmarks_enabled

        if not x_bookmarks_enabled():
            raise ValueError(
                "书签批量抓取未启用。请在 .env 中设置 X_BOOKMARKS_ENABLED=true"
            )

        from feedgrab.fetchers.twitter_bookmarks import fetch_bookmarks
        from feedgrab.fetchers.twitter_cookies import load_twitter_cookies, has_required_cookies

        cookies = load_twitter_cookies()
        if not has_required_cookies(cookies):
            raise RuntimeError(
                "书签抓取需要 Twitter Cookie，请先运行: feedgrab login twitter"
            )

        result = await fetch_bookmarks(url, cookies)

        summary = (
            f"书签批量抓取完成\n"
            f"总数: {result['total']}, 成功: {result['fetched']}, "
            f"跳过: {result['skipped']}, 失败: {result['failed']}\n"
            f"URL 列表: {result.get('bookmark_list_path', '')}"
        )

        return UnifiedContent(
            source_type=SourceType.TWITTER,
            source_name="bookmarks",
            title=f"书签抓取 {result['fetched']}/{result['total']}",
            content=summary,
            url=url,
        )

    async def read_batch(self, urls: list[str]) -> list[UnifiedContent]:
        """Fetch multiple URLs concurrently."""
        tasks = [self.read(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        contents = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error(f"Batch failed for {url}: {result}")
            else:
                contents.append(result)

        return contents
