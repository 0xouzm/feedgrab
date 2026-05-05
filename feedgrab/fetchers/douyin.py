# -*- coding: utf-8 -*-
"""
Douyin fetcher (single-video MVP).

Strategy (single video):
    Tier 0  CDP — reuse a running Chrome window with douyin.com cookies and
            execute the detail-API fetch inside the page (browser auto-signs
            a_bogus / X-Bogus / msToken).
    Tier 1  Stealth Playwright launch + saved sessions/douyin.json.
    Tier 2  SSR — parse the __SSR_HYDRATED_DATA / RENDER_DATA inline JSON
            from the video page (no API call).
    Tier 3  Jina Reader markdown fallback (metadata only).

Short-link resolution:
    GET https://v.douyin.com/<short>/  →  302 → iesdouyin.com/share/video/<aweme_id>/
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

from loguru import logger

from feedgrab.config import (
    douyin_cdp_enabled,
    douyin_page_load_timeout,
    chrome_cdp_port,
    get_user_agent,
)
from feedgrab.utils import http_client


_SESSION_PATH = Path("sessions/douyin.json")
_AWEME_RE = re.compile(r"/(?:video|share/video|note)/(\d+)")


# =============================================================================
# URL helpers
# =============================================================================

def is_douyin_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(d in netloc for d in ("douyin.com", "iesdouyin.com"))


def parse_douyin_url(url: str) -> Tuple[str, str]:
    """Classify a Douyin URL.

    Returns (kind, ident):
      - "video" → ident is the aweme_id (numeric)
      - "short" → ident is the original short-link URL (needs redirect resolution)
      - "user"  → ident is the sec_uid (only used for warning)
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")

    if "v.douyin.com" in netloc:
        return "short", url

    m = _AWEME_RE.search(path)
    if m:
        return "video", m.group(1)

    if "/user/" in path:
        return "user", path.split("/user/", 1)[1].split("/")[0]

    raise ValueError(f"不支持的抖音链接: {url}")


def _resolve_short_link(url: str) -> Optional[str]:
    """Follow 30x to get the canonical iesdouyin.com URL containing aweme_id."""
    headers = {
        "User-Agent": get_user_agent(),
        "Accept": "text/html,application/xhtml+xml",
    }
    try:
        resp = http_client.get(url, headers=headers, timeout=10, allow_redirects=True)
        return str(resp.url)
    except Exception as exc:
        logger.warning(f"[Douyin] 短链解析失败 {url}: {exc}")
        return None


# =============================================================================
# Browser-based detail fetch (Tier 0 / 1)
# =============================================================================

async def _fetch_detail_via_browser(aweme_id: str) -> Optional[Dict[str, Any]]:
    """Run /aweme/v1/web/aweme/detail inside a real Chromium page.

    The browser takes care of a_bogus / X-Bogus / msToken signing.
    """
    from feedgrab.fetchers.browser import (
        get_async_playwright,
        stealth_launch,
        get_stealth_context_options,
        setup_resource_blocking,
        generate_referer,
    )

    pw = browser = context = page = None
    used_cdp = False
    video_url = f"https://www.douyin.com/video/{aweme_id}"

    try:
        try:
            from playwright.async_api import async_playwright as _pw_factory
        except ImportError:
            _pw_factory = None

        # --- Tier 0: CDP ---
        if douyin_cdp_enabled() and _pw_factory:
            try:
                pw = await _pw_factory().start()
                ws_url = f"ws://127.0.0.1:{chrome_cdp_port()}/devtools/browser"
                browser = await pw.chromium.connect_over_cdp(ws_url)
                for ctx in browser.contexts:
                    cookies = await ctx.cookies()
                    if any(c.get("domain", "").endswith("douyin.com") for c in cookies):
                        context = ctx
                        page = await ctx.new_page()
                        used_cdp = True
                        logger.info("[Douyin] CDP: 复用 Chrome douyin.com 会话")
                        break
                if not used_cdp:
                    await browser.close()
                    await pw.stop()
                    pw = browser = None
            except Exception as exc:
                logger.debug(f"[Douyin] CDP 连接失败: {exc}")
                if browser:
                    try: await browser.close()
                    except Exception: pass
                if pw:
                    try: await pw.stop()
                    except Exception: pass
                pw = browser = None

        # --- Tier 1: stealth launch ---
        if not page:
            async_playwright = get_async_playwright()
            pw = await async_playwright().start()
            browser = await stealth_launch(pw, headless=True)
            import os as _os
            storage_state = str(_SESSION_PATH) if _SESSION_PATH.exists() else None
            context = await browser.new_context(
                **get_stealth_context_options(storage_state=storage_state)
            )
            await setup_resource_blocking(context)
            page = await context.new_page()

        await page.goto(
            video_url,
            wait_until="domcontentloaded",
            timeout=douyin_page_load_timeout(),
            referer=generate_referer(video_url),
        )
        await page.wait_for_timeout(1500)

        # First try the detail API (browser will sign requests automatically)
        api_result = await page.evaluate(
            """async (id) => {
                try {
                    const url = `/aweme/v1/web/aweme/detail/?aweme_id=${id}`;
                    const r = await fetch(url, {
                        credentials: 'include',
                        headers: { 'Accept': 'application/json' },
                    });
                    const text = await r.text();
                    return { status: r.status, body: text };
                } catch (e) {
                    return { status: 0, body: String(e) };
                }
            }""",
            aweme_id,
        )

        if api_result and api_result.get("status") == 200:
            try:
                data = json.loads(api_result.get("body") or "")
                if data.get("aweme_detail"):
                    return data["aweme_detail"]
            except Exception:
                pass

        # Fall through to Tier 2 — parse SSR HTML
        ssr = await page.content()
        return _parse_ssr_render_data(ssr)

    except Exception as exc:
        logger.warning(f"[Douyin] browser fetch 异常: {exc}")
        return None
    finally:
        try:
            if page:
                await page.close()
        except Exception:
            pass
        if not used_cdp:
            try:
                if context:
                    await context.close()
            except Exception:
                pass
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass


# =============================================================================
# Tier 2 — SSR RENDER_DATA parsing
# =============================================================================

def _parse_ssr_render_data(html: str) -> Optional[Dict[str, Any]]:
    """Extract aweme detail from `<script id="RENDER_DATA">…</script>`."""
    if not html:
        return None
    m = re.search(
        r'<script[^>]*id="RENDER_DATA"[^>]*>([^<]+)</script>',
        html,
        re.IGNORECASE,
    )
    if not m:
        return None
    try:
        payload = json.loads(unquote(m.group(1)))
    except Exception:
        return None

    # Walk the tree for an "aweme" / "awemeDetail" key
    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("aweme", "awemeDetail", "videoInfoRes") and isinstance(v, dict):
                    if v.get("aweme_id") or v.get("awemeId"):
                        return v
                    if v.get("item_list") and v["item_list"]:
                        return v["item_list"][0]
                got = _walk(v)
                if got:
                    return got
        elif isinstance(obj, list):
            for item in obj:
                got = _walk(item)
                if got:
                    return got
        return None

    return _walk(payload)


# =============================================================================
# aweme_detail → result dict
# =============================================================================

def _format_unix_iso(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first_url(url_list: Any) -> str:
    if isinstance(url_list, list) and url_list:
        return url_list[0] or ""
    if isinstance(url_list, str):
        return url_list
    return ""


def _build_aweme_result(aweme: Dict[str, Any]) -> Dict[str, Any]:
    aweme_id = str(aweme.get("aweme_id") or aweme.get("awemeId") or "")
    desc = (aweme.get("desc") or aweme.get("description") or "").strip()

    author = aweme.get("author") or {}
    nickname = author.get("nickname") or ""
    sec_uid = author.get("sec_uid") or author.get("secUid") or ""

    statistics = aweme.get("statistics") or aweme.get("stats") or {}
    plays = statistics.get("play_count") or statistics.get("playCount", 0)
    likes = statistics.get("digg_count") or statistics.get("diggCount", 0)
    comments = statistics.get("comment_count") or statistics.get("commentCount", 0)
    shares = statistics.get("share_count") or statistics.get("shareCount", 0)

    video_info = aweme.get("video") or {}
    cover = _first_url((video_info.get("cover") or {}).get("url_list")) or _first_url((video_info.get("origin_cover") or {}).get("url_list"))
    play_url = _first_url((video_info.get("play_addr") or {}).get("url_list"))
    duration_ms = video_info.get("duration") or 0
    duration_seconds = int(duration_ms / 1000) if duration_ms else 0

    music = aweme.get("music") or {}
    music_title = music.get("title") or ""
    music_author = music.get("author") or ""

    text_extra = aweme.get("text_extra") or []
    topics: List[str] = []
    for ex in text_extra:
        if isinstance(ex, dict):
            t = ex.get("hashtag_name") or ex.get("hashtagName")
            if t and t not in topics:
                topics.append(t)

    create_time = aweme.get("create_time") or aweme.get("createTime") or 0

    body_parts: List[str] = []
    if cover:
        body_parts.append(f"![cover]({cover})")
        body_parts.append("")
    if desc:
        body_parts.append(desc)
        body_parts.append("")
    if play_url:
        body_parts.append(f"[▶ 视频]({play_url})")
        body_parts.append("")
    if music_title:
        ma = f" - {music_author}" if music_author else ""
        body_parts.append(f"🎵 **背景音乐：** {music_title}{ma}")
        body_parts.append("")

    content = "\n".join(body_parts).rstrip() + "\n" if body_parts else ""

    title_raw = desc.split("\n", 1)[0] if desc else f"douyin {aweme_id}"
    title = title_raw[:50] or f"douyin {aweme_id}"

    aweme_type = "image" if aweme.get("images") else "video"

    return {
        "aweme_id": aweme_id,
        "aweme_type": aweme_type,
        "url": f"https://www.douyin.com/video/{aweme_id}",
        "title": title,
        "content": content,
        "author": f"@{nickname}" if nickname else "douyin",
        "author_name": nickname,
        "author_sec_uid": sec_uid,
        "created_at": _format_unix_iso(create_time),
        "plays": plays,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "duration_seconds": duration_seconds,
        "music_title": music_title,
        "music_author": music_author,
        "cover_image": cover,
        "tags": topics,
    }


# =============================================================================
# Public API
# =============================================================================

async def fetch_douyin(url: str) -> Dict[str, Any]:
    """Fetch a single Douyin video metadata."""
    kind, ident = parse_douyin_url(url)

    if kind == "user":
        raise RuntimeError("抖音用户主页抓取尚未支持（v0.21+）")

    if kind == "short":
        resolved = _resolve_short_link(ident)
        if not resolved:
            raise RuntimeError(f"抖音短链解析失败: {ident}")
        m = _AWEME_RE.search(urlparse(resolved).path)
        if not m:
            raise RuntimeError(f"短链未指向视频: {resolved}")
        ident = m.group(1)

    aweme = await _fetch_detail_via_browser(ident)
    if not aweme:
        # Tier 3 — Jina fallback
        try:
            from feedgrab.fetchers.jina import fetch_via_jina
            jina = fetch_via_jina(f"https://www.douyin.com/video/{ident}")
            if jina and jina.get("content"):
                return {
                    "aweme_id": ident,
                    "aweme_type": "video",
                    "url": f"https://www.douyin.com/video/{ident}",
                    "title": jina.get("title", "Untitled"),
                    "content": jina["content"],
                    "author": "douyin",
                    "author_name": "",
                    "author_sec_uid": "",
                    "created_at": "",
                    "plays": 0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0,
                    "duration_seconds": 0,
                    "music_title": "",
                    "music_author": "",
                    "cover_image": "",
                    "tags": [],
                }
        except Exception as exc:
            logger.warning(f"[Douyin] Jina 兜底失败: {exc}")
        raise RuntimeError(f"抖音视频 {ident} 抓取全部 Tier 失败")

    return _build_aweme_result(aweme)
