# -*- coding: utf-8 -*-
"""
LinuxDo / Discourse topic fetcher.

Strategy:
    Tier 0: Discourse topic JSON API (guest or saved session cookies)
    Tier 1: CDP reuse running Chrome cookies / cf_clearance → page-side fetch JSON
    Tier 2: Stealth Playwright launch (with saved session if available) → page-side fetch JSON
    Tier 3: Jina Reader fallback (only for challenge-like failures, never for explicit 404/private)

Why JSON-first:
    Discourse topic JSON already contains thread structure, author, timestamps,
    tags, metrics, and cooked HTML per post. It is much more stable than
    scraping the rendered DOM directly.
"""

import json
import os
import re
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


_LINUXDO_DOMAINS = ("linux.do",)
_TOPIC_WITH_SLUG_RE = re.compile(r"^/t/([^/]+)/(\d+)(?:/(\d+))?/?$")
_TOPIC_ID_ONLY_RE = re.compile(r"^/t/(\d+)(?:/(\d+))?/?$")
_CF_CHALLENGE_HINTS = (
    "just a moment",
    "enable javascript and cookies to continue",
    "cf_chl_opt",
)
_NOT_FOUND_HINTS = (
    "找不到页面",
    "不公开页面",
    "page not found",
)


def is_linuxdo_url(url: str) -> bool:
    """Check whether *url* belongs to linux.do."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return any(netloc == d or netloc.endswith("." + d) for d in _LINUXDO_DOMAINS)


def parse_linuxdo_url(url: str) -> Tuple[str, str, Optional[str]]:
    """Parse LinuxDo topic URL into (slug, topic_id, post_number)."""
    path = urlparse(url).path.rstrip("/")

    m = _TOPIC_WITH_SLUG_RE.match(path)
    if m:
        slug, topic_id, post_number = m.groups()
        return slug, topic_id, post_number

    m = _TOPIC_ID_ONLY_RE.match(path)
    if m:
        topic_id, post_number = m.groups()
        return "topic", topic_id, post_number

    raise ValueError(f"不支持的 LinuxDo 帖子链接格式: {url}")


def _canonical_topic_url(url: str) -> str:
    slug, topic_id, _ = parse_linuxdo_url(url)
    return f"https://linux.do/t/{slug}/{topic_id}"


def _topic_json_candidates(url: str) -> List[str]:
    slug, topic_id, _ = parse_linuxdo_url(url)
    candidates = [
        f"https://linux.do/t/{slug}/{topic_id}.json",
        f"https://linux.do/t/{topic_id}.json",
    ]
    # Keep order but dedupe
    seen = set()
    result = []
    for item in candidates:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _session_path() -> Path:
    from feedgrab.config import get_session_dir

    return get_session_dir() / "linuxdo.json"


def _cookie_header_from_session() -> str:
    """Load linux.do cookies from Playwright storage_state."""
    session_path = _session_path()
    if not session_path.exists():
        return ""
    try:
        state = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"[linuxdo] session parse failed: {e}")
        return ""

    pairs = []
    for cookie in state.get("cookies", []):
        domain = cookie.get("domain", "")
        if domain.endswith(".linux.do") or domain == "linux.do":
            pairs.append(f"{cookie.get('name', '')}={cookie.get('value', '')}")
    return "; ".join(p for p in pairs if p and "=" in p)


def _looks_like_challenge(text: str) -> bool:
    snippet = (text or "").lower()
    return any(hint in snippet for hint in _CF_CHALLENGE_HINTS)


def _looks_like_not_found(text: str) -> bool:
    snippet = (text or "").lower()
    return any(hint in snippet for hint in _NOT_FOUND_HINTS)


def _html_to_markdown(html: str) -> str:
    """Convert Discourse cooked HTML to Markdown."""
    if not html:
        return ""

    try:
        from bs4 import BeautifulSoup
        from markdownify import markdownify as md
    except ImportError:
        text = re.sub(r"<[^>]+>", "", html)
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("noscript"):
        tag.decompose()

    for tag in soup.select("a.anchor"):
        tag.decompose()

    # Convert relative links and images to absolute URLs.
    for tag in soup.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        val = tag.get(attr, "")
        if not val:
            continue
        if val.startswith("//"):
            tag[attr] = "https:" + val
        elif val.startswith("/"):
            tag[attr] = urljoin("https://linux.do", val)

    _remove_noise_images(soup)
    _simplify_lightbox_images(soup)

    # Preserve code fences with language.
    details_blocks: List[str] = []
    for idx, details in enumerate(list(soup.find_all("details"))):
        if details.find_parent("details"):
            continue
        summary = details.find("summary")
        summary_text = summary.get_text(" ", strip=True) if summary else "展开"
        if summary:
            summary.extract()
        inner_html = "".join(str(child) for child in details.contents)
        inner_md = _html_to_markdown(inner_html).strip()
        if _is_simple_details_block(details, inner_md):
            block = _render_details_as_callout(summary_text, inner_md, is_open=details.has_attr("open"))
        else:
            block = _render_details_as_html(summary_text, inner_html, is_open=details.has_attr("open"))
        placeholder = f"\n\nFEEDGRABDETAILSBLOCK{idx}TOKEN\n\n"
        details_blocks.append(block)
        details.replace_with(soup.new_string(placeholder))

    # Preserve code fences with language.
    code_blocks: List[str] = []
    for idx, pre in enumerate(list(soup.find_all("pre"))):
        code = pre.find("code")
        text = code.get_text("\n") if code else pre.get_text("\n")
        classes = code.get("class", []) if code else []
        lang = ""
        for cls in classes:
            if cls.startswith("lang-"):
                lang = cls[5:]
                break
            if cls.startswith("language-"):
                lang = cls[9:]
                break
        fence = f"```{lang}\n{text.rstrip()}\n```"
        placeholder = f"\n\nFEEDGRABCODEBLOCK{idx}TOKEN\n\n"
        code_blocks.append(fence)
        pre.replace_with(soup.new_string(placeholder))

    result = md(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    for idx, block in enumerate(details_blocks):
        result = result.replace(f"FEEDGRABDETAILSBLOCK{idx}TOKEN", block)
    for idx, block in enumerate(code_blocks):
        result = result.replace(f"FEEDGRABCODEBLOCK{idx}TOKEN", block)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result


def _remove_noise_images(soup) -> None:
    """Remove forum avatar and emoji thumbnails that pollute exported markdown."""
    avatar_markers = ("user_avatar", "letter_avatar", "emoji", "twemoji")
    shortcode_pattern = re.compile(r"^:[a-z0-9_+-]+:$", re.IGNORECASE)
    for image in list(soup.find_all("img")):
        src = (image.get("src") or "").lower()
        alt = (image.get("alt") or "").strip()
        title = (image.get("title") or "").strip()
        classes = [str(cls).lower() for cls in image.get("class", [])]
        if any(marker in src for marker in avatar_markers):
            image.decompose()
            continue
        if any("emoji" in cls for cls in classes):
            image.decompose()
            continue
        if shortcode_pattern.match(alt) or shortcode_pattern.match(title):
            image.decompose()


def _simplify_lightbox_images(soup) -> None:
    """Replace Discourse lightbox wrappers with a single original image node."""
    for anchor in list(soup.find_all("a")):
        image = anchor.find("img")
        if not image:
            continue

        classes = set(anchor.get("class", []))
        has_meta = anchor.find(class_="meta") is not None
        if "lightbox" not in classes and not has_meta:
            continue

        original_url = (anchor.get("href") or "").strip()
        if not original_url:
            continue

        alt_text = (image.get("alt") or anchor.get("title") or "").strip()
        clean_img = soup.new_tag("img")
        clean_img["src"] = original_url
        if alt_text:
            clean_img["alt"] = alt_text

        anchor.replace_with(clean_img)


def _is_simple_details_block(details, inner_md: str) -> bool:
    """Decide whether a fold block is simple enough for Obsidian callout output."""
    complex_tags = {
        "h1", "h2", "h3", "h4", "h5", "h6",
        "pre", "table", "img", "blockquote", "details",
        "iframe", "video", "audio",
    }
    if any(details.find(tag) for tag in complex_tags):
        return False
    if details.select("ul ul, ul ol, ol ul, ol ol"):
        return False
    if "```" in inner_md:
        return False
    if "![" in inner_md:
        return False
    if re.search(r"(?m)^\|.+\|$", inner_md):
        return False
    return True


def _render_details_as_callout(summary_text: str, inner_md: str, is_open: bool = False) -> str:
    """Render a simple fold block as an Obsidian collapsible callout."""
    toggle = "+" if is_open else "-"
    lines = [f"> [!feedgrab-fold]{toggle} {summary_text}"]
    if inner_md:
        lines.append(">")
        for line in inner_md.splitlines():
            if line.strip():
                lines.append(f"> {line}")
            else:
                lines.append(">")
    return "\n".join(lines)


def _render_details_as_html(summary_text: str, inner_html: str, is_open: bool = False) -> str:
    """Render a complex fold block as pure HTML so Obsidian keeps it collapsible."""
    open_attr = " open" if is_open else ""
    body = inner_html.strip()
    return (
        f'<details class="feedgrab-fold feedgrab-fold--complex"{open_attr}>\n'
        f'<summary class="feedgrab-fold__summary">{summary_text}</summary>\n'
        f"{body}\n"
        "</details>"
    )


def _format_post_author(post: Dict[str, Any]) -> str:
    return (post.get("name") or "").strip() or (post.get("username") or "").strip() or "匿名"


def _format_iso_dt(raw: str) -> str:
    if not raw:
        return ""
    try:
        from datetime import datetime

        return (
            datetime.fromisoformat(raw.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except ValueError:
        return raw[:16]


def _extract_first_image(payload: Dict[str, Any]) -> str:
    posts = payload.get("post_stream", {}).get("posts", [])
    cooked = posts[0].get("cooked", "") if posts else ""
    lightbox_match = re.search(r'<a[^>]+href="([^"]+)"[^>]*>\s*<img\b', cooked)
    if lightbox_match:
        src = lightbox_match.group(1)
        if src.startswith("/"):
            return urljoin("https://linux.do", src)
        if src.startswith("//"):
            return "https:" + src
        return src
    img_match = re.search(r'<img[^>]+src="([^"]+)"', cooked)
    if not img_match:
        image_url = payload.get("image_url", "")
        if image_url:
            return image_url
        return ""
    src = img_match.group(1)
    if src.startswith("/"):
        return urljoin("https://linux.do", src)
    if src.startswith("//"):
        return "https:" + src
    return src


def _parse_topic_payload(payload: Dict[str, Any], url: str) -> Dict[str, Any]:
    """Normalize Discourse topic JSON into feedgrab's internal dict."""
    posts = payload.get("post_stream", {}).get("posts", [])
    if not posts:
        raise RuntimeError("LinuxDo topic JSON 中没有 posts 数据")

    canonical_url = _canonical_topic_url(url)
    op = posts[0]
    author = _format_post_author(op)
    category_name = payload.get("category_name", "") or ""
    tags = []
    for tag in payload.get("tags", []):
        if isinstance(tag, dict):
            name = tag.get("name") or tag.get("slug")
        else:
            name = str(tag).strip()
        if name:
            tags.append(name)

    lines: List[str] = []
    meta_lines = []
    if author:
        meta_lines.append(f"作者: {author}")
    published = _format_iso_dt(op.get("created_at") or payload.get("created_at", ""))
    if published:
        meta_lines.append(f"发布时间: {published}")
    metrics = []
    if payload.get("views") is not None:
        metrics.append(f"浏览 {payload.get('views', 0)}")
    if payload.get("reply_count") is not None:
        metrics.append(f"回复 {payload.get('reply_count', 0)}")
    if payload.get("like_count") is not None:
        metrics.append(f"点赞 {payload.get('like_count', 0)}")
    if category_name:
        metrics.append(f"分类 {category_name}")
    if metrics:
        meta_lines.append("统计: " + " · ".join(metrics))
    if meta_lines:
        lines.append("> " + "\n> ".join(meta_lines))
        lines.append("")

    lines.append(_html_to_markdown(op.get("cooked", "")))

    replies = posts[1:]
    if replies:
        lines.extend(["", "---", "", f"## 回复 ({len(replies)})", ""])
        for post in replies:
            header = f"### [{post.get('post_number', '?')}楼] {_format_post_author(post)}"
            post_time = _format_iso_dt(post.get("created_at", ""))
            if post_time:
                header += f" · {post_time}"
            if post.get("reply_to_post_number"):
                header += f" · 回复 {post['reply_to_post_number']}楼"
            lines.extend([header, "", _html_to_markdown(post.get("cooked", "")), ""])

    content = "\n".join(lines).strip()
    return {
        "title": payload.get("title", "") or "Untitled",
        "content": content,
        "url": canonical_url,
        "author": author,
        "category": category_name,
        "category_id": payload.get("category_id", 0),
        "tags": tags,
        "topic_id": str(payload.get("id", "")),
        "topic_slug": payload.get("slug", ""),
        "posts_count": payload.get("posts_count", len(posts)),
        "reply_count": payload.get("reply_count", max(len(posts) - 1, 0)),
        "like_count": payload.get("like_count", 0),
        "views": payload.get("views", 0),
        "created_at": payload.get("created_at") or op.get("created_at", ""),
        "last_posted_at": payload.get("last_posted_at", ""),
        "cover_image": _extract_first_image(payload),
        "post_count_loaded": len(posts),
    }


def _http_fetch_topic_json(url: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Try Discourse topic JSON via HTTP. Returns (payload, terminal_error)."""
    from feedgrab.config import get_stealth_headers

    cookie_header = _cookie_header_from_session()
    headers = get_stealth_headers()
    headers["Accept"] = "application/json, text/plain, */*"
    headers["Referer"] = _canonical_topic_url(url)
    headers["X-Requested-With"] = "XMLHttpRequest"
    if cookie_header:
        headers["Cookie"] = cookie_header

    for api_url in _topic_json_candidates(url):
        try:
            resp = http_client.get(api_url, headers=headers, timeout=20)
        except requests.RequestException as e:
            logger.debug(f"[linuxdo] HTTP JSON failed: {e}")
            continue

        text = resp.text or ""
        if resp.status_code == 404:
            return None, "LinuxDo 帖子不存在，或当前游客状态无权访问。"
        if resp.status_code in (401, 403) and _looks_like_challenge(text):
            logger.info("[linuxdo] HTTP JSON hit Cloudflare challenge")
            continue
        if resp.status_code in (401, 403):
            return None, "LinuxDo 帖子需要登录后才能抓取。请先运行 feedgrab login linuxdo。"
        if resp.status_code != 200:
            logger.debug(f"[linuxdo] HTTP JSON status={resp.status_code}")
            continue
        if _looks_like_challenge(text):
            logger.info("[linuxdo] HTTP JSON returned challenge page")
            continue
        if _looks_like_not_found(text):
            return None, "LinuxDo 帖子不存在，或当前游客状态无权访问。"

        try:
            data = resp.json()
        except ValueError:
            logger.debug("[linuxdo] HTTP JSON response was not valid JSON")
            continue
        if data.get("post_stream", {}).get("posts"):
            return data, None

    return None, None


async def _connect_linuxdo_cdp() -> Optional[tuple]:
    """Connect to running Chrome via CDP and reuse a context with linux.do cookies."""
    from feedgrab.config import chrome_cdp_port

    ws_url = f"ws://127.0.0.1:{chrome_cdp_port()}/devtools/browser"
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(ws_url)
        logger.debug(f"[linuxdo] CDP connected: {ws_url}")
        for ctx in browser.contexts:
            cookies = await ctx.cookies()
            if any(
                c.get("domain", "").endswith(".linux.do") or c.get("domain", "") == "linux.do"
                for c in cookies
            ):
                await _save_linuxdo_cookies(cookies)
                page = await ctx.new_page()
                logger.info("[linuxdo] CDP: reusing existing Chrome linux.do session")
                return pw, browser, ctx, page
        await browser.close()
        await pw.stop()
    except Exception as e:
        logger.debug(f"[linuxdo] CDP connect failed: {e}")
    return None


async def _save_linuxdo_cookies(cookies: List[Dict[str, Any]]) -> None:
    session_path = _session_path()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    linuxdo_cookies = [
        cookie for cookie in cookies
        if cookie.get("domain", "").endswith(".linux.do") or cookie.get("domain", "") == "linux.do"
    ]
    if not linuxdo_cookies:
        return
    session_path.write_text(
        json.dumps({"cookies": linuxdo_cookies, "origins": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(str(session_path), 0o600)
    except OSError:
        pass


async def _launch_linuxdo_browser():
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


async def _wait_linuxdo_page_ready(page) -> Dict[str, str]:
    """Wait for Cloudflare / topic page to settle enough for same-origin fetch."""
    status: Dict[str, str] = {"title": "", "body": ""}
    for _ in range(18):
        status = await page.evaluate(
            """() => ({
                title: document.title || "",
                body: (document.body && document.body.innerText || "").slice(0, 800)
            })"""
        )
        title = status.get("title", "")
        body = status.get("body", "")
        if not _looks_like_challenge(title) and not _looks_like_challenge(body):
            return status
        await page.wait_for_timeout(1000)
    return status


async def _fetch_topic_json_in_page(page, url: str) -> Dict[str, Any]:
    """Run same-origin fetch inside browser page to reuse challenge cookies / login state."""
    from feedgrab.config import linuxdo_page_load_timeout

    topic_url = _canonical_topic_url(url)
    await page.goto(
        topic_url,
        wait_until="domcontentloaded",
        timeout=linuxdo_page_load_timeout(),
        referer=generate_referer(topic_url),
    )
    page_status = await _wait_linuxdo_page_ready(page)
    json_urls = _topic_json_candidates(url)
    result = await page.evaluate(
        """async (apiUrls) => {
            const readText = (selectors) => {
              for (const sel of selectors) {
                const el = document.querySelector(sel);
                const text = el && el.textContent ? el.textContent.trim() : "";
                if (text) return text;
              }
              return "";
            };

            const meta = {
              pageTitle: document.title || "",
              bodyText: (document.body && document.body.innerText || "").slice(0, 1200),
              categoryName: readText([
                ".badge-category__name",
                ".topic-category .badge-category__name",
                ".category-breadcrumb .badge-category__name",
                ".category-name"
              ]),
            };

            for (const apiUrl of apiUrls) {
              try {
                const res = await fetch(apiUrl, {
                  credentials: "include",
                  headers: {
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                  },
                });
                const text = await res.text();
                if (res.ok && text.trim().startsWith("{")) {
                  return { ok: true, apiUrl, status: res.status, text, meta };
                }
                meta.lastStatus = String(res.status);
                meta.lastBody = text.slice(0, 500);
              } catch (e) {
                meta.lastError = String(e);
              }
            }
            return { ok: false, meta };
        }""",
        json_urls,
    )

    meta = result.get("meta", {})
    if meta.get("categoryName"):
        page_status["category_name"] = meta["categoryName"]
    if result.get("ok"):
        data = json.loads(result["text"])
        if page_status.get("category_name") and not data.get("category_name"):
            data["category_name"] = page_status["category_name"]
        return data

    body = meta.get("lastBody") or meta.get("bodyText") or page_status.get("body", "")
    title = meta.get("pageTitle") or page_status.get("title", "")
    if _looks_like_not_found(title) or _looks_like_not_found(body):
        raise RuntimeError("LinuxDo 帖子不存在，或当前游客状态无权访问。")
    if "登录" in body or "login" in body.lower():
        raise RuntimeError("LinuxDo 帖子需要登录后才能抓取。请先运行 feedgrab login linuxdo。")
    raise RuntimeError("LinuxDo 浏览器态 JSON 抓取失败，可能仍被 Cloudflare 拦截。")


async def fetch_linuxdo(url: str) -> Dict[str, Any]:
    """Fetch a LinuxDo topic with Discourse-aware multi-tier fallbacks."""
    if not is_linuxdo_url(url):
        raise ValueError(f"不是 LinuxDo 链接: {url}")

    # Tier 0 — HTTP JSON with guest/session cookies
    logger.info("[linuxdo] Tier 0 — Discourse topic JSON")
    data, terminal_error = _http_fetch_topic_json(url)
    if data:
        return _parse_topic_payload(data, url)
    if terminal_error:
        # explicit 404 / login-required: do not fall back to Jina and save garbage pages
        logger.warning(f"[linuxdo] Tier 0 terminal error: {terminal_error}")

    # Tier 1 — CDP: reuse running Chrome session / cf_clearance
    from feedgrab.config import linuxdo_cdp_enabled

    if linuxdo_cdp_enabled():
        logger.info("[linuxdo] Tier 1 — CDP browser reuse")
        cdp = await _connect_linuxdo_cdp()
        if cdp:
            pw = browser = ctx = page = None
            try:
                pw, browser, ctx, page = cdp
                data = await _fetch_topic_json_in_page(page, url)
                cookies = await ctx.cookies()
                await _save_linuxdo_cookies(cookies)
                return _parse_topic_payload(data, url)
            except Exception as e:
                logger.warning(f"[linuxdo] CDP fetch failed: {e}")
                if terminal_error:
                    raise RuntimeError(terminal_error) from e
            finally:
                try:
                    if page:
                        await page.close()
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

    # Tier 2 — Stealth Playwright launch
    logger.info("[linuxdo] Tier 2 — Stealth browser launch")
    pw = browser = context = page = None
    try:
        pw, browser, context, page = await _launch_linuxdo_browser()
        data = await _fetch_topic_json_in_page(page, url)
        await context.storage_state(path=str(_session_path()))
        return _parse_topic_payload(data, url)
    except Exception as e:
        logger.warning(f"[linuxdo] Tier 2 failed: {e}")
        if terminal_error:
            raise RuntimeError(terminal_error) from e
    finally:
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

    # Tier 3 — Jina fallback only for non-terminal challenge/network failures
    logger.info("[linuxdo] Tier 3 — Jina fallback")
    jina_data = fetch_via_jina(_canonical_topic_url(url))
    title = jina_data.get("title", "") or ""
    content = jina_data.get("content", "") or ""
    if _looks_like_not_found(title) or _looks_like_not_found(content):
        raise RuntimeError("LinuxDo 帖子不存在，或当前游客状态无权访问。")
    return {
        "title": title or "Untitled",
        "content": content,
        "url": _canonical_topic_url(url),
        "author": "linux.do",
        "category": "",
        "category_id": 0,
        "tags": [],
        "topic_id": parse_linuxdo_url(url)[1],
        "topic_slug": parse_linuxdo_url(url)[0],
        "posts_count": 1,
        "reply_count": 0,
        "like_count": 0,
        "views": 0,
        "created_at": "",
        "last_posted_at": "",
        "cover_image": "",
        "post_count_loaded": 1,
    }
