# -*- coding: utf-8 -*-
"""
Playwright browser fetcher — headless Chromium fallback for anti-scraping sites.

Used when Jina Reader fails (403/451/timeout). Supports persistent login
sessions via Playwright's storage_state for platforms requiring authentication.

Install: pip install "feedgrab[browser]" && playwright install chromium
"""

from loguru import logger
from pathlib import Path
from urllib.parse import urlparse

from feedgrab.config import get_session_dir, get_user_agent

SESSION_DIR = get_session_dir()
TIMEOUT_MS = 30_000


# ---------------------------------------------------------------------------
# Stealth browser engine: patchright (Tier 1) → playwright (Tier 3)
#
# patchright patches Chromium's CDP layer to remove automation detection
# (navigator.webdriver, Runtime.enable) at the protocol level — no JS hacks.
# Falls back to standard playwright if patchright is not installed.
# Adapted from: https://github.com/D4Vinci/Scrapling
# ---------------------------------------------------------------------------

_async_pw = None   # cached async_playwright function
_pw_engine = ""    # "patchright" or "playwright"


def get_async_playwright():
    """Return async_playwright: patchright (Tier 1) → playwright (Tier 3)."""
    global _async_pw, _pw_engine
    if _async_pw is not None:
        return _async_pw
    try:
        from patchright.async_api import async_playwright
        _async_pw, _pw_engine = async_playwright, "patchright"
        return _async_pw
    except ImportError:
        pass
    try:
        from playwright.async_api import async_playwright
        _async_pw, _pw_engine = async_playwright, "playwright"
        return _async_pw
    except ImportError:
        raise RuntimeError(
            "Neither patchright nor playwright is installed. Run:\n"
            "  pip install patchright && patchright install chromium\n"
            "OR:\n"
            "  pip install playwright && playwright install chromium"
        )


def get_stealth_engine_name() -> str:
    """Return active engine name ('patchright' or 'playwright')."""
    if not _pw_engine:
        get_async_playwright()
    return _pw_engine


# Chrome launch flags for anti-detection (adapted from Scrapling)
STEALTH_LAUNCH_ARGS = [
    # Core anti-detection
    "--disable-blink-features=AutomationControlled",
    "--test-type",
    # Performance & noise reduction
    "--no-pings",
    "--no-first-run",
    "--disable-infobars",
    "--disable-breakpad",
    "--no-service-autorun",
    "--password-store=basic",
    "--disable-hang-monitor",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    # Stealth fingerprint
    "--mute-audio",
    "--disable-sync",
    "--hide-scrollbars",
    "--disable-logging",
    "--start-maximized",
    "--enable-async-dns",
    "--use-mock-keychain",
    "--disable-translate",
    "--disable-voice-input",
    "--disable-wake-on-wifi",
    "--ignore-gpu-blocklist",
    "--enable-tcp-fast-open",
    "--disable-cloud-import",
    "--disable-print-preview",
    "--disable-dev-shm-usage",
    "--metrics-recording-only",
    "--disable-crash-reporter",
    "--disable-partial-raster",
    "--disable-gesture-typing",
    "--disable-prompt-on-repost",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--aggressive-cache-discard",
    "--disable-cookie-encryption",
    "--disable-domain-reliability",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--enable-simple-cache-backend",
    "--disable-background-networking",
    "--enable-surface-synchronization",
    "--disable-renderer-backgrounding",
    "--disable-ipc-flooding-protection",
    "--safebrowsing-disable-auto-update",
    "--disable-background-timer-throttling",
    "--disable-client-side-phishing-detection",
    "--disable-backgrounding-occluded-windows",
    "--autoplay-policy=user-gesture-required",
    "--enable-features=NetworkService,NetworkServiceInProcess",
    "--disable-features=AudioServiceOutOfProcess,TranslateUI,"
    "BlinkGenPropertyTrees",
    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
    "primaryPointerType=4,availablePointerTypes=4",
]

# Playwright adds these by default — they expose automation fingerprints
HARMFUL_DEFAULT_ARGS = [
    "--enable-automation",
    "--disable-popup-blocking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
]


async def stealth_launch(p, *, headless=True):
    """Launch Chromium with full stealth anti-detection settings.

    Uses system Chrome (channel='chrome') for genuine fingerprint;
    patchright's CDP patches still apply at the protocol level.
    """
    engine = get_stealth_engine_name()
    logger.debug(f"Launching browser [{engine}] headless={headless}")
    return await p.chromium.launch(
        headless=headless,
        channel="chrome",
        args=STEALTH_LAUNCH_ARGS,
        ignore_default_args=HARMFUL_DEFAULT_ARGS,
    )


def get_stealth_context_options(**overrides) -> dict:
    """Build browser context options with anti-detection defaults.

    Returns dict for ``browser.new_context(**opts)``.
    Caller can override any field via kwargs (e.g. storage_state).
    """
    opts = {
        "user_agent": get_user_agent(),
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "color_scheme": "dark",
        "device_scale_factor": 2,
        "is_mobile": False,
        "has_touch": False,
        "ignore_https_errors": True,
    }
    opts.update(overrides)
    return opts


# ---------------------------------------------------------------------------
# Referer — convincing search engine origin (adapted from Scrapling)
# ---------------------------------------------------------------------------

_CHINESE_DOMAINS = frozenset({
    "xiaohongshu.com", "xhslink.com", "weixin.sogou.com",
    "mp.weixin.qq.com", "sogou.com", "bilibili.com",
    "weibo.com", "zhihu.com", "douyin.com", "baidu.com",
})


def generate_referer(url: str) -> str:
    """Generate a convincing search engine referer for the target URL.

    Chinese platforms → Baidu search, others → Google search.
    Makes traffic appear as organic search rather than direct bot access.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Extract meaningful site name (skip short subdomains like en/mp/m/api)
    parts = hostname.replace("www.", "").split(".")
    site_name = parts[0]
    if len(parts) >= 3 and len(parts[0]) <= 3:
        site_name = parts[1]

    if any(d in hostname for d in _CHINESE_DOMAINS):
        return f"https://www.baidu.com/s?wd={site_name}"
    return f"https://www.google.com/search?q={site_name}"


# ---------------------------------------------------------------------------
# Resource interception — block non-essential requests for speed
# ---------------------------------------------------------------------------

# Resource types that are never needed for content extraction
_BLOCKED_RESOURCE_TYPES = frozenset({
    "font",         # Web fonts
    "media",        # Video / audio playback
    "texttrack",    # Subtitle tracks
    "beacon",       # Analytics beacons (navigator.sendBeacon)
    "eventsource",  # Server-sent events
    "manifest",     # Service worker / PWA manifest
    "websocket",    # WebSocket connections
})

# Tracking / analytics domains to block
_BLOCKED_DOMAINS = frozenset({
    "google-analytics.com",
    "googletagmanager.com",
    "connect.facebook.net",
    "doubleclick.net",
    "hotjar.com",
    "clarity.ms",
    "plausible.io",
    "umami.is",
    "cdn.mxpnl.com",          # Mixpanel
    "sentry.io",
    "browser.sentry-cdn.com",
})


async def setup_resource_blocking(target) -> None:
    """Install route handler to block non-essential resources.

    Args:
        target: A Playwright Page or BrowserContext.
                Context-level blocking applies to all pages in that context.
    """
    async def _handle_route(route):
        if route.request.resource_type in _BLOCKED_RESOURCE_TYPES:
            await route.abort()
            return
        req_url = route.request.url
        if any(d in req_url for d in _BLOCKED_DOMAINS):
            await route.abort()
            return
        await route.continue_()

    await target.route("**/*", _handle_route)


# XHS note page JS evaluate — extracted for reuse by batch fetcher
XHS_NOTE_JS_EVALUATE = """() => {
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
}"""


def _build_xhs_result(data: dict, page_url: str) -> dict:
    """Convert raw XHS JS evaluate output to a standardized result dict."""
    return {
        "title": (data["title"] or "").strip()[:200],
        "content": (data["content"] or "").strip(),
        "url": page_url,
        "author": (data["author"] or "").strip(),
        "author_url": data.get("authorUrl", ""),
        "tags": data.get("tags", []),
        "images": data.get("images", []),
        "likes": data.get("likes", 0),
        "collects": data.get("collects", 0),
        "comments": data.get("comments", 0),
        "date": data.get("date", ""),
    }


async def evaluate_xhs_note(page) -> dict:
    """Wait for XHS note to render, then extract structured data via JS evaluate.

    Assumes the page has already navigated to an XHS note URL.
    Returns standardized result dict.
    """
    try:
        await page.wait_for_selector("#noteContainer", timeout=8000)
    except Exception:
        pass
    # Wait for date element (lazy-loaded) — gives more time for full render
    try:
        await page.wait_for_selector(".bottom-container .date", timeout=3000)
    except Exception:
        pass
    await page.wait_for_timeout(500)

    data = await page.evaluate(XHS_NOTE_JS_EVALUATE)
    return _build_xhs_result(data, page.url)


async def fetch_via_browser(url: str, storage_state: str = None) -> dict:
    """
    Fetch a URL using stealth Chromium browser.

    Engine priority: patchright (Tier 1) → playwright (Tier 3).

    Args:
        url: Target URL to fetch.
        storage_state: Path to a storage state JSON file (cookies/localStorage).
                       If provided, the browser context will load this session.

    Returns:
        dict with keys: title, content, url, author
    """
    async_pw = get_async_playwright()
    logger.info(f"Browser fetch [{get_stealth_engine_name()}]: {url}")

    async with async_pw() as p:
        # Use headed mode for XHS (anti-bot detection), headless for others
        is_xhs = "xiaohongshu.com" in url or "xhslink.com" in url
        browser = await stealth_launch(p, headless=not is_xhs)

        ctx_opts = {}
        if storage_state and Path(storage_state).exists():
            ctx_opts["storage_state"] = storage_state
            logger.info(f"Using session: {storage_state}")

        context = await browser.new_context(
            **get_stealth_context_options(**ctx_opts)
        )
        page = await context.new_page()
        await setup_resource_blocking(page)

        try:
            await page.goto(
                url, wait_until="domcontentloaded", timeout=TIMEOUT_MS,
                referer=generate_referer(url),
            )

            if is_xhs:
                # XHS SPA needs the note container to render
                try:
                    await page.wait_for_selector("#noteContainer", timeout=8000)
                except Exception:
                    logger.warning("[XHS] #noteContainer not found within 8s, proceeding anyway")
                await page.wait_for_timeout(1000)

                data = await page.evaluate(XHS_NOTE_JS_EVALUATE)
                result = _build_xhs_result(data, page.url)
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
