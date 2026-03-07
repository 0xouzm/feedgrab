# -*- coding: utf-8 -*-
"""
Centralized configuration — paths, feature flags, defaults.

All cookie/session paths and feature toggles should be read from here,
not hardcoded in individual fetcher files.
"""

import os
import platform
import re
from pathlib import Path

from loguru import logger


# ---------------------------------------------------------------------------
# User-Agent — single source of truth
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/132.0.0.0 Safari/537.36"
)


def get_user_agent() -> str:
    """Return the User-Agent string for all browser/HTTP interactions.

    Priority:
      1. BROWSER_USER_AGENT env var (user-configured or auto-detected)
      2. browserforge generated UA (if installed)
      3. DEFAULT_USER_AGENT fallback
    """
    env_ua = os.getenv("BROWSER_USER_AGENT", "").strip()
    if env_ua:
        return env_ua
    if _stealth_headers is None:
        _init_stealth_headers()
    return _stealth_headers.get("User-Agent", DEFAULT_USER_AGENT)


# ---------------------------------------------------------------------------
# Stealth headers — browserforge-powered consistent fingerprint
# ---------------------------------------------------------------------------

_stealth_headers = None  # session-level cache


def _detect_browser_os() -> str:
    """Map platform.system() to browserforge OS name."""
    return {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(
        platform.system().lower(), "windows"
    )


def _init_stealth_headers():
    """Initialize consistent browser headers (called once, cached).

    Uses browserforge to generate a complete header set where UA, Sec-Ch-Ua,
    Accept, Accept-Language etc. are internally consistent.
    Falls back to basic headers if browserforge is not installed.
    """
    global _stealth_headers

    env_ua = os.getenv("BROWSER_USER_AGENT", "").strip()

    try:
        from browserforge.headers import Browser, HeaderGenerator

        # Match Chrome version from user's real UA if set
        chrome_ver = 0
        if env_ua:
            m = re.search(r"Chrome/(\d+)", env_ua)
            chrome_ver = int(m.group(1)) if m else 0

        if chrome_ver > 0:
            browsers = [Browser(name="chrome", min_version=chrome_ver, max_version=chrome_ver)]
        else:
            # Pin to DEFAULT_USER_AGENT version for consistent "Google Chrome" brand
            m = re.search(r"Chrome/(\d+)", DEFAULT_USER_AGENT)
            fallback_ver = int(m.group(1)) if m else 132
            browsers = [Browser(name="chrome", min_version=fallback_ver, max_version=fallback_ver)]

        gen = HeaderGenerator(
            browser=browsers, os=_detect_browser_os(), device="desktop"
        )
        _stealth_headers = dict(gen.generate())

        # Override with user's real UA if set (keeps Sec-Ch-Ua from browserforge)
        if env_ua:
            _stealth_headers["User-Agent"] = env_ua

        # Let HTTP libraries handle encoding negotiation
        _stealth_headers.pop("Accept-Encoding", None)

        # Chinese locale for feedgrab's primary targets
        _stealth_headers["Accept-Language"] = "zh-CN,zh;q=0.9,en;q=0.8"

    except ImportError:
        logger.warning(
            "[stealth] browserforge 未安装，浏览器指纹一致性降级。"
            "建议安装以提升反检测能力：\n"
            '  pip install "feedgrab[stealth]"   # 含 patchright + browserforge\n'
            "  或单独安装：pip install browserforge"
        )
        ua = env_ua or DEFAULT_USER_AGENT
        _stealth_headers = {
            "User-Agent": ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    except Exception as e:
        logger.warning(f"[stealth] browserforge 初始化失败: {e}，使用基础 header")
        ua = env_ua or DEFAULT_USER_AGENT
        _stealth_headers = {
            "User-Agent": ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }


def get_stealth_headers(**overrides) -> dict:
    """Return a complete set of consistent browser headers.

    Uses browserforge (if installed) to generate headers where UA, Sec-Ch-Ua,
    Accept, etc. are all internally consistent.  Falls back to basic headers.
    Kwargs override specific headers (e.g. Accept="text/markdown" for Jina).
    Cached per session — all requests share the same fingerprint.
    """
    if _stealth_headers is None:
        _init_stealth_headers()
    h = dict(_stealth_headers)
    h.update(overrides)
    return h


def get_data_dir() -> Path:
    """Return the feedgrab data/session directory (project-local by default).

    Reads FEEDGRAB_DATA_DIR from env; defaults to ``sessions``.
    Cookies and Playwright sessions are stored together in one flat directory.
    Relative paths are resolved against the current working directory.
    """
    raw = os.getenv("FEEDGRAB_DATA_DIR", "sessions")
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def get_cookie_dir() -> Path:
    """Return the cookie storage directory (same as session dir)."""
    return get_data_dir()


def get_session_dir() -> Path:
    """Return the Playwright session storage directory (same as cookie dir)."""
    return get_data_dir()


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def x_fetch_author_replies() -> bool:
    """Whether to collect the tweet author's own replies."""
    return os.getenv("X_FETCH_AUTHOR_REPLIES", "false").lower() in ("true", "1", "yes")


def x_fetch_all_comments() -> bool:
    """Whether to collect all comments under the main tweet."""
    return os.getenv("X_FETCH_ALL_COMMENTS", "false").lower() in ("true", "1", "yes")


def x_max_comments() -> int:
    """Maximum number of comments to collect (default 50)."""
    try:
        return int(os.getenv("X_MAX_COMMENTS", "50"))
    except ValueError:
        return 50


# ---------------------------------------------------------------------------
# Bookmarks batch fetch
# ---------------------------------------------------------------------------

def x_bookmarks_enabled() -> bool:
    """Whether bookmark batch fetching is enabled."""
    return os.getenv("X_BOOKMARKS_ENABLED", "false").lower() in ("true", "1", "yes")


def x_bookmark_max_pages() -> int:
    """Maximum bookmark pagination pages (default 50, ~1000 tweets)."""
    try:
        return int(os.getenv("X_BOOKMARK_MAX_PAGES", "50"))
    except ValueError:
        return 50


def x_bookmark_delay() -> float:
    """Delay in seconds between processing each bookmark tweet (default 2.0)."""
    try:
        return float(os.getenv("X_BOOKMARK_DELAY", "2.0"))
    except ValueError:
        return 2.0


# ---------------------------------------------------------------------------
# User timeline batch fetch
# ---------------------------------------------------------------------------

def x_user_tweets_enabled() -> bool:
    """Whether user timeline batch fetching is enabled."""
    return os.getenv("X_USER_TWEETS_ENABLED", "false").lower() in ("true", "1", "yes")


def x_user_tweet_max_pages() -> int:
    """Maximum user timeline pagination pages (default 200, ~4000 tweets)."""
    try:
        return int(os.getenv("X_USER_TWEET_MAX_PAGES", "200"))
    except ValueError:
        return 200


def x_user_tweet_delay() -> float:
    """Delay in seconds between processing each user tweet (default 2.0)."""
    try:
        return float(os.getenv("X_USER_TWEET_DELAY", "2.0"))
    except ValueError:
        return 2.0


def x_user_tweets_since() -> str:
    """Date filter for user tweets (e.g. '2025-10-01'). Empty = fetch all."""
    return os.getenv("X_USER_TWEETS_SINCE", "").strip()


# ---------------------------------------------------------------------------
# List tweets batch fetch
# ---------------------------------------------------------------------------

def x_list_tweets_enabled() -> bool:
    """Whether list tweets batch fetching is enabled."""
    return os.getenv("X_LIST_TWEETS_ENABLED", "false").lower() in ("true", "1", "yes")


def x_list_tweet_max_pages() -> int:
    """Maximum list timeline pagination pages (default 50)."""
    try:
        return int(os.getenv("X_LIST_TWEET_MAX_PAGES", "50"))
    except ValueError:
        return 50


def x_list_tweet_delay() -> float:
    """Delay in seconds between processing each list tweet (default 2.0)."""
    try:
        return float(os.getenv("X_LIST_TWEET_DELAY", "2.0"))
    except ValueError:
        return 2.0


def x_list_tweets_days() -> int:
    """Number of days to fetch from list (default: 1 = last 24h)."""
    try:
        return int(os.getenv("X_LIST_TWEETS_DAYS", "1"))
    except ValueError:
        return 1


def x_search_supplementary_enabled() -> bool:
    """Whether to use Search API to supplement UserTweets for older tweets.

    When enabled (default), after UserTweets finishes, if X_USER_TWEETS_SINCE
    is set and UserTweets didn't reach that far back, Search API will
    automatically fill the gap via monthly date chunking.
    """
    return os.getenv("X_SEARCH_SUPPLEMENTARY", "true").lower() in ("true", "1", "yes")


def x_search_max_pages_per_chunk() -> int:
    """Maximum pages per monthly search chunk (default 50)."""
    try:
        return int(os.getenv("X_SEARCH_MAX_PAGES_PER_CHUNK", "50"))
    except ValueError:
        return 50


# ---------------------------------------------------------------------------
# TwitterAPI.io paid API (supplementary / standalone)
# ---------------------------------------------------------------------------

def twitterapi_io_key() -> str:
    """TwitterAPI.io API Key. Empty = not configured.

    When configured, used as supplementary for UserTweets (replacing browser search).
    Get your key at https://twitterapi.io
    """
    return os.getenv("TWITTERAPI_IO_KEY", "").strip()


def x_api_provider() -> str:
    """API provider for user tweet batch fetch.

    'graphql' (default) — free GraphQL + optional API supplementary
    'api' — full TwitterAPI.io paid API path (no cookie needed, server-friendly)
    """
    val = os.getenv("X_API_PROVIDER", "graphql").strip().lower()
    if val not in ("graphql", "api"):
        return "graphql"
    return val


def x_api_save_directly() -> bool:
    """Whether to save API data directly without GraphQL secondary fetch.

    false (default) — use tweet_id to call GraphQL for full data (images/videos/thread)
    true — directly convert API data and save (faster, but no media)
    """
    return os.getenv("X_API_SAVE_DIRECTLY", "false").lower() in ("true", "1", "yes")


def x_api_min_likes() -> int:
    """Minimum likes filter for API fetch (OR logic). 0 = no filter."""
    try:
        val = os.getenv("X_API_MIN_LIKES", "").strip()
        return int(val) if val else 0
    except ValueError:
        return 0


def x_api_min_retweets() -> int:
    """Minimum retweets filter for API fetch (OR logic). 0 = no filter."""
    try:
        val = os.getenv("X_API_MIN_RETWEETS", "").strip()
        return int(val) if val else 0
    except ValueError:
        return 0


def x_api_min_views() -> int:
    """Minimum views filter for API fetch (OR logic). 0 = no filter."""
    try:
        val = os.getenv("X_API_MIN_VIEWS", "").strip()
        return int(val) if val else 0
    except ValueError:
        return 0


def force_refetch() -> bool:
    """Skip dedup check and re-fetch/overwrite existing files.

    Set FORCE_REFETCH=true to re-fetch all items even if already saved.
    Useful after code fixes or to update metadata (likes/views).
    """
    return os.getenv("FORCE_REFETCH", "false").lower() in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# XHS user notes batch fetch
# ---------------------------------------------------------------------------

def xhs_user_notes_enabled() -> bool:
    """Whether XHS user notes batch fetching is enabled."""
    return os.getenv("XHS_USER_NOTES_ENABLED", "false").lower() in ("true", "1", "yes")


def xhs_user_note_max_scrolls() -> int:
    """Maximum scroll iterations on XHS profile page (default 50)."""
    try:
        return int(os.getenv("XHS_USER_NOTE_MAX_SCROLLS", "50"))
    except ValueError:
        return 50


def xhs_user_note_delay() -> float:
    """Delay in seconds between processing each XHS note (default 3.0)."""
    try:
        return float(os.getenv("XHS_USER_NOTE_DELAY", "3.0"))
    except ValueError:
        return 3.0


def xhs_user_notes_since() -> str:
    """Date filter for XHS user notes (e.g. '2025-10-01'). Empty = fetch all."""
    return os.getenv("XHS_USER_NOTES_SINCE", "").strip()


# ---------------------------------------------------------------------------
# XHS search notes batch fetch
# ---------------------------------------------------------------------------

def xhs_search_enabled() -> bool:
    """Whether XHS search notes batch fetching is enabled."""
    return os.getenv("XHS_SEARCH_ENABLED", "false").lower() in ("true", "1", "yes")


def xhs_search_max_scrolls() -> int:
    """Maximum scroll iterations on XHS search page (default 30)."""
    try:
        return int(os.getenv("XHS_SEARCH_MAX_SCROLLS", "30"))
    except ValueError:
        return 30


def xhs_search_delay() -> float:
    """Delay in seconds between processing each XHS search note (default 3.0)."""
    try:
        return float(os.getenv("XHS_SEARCH_DELAY", "3.0"))
    except ValueError:
        return 3.0


# ---------------------------------------------------------------------------
# WeChat Sogou search (mpweixin-so)
# ---------------------------------------------------------------------------

def mpweixin_sogou_enabled() -> bool:
    """Whether Sogou WeChat article search is enabled."""
    return os.getenv("MPWEIXIN_SOGOU_ENABLED", "false").lower() in ("true", "1", "yes")


def mpweixin_sogou_max_results() -> int:
    """Maximum articles per search (default 10, max ~100, 10 per page)."""
    try:
        val = int(os.getenv("MPWEIXIN_SOGOU_MAX_RESULTS", "10"))
        return min(val, 100)  # Sogou caps at ~10 pages
    except ValueError:
        return 10


def mpweixin_sogou_delay() -> float:
    """Delay in seconds between fetching each article (default 3.0)."""
    try:
        return float(os.getenv("MPWEIXIN_SOGOU_DELAY", "3.0"))
    except ValueError:
        return 3.0


# ---------------------------------------------------------------------------
# WeChat MP account article fetch (mpweixin-id)
# ---------------------------------------------------------------------------

def mpweixin_id_since() -> str:
    """Date filter for MP account articles (e.g. '2025-10-01').

    Only fetch articles published after this date.
    Empty = fetch all articles.
    """
    return os.getenv("MPWEIXIN_ID_SINCE", "").strip()


def mpweixin_id_delay() -> float:
    """Delay in seconds between fetching each article (default 3.0)."""
    try:
        return float(os.getenv("MPWEIXIN_ID_DELAY", "3.0"))
    except ValueError:
        return 3.0


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def parse_twitter_date_local(created_at: str, fmt: str = "%Y-%m-%d") -> str:
    """Parse Twitter created_at to local timezone string.

    Supports both:
    - RFC 2822 from GraphQL: "Thu Oct 28 03:49:11 +0000 2022"
    - ISO 8601 from Syndication API: "2022-10-28T03:49:11.000Z"

    Converts UTC to system local timezone so dates match the Twitter web UI.
    """
    if not created_at:
        return ""
    try:
        # Try ISO 8601 first (Syndication API format)
        # Use regex to avoid matching "T" in weekday names like "Tue", "Thu"
        if re.search(r"\d{4}-\d{2}-\d{2}T", created_at):
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            dt = dt.astimezone()  # UTC → system local timezone
            return dt.strftime(fmt)
        # Fallback to RFC 2822 (GraphQL format)
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(created_at)
        dt = dt.astimezone()  # UTC → system local timezone
        return dt.strftime(fmt)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def github_token() -> str:
    """GitHub personal access token. Without: 60 req/h, with: 5000 req/h."""
    return os.getenv("GITHUB_TOKEN", "").strip()
