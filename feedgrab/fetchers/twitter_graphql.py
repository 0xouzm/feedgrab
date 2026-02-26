# -*- coding: utf-8 -*-
"""
Twitter/X GraphQL API client — fetch tweet data via X's internal GraphQL endpoints.

Ported from baoyu-danger-x-to-markdown (TypeScript) to Python.
Reference files: constants.ts, graphql.ts, http.ts, thread.ts

Core capabilities:
    - Dynamic queryId resolution from X's frontend JS bundle (self-updating)
    - Hardcoded fallback queryIds when dynamic resolution fails
    - TweetDetail / TweetResultByRestId API calls
    - Rate limiting with configurable delays (safety measure, not in original)

This module uses X's private GraphQL API (reverse-engineered from the web client).
Users must acknowledge this via consent mechanism before first use.
"""

import json
import os
import re
import time
import requests
from loguru import logger
from typing import Dict, Any, Optional, List

from feedgrab.fetchers.twitter_cookies import (
    build_graphql_headers,
    DEFAULT_USER_AGENT,
)

# ---------------------------------------------------------------------------
# Fallback queryIds — from baoyu constants.ts
# ---------------------------------------------------------------------------

FALLBACK_TWEET_DETAIL_QUERY_ID = "_8aYOgEDz35BrBcBal1-_w"
FALLBACK_TWEET_RESULT_QUERY_ID = "HJ9lpOL-ZlOk5CkCw0JW6Q"
FALLBACK_ARTICLE_QUERY_ID = "id8pHQbQi7eZ6P9mA1th1Q"

# ---------------------------------------------------------------------------
# Feature switches — per-operation, from baoyu constants.ts
# ---------------------------------------------------------------------------

# TweetResultByRestId features (constants.ts lines 25-61)
TWEET_RESULT_FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": True,
    "creator_subscriptions_quote_tweet_preview_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": True,
    "premium_content_api_read_enabled": True,
    "responsive_web_text_conversations_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": True,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_show_grok_translated_post": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
    "rweb_video_screen_enabled": True,
}

# TweetDetail features (constants.ts lines 105-137)
TWEET_DETAIL_FEATURES = {
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
    "responsive_web_text_conversations_enabled": True,
    "responsive_web_media_download_video_enabled": True,
    "premium_content_api_read_enabled": False,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_jetfuel_frame": False,
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": True,
}

# ---------------------------------------------------------------------------
# Field toggles — per-operation, from baoyu constants.ts
# ---------------------------------------------------------------------------

# TweetResultByRestId field toggles
TWEET_RESULT_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
    "withPayments": True,
    "withAuxiliaryUserLabels": True,
}

# TweetDetail field toggles
TWEET_DETAIL_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

# ---------------------------------------------------------------------------
# Rate limiting (safety measure — original baoyu has none)
# ---------------------------------------------------------------------------

DEFAULT_REQUEST_DELAY = float(os.getenv("X_REQUEST_DELAY", "1.5"))
DEFAULT_MAX_PAGES = int(os.getenv("X_THREAD_MAX_PAGES", "20"))

# GraphQL base URL
GRAPHQL_BASE = "https://x.com/i/api/graphql"

# Cache for resolved query info and home HTML
_query_cache: Dict[str, Any] = {}
_cache_timestamp: float = 0
_cached_home_html: str = ""
CACHE_TTL = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_tweet_detail(
    tweet_id: str, cookies: dict, cursor: str = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch full tweet detail via TweetDetail GraphQL endpoint.

    Returns the tweet plus surrounding conversation context (thread, quoted tweets).
    Supports cursor-based pagination for thread traversal.

    Args:
        tweet_id: The numeric tweet/status ID.
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor from a previous response.

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("TweetDetail")
    headers = build_graphql_headers(cookies)

    # Variables — matches baoyu graphql.ts fetchTweetDetail()
    variables = {
        "focalTweetId": tweet_id,
        "with_rux_injections": False,
        "rankingMode": "Relevance",
        "includePromotedContent": True,
        "withCommunity": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withBirdwatchNotes": True,
        "withVoice": True,
        "withV2Timeline": True,
        "withDownvotePerspective": False,
        "withReactionsMetadata": False,
        "withReactionsPerspective": False,
        "withSuperFollowsTweetFields": False,
        "withSuperFollowsUserFields": False,
    }

    if cursor:
        variables["cursor"] = cursor
        variables["referrer"] = "tweet"
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="TweetDetail",
        variables=variables,
        features=dict(TWEET_DETAIL_FEATURES),
        field_toggles=dict(TWEET_DETAIL_FIELD_TOGGLES),
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
    query_id = _get_query_id("TweetResultByRestId")
    headers = build_graphql_headers(cookies)

    variables = {
        "tweetId": tweet_id,
        "withCommunity": False,
        "includePromotedContent": False,
        "withVoice": False,
    }

    return _execute_graphql(
        query_id=query_id,
        operation_name="TweetResultByRestId",
        variables=variables,
        features=dict(TWEET_RESULT_FEATURES),
        field_toggles=dict(TWEET_RESULT_FIELD_TOGGLES),
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Dynamic queryId resolution — from baoyu graphql.ts
# ---------------------------------------------------------------------------

def resolve_query_ids(user_agent: str = None) -> Dict[str, str]:
    """
    Dynamically resolve queryIds from X's frontend JS bundles.

    Process (matches baoyu graphql.ts):
        - TweetDetail: x.com HTML → api:"<hash>" → api.<hash>a.js → extract queryId
        - TweetResultByRestId: x.com HTML → main.<hash>.js → extract queryId

    Returns:
        Dict mapping operation_name → query_id.
    """
    ua = user_agent or DEFAULT_USER_AGENT
    result = {}

    try:
        html = _fetch_home_html(ua)
        if not html:
            return _fallback_query_ids()

        # TweetDetail — from api.<hash>a.js
        api_match = re.search(r'api:"([a-zA-Z0-9]+)"', html)
        if api_match:
            chunk_hash = api_match.group(1)
            chunk_url = f"https://abs.twimg.com/responsive-web/client-web/api.{chunk_hash}a.js"
            qid = _fetch_and_extract_query_id(chunk_url, "TweetDetail", ua)
            if qid:
                result["TweetDetail"] = qid
                logger.debug(f"Resolved TweetDetail: queryId={qid}")

        # TweetResultByRestId — from main.<hash>.js (different bundle!)
        main_match = re.search(r'main:"([a-zA-Z0-9]+)"', html)
        if main_match:
            chunk_hash = main_match.group(1)
            chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
            qid = _fetch_and_extract_query_id(chunk_url, "TweetResultByRestId", ua)
            if qid:
                result["TweetResultByRestId"] = qid
                logger.debug(f"Resolved TweetResultByRestId: queryId={qid}")

        # ArticleEntityResultByRestId — from bundle.TwitterArticles.<hash>a.js
        article_match = re.search(r'bundle\.TwitterArticles:"([a-zA-Z0-9]+)"', html)
        if article_match:
            chunk_hash = article_match.group(1)
            chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.TwitterArticles.{chunk_hash}a.js"
            qid = _fetch_and_extract_query_id(chunk_url, "ArticleEntityResultByRestId", ua)
            if qid:
                result["ArticleEntityResultByRestId"] = qid
                logger.debug(f"Resolved ArticleEntityResultByRestId: queryId={qid}")

    except Exception as e:
        logger.warning(f"Dynamic queryId resolution failed ({e}), using fallbacks")

    # Merge with fallbacks for any missing operations
    fallbacks = _fallback_query_ids()
    for op, qid in fallbacks.items():
        if op not in result:
            result[op] = qid

    return result


# ---------------------------------------------------------------------------
# Response parsing helpers — from baoyu thread.ts parseTweetsAndToken
# ---------------------------------------------------------------------------

def parse_tweet_entries(response: Dict[str, Any]) -> List[dict]:
    """
    Extract tweet entries from a TweetDetail GraphQL response.

    Checks both v2 and v1 conversation paths (matches baoyu thread.ts).
    Filters out "you_might_also_like" recommendation entries.

    Returns:
        List of entry dicts from the timeline instructions.
    """
    if not response or "data" not in response:
        return []

    data = response["data"]

    # Try v2 first, then v1 (matches baoyu thread.ts)
    instructions = (
        data.get("threaded_conversation_with_injections_v2", {}).get("instructions")
        or data.get("threaded_conversation_with_injections", {}).get("instructions")
        or []
    )

    entries = []

    for instruction in instructions:
        inst_type = instruction.get("type", "")

        if inst_type == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                # Skip "you_might_also_like" recommendations
                component = (
                    entry.get("content", {})
                    .get("clientEventInfo", {})
                    .get("component", "")
                )
                if component == "you_might_also_like":
                    continue
                entries.append(entry)

        elif inst_type == "TimelineAddToModule":
            for item in instruction.get("moduleItems", []):
                entries.append(item)

    return entries


def parse_cursors(entries: List[dict]) -> Dict[str, str]:
    """
    Extract pagination cursors from timeline entries.

    Cursor types (matches baoyu thread.ts parseInstruction):
        - top: TimelineTimelineCursor with cursorType "Top"
        - bottom: TimelineTimelineCursor with cursorType "Bottom"
        - more: cursor with cursorType "ShowMore" or "ShowMoreThreads"

    Returns:
        dict with optional keys: 'top', 'bottom', 'more'
    """
    cursors = {}

    for entry in entries:
        entry_id = entry.get("entryId", "")
        content = entry.get("content", {})
        entry_type = content.get("entryType", "")
        cursor_type = content.get("cursorType", "")

        # Top-level cursor entries (cursor-top-xxx, cursor-bottom-xxx)
        if entry_type == "TimelineTimelineCursor":
            value = content.get("value", "")
            if cursor_type == "Top" and value:
                cursors["top"] = value
            elif cursor_type == "Bottom" and value:
                cursors["bottom"] = value

        # Also check itemContent for cursors (nested in conversation modules)
        item_content = content.get("itemContent", {})
        if item_content.get("entryType") == "TimelineTimelineCursor":
            value = item_content.get("value", "")
            ct = item_content.get("cursorType", "")
            if ct == "Top" and value:
                cursors["top"] = value
            elif ct == "Bottom" and value:
                cursors["bottom"] = value

        # ShowMore / ShowMoreThreads cursors inside conversation thread modules
        if "conversationthread" in entry_id or content.get("entryType") == "TimelineTimelineModule":
            items = content.get("items", [])
            for item in items:
                ic = item.get("item", {}).get("itemContent", {})
                ic_type = ic.get("itemType", ic.get("__typename", ""))
                ic_cursor_type = ic.get("cursorType", "")
                if ic_type == "TimelineTimelineCursor" and ic_cursor_type in ("ShowMore", "ShowMoreThreads"):
                    value = ic.get("value", "")
                    if value:
                        cursors["more"] = value

    return cursors


def extract_tweet_data(entry: dict) -> Optional[Dict[str, Any]]:
    """
    Extract structured tweet data from a timeline entry.

    Navigates TweetWithVisibilityResults wrappers and extracts:
    id, text (with note_tweet long text), author, media, quoted tweet, metrics.

    Matches baoyu thread.ts parseTweetsAndToken tweet extraction path.

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

    # Extract note_tweet (long text) if available — priority over legacy.full_text
    note_tweet = (
        result.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
    )
    full_text = note_tweet.get("text") or legacy.get("full_text", "")

    # Extract media from extended_entities
    media_list = legacy.get("extended_entities", {}).get("media", [])
    images = []
    videos = []
    for media in media_list:
        media_type = media.get("type", "")
        if media_type == "photo":
            images.append(media.get("media_url_https", ""))
        elif media_type in ("video", "animated_gif"):
            # Get highest bitrate mp4 variant
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

    # Extract article reference if present
    article = _extract_article_ref(result)

    return {
        "id": legacy.get("id_str", result.get("rest_id", "")),
        "rest_id": result.get("rest_id", ""),
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
        "article": article,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "bookmarks": legacy.get("bookmark_count", 0),
        "views": result.get("views", {}).get("count", "0"),
        # Keep raw result for article extraction in later PRs
        "_raw_result": result,
    }


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
    # Always inject this feature (matches baoyu http.ts buildFeatureMap)
    features["responsive_web_graphql_exclude_directive_enabled"] = True

    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(features, separators=(",", ":")),
        "fieldToggles": json.dumps(field_toggles, separators=(",", ":")),
    }

    url = f"{GRAPHQL_BASE}/{query_id}/{operation_name}"

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code in (401, 403):
            logger.error(f"GraphQL {resp.status_code} — cookies may have expired or account restricted")
            return None
        if resp.status_code == 429:
            logger.error("GraphQL 429 Rate Limited — too many requests")
            return None

        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            for err in data["errors"]:
                logger.warning(f"GraphQL error: {err.get('message', 'unknown')}")

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


def _get_query_id(operation_name: str) -> str:
    """Get queryId for an operation, with caching and dynamic resolution."""
    global _query_cache, _cache_timestamp

    now = time.time()
    if _query_cache and (now - _cache_timestamp) < CACHE_TTL:
        if operation_name in _query_cache:
            return _query_cache[operation_name]

    resolved = resolve_query_ids()
    _query_cache = resolved
    _cache_timestamp = now

    fallbacks = _fallback_query_ids()
    return resolved.get(operation_name, fallbacks.get(operation_name, ""))


def _fallback_query_ids() -> Dict[str, str]:
    """Hardcoded fallback queryIds from baoyu constants.ts."""
    return {
        "TweetDetail": FALLBACK_TWEET_DETAIL_QUERY_ID,
        "TweetResultByRestId": FALLBACK_TWEET_RESULT_QUERY_ID,
        "ArticleEntityResultByRestId": FALLBACK_ARTICLE_QUERY_ID,
    }


def _fetch_home_html(user_agent: str) -> str:
    """Fetch and cache x.com homepage HTML (matches baoyu http.ts caching)."""
    global _cached_home_html

    if _cached_home_html:
        return _cached_home_html

    try:
        logger.debug("Fetching x.com homepage for JS bundle discovery...")
        resp = requests.get(
            "https://x.com",
            headers={"user-agent": user_agent},
            timeout=15,
        )
        resp.raise_for_status()
        _cached_home_html = resp.text
        return _cached_home_html
    except Exception as e:
        logger.warning(f"Failed to fetch x.com homepage: {e}")
        return ""


def _fetch_and_extract_query_id(
    chunk_url: str, operation_name: str, user_agent: str
) -> Optional[str]:
    """Download a JS bundle chunk and extract queryId for an operation."""
    try:
        resp = requests.get(
            chunk_url,
            headers={"user-agent": user_agent},
            timeout=15,
        )
        resp.raise_for_status()
        return _extract_query_id(resp.text, operation_name)
    except Exception as e:
        logger.debug(f"Failed to fetch/parse {chunk_url}: {e}")
        return None


def _extract_query_id(js_content: str, operation_name: str) -> Optional[str]:
    """
    Extract queryId for a given operationName from JS bundle content.

    Tries multiple regex patterns since X's bundle format can vary.
    """
    patterns = [
        rf'queryId:"([^"]+)",operationName:"{operation_name}"',
        rf'operationName:"{operation_name}"[^}}]*?queryId:"([^"]+)"',
        rf'\{{[^}}]*queryId:"([^"]+)"[^}}]*operationName:"{operation_name}"[^}}]*\}}',
    ]

    for pattern in patterns:
        match = re.search(pattern, js_content)
        if match:
            return match.group(1)

    return None


def _extract_article_ref(result: dict) -> Optional[Dict[str, Any]]:
    """
    Extract article entity reference from a tweet result.

    Matches baoyu tweet-article.ts resolveArticleEntityFromTweet() — checks
    multiple paths where articles can be embedded.
    """
    # Check various paths for embedded article
    for path in [
        lambda r: r.get("article", {}).get("article_results", {}).get("result"),
        lambda r: r.get("article", {}).get("result"),
        lambda r: r.get("legacy", {}).get("article", {}).get("article_results", {}).get("result"),
        lambda r: r.get("legacy", {}).get("article", {}).get("result"),
        lambda r: r.get("article_results", {}).get("result"),
    ]:
        try:
            article = path(result)
            if article and article.get("rest_id"):
                return {
                    "id": article.get("rest_id", ""),
                    "title": article.get("title", ""),
                    "has_content": bool(
                        article.get("content_state")
                        or article.get("plain_text")
                        or article.get("preview_text")
                    ),
                }
        except (TypeError, AttributeError):
            continue

    return None


_last_request_time: float = 0


def _rate_limit_wait():
    """
    Enforce minimum delay between GraphQL requests.

    Safety measure added in feedgrab — the original baoyu has no rate limiting,
    which risks account throttling with aggressive thread pagination.
    """
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    delay = DEFAULT_REQUEST_DELAY
    if elapsed < delay:
        wait = delay - elapsed
        logger.debug(f"Rate limiting: waiting {wait:.1f}s")
        time.sleep(wait)
    _last_request_time = time.time()
