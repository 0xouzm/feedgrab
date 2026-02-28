# -*- coding: utf-8 -*-
"""
Twitter/X Cookie management — multi-source authentication for GraphQL API.

Cookie sources (priority order):
    1. Environment variables: X_AUTH_TOKEN + X_CT0
    2. Cookie file: sessions/x.json
    3. Playwright session: sessions/twitter.json
    4. Chrome CDP: auto-extract from running Chrome (requires --remote-debugging-port)

Required cookies for GraphQL API:
    - auth_token: session authentication token
    - ct0: CSRF protection token
"""

import json
import os
import shutil
from pathlib import Path
from loguru import logger

from feedgrab.config import get_cookie_dir, get_session_dir, get_user_agent

COOKIE_DIR = get_cookie_dir()
SESSION_DIR = get_session_dir()

# Legacy paths (for backward compatibility migration)
_LEGACY_COOKIE_DIRS = [
    Path.cwd() / ".feedgrab" / "cookies",       # project-local .feedgrab/cookies/
    Path.home() / ".feedgrab" / "cookies",       # user-home ~/.feedgrab/cookies/
]
_LEGACY_SESSION_DIRS = [
    Path.cwd() / ".feedgrab" / "sessions",       # project-local .feedgrab/sessions/
    Path.home() / ".feedgrab" / "sessions",       # user-home ~/.feedgrab/sessions/
]

REQUIRED_COOKIES = ("auth_token", "ct0")

# Public bearer token used by X's web client (not a secret).
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

DEFAULT_USER_AGENT = get_user_agent()


def load_twitter_cookies() -> dict:
    """
    Load Twitter cookies from multiple sources with priority fallback.

    Returns:
        dict with 'auth_token' and 'ct0' keys, or empty dict if none found.
    """
    # Source 1: Environment variables (highest priority, good for CI/servers)
    cookies = _load_from_env()
    if has_required_cookies(cookies):
        logger.info(f"Twitter cookies loaded from env (auth_token={cookies['auth_token'][:8]}...)")
        return cookies

    # Source 2: Dedicated cookie file
    cookies = _load_from_cookie_file()
    if has_required_cookies(cookies):
        logger.info(f"Twitter cookies loaded from cookie file (auth_token={cookies['auth_token'][:8]}...)")
        return cookies

    # Source 3: Playwright session (bridge from `feedgrab login twitter`)
    cookies = _load_from_playwright_session()
    if has_required_cookies(cookies):
        logger.info(f"Twitter cookies loaded from Playwright session (auth_token={cookies['auth_token'][:8]}...)")
        return cookies

    # Source 4: Chrome CDP auto-extract
    cookies = _load_from_chrome_cdp()
    if has_required_cookies(cookies):
        logger.info(f"Twitter cookies loaded from Chrome CDP (auth_token={cookies['auth_token'][:8]}...)")
        return cookies

    logger.warning("No valid Twitter cookies found from any source")
    return {}


def has_required_cookies(cookies: dict) -> bool:
    """Check if cookies contain both auth_token and ct0."""
    return all(cookies.get(k) for k in REQUIRED_COOKIES)


def save_twitter_cookies(cookies: dict) -> None:
    """Save cookies to cookie directory with restrictive permissions."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    cookie_path = COOKIE_DIR / "x.json"

    with open(cookie_path, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)

    try:
        os.chmod(str(cookie_path), 0o600)
    except OSError:
        pass  # Windows doesn't support Unix permissions

    logger.info(f"Cookies saved to {cookie_path}")


def build_graphql_headers(cookies: dict, user_agent: str = None) -> dict:
    """
    Build HTTP headers for X GraphQL API requests.

    Args:
        cookies: dict with 'auth_token' and 'ct0'.
        user_agent: optional custom User-Agent string.

    Returns:
        dict of HTTP headers ready for requests.get/post.
    """
    ua = user_agent or DEFAULT_USER_AGENT
    return {
        "authorization": f"Bearer {BEARER_TOKEN}",
        "x-csrf-token": cookies.get("ct0", ""),
        "cookie": f"auth_token={cookies.get('auth_token', '')}; ct0={cookies.get('ct0', '')}",
        "content-type": "application/json",
        "user-agent": ua,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
    }


# ---------------------------------------------------------------------------
# Private: cookie source loaders
# ---------------------------------------------------------------------------

def _load_from_env() -> dict:
    """Source 1: Load cookies from environment variables."""
    return {
        "auth_token": os.getenv("X_AUTH_TOKEN", ""),
        "ct0": os.getenv("X_CT0", ""),
    }


def _load_from_cookie_file() -> dict:
    """Source 2: Load cookies from cookie file (sessions/x.json)."""
    cookie_path = COOKIE_DIR / "x.json"
    if not cookie_path.exists():
        # Backward compat: search legacy cookie dirs and migrate
        for legacy_dir in _LEGACY_COOKIE_DIRS:
            for name in ("x.json", "twitter.json"):
                legacy_path = legacy_dir / name
                if legacy_path.exists():
                    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(legacy_path), str(cookie_path))
                    logger.info(f"Migrated cookie: {legacy_path} -> {cookie_path}")
                    break
            else:
                continue
            break
        else:
            return {}

    try:
        with open(cookie_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "auth_token": data.get("auth_token", ""),
            "ct0": data.get("ct0", ""),
        }
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to read cookie file: {e}")
        return {}


def _load_from_playwright_session() -> dict:
    """
    Source 3: Extract auth_token and ct0 from Playwright storage_state JSON.

    This bridges the existing `feedgrab login twitter` flow with GraphQL:
    users login once via Playwright, both browser and GraphQL paths work.
    """
    # Try new path first, then legacy session dirs
    session_path = SESSION_DIR / "twitter.json"
    if not session_path.exists():
        for legacy_dir in _LEGACY_SESSION_DIRS:
            legacy_path = legacy_dir / "twitter.json"
            if legacy_path.exists():
                SESSION_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(legacy_path), str(session_path))
                logger.info(f"Migrated session: {legacy_path} -> {session_path}")
                break
        else:
            return {}

    try:
        with open(session_path, "r", encoding="utf-8") as f:
            state = json.load(f)

        cookie_map = {}
        for cookie in state.get("cookies", []):
            if cookie.get("name") in REQUIRED_COOKIES:
                domain = cookie.get("domain", "")
                if "x.com" in domain or "twitter.com" in domain:
                    cookie_map[cookie["name"]] = cookie["value"]

        return cookie_map
    except (json.JSONDecodeError, IOError, KeyError) as e:
        logger.warning(f"Failed to extract cookies from Playwright session: {e}")
        return {}


def _load_from_chrome_cdp() -> dict:
    """
    Source 4: Auto-extract cookies from a running Chrome instance via CDP.

    Requires Chrome launched with: --remote-debugging-port=9222
    Connects via WebSocket, calls Network.getCookies for .x.com domain.
    """
    import urllib.request

    cdp_port = os.getenv("CHROME_CDP_PORT", "9222")
    cdp_url = f"http://127.0.0.1:{cdp_port}"

    try:
        # Check if Chrome CDP is reachable
        req = urllib.request.Request(f"{cdp_url}/json/version", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            version_info = json.loads(resp.read())
            ws_url = version_info.get("webSocketDebuggerUrl")

        if not ws_url:
            return {}

        # Use HTTP endpoint to get cookies (simpler than WebSocket)
        # Send CDP command via /json/protocol isn't straightforward,
        # so we use the REST-like endpoint to list targets and get cookies
        req = urllib.request.Request(f"{cdp_url}/json/list", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            targets = json.loads(resp.read())

        # Find an x.com tab
        x_target = None
        for target in targets:
            if "x.com" in target.get("url", ""):
                x_target = target
                break

        if not x_target:
            return {}

        # Extract cookies via CDP WebSocket
        return _extract_cookies_via_websocket(ws_url)

    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return {}


def _extract_cookies_via_websocket(ws_url: str) -> dict:
    """Connect to Chrome DevTools WebSocket and extract X cookies."""
    try:
        import websocket  # optional dependency
    except ImportError:
        logger.debug("websocket-client not installed, skipping Chrome CDP cookie extraction")
        return {}

    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        ws.send(json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": ["https://x.com", "https://twitter.com"]},
        }))
        result = json.loads(ws.recv())
        ws.close()

        cookie_map = {}
        for cookie in result.get("result", {}).get("cookies", []):
            if cookie.get("name") in REQUIRED_COOKIES:
                cookie_map[cookie["name"]] = cookie["value"]

        return cookie_map
    except Exception as e:
        logger.debug(f"Chrome CDP WebSocket extraction failed: {e}")
        return {}
