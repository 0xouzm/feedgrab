# -*- coding: utf-8 -*-
"""
Zsxq (知识星球) fetcher.

Strategy:
    Tier 0: HTTP GET with sessions/zsxq.json cookies + browser-like headers
            ├─ articles.zsxq.com/id_<hashid>.html → BeautifulSoup .ql-editor
            └─ api.zsxq.com/v2/topics/<topic_id>/info → JSON
    Tier 1: CDP reuse running Chrome (.zsxq.com cookie context)
    Tier 2: Stealth Playwright launch + sessions/zsxq.json
    Tier 3: Jina Reader (kept as last-resort posture only — Zsxq is auth-walled)

Short-link resolution:
    t.zsxq.com/<code> → 302 → wx.zsxq.com/group/<gid>/topic/<tid>
    Resolved before parse_zsxq_url() so all downstream paths see the canonical URL.

Why both HTML and JSON paths:
    - articles.zsxq.com SSRs the article body in `.ql-editor` (free for logged-in
      users of the host star), no public API endpoint exists for article hashid.
    - wx.zsxq.com/group/<gid>/topic/<tid> is a SPA shell — the data is fetched
      via api.zsxq.com/v2/topics/<topic_id>/info, which returns JSON we can
      consume directly.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from loguru import logger

from feedgrab.fetchers.browser import (
    generate_referer,
    get_async_playwright,
    get_stealth_context_options,
    setup_resource_blocking,
    stealth_launch,
)
from feedgrab.fetchers.jina import fetch_via_jina
from feedgrab.utils import http_client


_ZSXQ_DOMAIN_SUFFIX = ".zsxq.com"
_API_BASE = "https://api.zsxq.com/v2"
_ARTICLE_PATH_RE = re.compile(r"^/id_([A-Za-z0-9]+)\.html?$", re.IGNORECASE)
_TOPIC_PATH_RE = re.compile(r"/topic(?:_detail)?/(\d+)")
_GROUP_TOPIC_PATH_RE = re.compile(r"/group/(\d+)/topic/(\d+)")
_NOT_FOUND_HINTS = (
    "话题不存在",
    "文章不存在",
    "已被删除",
    "topic not found",
)
_LOGIN_REQUIRED_HINTS = (
    "请先登录",
    "登录已过期",
    "未加入",
    "无权访问",
    "您未加入该星球",
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def is_zsxq_url(url: str) -> bool:
    """Return True for any zsxq.com / t.zsxq.com URL."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc == "zsxq.com" or netloc.endswith(_ZSXQ_DOMAIN_SUFFIX)


def _resolve_zsxq_short_url(url: str) -> str:
    """Resolve t.zsxq.com/<code> short-link via 302 to canonical URL."""
    parsed = urlparse(url)
    if parsed.netloc.lower() != "t.zsxq.com":
        return url

    headers = _zsxq_default_headers(referer="https://wx.zsxq.com/")
    try:
        # follow_redirects=False so we can capture the Location header verbatim.
        resp = http_client.get(url, headers=headers, allow_redirects=False, timeout=10)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location") or resp.headers.get("location")
            if location:
                logger.info(f"[zsxq] short-link resolved: {url} → {location}")
                return location
    except requests.RequestException as e:
        logger.debug(f"[zsxq] short-link no-redirect probe failed: {e}")

    # Fallback: follow redirects and use final URL
    try:
        resp = http_client.get(url, headers=headers, allow_redirects=True, timeout=15)
        final = getattr(resp, "url", None) or url
        if final != url:
            logger.info(f"[zsxq] short-link followed: {url} → {final}")
        return str(final)
    except requests.RequestException as e:
        logger.warning(f"[zsxq] short-link follow failed: {e}")
        return url


def parse_zsxq_url(url: str) -> Tuple[str, str, str]:
    """Parse Zsxq URL → (kind, primary_id, group_id).

    kind: "article" | "topic"
    primary_id: article hashid (e.g. "sz9kew31q6we") | numeric topic_id
    group_id: numeric group id when discoverable, otherwise empty string

    Raises ValueError for unknown URL shapes.
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower().lstrip("www.")
    path = parsed.path or ""

    # articles.zsxq.com/id_<hashid>.html
    if netloc == "articles.zsxq.com":
        m = _ARTICLE_PATH_RE.match(path.rstrip("/"))
        if m:
            return "article", m.group(1), ""

    # wx.zsxq.com / dweb2 (SPA path) / dweb (hash-routed)
    # Try /group/<gid>/topic/<tid> first to capture group_id when present.
    if netloc.endswith(_ZSXQ_DOMAIN_SUFFIX) or netloc == "zsxq.com":
        m = _GROUP_TOPIC_PATH_RE.search(path)
        if m:
            return "topic", m.group(2), m.group(1)
        m = _TOPIC_PATH_RE.search(path)
        if m:
            return "topic", m.group(1), ""
        # Hash-routed fallback: /dweb/#/group/<gid>/topic/<tid>
        if parsed.fragment:
            m = _GROUP_TOPIC_PATH_RE.search(parsed.fragment)
            if m:
                return "topic", m.group(2), m.group(1)
            m = _TOPIC_PATH_RE.search(parsed.fragment)
            if m:
                return "topic", m.group(1), ""

        # Mobile H5 / 邀请短链跳转目标：?topic_id=<digits>&inviter_id=...
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        topic_id_q = (qs.get("topic_id") or [None])[0]
        if topic_id_q and topic_id_q.isdigit():
            group_id_q = (qs.get("group_id") or [""])[0]
            return "topic", topic_id_q, group_id_q

    raise ValueError(f"不支持的知识星球链接: {url}")


def _canonical_url(kind: str, primary_id: str, group_id: str) -> str:
    if kind == "article":
        return f"https://articles.zsxq.com/id_{primary_id}.html"
    if kind == "topic":
        if group_id:
            return f"https://wx.zsxq.com/group/{group_id}/topic/{primary_id}"
        return f"https://wx.zsxq.com/dweb2/index/topic_detail/{primary_id}"
    return ""


# ---------------------------------------------------------------------------
# Session / cookie helpers
# ---------------------------------------------------------------------------

def _session_path() -> Path:
    from feedgrab.config import get_session_dir

    return get_session_dir() / "zsxq.json"


def _cookie_header_from_session() -> str:
    """Build a Cookie header string from sessions/zsxq.json."""
    path = _session_path()
    if not path.exists():
        return ""
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"[zsxq] session parse failed: {e}")
        return ""

    pairs = []
    for cookie in state.get("cookies", []):
        domain = cookie.get("domain", "")
        if domain.endswith(_ZSXQ_DOMAIN_SUFFIX) or domain == "zsxq.com":
            pairs.append(f"{cookie.get('name', '')}={cookie.get('value', '')}")
    return "; ".join(p for p in pairs if p and "=" in p)


def _has_zsxq_session_cookie() -> bool:
    """True when the saved session contains the critical zsxq_access_token."""
    return "zsxq_access_token=" in _cookie_header_from_session()


def _zsxq_default_headers(*, referer: Optional[str] = None) -> Dict[str, str]:
    """Build browser-like headers required by api.zsxq.com / articles.zsxq.com."""
    from feedgrab.config import get_user_agent, zsxq_api_version

    headers = {
        "User-Agent": get_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer or "https://wx.zsxq.com/",
        "X-Timestamp": str(int(time.time())),
        "X-Version": zsxq_api_version(),
    }
    cookie = _cookie_header_from_session()
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _login_guidance() -> str:
    return (
        "请先运行 feedgrab login zsxq 保存会话，"
        "或设置 CHROME_CDP_LOGIN=true 后再执行 feedgrab login zsxq 直接复用已登录 Chrome。"
    )


def _normalize_text(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def _looks_like_login_required(text: str) -> bool:
    snippet = (text or "").lower()
    if "未登录" in (text or "") or "登录已过期" in (text or ""):
        return True
    return any(hint.lower() in snippet for hint in _LOGIN_REQUIRED_HINTS if hint)


def _looks_like_not_found(text: str) -> bool:
    snippet = (text or "")
    return any(hint in snippet for hint in _NOT_FOUND_HINTS)


# ---------------------------------------------------------------------------
# HTML → Markdown (article path)
# ---------------------------------------------------------------------------

def _ql_editor_to_markdown(html: str) -> str:
    """Convert a Quill editor block (.ql-editor) to Markdown."""
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup
        from markdownify import markdownify as md
    except ImportError:
        return re.sub(r"<[^>]+>", "", html).strip()

    soup = BeautifulSoup(html, "html.parser")

    # Quill code blocks: <pre class="ql-syntax" spec-language="X">...</pre>
    code_blocks: List[str] = []
    for idx, pre in enumerate(list(soup.find_all("pre"))):
        classes = pre.get("class", []) or []
        is_quill_code = any("ql-syntax" in str(c) for c in classes)
        lang = pre.get("spec-language") or pre.get("data-language") or ""
        if not is_quill_code:
            code = pre.find("code")
            if code:
                for cls in code.get("class", []) or []:
                    if cls.startswith("language-"):
                        lang = cls[9:]
                        break
        text = pre.get_text("\n")
        fence = f"````{lang}\n{text.rstrip()}\n````"
        placeholder = f"\n\nZSXQCODE{idx}END\n\n"
        code_blocks.append(fence)
        pre.replace_with(soup.new_string(placeholder))

    # Absolutize image / link URLs that come back as protocol-relative
    for tag in soup.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        val = tag.get(attr, "")
        if val and val.startswith("//"):
            tag[attr] = "https:" + val

    result = md(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )

    for idx, fence in enumerate(code_blocks):
        result = result.replace(f"ZSXQCODE{idx}END", fence)

    # Drop empty heading lines (Quill 偶尔产生 "# " 空标题)
    result = re.sub(r"(?m)^#{1,6}\s*$", "", result)
    return re.sub(r"\n{3,}", "\n\n", result).strip()


def _parse_article_html(html: str, url: str, primary_id: str) -> Dict[str, Any]:
    """Extract title / author / body / metadata from articles.zsxq.com SSR HTML."""
    if not html:
        raise RuntimeError("Zsxq 文章 HTML 为空。")

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("缺少 beautifulsoup4，请先 pip install beautifulsoup4 markdownify")

    soup = BeautifulSoup(html, "html.parser")

    body_node = soup.find(class_="ql-editor")
    if body_node is None:
        # Login wall / guest landing page — fail terminally.
        page_text = soup.get_text(" ", strip=True)[:500]
        if _looks_like_not_found(page_text):
            raise RuntimeError("知识星球文章不存在或已被删除。")
        raise RuntimeError(
            "知识星球文章正文未渲染，可能需要登录或加入该星球。" + _login_guidance()
        )

    body_html = "".join(str(c) for c in body_node.contents)
    content_md = _ql_editor_to_markdown(body_html)
    if not content_md.strip():
        raise RuntimeError("知识星球文章正文为空。")

    # Title — prefer <title>, fall back to first H1 inside body
    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = title_tag.string.strip()
        # Drop trailing brand suffix " - <group> - 知识星球"
        title = re.sub(r"\s*[\-—]+\s*知识星球\s*$", "", title)
    if not title:
        h1 = body_node.find(["h1", "h2"])
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title:
        title = primary_id

    # Author / group / metrics from meta tags + visible elements
    def _meta(name: str) -> str:
        tag = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": name}
        )
        return _normalize_text(tag.get("content")) if tag else ""

    author = _meta("author") or _meta("og:article:author")
    if not author:
        # Zsxq 文章页 SSR 把昵称放在 .author-info .nick-name
        nick = soup.find(class_="nick-name")
        if nick:
            author = nick.get_text(" ", strip=True)

    group_name = _meta("og:site_name") or ""
    if not group_name:
        gn = soup.find(class_="group-name")
        if gn:
            group_name = gn.get_text(" ", strip=True)

    group_id_extracted = ""
    gi = soup.find(class_="group-info")
    if gi:
        a = gi.find("a", href=True)
        if a:
            m = re.search(r"/group/(\d+)", a["href"])
            if m:
                group_id_extracted = m.group(1)

    cover_image = _meta("og:image") or ""
    if not cover_image:
        # 文章封面经常出现在正文第一个 <img>
        first_img = body_node.find("img")
        if first_img and first_img.get("src"):
            cover_image = first_img["src"]

    published = _meta("article:published_time") or _meta("og:article:published_time")
    if not published:
        # zsxq 文章页常见 "<span class="time">2026-04-25 20:13</span>" 形态
        time_node = soup.find("span", class_="time") or soup.find(class_="created-time")
        if time_node:
            published = time_node.get_text(" ", strip=True)

    # Visible metric strip "阅读 1234 · 点赞 12 · 评论 5"
    likes = comments = reads = 0
    body_text = soup.get_text(" ", strip=True)
    m = re.search(r"阅读\s*([\d,]+)", body_text)
    if m:
        try:
            reads = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m = re.search(r"(?:点赞|赞)\s*([\d,]+)", body_text)
    if m:
        try:
            likes = int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    m = re.search(r"评论\s*([\d,]+)", body_text)
    if m:
        try:
            comments = int(m.group(1).replace(",", ""))
        except ValueError:
            pass

    return {
        "title": title,
        "author": author,
        "content": content_md,
        "url": url,
        "zsxq_type": "article",
        "article_id": primary_id,
        "topic_id": "",
        "group_id": group_id_extracted,
        "group_name": group_name,
        "likes": likes,
        "comments": comments,
        "reads": reads,
        "rewards": 0,
        "comment_mode": "none",
        "rendered_comment_count": 0,
        "created_at": published,
        "cover_image": cover_image,
        "images": [],
        "tags": [],
    }


# ---------------------------------------------------------------------------
# JSON → Markdown (topic path)
# ---------------------------------------------------------------------------

def _topic_text_to_markdown(text: str) -> str:
    """Best-effort conversion of zsxq topic.text (mostly plain) to Markdown."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").strip()
    # zsxq encloses bold links as <e type="hashtag" ...> / <e type="web" ...>
    # Drop the angle-bracket markers but keep inner text.
    cleaned = re.sub(r"<e[^>]*title=\"([^\"]+)\"[^>]*/?>", lambda m: m.group(1), cleaned)
    cleaned = re.sub(r"<e[^>]*>", "", cleaned)
    cleaned = re.sub(r"</e>", "", cleaned)
    return cleaned


def _parse_topic_payload(
    payload: Dict[str, Any], url: str, topic_id: str, group_id: str
) -> Dict[str, Any]:
    """Normalize api.zsxq.com /v2/topics/<id>/info JSON into feedgrab dict.

    Supports topic types: ``talk`` / ``question`` + ``answer`` / ``article`` / ``solution``.
    """
    resp_data = payload.get("resp_data", payload)
    topic = resp_data.get("topic") or resp_data

    talk = topic.get("talk") or {}
    question = topic.get("question") or {}
    answer = topic.get("answer") or {}
    article = topic.get("article") or {}
    solution = topic.get("solution") or {}
    group = topic.get("group") or {}

    owner = (
        talk.get("owner")
        or question.get("owner")
        or solution.get("owner")
        or answer.get("owner")
        or {}
    )
    author = _normalize_text(owner.get("name")) or "知识星球用户"

    # Top-level title is sometimes set directly (e.g. for type=solution).
    topic_title = _normalize_text(topic.get("title"))

    parts: List[str] = []
    if talk:
        text = _topic_text_to_markdown(talk.get("text", ""))
        if text:
            parts.append(text)
        for img in talk.get("images") or []:
            url_img = (img.get("large") or img.get("original") or {}).get("url")
            if url_img:
                parts.append(f"![]({url_img})")
    elif question or answer:
        q_owner = _normalize_text((question.get("owner") or {}).get("name")) or "提问"
        q_text = _topic_text_to_markdown(question.get("text", ""))
        a_owner = _normalize_text((answer.get("owner") or {}).get("name")) or "回答"
        a_text = _topic_text_to_markdown(answer.get("text", ""))
        if q_text:
            parts.append(f"**❓ {q_owner} 提问：**\n\n{q_text}")
        if a_text:
            parts.append(f"\n---\n\n**💡 {a_owner} 回答：**\n\n{a_text}")
    elif solution:
        # type=solution: top-level title 是用户提问；solution.text 是 AI / 星主解答
        if topic_title:
            parts.append(f"**❓ 提问：**\n\n{_topic_text_to_markdown(topic_title)}")
        s_owner = _normalize_text((solution.get("owner") or {}).get("name")) or "解答者"
        s_text = _topic_text_to_markdown(solution.get("text", ""))
        if s_text:
            parts.append(f"\n---\n\n**💡 {s_owner} 解答：**\n\n{s_text}")
    elif article:
        title_in = _normalize_text(article.get("title"))
        if title_in:
            parts.append(f"# {title_in}\n")
        article_url = _normalize_text(article.get("article_url"))
        if article_url:
            parts.append(f"原文链接：{article_url}")

    content = "\n\n".join(p for p in parts if p).strip() or "(空内容)"

    # Resolve title: top-level → article.title → first words of body
    title = topic_title
    if not title and article:
        title = _normalize_text(article.get("title"))
    if not title and talk:
        title = _topic_text_to_markdown(talk.get("text", ""))[:30].strip()
    if not title and question:
        title = _topic_text_to_markdown(question.get("text", ""))[:30].strip()
    if not title and solution:
        title = _topic_text_to_markdown(solution.get("text", ""))[:30].strip()
    if not title:
        title = f"知识星球话题 {topic_id}"
    title = re.sub(r"\s+", " ", title).strip()
    if len(title) > 60:
        title = title[:60].rstrip() + "…"

    likes = topic.get("likes_count", 0) or 0
    comments = topic.get("comments_count", 0) or 0
    reads = topic.get("reading_count", 0) or 0
    rewards = topic.get("rewards_count", 0) or 0

    images: List[str] = []
    for img in (talk.get("images") if talk else []) or []:
        u = (img.get("large") or img.get("original") or {}).get("url")
        if u:
            images.append(u)

    cover = images[0] if images else ""
    if article and article.get("cover_image"):
        cover = article["cover_image"]

    return {
        "title": title,
        "author": author,
        "content": content,
        "url": url,
        "zsxq_type": "topic",
        "article_id": "",
        "topic_id": topic_id,
        "group_id": group_id or _normalize_text(group.get("group_id")),
        "group_name": _normalize_text(group.get("name")),
        "likes": likes,
        "comments": comments,
        "reads": reads,
        "rewards": rewards,
        "comment_mode": "none",
        "rendered_comment_count": 0,
        "created_at": _normalize_text(topic.get("create_time")),
        "cover_image": cover,
        "images": images,
        "tags": [_normalize_text(t) for t in topic.get("hashtags", []) if t],
        "_owner_user_id": owner.get("user_id"),
    }


def _select_comments(
    comments: List[Dict[str, Any]], owner_user_id: Optional[int], mode: str
) -> List[Dict[str, Any]]:
    if mode == "none" or not comments:
        return []
    if mode == "all":
        return comments
    # author mode
    if not owner_user_id:
        return []
    return [
        c for c in comments
        if (c.get("owner") or {}).get("user_id") == owner_user_id
    ]


def _render_comments(comments: List[Dict[str, Any]]) -> str:
    if not comments:
        return ""
    lines = ["", "---", "", f"## 评论 ({len(comments)})", ""]
    for c in comments:
        owner = (c.get("owner") or {}).get("name", "匿名")
        text = _topic_text_to_markdown(c.get("text", ""))
        ctime = c.get("create_time", "")[:16].replace("T", " ")
        lines.append(f"### {owner} · {ctime}")
        lines.append("")
        lines.append(text or "(空)")
        lines.append("")
    return "\n".join(lines)


def _http_fetch_comments(topic_id: str, max_n: int) -> List[Dict[str, Any]]:
    """Fetch up to *max_n* comments via api.zsxq.com."""
    if max_n <= 0:
        return []
    api = f"{_API_BASE}/topics/{topic_id}/comments?count={max_n}&sort=asc"
    try:
        resp = http_client.get(api, headers=_zsxq_default_headers(), timeout=15)
    except requests.RequestException as e:
        logger.debug(f"[zsxq] comments fetch failed: {e}")
        return []
    if resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    if not data.get("succeeded"):
        return []
    return (data.get("resp_data") or {}).get("comments") or []


# ---------------------------------------------------------------------------
# Tier 0: HTTP
# ---------------------------------------------------------------------------

def _http_fetch_article(url: str, primary_id: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Tier 0: HTTP GET articles.zsxq.com/id_<hashid>.html → parse .ql-editor."""
    if not _has_zsxq_session_cookie():
        return None, None  # no cookie → skip to Tier 1

    headers = _zsxq_default_headers(referer="https://articles.zsxq.com/")
    headers["Accept"] = "text/html,application/xhtml+xml,*/*;q=0.8"

    try:
        resp = http_client.get(url, headers=headers, timeout=20, allow_redirects=False)
    except requests.RequestException as e:
        logger.debug(f"[zsxq] article HTTP failed: {e}")
        return None, None

    # Login-wall redirect → terminal
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        if "login" in location:
            return None, "知识星球未登录或登录已过期。" + _login_guidance()
        return None, None
    if resp.status_code == 401:
        return None, "知识星球未登录或登录已过期。" + _login_guidance()
    if resp.status_code == 404:
        return None, "知识星球文章不存在或已被删除。"
    if resp.status_code != 200:
        logger.debug(f"[zsxq] article HTTP status={resp.status_code}")
        return None, None

    try:
        data = _parse_article_html(resp.text, url, primary_id)
        return data, None
    except RuntimeError as e:
        msg = str(e)
        if "未登录" in msg or "未渲染" in msg:
            return None, msg
        if "不存在" in msg:
            return None, msg
        logger.debug(f"[zsxq] article parse failed: {e}")
        return None, None


def _http_fetch_topic(topic_id: str, group_id: str, url: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Tier 0: HTTP GET api.zsxq.com/v2/topics/<id>/info → JSON."""
    if not _has_zsxq_session_cookie():
        return None, None

    api = f"{_API_BASE}/topics/{topic_id}/info"
    try:
        resp = http_client.get(api, headers=_zsxq_default_headers(), timeout=15)
    except requests.RequestException as e:
        logger.debug(f"[zsxq] topic HTTP failed: {e}")
        return None, None

    if resp.status_code == 401:
        return None, "知识星球未登录或登录已过期。" + _login_guidance()
    if resp.status_code == 404:
        return None, "知识星球话题不存在或已被删除。"
    if resp.status_code != 200:
        logger.debug(f"[zsxq] topic HTTP status={resp.status_code}")
        return None, None

    try:
        payload = resp.json()
    except ValueError:
        return None, None

    if not payload.get("succeeded"):
        info = payload.get("info") or "Zsxq API 返回业务错误"
        if any(hint in info for hint in ("未加入", "无权", "已删除", "不存在")):
            return None, f"知识星球访问失败：{info}"
        return None, None

    try:
        data = _parse_topic_payload(payload, url, topic_id, group_id)
        return data, None
    except Exception as e:
        logger.debug(f"[zsxq] topic parse failed: {e}")
        return None, None


# ---------------------------------------------------------------------------
# Tier 1: CDP reuse
# ---------------------------------------------------------------------------

async def _connect_zsxq_cdp() -> Optional[tuple]:
    """Connect via CDP to running Chrome and return (pw, browser, ctx, page)."""
    from feedgrab.config import chrome_cdp_port

    ws_url = f"ws://127.0.0.1:{chrome_cdp_port()}/devtools/browser"
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(ws_url)
        logger.debug(f"[zsxq] CDP connected: {ws_url}")
        for ctx in browser.contexts:
            cookies = await ctx.cookies()
            if any(
                c.get("domain", "").endswith(_ZSXQ_DOMAIN_SUFFIX)
                or c.get("domain", "") == "zsxq.com"
                for c in cookies
            ):
                await _save_zsxq_cookies(cookies)
                page = await ctx.new_page()
                logger.info("[zsxq] CDP: reusing existing Chrome zsxq session")
                return pw, browser, ctx, page
        await browser.close()
        await pw.stop()
    except Exception as e:
        logger.debug(f"[zsxq] CDP connect failed: {e}")
    return None


async def _save_zsxq_cookies(cookies: List[Dict[str, Any]]) -> None:
    path = _session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    zsxq_cookies = [
        c for c in cookies
        if c.get("domain", "").endswith(_ZSXQ_DOMAIN_SUFFIX)
        or c.get("domain", "") == "zsxq.com"
    ]
    if not zsxq_cookies:
        return
    path.write_text(
        json.dumps({"cookies": zsxq_cookies, "origins": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(str(path), 0o600)
    except OSError:
        pass


async def _fetch_article_in_page(page, url: str, primary_id: str) -> Dict[str, Any]:
    """Open articles URL in a page and parse .ql-editor."""
    from feedgrab.config import zsxq_page_load_timeout

    await page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=zsxq_page_load_timeout(),
        referer=generate_referer(url),
    )
    # Wait briefly for Quill body
    try:
        await page.wait_for_selector(".ql-editor", timeout=8000)
    except Exception:
        await page.wait_for_timeout(1500)
    html = await page.content()
    return _parse_article_html(html, url, primary_id)


async def _fetch_topic_in_page(page, url: str, topic_id: str, group_id: str) -> Dict[str, Any]:
    """Open zsxq inside browser and call topic/info API via same-origin fetch."""
    from feedgrab.config import zsxq_page_load_timeout, zsxq_api_version

    landing = url
    await page.goto(
        landing,
        wait_until="domcontentloaded",
        timeout=zsxq_page_load_timeout(),
        referer=generate_referer(landing),
    )
    await page.wait_for_timeout(1500)

    api = f"{_API_BASE}/topics/{topic_id}/info"
    result = await page.evaluate(
        """async ({apiUrl, version}) => {
            try {
                const res = await fetch(apiUrl, {
                    credentials: "include",
                    headers: {
                        "Accept": "application/json, text/plain, */*",
                        "X-Timestamp": String(Math.floor(Date.now() / 1000)),
                        "X-Version": version,
                    },
                });
                const text = await res.text();
                return { status: res.status, text };
            } catch (e) {
                return { status: 0, text: "", error: String(e) };
            }
        }""",
        {"apiUrl": api, "version": zsxq_api_version()},
    )

    if result.get("status") != 200:
        raise RuntimeError(
            f"知识星球 topic API 返回 {result.get('status')}：{(result.get('text') or '')[:200]}"
        )
    payload = json.loads(result["text"])
    if not payload.get("succeeded"):
        info = payload.get("info") or "Zsxq API 返回业务错误"
        raise RuntimeError(f"知识星球访问失败：{info}")
    return _parse_topic_payload(payload, url, topic_id, group_id)


async def _launch_zsxq_browser():
    async_playwright = get_async_playwright()
    pw = await async_playwright().start()
    browser = await stealth_launch(pw, headless=True)
    storage_state = str(_session_path()) if _session_path().exists() else None
    context = await browser.new_context(
        **get_stealth_context_options(storage_state=storage_state)
    )
    await setup_resource_blocking(context)
    page = await context.new_page()
    return pw, browser, context, page


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def fetch_zsxq(url: str) -> Dict[str, Any]:
    """Fetch a Zsxq article or topic with multi-tier fallbacks."""
    if not is_zsxq_url(url):
        raise ValueError(f"不是知识星球链接: {url}")

    # 0. resolve short link first
    resolved = _resolve_zsxq_short_url(url)
    kind, primary_id, group_id = parse_zsxq_url(resolved)
    canonical = _canonical_url(kind, primary_id, group_id) or resolved

    # ---------- Tier 0 — HTTP ----------
    logger.info(f"[zsxq] Tier 0 — HTTP ({kind})")
    if kind == "article":
        data, terminal = _http_fetch_article(canonical, primary_id)
    else:
        data, terminal = _http_fetch_topic(primary_id, group_id, canonical)
    if data:
        _enrich_with_comments(data, primary_id, kind)
        return data
    if terminal:
        logger.warning(f"[zsxq] Tier 0 terminal: {terminal}")

    # ---------- Tier 1 — CDP reuse ----------
    from feedgrab.config import zsxq_cdp_enabled

    if zsxq_cdp_enabled():
        logger.info("[zsxq] Tier 1 — CDP reuse")
        cdp = await _connect_zsxq_cdp()
        if cdp:
            pw = browser = ctx = page = None
            try:
                pw, browser, ctx, page = cdp
                if kind == "article":
                    data = await _fetch_article_in_page(page, canonical, primary_id)
                else:
                    data = await _fetch_topic_in_page(page, canonical, primary_id, group_id)
                cookies = await ctx.cookies()
                await _save_zsxq_cookies(cookies)
                _enrich_with_comments(data, primary_id, kind)
                return data
            except Exception as e:
                logger.warning(f"[zsxq] Tier 1 failed: {e}")
                if terminal is None and ("不存在" in str(e) or "未加入" in str(e)):
                    terminal = str(e)
            finally:
                for closer in (page, browser):
                    try:
                        if closer:
                            await closer.close()
                    except Exception:
                        pass
                try:
                    if pw:
                        await pw.stop()
                except Exception:
                    pass

    # ---------- Tier 2 — Stealth Playwright ----------
    logger.info("[zsxq] Tier 2 — Stealth browser launch")
    pw = browser = context = page = None
    try:
        pw, browser, context, page = await _launch_zsxq_browser()
        if kind == "article":
            data = await _fetch_article_in_page(page, canonical, primary_id)
        else:
            data = await _fetch_topic_in_page(page, canonical, primary_id, group_id)
        try:
            await context.storage_state(path=str(_session_path()))
        except Exception:
            pass
        _enrich_with_comments(data, primary_id, kind)
        return data
    except Exception as e:
        logger.warning(f"[zsxq] Tier 2 failed: {e}")
        if terminal is None and ("不存在" in str(e) or "未加入" in str(e) or "未登录" in str(e)):
            terminal = str(e)
    finally:
        for closer in (context, browser):
            try:
                if closer:
                    await closer.close()
            except Exception:
                pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass

    # ---------- Tier 3 — Jina (last-resort posture) ----------
    if terminal:
        raise RuntimeError(terminal)

    logger.info("[zsxq] Tier 3 — Jina fallback")
    jina_data = fetch_via_jina(canonical)
    title = jina_data.get("title", "") or ""
    content = jina_data.get("content", "") or ""
    if _looks_like_login_required(title) or _looks_like_login_required(content):
        raise RuntimeError("知识星球未登录或登录已过期。" + _login_guidance())
    if _looks_like_not_found(title) or _looks_like_not_found(content):
        raise RuntimeError("知识星球文章/话题不存在或已被删除。")
    return {
        "title": title or primary_id,
        "author": "zsxq",
        "content": content,
        "url": canonical,
        "zsxq_type": kind,
        "article_id": primary_id if kind == "article" else "",
        "topic_id": primary_id if kind == "topic" else "",
        "group_id": group_id,
        "group_name": "",
        "likes": 0,
        "comments": 0,
        "reads": 0,
        "rewards": 0,
        "comment_mode": "none",
        "rendered_comment_count": 0,
        "created_at": "",
        "cover_image": "",
        "images": [],
        "tags": [],
    }


def _enrich_with_comments(data: Dict[str, Any], primary_id: str, kind: str) -> None:
    """Append comment section to data['content'] when comment_mode != none."""
    from feedgrab.config import zsxq_comment_mode, zsxq_max_comments

    mode = zsxq_comment_mode()
    if mode == "none" or kind != "topic":
        data["comment_mode"] = mode
        data["rendered_comment_count"] = 0
        return

    raw = _http_fetch_comments(primary_id, zsxq_max_comments())
    selected = _select_comments(raw, data.get("_owner_user_id"), mode)
    data["comment_mode"] = mode
    data["rendered_comment_count"] = len(selected)
    rendered = _render_comments(selected)
    if rendered:
        data["content"] = (data.get("content", "") or "") + "\n" + rendered
    data.pop("_owner_user_id", None)
