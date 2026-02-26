# -*- coding: utf-8 -*-
"""
Twitter/X GraphQL API client — fetch tweet data via X's internal GraphQL endpoints.

Core capabilities:
    - Dynamic queryId resolution from X's frontend JS bundle (self-updating)
    - Hardcoded fallback queryIds when dynamic resolution fails
    - TweetDetail / TweetResultByRestId API calls
    - Rate limiting with configurable delays

This module uses X's private GraphQL API (reverse-engineered from the web client).
Users must acknowledge this via consent mechanism before first use.
"""

import json
import os
import re
import time
import requests
from loguru import logger
from typing import Dict, Any, Optional, Tuple

from feedgrab.fetchers.twitter_cookies import (
    build_graphql_headers,
    DEFAULT_USER_AGENT,
)

# ---------------------------------------------------------------------------
# Fallback query info (updated manually when dynamic resolution breaks)
# ---------------------------------------------------------------------------

FALLBACK_TWEET_DETAIL = {
    "query_id": "nBS-WpgA6ZG0CyNHD517JQ",
    "operation_name": "TweetDetail",
}

FALLBACK_TWEET_RESULT = {
    "query_id": "DJS3BdhUhcaEpZ7B7irJDg",
    "operation_name": "TweetResultByRestId",
}

FALLBACK_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_text_conversations_enabled": False,
    "responsive_web_media_download_video_enabled": False,
}

FALLBACK_FIELD_TOGGLES = {
    "withArticlePlainText": False,
}

# Rate limiting defaults
DEFAULT_REQUEST_DELAY = float(os.getenv("X_REQUEST_DELAY", "1.5"))
DEFAULT_MAX_PAGES = int(os.getenv("X_THREAD_MAX_PAGES", "20"))

# GraphQL base URL
GRAPHQL_BASE = "https://x.com/i/api/graphql"

# Cache for resolved query info (avoid re-fetching on every call)
_query_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0
CACHE_TTL = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_tweet_detail(tweet_id: str, cookies: dict) -> Optional[Dict[str, Any]]:
    """
    Fetch full tweet detail via TweetDetail GraphQL endpoint.

    This is the primary endpoint — returns the tweet plus surrounding context
    (conversation thread, quoted tweets, etc.).

    Args:
        tweet_id: The numeric tweet/status ID.
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_info = _get_query_info("TweetDetail")
    headers = build_graphql_headers(cookies)

    variables = {
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
    }

    return _execute_graphql(
        query_id=query_info["query_id"],
        operation_name=query_info["operation_name"],
        variables=variables,
        features=_get_features(),
        field_toggles=FALLBACK_FIELD_TOGGLES,
        headers=headers,
    )


def fetch_tweet_detail_with_cursor(
    tweet_id: str, cursor: str, cookies: dict
) -> Optional[Dict[str, Any]]:
    """
    Fetch additional tweets in a thread using a pagination cursor.

    Used for both upward (topCursor) and downward (moreCursor/bottomCursor)
    pagination when fetching complete threads.

    Args:
        tweet_id: The focal tweet ID.
        cursor: Pagination cursor string from a previous response.
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_info = _get_query_info("TweetDetail")
    headers = build_graphql_headers(cookies)

    variables = {
        "focalTweetId": tweet_id,
        "cursor": cursor,
        "referrer": "tweet",
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
    }

    _rate_limit_wait()

    return _execute_graphql(
        query_id=query_info["query_id"],
        operation_name=query_info["operation_name"],
        variables=variables,
        features=_get_features(),
        field_toggles=FALLBACK_FIELD_TOGGLES,
        headers=headers,
    )


def fetch_tweet_by_rest_id(tweet_id: str, cookies: dict) -> Optional[Dict[str, Any]]:
    """
    Fetch a single tweet by REST ID (simpler endpoint, less context).

    Fallback when TweetDetail fails — returns just the tweet without
    surrounding conversation context.

    Args:
        tweet_id: The numeric tweet/status ID.
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_info = _get_query_info("TweetResultByRestId")
    headers = build_graphql_headers(cookies)

    variables = {
        "tweetId": tweet_id,
        "withCommunity": False,
        "includePromotedContent": False,
        "withVoice": False,
    }

    return _execute_graphql(
        query_id=query_info["query_id"],
        operation_name=query_info["operation_name"],
        variables=variables,
        features=_get_features(),
        field_toggles=FALLBACK_FIELD_TOGGLES,
        headers=headers,
    )


def resolve_query_info_from_bundle(user_agent: str = None) -> Dict[str, Dict[str, str]]:
    """
    Dynamically resolve queryIds from X's frontend JS bundle.

    Process:
        1. Fetch x.com HTML → extract JS bundle hash (api:"<hash>")
        2. Download the JS chunk → regex-extract queryId per operationName
        3. Return mapping of operationName → {query_id, operation_name}

    Falls back to hardcoded values on any failure.
    """
    ua = user_agent or DEFAULT_USER_AGENT
    headers = {"user-agent": ua}

    try:
        # Step 1: Fetch x.com homepage to find the API chunk hash
        logger.debug("Resolving queryIds from X frontend bundle...")
        resp = requests.get("https://x.com", headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # Look for api:"<hash>" pattern in the HTML
        api_match = re.search(r'api:"([a-zA-Z0-9]+)"', html)
        if not api_match:
            logger.warning("Could not find API chunk hash in x.com HTML, using fallbacks")
            return _fallback_query_map()

        chunk_hash = api_match.group(1)

        # Step 2: Download the JS bundle chunk
        chunk_url = f"https://abs.twimg.com/responsive-web/client-web/api.{chunk_hash}a.js"
        logger.debug(f"Fetching JS bundle: {chunk_url}")
        chunk_resp = requests.get(chunk_url, headers=headers, timeout=15)
        chunk_resp.raise_for_status()
        chunk_js = chunk_resp.text

        # Step 3: Extract queryId for each operation
        result = {}
        for op_name in ("TweetDetail", "TweetResultByRestId"):
            qid = _extract_query_id(chunk_js, op_name)
            if qid:
                result[op_name] = {"query_id": qid, "operation_name": op_name}
                logger.debug(f"Resolved {op_name}: queryId={qid}")

        if result:
            return result

        logger.warning("No queryIds extracted from JS bundle, using fallbacks")
        return _fallback_query_map()

    except Exception as e:
        logger.warning(f"Dynamic queryId resolution failed ({e}), using fallbacks")
        return _fallback_query_map()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _execute_graphql(
    query_id: str,
    operation_name: str,
    variables: dict,
    features: dict,
    field_toggles: dict,
    headers: dict,
) -> Optional[Dict[str, Any]]:
    """Execute a GraphQL GET request against X's API."""
    import urllib.parse

    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(features, separators=(",", ":")),
        "fieldToggles": json.dumps(field_toggles, separators=(",", ":")),
    }

    url = f"{GRAPHQL_BASE}/{query_id}/{operation_name}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code == 401:
            logger.error("GraphQL 401 Unauthorized — cookies may have expired")
            return None
        if resp.status_code == 403:
            logger.error("GraphQL 403 Forbidden — account may be restricted")
            return None
        if resp.status_code == 429:
            logger.error("GraphQL 429 Rate Limited — too many requests")
            return None

        resp.raise_for_status()
        data = resp.json()

        # Check for GraphQL-level errors
        if "errors" in data:
            for err in data["errors"]:
                logger.warning(f"GraphQL error: {err.get('message', 'unknown')}")
            # Still return data — some errors are non-fatal (e.g. "Not found" for deleted tweets)

        return data

    except requests.Timeout:
        logger.error(f"GraphQL request timed out: {operation_name}")
        return None
    except requests.RequestException as e:
        logger.error(f"GraphQL request failed: {e}")
        return None
    except json.JSONDecodeError:
        logger.error("GraphQL response is not valid JSON")
        return None


def _get_query_info(operation_name: str) -> Dict[str, str]:
    """Get query info for an operation, with caching and dynamic resolution."""
    global _query_cache, _cache_timestamp

    now = time.time()
    if _query_cache and (now - _cache_timestamp) < CACHE_TTL:
        if operation_name in _query_cache:
            return _query_cache[operation_name]

    # Try dynamic resolution
    resolved = resolve_query_info_from_bundle()
    _query_cache = resolved
    _cache_timestamp = now

    return resolved.get(operation_name, _fallback_for(operation_name))


def _get_features() -> dict:
    """Get feature switches for GraphQL requests."""
    return dict(FALLBACK_FEATURES)


def _fallback_query_map() -> Dict[str, Dict[str, str]]:
    """Return hardcoded fallback query info for all operations."""
    return {
        "TweetDetail": dict(FALLBACK_TWEET_DETAIL),
        "TweetResultByRestId": dict(FALLBACK_TWEET_RESULT),
    }


def _fallback_for(operation_name: str) -> Dict[str, str]:
    """Get fallback query info for a specific operation."""
    fallbacks = _fallback_query_map()
    return fallbacks.get(operation_name, {"query_id": "", "operation_name": operation_name})


def _extract_query_id(js_content: str, operation_name: str) -> Optional[str]:
    """
    Extract queryId for a given operationName from the JS bundle.

    Tries multiple regex patterns since X's bundle format can vary.
    """
    patterns = [
        # Pattern 1: queryId:"xxx",operationName:"TweetDetail"
        rf'queryId:"([^"]+)",operationName:"{operation_name}"',
        # Pattern 2: operationName:"TweetDetail",...queryId:"xxx"
        rf'operationName:"{operation_name}"[^}}]*?queryId:"([^"]+)"',
        # Pattern 3: {queryId:"xxx",...operationName:"TweetDetail"...}
        rf'\{{[^}}]*queryId:"([^"]+)"[^}}]*operationName:"{operation_name}"[^}}]*\}}',
    ]

    for pattern in patterns:
        match = re.search(pattern, js_content)
        if match:
            return match.group(1)

    return None


_last_request_time: float = 0


def _rate_limit_wait():
    """Enforce minimum delay between GraphQL requests."""
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    delay = DEFAULT_REQUEST_DELAY
    if elapsed < delay:
        wait = delay - elapsed
        logger.debug(f"Rate limiting: waiting {wait:.1f}s")
        time.sleep(wait)
    _last_request_time = time.time()


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def extract_tweet_entries(response: Dict[str, Any]) -> list:
    """
    Extract tweet entries from a TweetDetail GraphQL response.

    Navigates the nested response structure:
        data → tweetResult → result (for TweetResultByRestId)
        data → threaded_conversation_with_injections_v2 → instructions (for TweetDetail)

    Returns:
        List of tweet entry dicts from the timeline instructions.
    """
    if not response or "data" not in response:
        return []

    entries = []

    # TweetDetail response structure
    try:
        instructions = (
            response["data"]
            .get("threaded_conversation_with_injections_v2", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            inst_type = instruction.get("type")

            if inst_type == "TimelineAddEntries":
                for entry in instruction.get("entries", []):
                    entries.append(entry)

            elif inst_type == "TimelineAddToModule":
                module_items = instruction.get("moduleItems", [])
                for item in module_items:
                    entries.append(item)

    except (KeyError, TypeError) as e:
        logger.debug(f"Failed to parse TweetDetail entries: {e}")

    return entries


def extract_cursors(entries: list) -> Dict[str, str]:
    """
    Extract pagination cursors from timeline entries.

    Returns:
        dict with optional keys: 'top', 'bottom', 'more'
    """
    cursors = {}

    for entry in entries:
        entry_id = entry.get("entryId", "")
        content = entry.get("content", {})

        # Cursor entries have entryId like "cursor-top-...", "cursor-bottom-..."
        if "cursor-top" in entry_id:
            cursor_val = (
                content.get("value")
                or content.get("itemContent", {}).get("value", "")
            )
            if cursor_val:
                cursors["top"] = cursor_val

        elif "cursor-bottom" in entry_id:
            cursor_val = (
                content.get("value")
                or content.get("itemContent", {}).get("value", "")
            )
            if cursor_val:
                cursors["bottom"] = cursor_val

        elif "cursor-showMore" in entry_id or "conversationthread" in entry_id:
            # "Show more replies" cursor within a conversation module
            items = content.get("items", [])
            for item in items:
                item_content = item.get("item", {}).get("itemContent", {})
                if item_content.get("cursorType") == "ShowMoreThreads":
                    cursors["more"] = item_content.get("value", "")

    return cursors


def extract_tweet_data(entry: dict) -> Optional[Dict[str, Any]]:
    """
    Extract structured tweet data from a timeline entry.

    Navigates through the nested result types (Tweet, TweetWithVisibilityResults)
    and extracts core fields: id, text, author, media, quoted tweet, etc.

    Returns:
        Flat dict with tweet fields, or None if entry is not a tweet.
    """
    # Navigate to the tweet result object
    content = entry.get("content", entry)
    item_content = (
        content.get("itemContent")
        or content.get("item", {}).get("itemContent")
        or {}
    )

    tweet_results = item_content.get("tweet_results", {})
    result = tweet_results.get("result", {})

    # Handle TweetWithVisibilityResults wrapper
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    if result.get("__typename") not in ("Tweet",):
        return None

    legacy = result.get("legacy", {})
    core = result.get("core", {})
    user_results = core.get("user_results", {}).get("result", {})
    user_legacy = user_results.get("legacy", {})

    # Extract note_tweet (long text) if available
    note_tweet = result.get("note_tweet", {}).get("note_tweet_results", {}).get("result", {})
    full_text = note_tweet.get("text") or legacy.get("full_text", "")

    # Extract media
    media_list = legacy.get("extended_entities", {}).get("media", [])
    images = []
    videos = []
    for media in media_list:
        media_type = media.get("type", "")
        if media_type == "photo":
            images.append(media.get("media_url_https", ""))
        elif media_type in ("video", "animated_gif"):
            # Get highest bitrate video variant
            variants = media.get("video_info", {}).get("variants", [])
            mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4_variants:
                best = max(mp4_variants, key=lambda v: v.get("bitrate", 0))
                videos.append(best.get("url", ""))
            # Also keep poster image
            images.append(media.get("media_url_https", ""))

    # Extract quoted tweet
    quoted_tweet = None
    quoted_status = result.get("quoted_status_result", {}).get("result", {})
    if quoted_status.get("__typename") == "TweetWithVisibilityResults":
        quoted_status = quoted_status.get("tweet", {})
    if quoted_status.get("__typename") == "Tweet":
        q_legacy = quoted_status.get("legacy", {})
        q_user = (
            quoted_status.get("core", {})
            .get("user_results", {})
            .get("result", {})
            .get("legacy", {})
        )
        quoted_tweet = {
            "id": q_legacy.get("id_str", ""),
            "text": q_legacy.get("full_text", ""),
            "author": q_user.get("screen_name", ""),
            "author_name": q_user.get("name", ""),
        }

    return {
        "id": legacy.get("id_str", ""),
        "text": full_text,
        "author": user_legacy.get("screen_name", ""),
        "author_name": user_legacy.get("name", ""),
        "user_id": user_legacy.get("id_str", legacy.get("user_id_str", "")),
        "conversation_id": legacy.get("conversation_id_str", ""),
        "in_reply_to_user_id": legacy.get("in_reply_to_user_id_str", ""),
        "in_reply_to_status_id": legacy.get("in_reply_to_status_id_str", ""),
        "created_at": legacy.get("created_at", ""),
        "images": images,
        "videos": videos,
        "quoted_tweet": quoted_tweet,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "bookmarks": legacy.get("bookmark_count", 0),
        "views": result.get("views", {}).get("count", "0"),
    }
