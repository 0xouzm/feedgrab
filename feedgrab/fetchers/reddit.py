# -*- coding: utf-8 -*-
"""
Reddit fetcher.

Strategy (single post):
    Tier 0  GET https://old.reddit.com/<path>.json   — primary, with feedgrab UA
    Tier 1  CDP via running Chrome (REDDIT_CDP_ENABLED=true)
    Tier 2  Stealth Playwright + saved session
    Tier 3  Jina Reader markdown fallback (no comments)

Strategy (subreddit listing):
    GET https://old.reddit.com/r/<sub>/<sort>.json?limit=N
    Each child is rendered through the single-post tier chain so comments
    are included in each saved Markdown file.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from feedgrab.config import (
    reddit_cdp_enabled,
    reddit_max_comments,
    reddit_user_agent,
    reddit_sub_delay,
)
from feedgrab.utils import http_client


_VALID_SORTS = {"hot", "new", "top", "best", "rising", "controversial"}


# =============================================================================
# URL helpers
# =============================================================================

def is_reddit_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www.") or netloc.startswith("old."):
        netloc = netloc.split(".", 1)[1]
    return netloc == "reddit.com" or netloc == "redd.it" or netloc.endswith(".reddit.com")


def parse_reddit_url(url: str) -> Tuple[str, Dict[str, str]]:
    """Classify a Reddit URL.

    Returns:
        (kind, info)
          kind = "post" | "subreddit" | "user"
          info dict carries fields such as id / subreddit / sort
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    # redd.it/<id> short link
    if netloc == "redd.it" or netloc.endswith(".redd.it"):
        if parts:
            return "post", {"id": parts[0]}
        raise ValueError(f"无效的 redd.it 短链: {url}")

    # /r/<sub>/comments/<id>/...
    if len(parts) >= 4 and parts[0] == "r" and parts[2] == "comments":
        return "post", {
            "id": parts[3],
            "subreddit": parts[1],
            "slug": parts[4] if len(parts) > 4 else "",
        }

    # /comments/<id>/<slug>?
    if len(parts) >= 2 and parts[0] == "comments":
        return "post", {"id": parts[1]}

    # /r/<sub> or /r/<sub>/<sort>
    if len(parts) >= 1 and parts[0] == "r":
        sub = parts[1] if len(parts) > 1 else ""
        sort = parts[2] if len(parts) > 2 and parts[2] in _VALID_SORTS else "hot"
        return "subreddit", {"subreddit": sub, "sort": sort}

    # /user/<name> or /u/<name>
    if parts and parts[0] in ("user", "u") and len(parts) >= 2:
        return "user", {"username": parts[1]}

    raise ValueError(f"不支持的 Reddit 链接格式: {url}")


def _canonicalize_post_url(info: Dict[str, str]) -> str:
    """Canonicalise to old.reddit.com .json endpoint."""
    pid = info.get("id", "")
    sub = info.get("subreddit", "")
    if sub:
        return f"https://old.reddit.com/r/{sub}/comments/{pid}/.json?limit=500&raw_json=1"
    # No sub known — use generic comments endpoint that follows redirects
    return f"https://old.reddit.com/comments/{pid}/.json?limit=500&raw_json=1"


# =============================================================================
# Tier 0 — direct .json with feedgrab UA
# =============================================================================

def _fetch_json_direct(url: str) -> Optional[Any]:
    headers = {
        "User-Agent": reddit_user_agent(),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = http_client.get(url, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"[Reddit] direct .json HTTP {resp.status_code}")
            return None
        try:
            return resp.json()
        except Exception:
            return None
    except Exception as exc:
        logger.warning(f"[Reddit] direct .json 异常: {exc}")
        return None


# =============================================================================
# Tier 1/2 — CDP / Browser fetch (page.evaluate fetch)
# =============================================================================

async def _fetch_json_via_browser(url: str) -> Optional[Any]:
    """Run fetch(<json url>) inside a real browser to bypass 403 IP blocks.

    Strategy:
      1. If REDDIT_CDP_ENABLED — connect to running Chrome and reuse a
         reddit.com cookie context.
      2. Otherwise stealth_launch a fresh patchright browser (with
         sessions/reddit.json storage_state if available).
      3. Navigate to https://old.reddit.com/ first, then page.evaluate fetch.
    """
    from feedgrab.config import reddit_page_load_timeout, chrome_cdp_port
    from feedgrab.fetchers.browser import (
        get_async_playwright,
        stealth_launch,
        get_stealth_context_options,
        setup_resource_blocking,
        generate_referer,
    )

    pw = browser = context = page = None
    used_cdp = False
    session_path = "sessions/reddit.json"

    try:
        try:
            from playwright.async_api import async_playwright as _pw_factory
        except ImportError:
            _pw_factory = None

        # --- Tier 1: CDP connect ---
        if reddit_cdp_enabled() and _pw_factory:
            try:
                pw = await _pw_factory().start()
                ws_url = f"ws://127.0.0.1:{chrome_cdp_port()}/devtools/browser"
                browser = await pw.chromium.connect_over_cdp(ws_url)
                for ctx in browser.contexts:
                    cookies = await ctx.cookies()
                    if any(c.get("domain", "").endswith("reddit.com") for c in cookies):
                        context = ctx
                        page = await ctx.new_page()
                        used_cdp = True
                        logger.info("[Reddit] CDP: 复用 Chrome reddit.com 会话")
                        break
                if not used_cdp:
                    await browser.close()
                    await pw.stop()
                    pw = browser = None
            except Exception as exc:
                logger.debug(f"[Reddit] CDP 连接失败: {exc}")
                if browser:
                    try:
                        await browser.close()
                    except Exception:
                        pass
                if pw:
                    try:
                        await pw.stop()
                    except Exception:
                        pass
                pw = browser = None

        # --- Tier 2: stealth launch ---
        if not page:
            async_playwright = get_async_playwright()
            pw = await async_playwright().start()
            browser = await stealth_launch(pw, headless=True)
            import os as _os
            storage_state = session_path if _os.path.exists(session_path) else None
            context = await browser.new_context(
                **get_stealth_context_options(storage_state=storage_state)
            )
            await setup_resource_blocking(context)
            page = await context.new_page()

        await page.goto(
            "https://old.reddit.com/",
            wait_until="domcontentloaded",
            timeout=reddit_page_load_timeout(),
            referer=generate_referer("https://old.reddit.com/"),
        )
        await page.wait_for_timeout(1000)

        result = await page.evaluate(
            """async (jsonUrl) => {
                try {
                    const r = await fetch(jsonUrl, {
                        credentials: 'include',
                        headers: { 'Accept': 'application/json' },
                    });
                    const text = await r.text();
                    return { status: r.status, body: text };
                } catch (e) {
                    return { status: 0, body: String(e) };
                }
            }""",
            url,
        )

        if not result:
            return None
        if result.get("status") != 200:
            logger.warning(f"[Reddit] browser fetch HTTP {result.get('status')}")
            return None
        body = result.get("body") or ""
        try:
            import json as _json
            return _json.loads(body)
        except Exception:
            return None

    except Exception as exc:
        logger.warning(f"[Reddit] browser fetch 异常: {exc}")
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
# Markdown rendering
# =============================================================================

def _format_unix_iso(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_unix_display(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _strip_html(html: str) -> str:
    """Lightweight HTML → Markdown for Reddit body_html / selftext_html."""
    if not html:
        return ""
    text = html
    import html as _html
    text = _html.unescape(text)
    text = re.sub(r"<p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<em>(.*?)</em>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<strong>(.*?)</strong>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<pre>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(
        r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Strip any remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _render_post(post: Dict[str, Any], comments: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Render a Reddit post + top-level comments into the result dict."""
    title = (post.get("title") or "").strip() or "Untitled"
    author = post.get("author", "[deleted]") or "[deleted]"
    sub = post.get("subreddit", "")
    score = post.get("score", 0)
    upvote_ratio = post.get("upvote_ratio", 0.0)
    num_comments = post.get("num_comments", 0)
    flair = post.get("link_flair_text", "") or ""
    is_self = bool(post.get("is_self", True))
    permalink = post.get("permalink", "")
    if permalink and not permalink.startswith("http"):
        permalink = f"https://www.reddit.com{permalink}"
    linked_url = ""
    if not is_self:
        linked_url = post.get("url_overridden_by_dest") or post.get("url", "") or ""
        if linked_url and linked_url.startswith(f"/r/{sub}"):
            linked_url = ""  # internal link only, not external
    selftext_html = post.get("selftext_html") or ""
    selftext = post.get("selftext") or ""
    body_md = _strip_html(selftext_html) if selftext_html else (selftext or "")

    ts_iso = _format_unix_iso(post.get("created_utc") or post.get("created") or 0)

    # Header line
    header_meta = [f"**作者：** u/{author}", f"**r/{sub}**", f"**得分：** {score}"]
    if num_comments:
        header_meta.append(f"**评论：** {num_comments}")
    if upvote_ratio:
        header_meta.append(f"**好评率：** {int(upvote_ratio * 100)}%")
    if flair:
        header_meta.append(f"**标签：** {flair}")
    header_line = "> " + " · ".join(header_meta)

    body_parts: List[str] = [header_line, ""]
    if body_md:
        body_parts.append(body_md)
        body_parts.append("")
    if linked_url:
        body_parts.append(f"[🔗 原始外链]({linked_url})")
        body_parts.append("")

    # Comments (top-level only)
    if comments:
        body_parts.append("---")
        body_parts.append("")
        body_parts.append(f"## 💬 评论（Top {len(comments)}，按得分排序）")
        body_parts.append("")
        for idx, c in enumerate(comments, 1):
            c_author = c.get("author", "[deleted]") or "[deleted]"
            c_score = c.get("score", 0)
            c_html = c.get("body_html") or ""
            c_body = _strip_html(c_html) if c_html else (c.get("body") or "")
            if not c_body:
                continue
            body_parts.append(f"### #{idx} u/{c_author} · {c_score} 分")
            body_parts.append("")
            body_parts.append(c_body)
            body_parts.append("")

    content = "\n".join(body_parts).rstrip() + "\n"

    return {
        "id": post.get("id", ""),
        "title": title,
        "content": content,
        "url": permalink or post.get("url", ""),
        "author": author,
        "author_name": author,
        "subreddit": sub,
        "flair": flair,
        "score": score,
        "upvote_ratio": upvote_ratio,
        "comment_count": num_comments,
        "is_self": is_self,
        "linked_url": linked_url,
        "created_at": ts_iso,
        "tags": [],
    }


def _extract_top_comments(json_payload: Any, max_n: int) -> List[Dict[str, Any]]:
    """Reddit comments JSON is a 2-element list: [post listing, comments listing]."""
    if not isinstance(json_payload, list) or len(json_payload) < 2:
        return []
    comments_listing = json_payload[1]
    children = (comments_listing.get("data") or {}).get("children") or []
    out: List[Dict[str, Any]] = []
    for child in children:
        if child.get("kind") != "t1":
            continue
        data = child.get("data") or {}
        if data.get("stickied"):
            continue
        out.append(data)
    out.sort(key=lambda c: c.get("score", 0), reverse=True)
    return out[:max_n]


def _extract_post_data(json_payload: Any) -> Optional[Dict[str, Any]]:
    """Get the top-level post data dict from a comments JSON payload."""
    if isinstance(json_payload, list) and json_payload:
        post_listing = json_payload[0]
        children = (post_listing.get("data") or {}).get("children") or []
        if children:
            return children[0].get("data") or {}
    elif isinstance(json_payload, dict):
        # Subreddit listing item
        if json_payload.get("kind") == "t3":
            return json_payload.get("data") or {}
    return None


# =============================================================================
# Public API
# =============================================================================

async def fetch_reddit(url: str) -> Dict[str, Any]:
    """Fetch a single Reddit post (with comments) through the tier chain."""
    kind, info = parse_reddit_url(url)

    if kind == "subreddit":
        raise RuntimeError(
            f"Reddit 子版块请使用：feedgrab reddit-sub {info.get('subreddit')} --sort {info.get('sort','hot')}"
        )
    if kind == "user":
        raise RuntimeError("Reddit 用户主页抓取尚未支持（v0.21+）")

    json_url = _canonicalize_post_url(info)

    # Tier 0 — direct
    payload = _fetch_json_direct(json_url)

    # Tier 1/2 — browser
    if not payload:
        logger.info("[Reddit] direct .json 失败，尝试 browser fetch...")
        payload = await _fetch_json_via_browser(json_url)

    # Reject error payloads
    if isinstance(payload, dict) and (payload.get("error") or payload.get("reason")):
        raise RuntimeError(
            f"Reddit 帖子无法访问: {payload.get('reason') or payload.get('error')}"
        )

    if not payload:
        # Tier 3 — Jina fallback (no comments)
        logger.info("[Reddit] browser 失败，使用 Jina 兜底...")
        try:
            from feedgrab.fetchers.jina import fetch_via_jina
            jina_data = fetch_via_jina(url)
            if jina_data and jina_data.get("content"):
                return {
                    "id": info.get("id", ""),
                    "title": jina_data.get("title", "Untitled"),
                    "content": jina_data["content"],
                    "url": url,
                    "author": "reddit",
                    "author_name": "reddit",
                    "subreddit": info.get("subreddit", ""),
                    "flair": "",
                    "score": 0,
                    "upvote_ratio": 0.0,
                    "comment_count": 0,
                    "is_self": True,
                    "linked_url": "",
                    "created_at": "",
                    "tags": [],
                }
        except Exception as exc:
            logger.warning(f"[Reddit] Jina 兜底失败: {exc}")
        raise RuntimeError(f"Reddit 抓取全部 Tier 失败: {url}")

    post = _extract_post_data(payload)
    if not post:
        raise RuntimeError(f"Reddit 响应不含帖子数据: {url}")

    comments = _extract_top_comments(payload, reddit_max_comments())
    return _render_post(post, comments)


async def fetch_reddit_subreddit(sub: str, sort: str = "hot", limit: int = 25) -> List[Dict[str, Any]]:
    """Fetch a subreddit listing and re-render each post with comments."""
    if sort not in _VALID_SORTS:
        raise ValueError(f"未知 sort: {sort}（可选 {sorted(_VALID_SORTS)}）")

    listing_url = f"https://old.reddit.com/r/{sub}/{sort}.json?limit={limit}&raw_json=1"
    logger.info(f"[Reddit] 子版块 listing: {listing_url}")

    payload = _fetch_json_direct(listing_url)
    if not payload:
        payload = await _fetch_json_via_browser(listing_url)
    if not payload:
        raise RuntimeError(f"Reddit 子版块 listing 抓取失败: r/{sub}")

    if isinstance(payload, dict) and (payload.get("error") or payload.get("reason")):
        raise RuntimeError(
            f"r/{sub} 不可访问: {payload.get('reason') or payload.get('error')}"
        )

    children = ((payload.get("data") or {}).get("children")) or []
    delay = reddit_sub_delay()
    results: List[Dict[str, Any]] = []
    for idx, child in enumerate(children, 1):
        if child.get("kind") != "t3":
            continue
        post = child.get("data") or {}
        permalink = post.get("permalink") or ""
        if not permalink:
            continue
        full_url = f"https://www.reddit.com{permalink}"
        try:
            data = await fetch_reddit(full_url)
            results.append(data)
        except Exception as exc:
            logger.warning(f"[Reddit] 第 {idx} 条 ({permalink}) 抓取失败: {exc}")
        if idx < len(children) and delay > 0:
            await asyncio.sleep(delay)
    return results
