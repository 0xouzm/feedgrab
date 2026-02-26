# -*- coding: utf-8 -*-
"""
Twitter/X thread fetcher — complete thread reconstruction via GraphQL.

Ported from baoyu-danger-x-to-markdown thread.ts.

Algorithm (multi-phase):
    1. Fetch TweetDetail for focal tweet → get entries + cursors
    2. Paginate upward via topCursor (find earlier thread tweets)
    3. Paginate downward via moreCursor / bottomCursor (find later replies)
    4. Re-fetch from last thread entry to catch continuation
    5. Deduplicate by tweet ID
    6. Walk up to find true conversation root
    7. Sort by timestamp, slice from root, filter by isSameThread
"""

import os
from loguru import logger
from typing import Dict, Any, Optional, List

from feedgrab.config import x_fetch_author_replies, x_fetch_all_comments, x_max_comments
from feedgrab.fetchers.twitter_graphql import (
    fetch_tweet_detail,
    parse_tweet_entries,
    parse_cursors,
    extract_tweet_data,
    DEFAULT_MAX_PAGES,
)

# Max pagination requests per thread fetch (safety cap)
MAX_REQUEST_COUNT = int(os.getenv("X_THREAD_MAX_PAGES", str(DEFAULT_MAX_PAGES)))


def fetch_tweet_thread(
    tweet_id: str, cookies: dict
) -> Optional[Dict[str, Any]]:
    """
    Fetch a complete tweet thread by the same author.

    This is the main entry point. Given any tweet ID in a thread,
    reconstructs the full author self-reply chain.

    Args:
        tweet_id: Any tweet ID in the thread.
        cookies: dict with 'auth_token' and 'ct0'.

    Returns:
        Dict with:
            - tweets: List of tweet dicts (ordered, same-author only)
            - root_tweet: The first tweet in the thread
            - author: Screen name of the thread author
            - tweet_count: Number of tweets in the thread
        Or None on failure.
    """
    logger.info(f"[Thread] Fetching thread for tweet {tweet_id}")

    # Phase 1: Initial fetch
    response = fetch_tweet_detail(tweet_id, cookies)
    if not response:
        logger.error("[Thread] Initial TweetDetail fetch failed")
        return None

    entries = parse_tweet_entries(response)
    cursors = parse_cursors(entries)

    # Parse all tweet entries
    all_entries = _parse_entries_to_tweets(entries)
    if not all_entries:
        logger.warning("[Thread] No tweet entries found in response")
        return None

    requests_remaining = MAX_REQUEST_COUNT

    # Phase 2: Paginate upward via topCursor
    top_cursor = cursors.get("top")
    while top_cursor and requests_remaining > 0:
        requests_remaining -= 1
        logger.debug(f"[Thread] Paginating up (remaining={requests_remaining})")

        resp = fetch_tweet_detail(tweet_id, cookies, cursor=top_cursor)
        if not resp:
            break

        new_entries = parse_tweet_entries(resp)
        new_cursors = parse_cursors(new_entries)
        new_tweets = _parse_entries_to_tweets(new_entries)

        if not new_tweets or not _has_thread_entries(new_tweets, all_entries):
            break

        # Prepend earlier tweets
        all_entries = new_tweets + all_entries
        top_cursor = new_cursors.get("top")

    # Phase 3: Paginate downward via moreCursor / bottomCursor
    more_cursor = cursors.get("more")
    bottom_cursor = cursors.get("bottom")
    all_entries, requests_remaining = _paginate_downward(
        tweet_id, cookies, all_entries, more_cursor, bottom_cursor, requests_remaining
    )

    # Phase 4: Re-fetch from last thread entry to catch continuation
    # (matches baoyu thread.ts — fetches TweetDetail with last entry's ID)
    thread_entries = _filter_same_thread(all_entries)
    if thread_entries and requests_remaining > 0:
        last_entry = thread_entries[-1]
        last_id = last_entry.get("id", "")
        if last_id and last_id != tweet_id:
            logger.debug(f"[Thread] Re-fetching from last thread entry {last_id}")
            resp = fetch_tweet_detail(last_id, cookies)
            requests_remaining -= 1
            if resp:
                new_entries = parse_tweet_entries(resp)
                new_cursors = parse_cursors(new_entries)
                new_tweets = _parse_entries_to_tweets(new_entries)
                all_entries = all_entries + new_tweets

                # Continue downward from re-fetch
                more_cursor = new_cursors.get("more")
                bottom_cursor = new_cursors.get("bottom")
                all_entries, requests_remaining = _paginate_downward(
                    last_id, cookies, all_entries,
                    more_cursor, bottom_cursor, requests_remaining
                )

    # Phase 5: Deduplicate
    all_entries = _deduplicate(all_entries)

    # Phase 6: Find true root (walk up the reply chain)
    root = _find_root(all_entries)

    # Phase 7: Sort by time, slice from root, filter same-thread
    all_entries.sort(key=lambda t: t.get("created_at", ""))

    # Slice from root onwards
    root_id = root.get("id", "") if root else ""
    if root_id:
        root_idx = next(
            (i for i, t in enumerate(all_entries) if t.get("id") == root_id),
            0,
        )
        all_entries = all_entries[root_idx:]

    # Final isSameThread filter
    if root:
        thread_tweets = [t for t in all_entries if _is_same_thread(t, root)]
    else:
        thread_tweets = all_entries

    if not thread_tweets:
        logger.warning("[Thread] No same-thread tweets after filtering")
        return None

    root_tweet = thread_tweets[0]
    author = root_tweet.get("author", "")
    root_user_id = root_tweet.get("user_id", "")

    logger.info(f"[Thread] Found {len(thread_tweets)} tweets by @{author}")

    result = {
        "tweets": thread_tweets,
        "root_tweet": root_tweet,
        "author": author,
        "author_name": root_tweet.get("author_name", ""),
        "tweet_count": len(thread_tweets),
    }

    # --- Classify remaining entries (zero extra API calls) ---
    thread_ids = {t.get("id") for t in thread_tweets}

    # C 类：作者回复评论者（不在自回复链中的作者推文）
    if x_fetch_author_replies():
        author_replies = [
            t for t in all_entries
            if t.get("user_id") == root_user_id
            and t.get("id") not in thread_ids
            and t.get("in_reply_to_user_id") != root_user_id
        ]
        author_replies.sort(key=lambda t: t.get("created_at", ""))
        result["author_replies"] = author_replies
        logger.info(f"[Thread] Collected {len(author_replies)} author replies to commenters")

    # B 类：其他用户评论（按点赞数降序）
    if x_fetch_all_comments():
        max_c = x_max_comments()
        comments = [
            t for t in all_entries
            if t.get("user_id") != root_user_id
        ]
        comments.sort(key=lambda t: t.get("likes", 0), reverse=True)
        result["comments"] = comments[:max_c]
        logger.info(f"[Thread] Collected {len(result['comments'])} comments (max {max_c})")

    return result


# ---------------------------------------------------------------------------
# isSameThread — exact port from baoyu thread.ts lines 168-179
# ---------------------------------------------------------------------------

def _is_same_thread(tweet: dict, root: dict) -> bool:
    """
    Determine if a tweet belongs to the same author thread.

    Matches baoyu thread.ts isSameThread() exactly:
        1. Same user_id as root
        2. Same conversation_id as root
        3. AND one of:
           a. It IS the root tweet
           b. It replies to the root author
           c. It replies to the conversation root status
           d. It has no in_reply_to_user_id (top-level in conversation)
    """
    if not tweet or not root:
        return False

    user_id = tweet.get("user_id", "")
    root_user_id = root.get("user_id", "")
    conversation_id = tweet.get("conversation_id", "")
    root_conversation_id = root.get("conversation_id", "")

    # Must be same author and same conversation
    if user_id != root_user_id:
        return False
    if conversation_id != root_conversation_id:
        return False

    # Must match one of these conditions
    tweet_id = tweet.get("id", "")
    root_id = root.get("id", "")
    in_reply_to_user = tweet.get("in_reply_to_user_id", "")
    in_reply_to_status = tweet.get("in_reply_to_status_id", "")

    return (
        tweet_id == root_id                              # is the root itself
        or in_reply_to_user == root_user_id              # replies to same author
        or in_reply_to_status == root_conversation_id    # replies to conversation root
        or not in_reply_to_user                          # no reply target (top-level)
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_entries_to_tweets(entries: list) -> List[Dict[str, Any]]:
    """Parse timeline entries into flat tweet dicts, skipping non-tweet entries."""
    tweets = []

    for entry in entries:
        # Handle conversation thread modules (contain nested items)
        content = entry.get("content", {})
        if content.get("entryType") == "TimelineTimelineModule":
            items = content.get("items", [])
            for item in items:
                tweet = extract_tweet_data(item)
                if tweet:
                    tweets.append(tweet)
        else:
            tweet = extract_tweet_data(entry)
            if tweet:
                tweets.append(tweet)

    return tweets


def _paginate_downward(
    focal_id: str,
    cookies: dict,
    all_entries: list,
    more_cursor: Optional[str],
    bottom_cursor: Optional[str],
    requests_remaining: int,
) -> tuple:
    """
    Paginate downward through moreCursor and bottomCursor.

    Matches baoyu thread.ts checkMoreTweets() pattern:
        1. Follow moreCursor until exhausted
        2. Then follow bottomCursor once
    """
    # Follow moreCursor
    while more_cursor and requests_remaining > 0:
        requests_remaining -= 1
        logger.debug(f"[Thread] Paginating down/more (remaining={requests_remaining})")

        resp = fetch_tweet_detail(focal_id, cookies, cursor=more_cursor)
        if not resp:
            break

        new_entries = parse_tweet_entries(resp)
        new_cursors = parse_cursors(new_entries)
        new_tweets = _parse_entries_to_tweets(new_entries)

        if not new_tweets or not _has_thread_entries(new_tweets, all_entries):
            break

        all_entries = all_entries + new_tweets
        more_cursor = new_cursors.get("more")
        # Pick up bottomCursor if we don't have one yet
        if not bottom_cursor:
            bottom_cursor = new_cursors.get("bottom")

    # Follow bottomCursor once
    if bottom_cursor and requests_remaining > 0:
        requests_remaining -= 1
        logger.debug(f"[Thread] Paginating down/bottom (remaining={requests_remaining})")

        resp = fetch_tweet_detail(focal_id, cookies, cursor=bottom_cursor)
        if resp:
            new_entries = parse_tweet_entries(resp)
            new_tweets = _parse_entries_to_tweets(new_entries)
            all_entries = all_entries + new_tweets

    return all_entries, requests_remaining


def _has_thread_entries(new_tweets: list, existing_tweets: list) -> bool:
    """Check if new tweets contain any entries that could be part of a thread."""
    if not new_tweets:
        return False

    existing_ids = {t.get("id") for t in existing_tweets}

    # At least one new tweet that we haven't seen
    for t in new_tweets:
        if t.get("id") not in existing_ids:
            return True

    return False


def _deduplicate(tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate tweets by ID, keeping first occurrence.

    Matches baoyu thread.ts deduplication: uses Map keyed by
    tweet.legacy.id_str ?? tweet.rest_id, first occurrence wins.
    """
    seen = set()
    unique = []
    for tweet in tweets:
        tid = tweet.get("id") or tweet.get("rest_id", "")
        if tid and tid not in seen:
            seen.add(tid)
            unique.append(tweet)
    return unique


def _find_root(tweets: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Walk up the reply chain to find the true conversation root.

    Matches baoyu thread.ts root-walking logic: follows
    in_reply_to_status_id_str upward as long as the parent is
    the same author in the same conversation.
    """
    if not tweets:
        return None

    # Build lookup by tweet ID
    by_id = {t.get("id"): t for t in tweets if t.get("id")}

    # Start from the first tweet (earliest in the collection)
    root = tweets[0]

    # Walk upward
    max_depth = 100  # safety limit
    depth = 0
    while depth < max_depth:
        parent_id = root.get("in_reply_to_status_id", "")
        if not parent_id:
            break

        parent = by_id.get(parent_id)
        if not parent:
            break

        # Parent must be same author and same conversation
        if (
            parent.get("user_id") != root.get("user_id")
            or parent.get("conversation_id") != root.get("conversation_id")
            or parent.get("id") == root.get("id")
        ):
            break

        root = parent
        depth += 1

    return root


def _filter_same_thread(tweets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Quick filter for thread entries before full processing."""
    if not tweets:
        return []

    # Find likely root (tweet with matching conversation_id == id, or first tweet)
    root = None
    for t in tweets:
        if t.get("id") == t.get("conversation_id"):
            root = t
            break
    if not root:
        root = _find_root(tweets)
    if not root:
        return tweets

    return [t for t in tweets if _is_same_thread(t, root)]
