# -*- coding: utf-8 -*-
"""
Weibo fetcher.

Strategy:
    - All API calls go through https://m.weibo.cn (mobile-web JSON endpoints
      are simpler and more stable than the desktop GraphQL API).
    - When WEIBO_COOKIE / sessions/weibo.json is present, use it directly.
    - Otherwise (WEIBO_USE_VISITOR=true) attempt a passport visitor handshake
      to obtain a temporary tid cookie. The visitor flow is best-effort —
      Weibo gates new endpoints behind it occasionally, but most public
      endpoints work fine without it.

Endpoints used:
    GET /statuses/show?id=<mid>
    GET /api/container/getIndex?type=uid&value=<uid>&containerid=<cid>
    GET /detail/<mid>                  (SSR fallback — extract $render_data)
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from loguru import logger

from feedgrab.config import (
    get_user_agent,
    weibo_cookie,
    weibo_user_delay,
)
from feedgrab.utils import http_client


_M_BASE = "https://m.weibo.cn"
_SESSION_PATH = Path("sessions/weibo.json")


# =============================================================================
# URL helpers
# =============================================================================

def is_weibo_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(d in netloc for d in ("weibo.com", "weibo.cn"))


def parse_weibo_url(url: str) -> Tuple[str, str]:
    """Classify a Weibo URL.

    Returns:
        (kind, ident) where kind is one of:
          - "status"   → ident is the mid
          - "user"     → ident is the uid
        Raises ValueError otherwise.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]

    if "weibo.cn" in netloc or "weibo.com" in netloc:
        # /status/<mid>
        if parts and parts[0] in ("status", "detail") and len(parts) >= 2:
            return "status", parts[1]
        # /u/<uid>  or  /profile/<uid>
        if parts and parts[0] in ("u", "profile") and len(parts) >= 2:
            return "user", parts[1]
        # weibo.com/<uid>/<bid>  (desktop-style)
        if "weibo.com" in netloc and len(parts) >= 2:
            uid = parts[0]
            second = parts[1]
            if uid.isdigit() and second:
                # Status with bid (mblogid) — convert via lookup
                return "status_bid", second
        # weibo.com/u/<uid>
        if "weibo.com" in netloc and parts and parts[0] == "u" and len(parts) >= 2:
            return "user", parts[1]

    raise ValueError(f"不支持的微博链接: {url}")


def normalize_weibo_url(url: str) -> str:
    """Canonical form points at m.weibo.cn for consistent fetching."""
    try:
        kind, ident = parse_weibo_url(url)
    except ValueError:
        return url
    if kind == "status":
        return f"{_M_BASE}/status/{ident}"
    if kind == "status_bid":
        return f"{_M_BASE}/status/{ident}"  # Treat bid as opaque; show API will resolve
    if kind == "user":
        return f"{_M_BASE}/u/{ident}"
    return url


# =============================================================================
# Cookie / Session
# =============================================================================

def _load_cookie_header() -> str:
    """Build a Cookie header string from env / session file."""
    raw = weibo_cookie()
    if raw:
        return raw
    if _SESSION_PATH.exists():
        try:
            data = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
            cookies = data.get("cookies", [])
            pairs = [
                f"{c['name']}={c['value']}"
                for c in cookies
                if c.get("name") and c.get("value")
                and any(d in c.get("domain", "") for d in ("weibo.com", "weibo.cn"))
            ]
            if pairs:
                return "; ".join(pairs)
        except Exception as exc:
            logger.debug(f"[Weibo] 读取 sessions/weibo.json 失败: {exc}")
    return ""


def _build_headers(referer: str = "") -> Dict[str, str]:
    headers = {
        "User-Agent": get_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "MWeibo-Pwa": "1",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer or _M_BASE + "/",
    }
    cookie = _load_cookie_header()
    if cookie:
        headers["Cookie"] = cookie
    return headers


# =============================================================================
# HTML / text utilities
# =============================================================================

_TAG_RE = re.compile(r"<[^>]+>")
_HASHTAG_RE = re.compile(r"#([^#]+)#")
_AT_RE = re.compile(r"@([\w一-龥\-_]+)")


def _html_text_to_markdown(html: str) -> str:
    """Convert mblog `text` HTML to Markdown.

    Preserves topic / mention / link rendering but strips style spans.
    """
    if not html:
        return ""
    text = html
    import html as _html
    # Convert <a href="..."> with text including topic markers
    text = re.sub(
        r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        r"[\2](\1)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Convert <br>
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = _TAG_RE.sub("", text)
    text = _html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _parse_weibo_created(s: str) -> str:
    """Parse Weibo's 'Sun Mar 17 12:34:56 +0800 2024' style → ISO 8601."""
    if not s:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return s


def _extract_topics(text_raw: str) -> List[str]:
    if not text_raw:
        return []
    seen = []
    for m in _HASHTAG_RE.finditer(text_raw):
        topic = m.group(1).strip()
        if topic and topic not in seen:
            seen.append(topic)
    return seen


# =============================================================================
# API low-level
# =============================================================================

def _api_get(path: str, *, referer: str = "") -> Optional[Any]:
    url = f"{_M_BASE}{path}"
    try:
        resp = http_client.get(url, headers=_build_headers(referer=referer), timeout=15)
        if resp.status_code != 200:
            logger.warning(f"[Weibo] GET {path} HTTP {resp.status_code}")
            return None
        try:
            return resp.json()
        except Exception:
            return None
    except Exception as exc:
        logger.warning(f"[Weibo] GET {path} 异常: {exc}")
        return None


def _fetch_status(mid: str) -> Optional[Dict[str, Any]]:
    """Fetch a single status via /statuses/show."""
    data = _api_get(f"/statuses/show?id={mid}", referer=f"{_M_BASE}/detail/{mid}")
    if not data:
        return None
    if data.get("ok") == 1 and data.get("data"):
        return data["data"]
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def _fetch_user_index(uid: str) -> Optional[Dict[str, Any]]:
    """Fetch user profile container index (returns userInfo + tabsInfo)."""
    return _api_get(f"/api/container/getIndex?type=uid&value={uid}", referer=f"{_M_BASE}/u/{uid}")


def _fetch_user_timeline(uid: str, containerid: str, since_id: str = "") -> Optional[Dict[str, Any]]:
    qs = f"?containerid={containerid}&type=uid&value={uid}"
    if since_id:
        qs += f"&since_id={since_id}"
    return _api_get(f"/api/container/getIndex{qs}", referer=f"{_M_BASE}/u/{uid}")


# =============================================================================
# mblog → result dict
# =============================================================================

def _build_status_result(mblog: Dict[str, Any]) -> Dict[str, Any]:
    user = mblog.get("user") or {}
    screen_name = user.get("screen_name", "") or ""
    uid = str(user.get("id", "") or "")

    text_html = mblog.get("text") or ""
    text_md = _html_text_to_markdown(text_html)
    text_raw = mblog.get("text_raw") or text_md

    pic_urls: List[str] = []
    pic_infos = mblog.get("pic_infos") or {}
    pic_ids = mblog.get("pic_ids") or []
    if pic_infos:
        for pid in pic_ids:
            info = pic_infos.get(pid)
            if not info:
                continue
            large = (info.get("largest") or {}).get("url") or info.get("large", {}).get("url")
            if large:
                pic_urls.append(large)
    elif mblog.get("pics"):
        for pic in mblog.get("pics") or []:
            url = (pic.get("large") or {}).get("url") or pic.get("url")
            if url:
                pic_urls.append(url)

    video_url = ""
    page_info = mblog.get("page_info") or {}
    media_info = (page_info.get("media_info") or {}) if isinstance(page_info, dict) else {}
    if media_info.get("stream_url"):
        video_url = media_info["stream_url"]

    body_parts = [text_md] if text_md else []
    if pic_urls:
        body_parts.append("")
        for u in pic_urls:
            body_parts.append(f"![image]({u})")
    if video_url:
        body_parts.append("")
        body_parts.append(f"[▶ 视频]({video_url})")

    # Retweeted status
    retweeted = mblog.get("retweeted_status")
    if retweeted:
        rt_user = retweeted.get("user") or {}
        rt_name = rt_user.get("screen_name", "")
        rt_mid = retweeted.get("id") or retweeted.get("mid", "")
        rt_html = retweeted.get("text") or ""
        rt_md = _html_text_to_markdown(rt_html)
        body_parts.append("")
        body_parts.append(f"> **转发自：** @{rt_name}")
        if rt_mid:
            body_parts.append(f"> {_M_BASE}/status/{rt_mid}")
        body_parts.append(">")
        for line in (rt_md or "").splitlines() or [""]:
            body_parts.append(f"> {line}")

    content = "\n".join(body_parts).rstrip() + "\n" if body_parts else ""

    mid = str(mblog.get("id") or mblog.get("mid") or "")
    bid = mblog.get("bid", "") or mblog.get("mblogid", "")
    # Title: prefer text_raw; otherwise strip tags from HTML to a plain string
    # (avoid text_md which still carries Markdown link syntax for # / @).
    raw_for_title = mblog.get("text_raw") or ""
    if not raw_for_title and text_html:
        import html as _html
        raw_for_title = _html.unescape(_TAG_RE.sub("", text_html))
    title_raw = (raw_for_title or "").strip().split("\n", 1)[0]
    title = title_raw[:50] or f"weibo {mid}"

    topics = _extract_topics(raw_for_title)
    is_repost = "mblog_type" in mblog
    mblog_type = "repost" if retweeted else "status"

    return {
        "mid": mid,
        "bid": bid,
        "uid": uid,
        "url": f"{_M_BASE}/status/{mid}",
        "title": title,
        "content": content,
        "author": f"@{screen_name}" if screen_name else "weibo",
        "author_name": screen_name,
        "created_at": _parse_weibo_created(mblog.get("created_at", "")),
        "likes": mblog.get("attitudes_count", 0),
        "comments": mblog.get("comments_count", 0),
        "reposts": mblog.get("reposts_count", 0),
        "source_app": mblog.get("source", "") or "",
        "mblog_type": mblog_type,
        "tags": topics,
    }


# =============================================================================
# Public API
# =============================================================================

async def fetch_weibo(url: str) -> Dict[str, Any]:
    """Fetch a single Weibo status."""
    canonical = normalize_weibo_url(url)
    kind, ident = parse_weibo_url(canonical)

    if kind == "user":
        raise RuntimeError(
            f"微博用户主页请使用：feedgrab weibo-user {ident} --limit N"
        )

    if kind == "status_bid":
        # Resolve bid via the /detail page redirect — just hit show with bid
        # (Weibo accepts both numeric mid and bid here)
        mblog = _fetch_status(ident)
        if not mblog:
            raise RuntimeError(f"微博 bid={ident} 抓取失败")
        return _build_status_result(mblog)

    # kind == "status"
    mblog = _fetch_status(ident)
    if not mblog:
        # SSR fallback — fetch detail page and parse $render_data
        mblog = _fetch_status_via_ssr(ident)
    if not mblog:
        raise RuntimeError(f"微博 {ident} 抓取失败（可能需要 SUB Cookie）")
    return _build_status_result(mblog)


def _fetch_status_via_ssr(mid: str) -> Optional[Dict[str, Any]]:
    """Tier 2 — load /detail/<mid> SSR HTML and extract $render_data."""
    url = f"{_M_BASE}/detail/{mid}"
    try:
        resp = http_client.get(url, headers=_build_headers(referer=url), timeout=15)
        if resp.status_code != 200:
            return None
        html = resp.text
    except Exception:
        return None
    m = re.search(r"var\s+\$render_data\s*=\s*(\[.*?\])\[0\]\s*\|\|", html, re.DOTALL)
    if not m:
        return None
    try:
        payload = json.loads(m.group(1))
        if isinstance(payload, list) and payload:
            status = payload[0].get("status")
            if status:
                return status
    except Exception:
        return None
    return None


async def fetch_weibo_user(uid: str, limit: int = 20) -> Tuple[List[Dict[str, Any]], str]:
    """Fetch a user's recent statuses via container/getIndex."""
    profile = _fetch_user_index(uid)
    screen_name = ""
    containerid = ""
    if profile:
        user_info = (profile.get("data") or {}).get("userInfo") or {}
        screen_name = user_info.get("screen_name", "")
        tabs = (profile.get("data") or {}).get("tabsInfo", {}).get("tabs", [])
        for tab in tabs:
            if tab.get("tabKey") in ("weibo", "home"):
                containerid = tab.get("containerid", "")
                break
        if not containerid:
            containerid = f"107603{uid}"
    else:
        containerid = f"107603{uid}"

    results: List[Dict[str, Any]] = []
    since_id = ""
    delay = weibo_user_delay()
    while len(results) < limit:
        timeline = _fetch_user_timeline(uid, containerid, since_id=since_id)
        if not timeline:
            break
        cards = (timeline.get("data") or {}).get("cards") or []
        new_count = 0
        for card in cards:
            mblog = card.get("mblog")
            if not mblog:
                continue
            try:
                results.append(_build_status_result(mblog))
                new_count += 1
                if len(results) >= limit:
                    break
            except Exception as exc:
                logger.warning(f"[Weibo] 渲染 mblog 失败: {exc}")
        if new_count == 0:
            break
        since_id = (timeline.get("data") or {}).get("cardlistInfo", {}).get("since_id", "")
        if not since_id:
            break
        if delay > 0:
            await asyncio.sleep(delay)
    return results[:limit], screen_name
