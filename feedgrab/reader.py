# -*- coding: utf-8 -*-
"""
Universal Reader — routes any URL to the right fetcher.

The core dispatcher: give it a URL, get back structured content.
"""

import asyncio
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from loguru import logger
from typing import Dict, Any, Optional

from feedgrab.schema import (
    UnifiedContent, SourceType,
    from_bilibili, from_twitter, from_wechat,
    from_xiaohongshu, from_youtube, from_rss, from_telegram,
    from_github, from_feishu, from_kdocs,
)
from feedgrab.fetchers.jina import fetch_via_jina
from feedgrab.utils.url_validator import validate_url


class UniversalReader:
    """
    Routes URLs to platform-specific fetchers.
    Falls back to Jina Reader for unknown platforms.
    """

    def __init__(self):
        pass

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
            # List URLs: x.com/i/lists/{listId}
            if re.match(r'^/i/lists/\d+', path):
                return "twitter_list_tweets"
            # Single tweet: x.com/{user}/status/{id}
            if "/status/" in path:
                return "twitter"
            # Profile URL: x.com/{username} (no /status/ in path)
            # Exclude system paths: /i/, /home, /explore, /search, /settings, /notifications
            if re.match(r'^/[a-zA-Z0-9_]{1,15}(/.*)?$', path):
                first_segment = path.strip("/").split("/")[0]
                system_paths = {
                    "i", "home", "explore", "search", "settings",
                    "notifications", "messages", "compose", "login",
                    "signup", "tos", "privacy", "hashtag",
                }
                if first_segment.lower() not in system_paths:
                    return "twitter_user_tweets"
            return "twitter"
        if "youtube.com" in domain or "youtu.be" in domain:
            return "youtube"
        if "xiaohongshu.com" in domain or "xhslink.com" in domain:
            if "/user/profile/" in path:
                return "xhs_user_notes"
            if "/search_result" in path or "/search" in path:
                return "xhs_search"
            return "xhs"
        if "bilibili.com" in domain or "b23.tv" in domain:
            return "bilibili"
        if "xiaoyuzhoufm.com" in domain:
            return "podcast"
        if "podcasts.apple.com" in domain:
            return "podcast"
        if "t.me" in domain or "telegram.org" in domain:
            return "telegram"
        if "github.com" in domain:
            return "github"
        # KDocs (WPS 金山文档)
        if "kdocs.cn" in domain:
            return "kdocs"
        # Feishu / Lark
        from feedgrab.fetchers.feishu import is_feishu_url
        if is_feishu_url(url):
            return "feishu"
        if url.endswith(".xml") or "/rss" in url or "/feed" in url or "/atom" in url:
            return "rss"
        return "generic"

    @staticmethod
    def _normalize_wechat_url(url: str) -> str:
        """Strip tracking params from WeChat URLs.

        Keep only __biz, mid, idx, sn which uniquely identify an article.
        Short-link format (mp.weixin.qq.com/s/xxx) is returned unchanged.
        """
        parsed = urlparse(url)
        qs = parse_qs(parsed.query, keep_blank_values=False)
        essential = {k: v for k, v in qs.items()
                     if k in ("__biz", "mid", "idx", "sn")}
        if not essential:
            # Short link or no essential params — strip all tracking junk
            return urlunparse(parsed._replace(query="", fragment=""))
        clean_query = urlencode(essential, doseq=True)
        return urlunparse(parsed._replace(query=clean_query))

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

        # WeChat URL normalization: keep only essential params
        if platform == "wechat":
            url = self._normalize_wechat_url(url)

        logger.info(f"[{platform}] {url[:60]}...")

        # Bookmark batch mode: special flow, returns summary
        if platform == "twitter_bookmarks":
            return await self._read_bookmarks(url)

        # List tweets batch mode: special flow, returns summary
        if platform == "twitter_list_tweets":
            return await self._read_list_tweets(url)

        # User tweets batch mode: special flow, returns summary
        if platform == "twitter_user_tweets":
            return await self._read_user_tweets(url)

        # XHS user notes batch mode: special flow, returns summary
        if platform == "xhs_user_notes":
            return await self._read_user_notes(url)

        # XHS search notes batch mode: special flow, returns summary
        if platform == "xhs_search":
            return await self._read_search_notes(url)

        try:
            content = await self._fetch(platform, url)

            # Save to markdown output if configured
            from feedgrab.utils.storage import save_to_markdown
            if content.source_type == SourceType.TWITTER and not content.category:
                content.category = "status"
            saved_path = save_to_markdown(content)

            # Feishu: download images to {md_dir}/attachments/{subdir}/ after saving
            if (saved_path
                    and content.source_type == SourceType.FEISHU
                    and content.extra.get("images_info")):
                from feedgrab.config import feishu_download_images
                if feishu_download_images():
                    from feedgrab.fetchers.feishu import download_feishu_images
                    download_feishu_images(
                        saved_path,
                        content.extra["images_info"],
                        content.url,
                        img_subdir=content.extra.get("img_subdir", ""),
                    )

            # KDocs: download images to {md_dir}/attachments/{subdir}/ after saving
            if (saved_path
                    and content.source_type == SourceType.KDOCS
                    and content.extra.get("images_info")):
                from feedgrab.config import kdocs_download_images
                if kdocs_download_images():
                    from feedgrab.fetchers.kdocs import download_kdocs_images
                    download_kdocs_images(
                        saved_path,
                        content.extra["images_info"],
                        img_subdir=content.extra.get("img_subdir", ""),
                    )

            # Twitter: download media to attachments/{item_id}/
            if (saved_path
                    and content.source_type == SourceType.TWITTER
                    and (content.extra.get("images") or content.extra.get("videos"))):
                from feedgrab.config import x_download_media
                if x_download_media():
                    from feedgrab.utils.media import download_media
                    download_media(
                        saved_path,
                        content.extra.get("images", []),
                        content.extra.get("videos", []),
                        content.id,
                        platform="twitter",
                    )

            # XHS: download media to attachments/{item_id}/
            if (saved_path
                    and content.source_type == SourceType.XIAOHONGSHU
                    and content.extra.get("images")):
                from feedgrab.config import xhs_download_media
                if xhs_download_media():
                    from feedgrab.utils.media import download_media
                    download_media(
                        saved_path,
                        content.extra.get("images", []),
                        content.extra.get("videos", []),
                        content.id,
                        platform="xhs",
                    )

            # WeChat: download videos to attachments/{item_id}/
            if (saved_path
                    and content.source_type == SourceType.WECHAT
                    and (content.extra.get("videos") or content.extra.get("images"))):
                from feedgrab.config import mpweixin_download_media
                if mpweixin_download_media():
                    from feedgrab.utils.media import download_media
                    download_media(
                        saved_path,
                        content.extra.get("images", []),
                        content.extra.get("videos", []),
                        content.id,
                        platform="wechat",
                    )

            # Register in global dedup index (single fetch: always save, never skip)
            try:
                from feedgrab.utils.dedup import load_index, save_index, add_item
                _dedup_plat_map = {
                    SourceType.XIAOHONGSHU: "XHS",
                    SourceType.GITHUB: "GitHub",
                    SourceType.YOUTUBE: "YouTube",
                    SourceType.WECHAT: "mpweixin",
                    SourceType.BILIBILI: "Bilibili",
                    SourceType.FEISHU: "Feishu",
                }
                plat = _dedup_plat_map.get(content.source_type, "X")
                index = load_index(platform=plat)
                if content.id not in index:
                    add_item(content.id, content.url, index)
                    save_index(index, platform=plat)
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

        if platform == "github":
            from feedgrab.fetchers.github import fetch_github
            data = await fetch_github(url)
            return from_github(data)

        if platform == "feishu":
            from feedgrab.fetchers.feishu import fetch_feishu
            data = await fetch_feishu(url)
            return from_feishu(data)

        if platform == "kdocs":
            from feedgrab.fetchers.kdocs import fetch_kdocs
            data = await fetch_kdocs(url)
            return from_kdocs(data)

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

    async def _read_list_tweets(self, url: str) -> UnifiedContent:
        """Batch-fetch tweets from a Twitter List, stream-save each, return summary."""
        from feedgrab.config import x_list_tweets_enabled

        if not x_list_tweets_enabled():
            raise ValueError(
                "列表推文批量抓取未启用。请在 .env 中设置 X_LIST_TWEETS_ENABLED=true"
            )

        from feedgrab.fetchers.twitter_list_tweets import fetch_list_tweets
        from feedgrab.fetchers.twitter_cookies import load_twitter_cookies, has_required_cookies

        cookies = load_twitter_cookies()
        if not has_required_cookies(cookies):
            raise RuntimeError(
                "列表推文抓取需要 Twitter Cookie，请先运行: feedgrab login twitter"
            )

        result = await fetch_list_tweets(url, cookies)

        list_name = result.get("list_name", "")
        summary = (
            f"列表推文批量抓取完成 (列表: {list_name})\n"
            f"总数: {result['total']}, 成功: {result['fetched']}, "
            f"跳过: {result['skipped']}, 失败: {result['failed']}\n"
            f"批量记录: {result.get('list_path', '')}"
        )
        if result.get("summary_path"):
            summary += f"\n汇总表格: {result['summary_path']}"

        return UnifiedContent(
            source_type=SourceType.TWITTER,
            source_name="list_tweets",
            title=f"列表抓取 '{list_name}' {result['fetched']}/{result['total']}",
            content=summary,
            url=url,
        )

    async def _read_user_tweets(self, url: str) -> UnifiedContent:
        """Batch-fetch user tweets, stream-save each tweet, return summary."""
        from feedgrab.config import x_user_tweets_enabled

        if not x_user_tweets_enabled():
            raise ValueError(
                "账号推文批量抓取未启用。请在 .env 中设置 X_USER_TWEETS_ENABLED=true"
            )

        # Check if full API path is requested (server deployment)
        from feedgrab.config import x_api_provider
        if x_api_provider() == "api":
            from feedgrab.config import twitterapi_io_key
            if not twitterapi_io_key():
                raise ValueError(
                    "X_API_PROVIDER=api 但 TWITTERAPI_IO_KEY 未配置。\n"
                    "请在 .env 中设置 TWITTERAPI_IO_KEY=xxx\n"
                    "或改回 X_API_PROVIDER=graphql 使用免费 GraphQL 方案"
                )

            from feedgrab.fetchers.twitter_api_user_tweets import fetch_api_user_tweets
            result = await fetch_api_user_tweets(url)

            filtered_info = ""
            if result.get("filtered", 0) > 0:
                filtered_info = f", 互动过滤: {result['filtered']}"

            summary = (
                f"账号推文批量抓取完成 (via TwitterAPI.io)\n"
                f"总数: {result['total']}, 成功: {result['fetched']}, "
                f"跳过: {result['skipped']}, 失败: {result['failed']}"
                f"{filtered_info}\n"
                f"批量记录: {result.get('list_path', '')}"
            )

            return UnifiedContent(
                source_type=SourceType.TWITTER,
                source_name="user_tweets",
                title=f"账号抓取(API) {result['fetched']}/{result['total']}",
                content=summary,
                url=url,
            )

        # Default: GraphQL path (existing behavior, unchanged)
        from feedgrab.fetchers.twitter_user_tweets import fetch_user_tweets
        from feedgrab.fetchers.twitter_cookies import load_twitter_cookies, has_required_cookies

        cookies = load_twitter_cookies()
        if not has_required_cookies(cookies):
            raise RuntimeError(
                "账号推文抓取需要 Twitter Cookie，请先运行: feedgrab login twitter"
            )

        result = await fetch_user_tweets(url, cookies)

        summary = (
            f"账号推文批量抓取完成\n"
            f"总数: {result['total']}, 成功: {result['fetched']}, "
            f"跳过: {result['skipped']}, 失败: {result['failed']}\n"
            f"批量记录: {result.get('list_path', '')}"
        )

        return UnifiedContent(
            source_type=SourceType.TWITTER,
            source_name="user_tweets",
            title=f"账号抓取 {result['fetched']}/{result['total']}",
            content=summary,
            url=url,
        )

    async def _read_user_notes(self, url: str) -> UnifiedContent:
        """Batch-fetch user notes from XHS profile, stream-save each, return summary."""
        from feedgrab.config import xhs_user_notes_enabled

        if not xhs_user_notes_enabled():
            raise ValueError(
                "小红书作者笔记批量抓取未启用。请在 .env 中设置 XHS_USER_NOTES_ENABLED=true"
            )

        from feedgrab.fetchers.xhs_user_notes import fetch_user_notes

        result = await fetch_user_notes(url)

        summary = (
            f"小红书作者笔记批量抓取完成\n"
            f"总数: {result['total']}, 成功: {result['fetched']}, "
            f"跳过: {result['skipped']}, 失败: {result['failed']}\n"
            f"批量记录: {result.get('list_path', '')}"
        )

        return UnifiedContent(
            source_type=SourceType.XIAOHONGSHU,
            source_name="user_notes",
            title=f"作者笔记抓取 {result['fetched']}/{result['total']}",
            content=summary,
            url=url,
        )

    async def _read_search_notes(self, url: str) -> UnifiedContent:
        """Batch-fetch notes from XHS search results, stream-save each, return summary."""
        from feedgrab.config import xhs_search_enabled

        if not xhs_search_enabled():
            raise ValueError(
                "小红书搜索批量抓取未启用。请在 .env 中设置 XHS_SEARCH_ENABLED=true"
            )

        from feedgrab.fetchers.xhs_search_notes import fetch_search_notes

        result = await fetch_search_notes(url)

        keyword = result.get("keyword", "")
        summary = (
            f"小红书搜索批量抓取完成 (关键词: {keyword})\n"
            f"总数: {result['total']}, 成功: {result['fetched']}, "
            f"跳过: {result['skipped']}, 失败: {result['failed']}\n"
            f"批量记录: {result.get('list_path', '')}"
        )

        return UnifiedContent(
            source_type=SourceType.XIAOHONGSHU,
            source_name="search_notes",
            title=f"搜索抓取 '{keyword}' {result['fetched']}/{result['total']}",
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
