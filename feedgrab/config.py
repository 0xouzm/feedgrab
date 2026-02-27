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
    """Maximum user timeline pagination pages (default 50, ~1000 tweets)."""
    try:
        return int(os.getenv("X_USER_TWEET_MAX_PAGES", "50"))
    except ValueError:
        return 50


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
