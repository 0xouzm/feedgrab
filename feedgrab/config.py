# -*- coding: utf-8 -*-
"""
Centralized configuration — paths, feature flags, defaults.

All cookie/session paths and feature toggles should be read from here,
not hardcoded in individual fetcher files.
"""

import os
from pathlib import Path


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
