# -*- coding: utf-8 -*-
"""
HackerNews fetcher.

Strategy:
    Single tier: Hacker News Firebase API v0 (https://hacker-news.firebaseio.com/v0)
    No authentication, no anti-bot — simplest fetcher in feedgrab.

Endpoints used:
    GET /v0/item/<id>.json       — single item (story/comment/ask/show/job/poll)
    GET /v0/user/<id>.json       — user profile
    GET /v0/topstories.json      — top stories (returns [id, id, ...])
    GET /v0/newstories.json      — new stories
    GET /v0/beststories.json     — best stories
    GET /v0/askstories.json      — Ask HN stories
    GET /v0/showstories.json     — Show HN stories
    GET /v0/jobstories.json      — job stories
    GET /v0/maxitem.json         — current largest item id
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from loguru import logger

from feedgrab.utils import http_client


_HACKERNEWS_DOMAINS = ("news.ycombinator.com",)
_API_BASE = "https://hacker-news.firebaseio.com/v0"

# Map CLI category names → API list endpoints
_LIST_ENDPOINTS = {
    "top": "topstories",
    "new": "newstories",
    "best": "beststories",
    "ask": "askstories",
    "show": "showstories",
    "jobs": "jobstories",
}


# =============================================================================
# URL helpers
# =============================================================================

def is_hackernews_url(url: str) -> bool:
    """Check whether *url* belongs to HackerNews."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return any(netloc == d or netloc.endswith("." + d) for d in _HACKERNEWS_DOMAINS)


def parse_hackernews_url(url: str) -> Tuple[str, str]:
    """Parse a HackerNews URL.

    Returns:
        (kind, id_or_name) — kind is one of:
          - "item"  → id_or_name is the numeric item id
          - "user"  → id_or_name is the username
          - "list"  → id_or_name is the list category ("top"/"new"/...)
        Raises ValueError if URL is not recognized.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    qs = parse_qs(parsed.query)

    # /item?id=<id>
    if path == "/item" and "id" in qs:
        item_id = qs["id"][0]
        if not item_id.isdigit():
            raise ValueError(f"无效的 HackerNews item id: {item_id}")
        return "item", item_id

    # /user?id=<username>
    if path == "/user" and "id" in qs:
        return "user", qs["id"][0]

    # /, /news, /newest, /best, /ask, /show, /jobs
    list_aliases = {
        "": "top",
        "/news": "top",
        "/newest": "new",
        "/best": "best",
        "/ask": "ask",
        "/show": "show",
        "/jobs": "jobs",
        "/front": "top",  # historical alias
    }
    if path in list_aliases:
        return "list", list_aliases[path]

    raise ValueError(f"不支持的 HackerNews 链接格式: {url}")


# =============================================================================
# Low-level API calls
# =============================================================================

def _api_get(endpoint: str, timeout: int = 15) -> Optional[Any]:
    """GET from Firebase API endpoint, return parsed JSON or None on error."""
    url = f"{_API_BASE}/{endpoint}.json"
    try:
        resp = http_client.get(url, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"[HN] GET {endpoint} → HTTP {resp.status_code}")
            return None
        return resp.json()
    except Exception as exc:
        logger.warning(f"[HN] GET {endpoint} 异常: {exc}")
        return None


def _fetch_item(item_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single item by id. Returns None on miss/dead/deleted."""
    data = _api_get(f"item/{item_id}")
    if not data or data.get("dead") or data.get("deleted"):
        return None
    return data


def _fetch_items_batch(item_ids: List[str], concurrency: int = 8) -> List[Dict[str, Any]]:
    """Fetch multiple items in parallel using a thread pool.

    Returns items in input order; missing/dead/deleted items are filtered out.
    """
    if not item_ids:
        return []

    import concurrent.futures
    results: List[Optional[Dict[str, Any]]] = [None] * len(item_ids)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_fetch_item, iid): idx for idx, iid in enumerate(item_ids)}
        for fut in concurrent.futures.as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:
                logger.warning(f"[HN] item {item_ids[idx]} 抓取失败: {exc}")

    return [r for r in results if r]


# =============================================================================
# Markdown rendering helpers
# =============================================================================

# Minimal HTML → Markdown for HN comment / story text.
# HN HTML is very limited: <p>, <i>, <a href>, <code>, <pre>, &amp; etc.
def _html_to_markdown(html: str) -> str:
    if not html:
        return ""
    text = html
    # Paragraph breaks
    text = re.sub(r"<p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "", text, flags=re.IGNORECASE)
    # Italic
    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    # Code span
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)
    # Pre
    text = re.sub(r"<pre>(.*?)</pre>", r"\n```\n\1\n```\n", text, flags=re.IGNORECASE | re.DOTALL)
    # Anchor: <a href="URL" rel="...">text</a>
    text = re.sub(
        r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Decode HTML entities
    import html as _html
    text = _html.unescape(text)
    # Collapse 3+ newlines → 2
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _format_unix_time(ts: int) -> str:
    """Convert HN Unix timestamp to ISO 8601 UTC.

    Use full ISO format so existing storage.py date parser can handle it
    (parse_twitter_date_local recognises ``YYYY-MM-DDTHH:MM:SSZ``).
    """
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_unix_time_display(ts: int) -> str:
    """Human-readable form for the in-body header line."""
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _render_comment(comment: Dict[str, Any], depth: int = 0, max_depth: int = 1) -> str:
    """Render a single comment as Markdown.

    For MVP (max_depth=1) we only render top-level comments.
    """
    if not comment or comment.get("dead") or comment.get("deleted"):
        return ""
    by = comment.get("by", "[deleted]")
    ts = _format_unix_time_display(comment.get("time", 0))
    body = _html_to_markdown(comment.get("text", ""))
    if not body:
        return ""
    indent = "" if depth == 0 else "> " * depth
    header_meta = [f"@{by}"]
    if ts:
        header_meta.append(ts)
    header = f"{indent}**{' · '.join(header_meta)}**"
    body_indented = body if depth == 0 else "\n".join(indent + line for line in body.split("\n"))
    return f"{header}\n\n{body_indented}"


# =============================================================================
# Public fetcher API
# =============================================================================

async def fetch_hackernews(url: str) -> Dict[str, Any]:
    """Fetch a HackerNews item or user URL.

    Returns a dict that ``schema.from_hackernews(...)`` can convert to
    ``UnifiedContent``. Raises RuntimeError for unsupported URL patterns
    or unrecoverable network failures.
    """
    kind, ident = parse_hackernews_url(url)

    if kind == "list":
        # /, /news, /newest 等列表入口 — 单 URL 模式不抓批量，提示用 hn 子命令
        raise RuntimeError(
            f"HackerNews 列表 URL 请使用子命令：feedgrab hn {ident} --limit N"
        )

    if kind == "user":
        raise RuntimeError(
            "HackerNews 用户主页抓取尚未支持（v0.21+）。"
            "请直接抓单条 item: https://news.ycombinator.com/item?id=<id>"
        )

    # kind == "item"
    item = _fetch_item(ident)
    if not item:
        raise RuntimeError(f"HackerNews item {ident} 不存在或已被删除")

    return _build_item_result(item)


def _build_item_result(item: Dict[str, Any]) -> Dict[str, Any]:
    """Build the result dict for a single item, including comments."""
    from feedgrab.config import hn_max_comments, hn_fetch_all_comments

    item_type = item.get("type", "story")
    item_id = str(item.get("id", ""))
    by = item.get("by", "")
    title = (item.get("title") or "").strip()
    text_html = item.get("text", "") or ""
    body_md = _html_to_markdown(text_html)
    score = item.get("score", 0)
    descendants = item.get("descendants", 0)
    ts_iso = _format_unix_time(item.get("time", 0))
    ts_display = _format_unix_time_display(item.get("time", 0))
    linked_url = item.get("url", "")

    # Render header line
    header_meta = [f"**作者：** @{by}", f"**得分：** {score}"]
    if descendants:
        header_meta.append(f"**评论：** {descendants}")
    if ts_display:
        header_meta.append(f"**时间：** {ts_display}")
    header_line = "> " + " · ".join(header_meta)

    body_parts: List[str] = [header_line, ""]
    if body_md:
        body_parts.append(body_md)
        body_parts.append("")
    if linked_url:
        body_parts.append(f"[🔗 原始外链]({linked_url})")
        body_parts.append("")

    # Top-level comments (MVP: only first level)
    kid_ids = [str(k) for k in (item.get("kids") or [])]
    max_comments = hn_max_comments()
    if kid_ids and max_comments > 0:
        truncated = kid_ids[:max_comments]
        comments = _fetch_items_batch(truncated, concurrency=8)
        rendered: List[str] = []
        for idx, c in enumerate(comments, 1):
            block = _render_comment(c, depth=0)
            if block:
                first_line = block.split("\n", 1)[0].strip().strip("*").strip()
                rendered.append(f"### #{idx} {first_line}")
                # Re-render without the inline header (we just printed it)
                lines = block.split("\n", 1)
                if len(lines) > 1:
                    rendered.append("")
                    rendered.append(lines[1].lstrip())
                rendered.append("")
        if rendered:
            body_parts.append("---")
            body_parts.append("")
            comment_count_label = (
                f"（Top {len(comments)}）"
                if not hn_fetch_all_comments()
                else f"（共 {descendants} 条）"
            )
            body_parts.append(f"## 💬 评论{comment_count_label}")
            body_parts.append("")
            body_parts.extend(rendered)

    content = "\n".join(body_parts).rstrip() + "\n"

    # Determine display title
    if not title:
        # For comment URLs (no title), use first 50 chars of body
        plain = re.sub(r"\s+", " ", body_md or "").strip()
        title = plain[:50] if plain else f"HN item {item_id}"

    # Map HN item type → category for display
    hn_type = item_type
    if title.startswith("Ask HN:"):
        hn_type = "ask"
    elif title.startswith("Show HN:"):
        hn_type = "show"

    return {
        "id": item_id,
        "type": hn_type,
        "title": title,
        "content": content,
        "url": f"https://news.ycombinator.com/item?id={item_id}",
        "author": by,
        "score": score,
        "comment_count": descendants,
        "linked_url": linked_url,
        "created_at": ts_iso,
        "tags": [],
    }


# =============================================================================
# List mode (hn top/new/best/...)
# =============================================================================

async def fetch_hackernews_list(category: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Fetch a list of stories from HackerNews.

    Args:
        category: One of "top"/"new"/"best"/"ask"/"show"/"jobs"
        limit: Max number of stories to return

    Returns:
        List of result dicts (same shape as fetch_hackernews single result),
        each containing item metadata + first-level comments.
    """
    if category not in _LIST_ENDPOINTS:
        raise ValueError(f"未知 HackerNews 列表类型: {category}（可选：{', '.join(_LIST_ENDPOINTS)}）")

    endpoint = _LIST_ENDPOINTS[category]
    logger.info(f"[HN] 抓取 {category} 列表，limit={limit}")
    ids = _api_get(endpoint)
    if not ids:
        raise RuntimeError(f"HackerNews 列表 {category} 抓取失败")

    truncated_ids = [str(i) for i in ids[:limit]]
    logger.info(f"[HN] 抓取 {len(truncated_ids)} 条 item 详情...")
    items = _fetch_items_batch(truncated_ids, concurrency=8)

    return [_build_item_result(item) for item in items]
