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
from pathlib import Path
from typing import Dict, Any, Optional, List

from feedgrab.config import get_data_dir
from feedgrab.fetchers.twitter_cookies import (
    build_graphql_headers,
    DEFAULT_USER_AGENT,
)
from feedgrab.utils import http_client

# ---------------------------------------------------------------------------
# Fallback queryIds — from baoyu constants.ts
# ---------------------------------------------------------------------------

FALLBACK_TWEET_DETAIL_QUERY_ID = "xd_EMdYvB9hfZsZ6Idri0w"
FALLBACK_TWEET_RESULT_QUERY_ID = "7xflPyRiUxGVbJd4uWmbfg"
FALLBACK_ARTICLE_QUERY_ID = "id8pHQbQi7eZ6P9mA1th1Q"
FALLBACK_BOOKMARKS_QUERY_ID = "2neUNDqrrFzbLui8yallcQ"
FALLBACK_BOOKMARK_FOLDERS_QUERY_ID = "i78YDd0Tza-dV4SYs58kRg"
FALLBACK_BOOKMARK_FOLDER_TIMELINE_QUERY_ID = "8HoabOvl7jl9IC1Aixj-vg"
FALLBACK_USER_BY_SCREEN_NAME_QUERY_ID = "1VOOyvKkiI3FMmkeDNxM9A"
FALLBACK_USER_TWEETS_QUERY_ID = "q6xj5bs0hapm9309hexA_g"
FALLBACK_SEARCH_TIMELINE_QUERY_ID = "VhUd6vHVmLBcw0uX-6jMLA"
FALLBACK_LIST_BY_REST_ID_QUERY_ID = "BpXQqi3VImT8bR7pAf26rg"
FALLBACK_LIST_LATEST_TWEETS_QUERY_ID = "RlZzktZY_9wJynoepm8ZsA"

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
# Bookmarks feature switches and field toggles
# ---------------------------------------------------------------------------

BOOKMARK_FEATURES = dict(TWEET_DETAIL_FEATURES)
BOOKMARK_FEATURES["graphql_timeline_v2_bookmark_timeline"] = True

BOOKMARK_FIELD_TOGGLES = {
    "withArticleRichContentState": True,
    "withArticlePlainText": False,
    "withGrokAnalyze": False,
    "withDisallowedReplyControls": False,
}

# ---------------------------------------------------------------------------
# UserByScreenName & UserTweets feature switches
# ---------------------------------------------------------------------------

USER_BY_SCREEN_NAME_FEATURES = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
}

USER_TWEETS_FEATURES = dict(TWEET_DETAIL_FEATURES)
USER_TWEETS_FEATURES["creator_subscriptions_tweet_preview_api_enabled"] = True

# ---------------------------------------------------------------------------
# ListLatestTweetsTimeline feature switches
# ---------------------------------------------------------------------------

LIST_TWEETS_FEATURES = dict(TWEET_DETAIL_FEATURES)
LIST_TWEETS_FEATURES["rweb_lists_timeline_redesign_enabled"] = True

# ---------------------------------------------------------------------------
# SearchTimeline feature switches and field toggles
# ---------------------------------------------------------------------------

SEARCH_TIMELINE_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": False,
    "responsive_web_grok_imagine_annotation_enabled": False,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
}

SEARCH_TIMELINE_FIELD_TOGGLES = {
    "withPayments": False,
    "withAuxiliaryUserLabels": False,
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

# Cache for x-client-transaction-id generator
_transaction_generator = None
_transaction_generator_timestamp: float = 0
_TRANSACTION_TTL = 1800  # 30 min — homepage/ondemand.s can change

# Disk cache for homepage + ondemand data (avoids cold-start HTTP requests)
_DISK_CACHE_TTL = 3600  # 1 hour (matches twitter-cli)

# Community queryId source (fa0311/twitter-openapi)
_COMMUNITY_QUERYID_URL = (
    "https://raw.githubusercontent.com/fa0311/twitter-openapi/"
    "main/src/config/placeholder.json"
)


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


def fetch_bookmarks_page(
    cookies: dict, cursor: str = None, count: int = 20
) -> Optional[Dict[str, Any]]:
    """
    Fetch one page of the authenticated user's bookmarks.

    Args:
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor from a previous response.
        count: Number of bookmarks per page (default 20).

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("Bookmarks")
    headers = build_graphql_headers(cookies)

    variables = {
        "count": count,
        "includePromotedContent": False,
        "withClientEventToken": False,
        "withBirdwatchNotes": False,
        "withVoice": True,
        "withV2Timeline": True,
    }

    if cursor:
        variables["cursor"] = cursor
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="Bookmarks",
        variables=variables,
        features=dict(BOOKMARK_FEATURES),
        field_toggles=dict(BOOKMARK_FIELD_TOGGLES),
        headers=headers,
    )


def fetch_bookmark_folders(cookies: dict) -> list:
    """
    Fetch the user's bookmark folder list via BookmarkFoldersSlice.

    Returns:
        [{"id": "...", "name": "OpenClaw"}, ...]
        Empty list on failure.
    """
    query_id = _get_query_id("BookmarkFoldersSlice")
    headers = build_graphql_headers(cookies)

    response = _execute_graphql(
        query_id=query_id,
        operation_name="BookmarkFoldersSlice",
        variables={},
        features={},
        field_toggles={},
        headers=headers,
    )

    if not response or "data" not in response:
        logger.warning("[BookmarkFolders] API returned empty response")
        return []

    data = response["data"]

    # Response path not yet verified by packet capture — try multiple paths
    # Path 0: data.viewer.user_results.result.bookmark_collections_slice.items (actual)
    items = (
        data.get("viewer", {})
        .get("user_results", {})
        .get("result", {})
        .get("bookmark_collections_slice", {})
        .get("items", [])
    )
    # Path 1: data.bookmark_collections_slice.items (from twikit)
    if not items:
        items = data.get("bookmark_collections_slice", {}).get("items", [])
    # Path 2: data.bookmarkFoldersSlice.folders
    if not items:
        items = data.get("bookmarkFoldersSlice", {}).get("folders", [])
    # Path 3: deep scan — find any list of dicts with "name" key
    if not items:
        def _find_folder_items(obj, depth=0):
            if depth > 5:
                return []
            if isinstance(obj, list) and obj and isinstance(obj[0], dict) and "name" in obj[0]:
                return obj
            if isinstance(obj, dict):
                for v in obj.values():
                    found = _find_folder_items(v, depth + 1)
                    if found:
                        return found
            return []
        items = _find_folder_items(data)

    if not items:
        logger.warning(f"[BookmarkFolders] Could not parse folders from response keys: {list(data.keys())}")
        logger.debug(f"[BookmarkFolders] Raw response: {json.dumps(data, ensure_ascii=False)[:500]}")

    folders = []
    for item in items:
        fid = item.get("id", "")
        fname = item.get("name", "")
        if fid and fname:
            folders.append({"id": str(fid), "name": fname})

    logger.info(f"[BookmarkFolders] Found {len(folders)} folders")
    return folders


def fetch_bookmark_folder_page(
    folder_id: str, cookies: dict, cursor: str = None, count: int = 20
) -> Optional[Dict[str, Any]]:
    """
    Fetch one page of tweets from a specific bookmark folder.

    Args:
        folder_id: The numeric bookmark folder ID.
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor.
        count: Items per page (default 20).

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("BookmarkFolderTimeline")
    headers = build_graphql_headers(cookies)

    variables = {
        "count": count,
        "includePromotedContent": True,
        "bookmark_collection_id": folder_id,
    }

    if cursor:
        variables["cursor"] = cursor
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="BookmarkFolderTimeline",
        variables=variables,
        features=dict(BOOKMARK_FEATURES),
        field_toggles=dict(BOOKMARK_FIELD_TOGGLES),
        headers=headers,
    )


def fetch_user_by_screen_name(screen_name: str, cookies: dict) -> Dict[str, str]:
    """
    Resolve a screen_name to user_id and display name via UserByScreenName API.

    Args:
        screen_name: Twitter handle without '@' (e.g. 'iBigQiang').
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        {"user_id": "123", "screen_name": "iBigQiang", "name": "强子手记"}
    """
    query_id = _get_query_id("UserByScreenName")
    headers = build_graphql_headers(cookies)

    variables = {
        "screen_name": screen_name,
        "withSafetyModeUserFields": True,
    }

    response = _execute_graphql(
        query_id=query_id,
        operation_name="UserByScreenName",
        variables=variables,
        features=dict(USER_BY_SCREEN_NAME_FEATURES),
        field_toggles={},
        headers=headers,
    )

    if not response or "data" not in response:
        logger.warning(f"[UserByScreenName] API returned empty for @{screen_name}")
        return {"user_id": "", "screen_name": screen_name, "name": ""}

    result = response.get("data", {}).get("user", {}).get("result", {})
    return {
        "user_id": result.get("rest_id", ""),
        "screen_name": result.get("legacy", {}).get("screen_name", screen_name),
        "name": result.get("legacy", {}).get("name", ""),
    }


def fetch_user_tweets_page(
    user_id: str, cookies: dict, cursor: str = None, count: int = 20
) -> Optional[Dict[str, Any]]:
    """
    Fetch one page of a user's tweets via UserTweets GraphQL endpoint.

    Args:
        user_id: The numeric user ID (from fetch_user_by_screen_name).
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor from a previous response.
        count: Number of tweets per page (default 20).

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("UserTweets")
    headers = build_graphql_headers(cookies)

    variables = {
        "userId": user_id,
        "count": count,
        "includePromotedContent": True,
        "withQuickPromoteEligibilityTweetFields": True,
        "withVoice": True,
        "withV2Timeline": True,
    }

    if cursor:
        variables["cursor"] = cursor
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="UserTweets",
        variables=variables,
        features=dict(USER_TWEETS_FEATURES),
        field_toggles=dict(BOOKMARK_FIELD_TOGGLES),
        headers=headers,
    )


def parse_user_tweets_entries(response: Dict[str, Any]) -> tuple:
    """
    Extract tweet entries and pagination cursors from a UserTweets GraphQL response.

    Response path: data.user.result.timeline_v2.timeline.instructions

    Returns:
        (entries, cursors) — entries can be passed to extract_tweet_data(),
        cursors is a dict with optional 'top' and 'bottom' keys.
    """
    if not response or "data" not in response:
        return [], {}

    data = response["data"]

    # Primary path: data.user.result.timeline_v2.timeline.instructions
    instructions = (
        data.get("user", {})
        .get("result", {})
        .get("timeline_v2", {})
        .get("timeline", {})
        .get("instructions", [])
    )
    # Fallback: data.user.result.timeline.timeline.instructions
    if not instructions:
        instructions = (
            data.get("user", {})
            .get("result", {})
            .get("timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )

    entries = []
    cursors = {}

    for instruction in instructions:
        inst_type = instruction.get("type", "")

        if inst_type == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {})

                # Extract cursor entries
                if entry_id.startswith("cursor-"):
                    cursor_type = content.get("cursorType", "")
                    value = content.get("value", "")
                    if cursor_type == "Top" and value:
                        cursors["top"] = value
                    elif cursor_type == "Bottom" and value:
                        cursors["bottom"] = value
                    continue

                # Skip promoted content
                if "promoted" in entry_id.lower():
                    continue

                # UserTweets wraps tweets in TimelineTimelineModule with items[]
                if content.get("entryType") == "TimelineTimelineModule":
                    for item in content.get("items", []):
                        # Filter non-tweet items (e.g. "Who to Follow" cards)
                        item_type = (item.get("item", {})
                                     .get("itemContent", {})
                                     .get("itemType", ""))
                        if item_type == "TimelineTweet":
                            entries.append(item)
                elif content.get("entryType") == "TimelineTimelineItem":
                    # Only keep tweet items, skip "who to follow" / "trends" etc.
                    item_type = content.get("itemContent", {}).get("itemType", "")
                    if item_type == "TimelineTweet":
                        entries.append(entry)
                else:
                    entries.append(entry)

        elif inst_type == "TimelineAddToModule":
            for item in instruction.get("moduleItems", []):
                item_type = (item.get("item", {})
                             .get("itemContent", {})
                             .get("itemType", ""))
                if item_type == "TimelineTweet":
                    entries.append(item)

    return entries, cursors


# ---------------------------------------------------------------------------
# List timeline: fetch metadata + tweets
# ---------------------------------------------------------------------------

def fetch_list_by_rest_id(list_id: str, cookies: dict) -> Dict[str, str]:
    """
    Fetch list metadata (name, description, member count) via ListByRestId.

    Args:
        list_id: Numeric list ID (e.g. '2002743803959300263').
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        {"list_id": "...", "name": "...", "description": "...", "member_count": 0}
    """
    query_id = _get_query_id("ListByRestId")
    headers = build_graphql_headers(cookies)

    variables = {
        "listId": list_id,
        "withSuperFollowsUserFields": True,
    }

    response = _execute_graphql(
        query_id=query_id,
        operation_name="ListByRestId",
        variables=variables,
        features=dict(USER_BY_SCREEN_NAME_FEATURES),
        field_toggles={},
        headers=headers,
    )

    if not response or "data" not in response:
        logger.warning(f"[ListByRestId] API returned empty for list {list_id}")
        return {"list_id": list_id, "name": "", "description": "", "member_count": 0}

    lst = response.get("data", {}).get("list", {})
    return {
        "list_id": lst.get("id_str", list_id),
        "name": lst.get("name", ""),
        "description": lst.get("description", ""),
        "member_count": lst.get("member_count", 0),
    }


def fetch_list_tweets_page(
    list_id: str, cookies: dict, cursor: str = None, count: int = 20
) -> Optional[Dict[str, Any]]:
    """
    Fetch one page of tweets from a Twitter List via ListLatestTweetsTimeline.

    Args:
        list_id: Numeric list ID.
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor from a previous response.
        count: Number of tweets per page (default 20).

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("ListLatestTweetsTimeline")
    headers = build_graphql_headers(cookies)

    variables = {
        "listId": list_id,
        "count": count,
        "withDownvotePerspective": False,
        "withReactionsMetadata": False,
        "withReactionsPerspective": False,
        "withSuperFollowsTweetFields": True,
        "withSuperFollowsUserFields": True,
        "withBirdwatchNotes": True,
    }

    if cursor:
        variables["cursor"] = cursor
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="ListLatestTweetsTimeline",
        variables=variables,
        features=dict(LIST_TWEETS_FEATURES),
        field_toggles=dict(BOOKMARK_FIELD_TOGGLES),
        headers=headers,
    )


def parse_list_tweets_entries(response: Dict[str, Any]) -> tuple:
    """
    Extract tweet entries and pagination cursors from a ListLatestTweetsTimeline response.

    Response path: data.list.tweets_timeline.timeline.instructions

    Returns:
        (entries, cursors) — entries can be passed to extract_tweet_data(),
        cursors is a dict with optional 'top' and 'bottom' keys.
    """
    if not response or "data" not in response:
        return [], {}

    data = response["data"]

    # Primary path: data.list.tweets_timeline.timeline.instructions
    instructions = (
        data.get("list", {})
        .get("tweets_timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )

    entries = []
    cursors = {}

    for instruction in instructions:
        inst_type = instruction.get("type", "")

        if inst_type == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {})

                # Extract cursor entries
                if entry_id.startswith("cursor-"):
                    cursor_type = content.get("cursorType", "")
                    value = content.get("value", "")
                    if cursor_type == "Top" and value:
                        cursors["top"] = value
                    elif cursor_type == "Bottom" and value:
                        cursors["bottom"] = value
                    continue

                # Skip promoted content
                if "promoted" in entry_id.lower():
                    continue

                # Filter to tweet items only
                item_type = content.get("itemContent", {}).get("itemType", "")
                if item_type == "TimelineTweet":
                    entries.append(entry)
                elif content.get("entryType") == "TimelineTimelineModule":
                    for item in content.get("items", []):
                        sub_type = (item.get("item", {})
                                    .get("itemContent", {})
                                    .get("itemType", ""))
                        if sub_type == "TimelineTweet":
                            entries.append(item)

        elif inst_type == "TimelineAddToModule":
            for item in instruction.get("moduleItems", []):
                item_type = (item.get("item", {})
                             .get("itemContent", {})
                             .get("itemType", ""))
                if item_type == "TimelineTweet":
                    entries.append(item)

    return entries, cursors


def parse_bookmark_entries(response: Dict[str, Any]) -> tuple:
    """
    Extract tweet entries and pagination cursors from a Bookmarks GraphQL response.

    Supports both Bookmarks and BookmarkFolderTimeline responses.
    Response path: data.bookmark_timeline_v2.timeline.instructions
    (different from TweetDetail's threaded_conversation_with_injections_v2)

    Returns:
        (entries, cursors) — entries can be passed to extract_tweet_data(),
        cursors is a dict with optional 'top' and 'bottom' keys.
    """
    if not response or "data" not in response:
        return [], {}

    data = response["data"]

    # Try multiple response paths:
    # Path 1: bookmark_timeline_v2 (Bookmarks endpoint)
    instructions = (
        data.get("bookmark_timeline_v2", {})
        .get("timeline", {})
        .get("instructions", [])
    )
    # Path 2: bookmark_folder_timeline (BookmarkFolderTimeline endpoint)
    if not instructions:
        instructions = (
            data.get("bookmark_folder_timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
    # Path 3: generic scan for instructions in nested timeline objects
    if not instructions:
        for v in data.values():
            if isinstance(v, dict):
                timeline = v.get("timeline", {})
                if isinstance(timeline, dict):
                    inst = timeline.get("instructions", [])
                    if inst:
                        instructions = inst
                        break

    entries = []
    cursors = {}

    for instruction in instructions:
        inst_type = instruction.get("type", "")

        if inst_type == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {})

                # Extract cursor entries
                if entry_id.startswith("cursor-"):
                    cursor_type = content.get("cursorType", "")
                    value = content.get("value", "")
                    if cursor_type == "Top" and value:
                        cursors["top"] = value
                    elif cursor_type == "Bottom" and value:
                        cursors["bottom"] = value
                    continue

                # Skip promoted content
                if "promoted" in entry_id.lower():
                    continue

                entries.append(entry)

        elif inst_type == "TimelineAddToModule":
            for item in instruction.get("moduleItems", []):
                entries.append(item)

    return entries, cursors


def fetch_search_timeline_page(
    raw_query: str,
    cookies: dict,
    cursor: str = None,
    count: int = 20,
    product: str = "Latest",
) -> Optional[Dict[str, Any]]:
    """
    Fetch one page of search results via SearchTimeline GraphQL endpoint.

    Args:
        raw_query: Search query string (e.g. "from:username since:2025-01-01 until:2025-02-01").
        cookies: dict with 'auth_token' and 'ct0'.
        cursor: Optional pagination cursor from a previous response.
        count: Number of results per page (default 20).
        product: Search product type — "Latest" (chronological) or "Top" (relevance).

    Returns:
        Raw GraphQL response dict, or None on failure.
    """
    query_id = _get_query_id("SearchTimeline")
    headers = build_graphql_headers(cookies)

    variables = {
        "rawQuery": raw_query,
        "count": count,
        "querySource": "typed_query",
        "product": product,
        "withGrokTranslatedBio": False,
    }

    if cursor:
        variables["cursor"] = cursor
        _rate_limit_wait()

    return _execute_graphql(
        query_id=query_id,
        operation_name="SearchTimeline",
        variables=variables,
        features=dict(SEARCH_TIMELINE_FEATURES),
        field_toggles=dict(SEARCH_TIMELINE_FIELD_TOGGLES),
        headers=headers,
    )


def parse_search_entries(response: Dict[str, Any]) -> tuple:
    """
    Extract tweet entries and pagination cursors from a SearchTimeline GraphQL response.

    Response path: data.search_by_raw_query.search_timeline.timeline.instructions

    Returns:
        (entries, cursors) — entries can be passed to extract_tweet_data(),
        cursors is a dict with optional 'top' and 'bottom' keys.
    """
    if not response or "data" not in response:
        return [], {}

    data = response["data"]

    # Primary path
    instructions = (
        data.get("search_by_raw_query", {})
        .get("search_timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )

    entries = []
    cursors = {}

    for instruction in instructions:
        inst_type = instruction.get("type", "")

        if inst_type == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entry_id = entry.get("entryId", "")
                content = entry.get("content", {})

                # Extract cursor entries
                if entry_id.startswith("cursor-"):
                    cursor_type = content.get("cursorType", "")
                    value = content.get("value", "")
                    if cursor_type == "Top" and value:
                        cursors["top"] = value
                    elif cursor_type == "Bottom" and value:
                        cursors["bottom"] = value
                    continue

                # Skip promoted content
                if "promoted" in entry_id.lower():
                    continue

                entries.append(entry)

        elif inst_type == "TimelineAddToModule":
            for item in instruction.get("moduleItems", []):
                entries.append(item)

        elif inst_type == "TimelineReplaceEntry":
            # Page 2+ returns cursors via ReplaceEntry instead of AddEntries
            entry = instruction.get("entry", {})
            entry_id = entry.get("entryId", "")
            content = entry.get("content", {})
            if entry_id.startswith("cursor-"):
                cursor_type = content.get("cursorType", "")
                value = content.get("value", "")
                if cursor_type == "Top" and value:
                    cursors["top"] = value
                elif cursor_type == "Bottom" and value:
                    cursors["bottom"] = value

    return entries, cursors

def resolve_query_ids(user_agent: str = None) -> Dict[str, str]:
    """
    Dynamically resolve queryIds from multiple sources.

    Resolution order (first wins per operation):
        Tier 0: Disk cache (queryids from previous run, < 1h old)
        Tier 1: Community source (fa0311/twitter-openapi, single HTTP request)
        Tier 2: JS bundle scan (x.com HTML → per-bundle JS downloads)
        Tier 3: Hardcoded fallback constants

    Returns:
        Dict mapping operation_name → query_id.
    """
    ua = user_agent or DEFAULT_USER_AGENT
    result = {}
    all_ops = set(_fallback_query_ids())

    # --- Tier 0: Disk cache ---
    cached_ids = _load_queryid_cache()
    if cached_ids:
        for op in all_ops:
            if op in cached_ids:
                result[op] = cached_ids[op]
        if len(result) >= len(all_ops):
            logger.debug(f"All {len(result)} queryIds loaded from disk cache")
            return result

    # --- Tier 1: Community source (fa0311/twitter-openapi) ---
    if set(result) < all_ops:
        community = _resolve_community_query_ids()
        for op in all_ops:
            if op not in result and op in community:
                result[op] = community[op]
        if len(result) >= len(all_ops):
            logger.debug(f"All {len(result)} queryIds resolved (cache + community)")
            _save_queryid_cache(result)
            return result

    # --- Tier 2: JS bundle scan (only for missing operations) ---
    missing = all_ops - set(result)

    if missing:
        try:
            html = _fetch_home_html(ua)
            if html:
                # TweetDetail — from api.<hash>a.js
                if "TweetDetail" in missing:
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
                if "TweetResultByRestId" in missing and main_match:
                    chunk_hash = main_match.group(1)
                    chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
                    qid = _fetch_and_extract_query_id(chunk_url, "TweetResultByRestId", ua)
                    if qid:
                        result["TweetResultByRestId"] = qid
                        logger.debug(f"Resolved TweetResultByRestId: queryId={qid}")

                # ArticleEntityResultByRestId — from bundle.TwitterArticles.<hash>a.js
                if "ArticleEntityResultByRestId" in missing:
                    article_match = re.search(r'bundle\.TwitterArticles:"([a-zA-Z0-9]+)"', html)
                    if article_match:
                        chunk_hash = article_match.group(1)
                        chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.TwitterArticles.{chunk_hash}a.js"
                        qid = _fetch_and_extract_query_id(chunk_url, "ArticleEntityResultByRestId", ua)
                        if qid:
                            result["ArticleEntityResultByRestId"] = qid
                            logger.debug(f"Resolved ArticleEntityResultByRestId: queryId={qid}")

                # Bookmarks — typically in main.<hash>.js
                if "Bookmarks" not in result and main_match:
                    chunk_hash = main_match.group(1)
                    chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
                    qid = _fetch_and_extract_query_id(chunk_url, "Bookmarks", ua)
                    if qid:
                        result["Bookmarks"] = qid
                        logger.debug(f"Resolved Bookmarks: queryId={qid}")

                # BookmarkFoldersSlice & BookmarkFolderTimeline
                bkf_ops_missing = {"BookmarkFoldersSlice", "BookmarkFolderTimeline"} - set(result)
                if bkf_ops_missing:
                    bkf_match = re.search(r'bundle\.BookmarkFolders:"([a-zA-Z0-9]+)"', html)
                    if bkf_match:
                        chunk_hash = bkf_match.group(1)
                        chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.BookmarkFolders.{chunk_hash}a.js"
                        for op in bkf_ops_missing.copy():
                            qid = _fetch_and_extract_query_id(chunk_url, op, ua)
                            if qid:
                                result[op] = qid
                                bkf_ops_missing.discard(op)
                                logger.debug(f"Resolved {op}: queryId={qid}")

                    # Also try main bundle for bookmark folder ops
                    if bkf_ops_missing and main_match:
                        chunk_hash = main_match.group(1)
                        chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
                        for op in bkf_ops_missing:
                            qid = _fetch_and_extract_query_id(chunk_url, op, ua)
                            if qid:
                                result[op] = qid
                                logger.debug(f"Resolved {op}: queryId={qid}")

                # UserByScreenName & UserTweets & List ops — typically in main bundle
                main_ops_missing = {"UserByScreenName", "UserTweets", "ListByRestId", "ListLatestTweetsTimeline"} - set(result)
                if main_ops_missing and main_match:
                    chunk_hash = main_match.group(1)
                    chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
                    for op in main_ops_missing:
                        qid = _fetch_and_extract_query_id(chunk_url, op, ua)
                        if qid:
                            result[op] = qid
                            logger.debug(f"Resolved {op}: queryId={qid}")

                # SearchTimeline — try main bundle first, then search-related bundles
                if "SearchTimeline" not in result:
                    if main_match:
                        chunk_hash = main_match.group(1)
                        chunk_url = f"https://abs.twimg.com/responsive-web/client-web/main.{chunk_hash}a.js"
                        qid = _fetch_and_extract_query_id(chunk_url, "SearchTimeline", ua)
                        if qid:
                            result["SearchTimeline"] = qid
                            logger.debug(f"Resolved SearchTimeline from main: queryId={qid}")

                    if "SearchTimeline" not in result:
                        for pattern in [
                            r'bundle\.search:"([a-zA-Z0-9]+)"',
                            r'bundle\.Search:"([a-zA-Z0-9]+)"',
                            r'bundle\.SearchTimeline:"([a-zA-Z0-9]+)"',
                            r'bundle\.explore:"([a-zA-Z0-9]+)"',
                            r'bundle\.Explore:"([a-zA-Z0-9]+)"',
                        ]:
                            bm = re.search(pattern, html)
                            if bm:
                                chunk_hash = bm.group(1)
                                bundle_name = pattern.split(r'\.')[1].split(':')[0].rstrip('\\')
                                chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.{bundle_name}.{chunk_hash}a.js"
                                qid = _fetch_and_extract_query_id(chunk_url, "SearchTimeline", ua)
                                if qid:
                                    result["SearchTimeline"] = qid
                                    logger.debug(f"Resolved SearchTimeline from bundle.{bundle_name}: queryId={qid}")
                                    break

                    # Brute-force: scan all bundle.* entries in HTML for SearchTimeline
                    if "SearchTimeline" not in result:
                        for bm in re.finditer(r'bundle\.(\w+):"([a-zA-Z0-9]+)"', html):
                            bundle_name = bm.group(1)
                            chunk_hash = bm.group(2)
                            chunk_url = f"https://abs.twimg.com/responsive-web/client-web/bundle.{bundle_name}.{chunk_hash}a.js"
                            qid = _fetch_and_extract_query_id(chunk_url, "SearchTimeline", ua)
                            if qid:
                                result["SearchTimeline"] = qid
                                logger.debug(f"Resolved SearchTimeline from bundle.{bundle_name}: queryId={qid}")
                                break

                    # Last resort: extract main JS URL from <script src="...main.HASH.js">
                    if "SearchTimeline" not in result:
                        main_src = re.search(
                            r'src="(https://abs\.twimg\.com/responsive-web/client-web/main\.[a-zA-Z0-9]+\.js)"',
                            html,
                        )
                        if main_src:
                            qid = _fetch_and_extract_query_id(main_src.group(1), "SearchTimeline", ua)
                            if qid:
                                result["SearchTimeline"] = qid
                                logger.debug(f"Resolved SearchTimeline from script src: queryId={qid}")

        except Exception as e:
            logger.warning(f"Dynamic queryId resolution failed ({e}), using fallbacks")

    # --- Tier 3: Hardcoded fallbacks ---
    fallbacks = _fallback_query_ids()
    for op, qid in fallbacks.items():
        if op not in result:
            result[op] = qid

    # Save resolved queryIds to disk for next cold start
    _save_queryid_cache(result)

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
    # New API format: screen_name/name moved to user_results.result.core
    user_core = user_results.get("core", {})

    # Extract note_tweet (long text) if available — priority over legacy.full_text
    note_tweet = (
        result.get("note_tweet", {})
        .get("note_tweet_results", {})
        .get("result", {})
    )
    full_text = note_tweet.get("text") or legacy.get("full_text", "")

    # Expand t.co short URLs to original URLs (note_tweet entity_set first, then legacy)
    note_urls = note_tweet.get("entity_set", {}).get("urls", [])
    legacy_urls = legacy.get("entities", {}).get("urls", [])
    for url_entity in (note_urls or legacy_urls):
        short_url = url_entity.get("url", "")
        expanded_url = url_entity.get("expanded_url", "")
        if short_url and expanded_url and short_url in full_text:
            full_text = full_text.replace(short_url, expanded_url)

    # Apply richtext_tags (bold/italic) from note_tweet to produce Markdown formatting
    full_text = _apply_richtext_tags(full_text, note_tweet)

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

    # Extract quoted tweet (full data: long text, media, metrics, t.co expansion)
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
        )
        q_user_legacy = q_user.get("legacy", {})
        q_user_core = q_user.get("core", {})

        # Use note_tweet for full text (avoids 280-char truncation)
        q_note = (
            quoted_status.get("note_tweet", {})
            .get("note_tweet_results", {})
            .get("result", {})
        )
        q_text = q_note.get("text") or q_legacy.get("full_text", "")

        # Expand t.co URLs in quoted tweet
        q_note_urls = q_note.get("entity_set", {}).get("urls", [])
        q_legacy_urls = q_legacy.get("entities", {}).get("urls", [])
        for q_url_ent in (q_note_urls or q_legacy_urls):
            q_short = q_url_ent.get("url", "")
            q_expanded = q_url_ent.get("expanded_url", "")
            if q_short and q_expanded and q_short in q_text:
                q_text = q_text.replace(q_short, q_expanded)

        # Apply richtext_tags to quoted tweet text
        q_text = _apply_richtext_tags(q_text, q_note)

        # Extract media from quoted tweet
        q_media_list = q_legacy.get("extended_entities", {}).get("media", [])
        q_images = []
        q_videos = []
        for q_media in q_media_list:
            q_mtype = q_media.get("type", "")
            if q_mtype == "photo":
                q_images.append(q_media.get("media_url_https", ""))
            elif q_mtype in ("video", "animated_gif"):
                q_variants = q_media.get("video_info", {}).get("variants", [])
                q_mp4s = [v for v in q_variants if v.get("content_type") == "video/mp4"]
                if q_mp4s:
                    q_best = max(q_mp4s, key=lambda v: v.get("bitrate", 0))
                    q_videos.append(q_best.get("url", ""))
                q_images.append(q_media.get("media_url_https", ""))

        # Remove trailing media t.co URL from text
        for q_media in q_legacy.get("entities", {}).get("media", []):
            q_short = q_media.get("url", "")
            if q_short and q_short in q_text:
                q_text = q_text.replace(q_short, "").strip()

        q_screen_name = q_user_legacy.get("screen_name", "") or q_user_core.get("screen_name", "")
        quoted_tweet = {
            "id": q_legacy.get("id_str", ""),
            "text": q_text,
            "author": q_screen_name,
            "author_name": q_user_legacy.get("name", "") or q_user_core.get("name", ""),
            "images": q_images,
            "videos": q_videos,
            "likes": q_legacy.get("favorite_count", 0),
            "retweets": q_legacy.get("retweet_count", 0),
            "views": quoted_status.get("views", {}).get("count", "0"),
            "url": f"https://x.com/{q_screen_name}/status/{q_legacy.get('id_str', '')}",
        }

    # Extract article reference if present
    article = _extract_article_ref(result)

    # Extract hashtags from entities (check note_tweet entity_set first, then legacy)
    note_hashtags = note_tweet.get("entity_set", {}).get("hashtags", [])
    legacy_hashtags = legacy.get("entities", {}).get("hashtags", [])
    raw_hashtags = note_hashtags or legacy_hashtags
    hashtags = [h.get("text", "") for h in raw_hashtags if h.get("text")]

    return {
        "id": legacy.get("id_str", result.get("rest_id", "")),
        "rest_id": result.get("rest_id", ""),
        "text": full_text,
        "author": user_legacy.get("screen_name", "") or user_core.get("screen_name", ""),
        "author_name": user_legacy.get("name", "") or user_core.get("name", ""),
        "user_id": user_legacy.get("id_str", "") or user_results.get("rest_id", "") or legacy.get("user_id_str", ""),
        "conversation_id": legacy.get("conversation_id_str", ""),
        "in_reply_to_user_id": legacy.get("in_reply_to_user_id_str", ""),
        "in_reply_to_status_id": legacy.get("in_reply_to_status_id_str", ""),
        "created_at": legacy.get("created_at", ""),
        "images": images,
        "videos": videos,
        "quoted_tweet": quoted_tweet,
        "article": article,
        "hashtags": hashtags,
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "bookmarks": legacy.get("bookmark_count", 0),
        "views": result.get("views", {}).get("count", "0"),
        # New metadata fields
        "quote_count": legacy.get("quote_count", 0),
        "lang": legacy.get("lang", ""),
        "source_app": _parse_source_app(result.get("source", "")),
        "possibly_sensitive": legacy.get("possibly_sensitive", False),
        # Author profile fields
        "is_blue_verified": user_results.get("is_blue_verified", False),
        "followers_count": user_legacy.get("followers_count", 0),
        "statuses_count": user_legacy.get("statuses_count", 0),
        "listed_count": user_legacy.get("listed_count", 0),
        # Keep raw result for article extraction in later PRs
        "_raw_result": result,
    }


# ---------------------------------------------------------------------------
# Disk cache helpers
# ---------------------------------------------------------------------------

def _disk_cache_path(name: str) -> Path:
    """Return path to a disk cache file under {data_dir}/cache/."""
    return get_data_dir() / "cache" / name


def _load_transaction_cache() -> Optional[dict]:
    """Load cached homepage HTML + ondemand.s text from disk (1h TTL)."""
    path = _disk_cache_path("twitter_transaction_cache.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) >= _DISK_CACHE_TTL:
            return None
        if "home_html" not in data or "ondemand_text" not in data:
            return None
        return data
    except Exception:
        return None


def _save_transaction_cache(home_html: str, ondemand_text: str):
    """Save homepage HTML + ondemand.s text to disk cache."""
    path = _disk_cache_path("twitter_transaction_cache.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ts": time.time(),
            "home_html": home_html,
            "ondemand_text": ondemand_text,
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        logger.debug(f"Transaction cache saved to {path}")
    except Exception as e:
        logger.debug(f"Failed to save transaction cache: {e}")


def _load_queryid_cache() -> Optional[Dict[str, str]]:
    """Load cached queryIds from disk (1h TTL)."""
    path = _disk_cache_path("twitter_queryid_cache.json")
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) >= _DISK_CACHE_TTL:
            return None
        return data.get("ids", {})
    except Exception:
        return None


def _save_queryid_cache(query_ids: Dict[str, str]):
    """Save resolved queryIds to disk cache."""
    path = _disk_cache_path("twitter_queryid_cache.json")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"ts": time.time(), "ids": query_ids}
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        logger.debug(f"QueryId cache saved to {path} ({len(query_ids)} ops)")
    except Exception as e:
        logger.debug(f"Failed to save queryId cache: {e}")


def _resolve_community_query_ids() -> Dict[str, str]:
    """Fetch queryIds from fa0311/twitter-openapi community source.

    Returns a dict mapping operationName → queryId. On failure returns {}.
    The community source is a single HTTP request to GitHub raw content.
    """
    try:
        resp = http_client.get(
            _COMMUNITY_QUERYID_URL,
            headers={"user-agent": DEFAULT_USER_AGENT},
            timeout=8,
        )
        http_client.raise_for_status(resp)
        data = resp.json()
        result = {}
        for op_name, op_data in data.items():
            if isinstance(op_data, dict) and "queryId" in op_data:
                result[op_name] = op_data["queryId"]
        if result:
            logger.debug(f"[GraphQL] Community source: {len(result)} queryIds fetched")
        return result
    except Exception as e:
        logger.debug(f"[GraphQL] Community queryId source unavailable: {e}")
        return {}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_transaction_id(method: str, path: str) -> str:
    """Generate x-client-transaction-id for Twitter anti-bot verification.

    Uses XClientTransaction library to compute a signed header value
    based on x.com homepage SVG animations + ondemand.s JS indices.
    Caches the generator instance in memory (TTL 30 min) and source
    data on disk (TTL 1 hour) to avoid cold-start HTTP requests.
    Returns empty string if generation fails (graceful degradation).
    """
    global _transaction_generator, _transaction_generator_timestamp, _cached_home_html

    now = time.time()

    # Re-initialize if expired or not yet created
    if _transaction_generator is None or (now - _transaction_generator_timestamp) >= _TRANSACTION_TTL:
        try:
            import bs4
            from x_client_transaction import ClientTransaction
            from x_client_transaction.utils import get_ondemand_file_url

            ua = DEFAULT_USER_AGENT
            home_html = None
            ondemand_text = None

            # Try disk cache first (avoids 2 HTTP requests on cold start)
            cached = _load_transaction_cache()
            if cached:
                home_html = cached["home_html"]
                ondemand_text = cached["ondemand_text"]
                logger.debug("x-client-transaction-id: loaded from disk cache")
            else:
                # Fetch from network
                home_resp = http_client.get(
                    "https://x.com", headers={"user-agent": ua}, timeout=15,
                )
                home_html = home_resp.text

                home_soup = bs4.BeautifulSoup(home_html, "html.parser")
                ondemand_url = get_ondemand_file_url(response=home_soup)
                ondemand_resp = http_client.get(
                    ondemand_url, headers={"user-agent": ua}, timeout=15,
                )
                ondemand_text = ondemand_resp.text

                # Save to disk cache for next cold start
                _save_transaction_cache(home_html, ondemand_text)

            # Also populate _cached_home_html for queryId JS bundle scan
            if not _cached_home_html and home_html:
                _cached_home_html = home_html

            home_soup = bs4.BeautifulSoup(home_html, "html.parser")
            _transaction_generator = ClientTransaction(
                home_page_response=home_soup,
                ondemand_file_response=ondemand_text,
            )
            _transaction_generator_timestamp = now
            logger.debug("x-client-transaction-id generator initialized")
        except ImportError:
            logger.warning(
                "[GraphQL] XClientTransaction not installed. "
                "Some endpoints (SearchTimeline) may return 404.\n"
                "  pip install XClientTransaction"
            )
            return ""
        except Exception as e:
            logger.warning(f"[GraphQL] Failed to init transaction generator: {e}")
            return ""

    try:
        return _transaction_generator.generate_transaction_id(
            method=method, path=path,
        )
    except Exception as e:
        logger.debug(f"[GraphQL] Failed to generate transaction id: {e}")
        return ""


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

    # Compact encoding: only send True-valued features (Twitter ignores
    # absent keys, treating them as false).  This reduces URL length by
    # ~30%, avoiding potential HTTP 414 URI Too Long errors.
    compact_features = {k: v for k, v in features.items() if v}

    params = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(compact_features, separators=(",", ":")),
        "fieldToggles": json.dumps(field_toggles, separators=(",", ":")),
    }

    url = f"{GRAPHQL_BASE}/{query_id}/{operation_name}"

    # Inject x-client-transaction-id (required by SearchTimeline etc.)
    path = f"/i/api/graphql/{query_id}/{operation_name}"
    tid = _get_transaction_id("GET", path)
    if tid:
        headers["x-client-transaction-id"] = tid

    try:
        resp = http_client.get(url, params=params, headers=headers, timeout=30)

        if resp.status_code in (401, 403):
            logger.error(f"GraphQL {resp.status_code} — cookies may have expired or account restricted")
            return None
        if resp.status_code == 429:
            logger.error("GraphQL 429 Rate Limited — too many requests")
            # Notify cookie rotation system
            from feedgrab.fetchers.twitter_cookies import mark_cookie_rate_limited
            mark_cookie_rate_limited()
            return None

        http_client.raise_for_status(resp)
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
        "Bookmarks": FALLBACK_BOOKMARKS_QUERY_ID,
        "BookmarkFoldersSlice": FALLBACK_BOOKMARK_FOLDERS_QUERY_ID,
        "BookmarkFolderTimeline": FALLBACK_BOOKMARK_FOLDER_TIMELINE_QUERY_ID,
        "UserByScreenName": FALLBACK_USER_BY_SCREEN_NAME_QUERY_ID,
        "UserTweets": FALLBACK_USER_TWEETS_QUERY_ID,
        "SearchTimeline": FALLBACK_SEARCH_TIMELINE_QUERY_ID,
        "ListByRestId": FALLBACK_LIST_BY_REST_ID_QUERY_ID,
        "ListLatestTweetsTimeline": FALLBACK_LIST_LATEST_TWEETS_QUERY_ID,
    }


def _fetch_home_html(user_agent: str) -> str:
    """Fetch and cache x.com homepage HTML (matches baoyu http.ts caching)."""
    global _cached_home_html

    if _cached_home_html:
        return _cached_home_html

    try:
        logger.debug("Fetching x.com homepage for JS bundle discovery...")
        resp = http_client.get(
            "https://x.com",
            headers={"user-agent": user_agent},
            timeout=15,
        )
        http_client.raise_for_status(resp)
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
        resp = http_client.get(
            chunk_url,
            headers={"user-agent": user_agent},
            timeout=15,
        )
        http_client.raise_for_status(resp)
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


def _apply_richtext_tags(text: str, note_tweet: dict) -> str:
    """Apply richtext_tags (Bold/Italic) from note_tweet to produce Markdown formatting.

    Tags are index-based on the original text. We process from end to start
    to avoid index shifting when inserting markers.
    """
    tags = note_tweet.get("richtext", {}).get("richtext_tags", [])
    if not tags or not text:
        return text

    # Sort by from_index descending so insertions don't shift earlier indices
    sorted_tags = sorted(tags, key=lambda t: t.get("from_index", 0), reverse=True)
    chars = list(text)

    for tag in sorted_tags:
        fr = tag.get("from_index", 0)
        to = tag.get("to_index", 0)
        types = tag.get("richtext_types", [])
        if fr >= to or fr >= len(chars):
            continue
        to = min(to, len(chars))
        if "Bold" in types and "Italic" in types:
            chars.insert(to, "***")
            chars.insert(fr, "***")
        elif "Bold" in types:
            chars.insert(to, "**")
            chars.insert(fr, "**")
        elif "Italic" in types:
            chars.insert(to, "*")
            chars.insert(fr, "*")

    return "".join(chars)


def _parse_source_app(source_html: str) -> str:
    """Extract app name from tweet source HTML tag.

    Input: '<a href="https://mobile.twitter.com" rel="nofollow">Twitter Web App</a>'
    Output: 'Twitter Web App'
    """
    if not source_html:
        return ""
    m = re.search(r">([^<]+)<", source_html)
    return m.group(1).strip() if m else ""


def _render_article_body(article: dict) -> str:
    """Render Twitter Article content_state (Draft.js format) to Markdown.

    The content_state contains:
    - blocks: list of {text, type, entityRanges, inlineStyleRanges, depth}
    - entityMap: list of {key, value: {type, data}} entries

    Block types: unstyled, header-two, header-three, ordered-list-item,
    unordered-list-item, blockquote, atomic, code-block.

    Entity types: MEDIA (images), MARKDOWN (code blocks), TWEMOJI (emoji SVG).
    """
    cs = article.get("content_state")
    if not cs:
        return ""
    blocks = cs.get("blocks", [])
    if not blocks:
        return ""

    # Build entityMap lookup: key (str) → {type, data}
    raw_em = cs.get("entityMap", {})
    if isinstance(raw_em, list):
        entity_map = {str(item["key"]): item["value"] for item in raw_em if "key" in item}
    elif isinstance(raw_em, dict):
        entity_map = raw_em
    else:
        entity_map = {}

    # Build mediaId → URL lookup from media_entities
    media_url_map = {}
    for me in article.get("media_entities", []):
        mi = me.get("media_info") or {}
        media_id = str(me.get("media_key", ""))
        url = mi.get("original_img_url", "")
        if url:
            media_url_map[media_id] = url
        # Also index by numeric media_id
        mid = str(mi.get("__rest_id", ""))
        if mid and url:
            media_url_map[mid] = url

    parts = []
    list_counter = 0  # for ordered lists

    for block in blocks:
        btype = block.get("type", "unstyled")
        text = block.get("text", "")
        entity_ranges = block.get("entityRanges", [])

        # atomic blocks: content comes from entityMap
        if btype == "atomic":
            for er in entity_ranges:
                ent_key = str(er.get("key", ""))
                ent = entity_map.get(ent_key, {})
                ent_type = ent.get("type", "")
                ent_data = ent.get("data", {})

                if ent_type == "MEDIA":
                    # Resolve image URL from media_entities
                    for mi in ent_data.get("mediaItems", []):
                        mid = str(mi.get("mediaId", ""))
                        img_url = media_url_map.get(mid, "")
                        if not img_url:
                            # Try matching by suffix in media_url_map keys
                            for mk, mv in media_url_map.items():
                                if mid in mk or mk in mid:
                                    img_url = mv
                                    break
                        if img_url:
                            parts.append(f"\n![image]({img_url})\n")
                elif ent_type == "MARKDOWN":
                    md = ent_data.get("markdown", "")
                    if md:
                        parts.append(f"\n{md}\n")
                # TWEMOJI: skip (emoji SVGs are oversized in Obsidian)
            continue

        # Empty block → blank line
        if not text.strip():
            parts.append("")
            list_counter = 0
            continue

        # Format text based on block type
        if btype == "header-one":
            parts.append(f"# {text}")
            list_counter = 0
        elif btype == "header-two":
            parts.append(f"## {text}")
            list_counter = 0
        elif btype == "header-three":
            parts.append(f"### {text}")
            list_counter = 0
        elif btype == "ordered-list-item":
            list_counter += 1
            parts.append(f"{list_counter}. {text}")
        elif btype == "unordered-list-item":
            parts.append(f"- {text}")
            list_counter = 0
        elif btype == "blockquote":
            for line in text.split("\n"):
                parts.append(f"> {line}")
            list_counter = 0
        elif btype == "code-block":
            parts.append(f"```\n{text}\n```")
            list_counter = 0
        else:
            # unstyled → regular paragraph
            parts.append(text)
            list_counter = 0

    return "\n\n".join(parts).strip()


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
                # Extract cover image from cover_media
                cover_media = article.get("cover_media") or {}
                media_info = cover_media.get("media_info") or {}
                cover_image = (
                    media_info.get("original_img_url")
                    or (media_info.get("preview_image") or {}).get("original_img_url")
                    or ""
                )
                # Render article body from content_state (Draft.js format)
                body = _render_article_body(article)
                return {
                    "id": article.get("rest_id", ""),
                    "title": article.get("title", ""),
                    "cover_image": cover_image,
                    "body": body,
                    "has_content": bool(body or article.get("preview_text")),
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
