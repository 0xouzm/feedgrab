# -*- coding: utf-8 -*-
"""v0.23.0 P2-3: Retweeters / Favoriters parser & URL routing tests."""

from feedgrab.fetchers.twitter_graphql import (
    parse_retweeters_users,
    parse_favoriters_users,
    extract_user_data,
)
from feedgrab.fetchers.twitter_retweeters import (
    parse_tweet_user_list_url,
    extract_tweet_id,
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def test_url_retweets_route():
    mode, tid = parse_tweet_user_list_url(
        "https://x.com/ai_xiaomu/status/1234567890/retweets"
    )
    assert mode == "retweeters"
    assert tid == "1234567890"


def test_url_likes_route():
    mode, tid = parse_tweet_user_list_url(
        "https://twitter.com/elonmusk/status/9876/likes/"
    )
    assert mode == "favoriters"
    assert tid == "9876"


def test_url_no_match():
    mode, tid = parse_tweet_user_list_url("https://x.com/ai_xiaomu")
    assert mode is None
    assert tid is None


def test_extract_tweet_id_numeric():
    assert extract_tweet_id("1234567890") == "1234567890"


def test_extract_tweet_id_url():
    url = "https://x.com/ai_xiaomu/status/9999888877776/likes"
    assert extract_tweet_id(url) == "9999888877776"


def test_extract_tweet_id_invalid():
    assert extract_tweet_id("not-a-tweet") is None
    assert extract_tweet_id("") is None


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _make_user_entry(rest_id: str, screen_name: str, followers: int = 0):
    return {
        "entryId": f"user-{rest_id}",
        "sortIndex": "10000",
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineUser",
                "user_results": {
                    "result": {
                        "__typename": "User",
                        "rest_id": rest_id,
                        "legacy": {
                            "screen_name": screen_name,
                            "name": f"Name {screen_name}",
                            "followers_count": followers,
                            "friends_count": 0,
                            "statuses_count": 0,
                            "favourites_count": 0,
                            "listed_count": 0,
                        },
                        "is_blue_verified": False,
                    }
                }
            }
        }
    }


def _wrap_response(timeline_path: str, entries: list):
    """Build a fake GraphQL response with the given timeline path & entries."""
    instructions = [
        {"type": "TimelineAddEntries", "entries": entries}
    ]
    if timeline_path == "retweeters":
        return {
            "data": {
                "retweeters_timeline": {
                    "timeline": {"instructions": instructions}
                }
            }
        }
    else:
        return {
            "data": {
                "favoriters_timeline": {
                    "timeline": {"instructions": instructions}
                }
            }
        }


def test_parse_retweeters_entries():
    resp = _wrap_response("retweeters", [
        _make_user_entry("1", "alice", followers=100),
        _make_user_entry("2", "bob", followers=200),
    ])
    entries, cursors = parse_retweeters_users(resp)
    assert len(entries) == 2
    # Verify extract_user_data path works on these entries
    user_a = extract_user_data(entries[0])
    user_b = extract_user_data(entries[1])
    assert user_a is not None
    assert user_b is not None
    assert {user_a["screen_name"], user_b["screen_name"]} == {"alice", "bob"}


def test_parse_favoriters_entries():
    resp = _wrap_response("favoriters", [
        _make_user_entry("99", "charlie", followers=50),
    ])
    entries, cursors = parse_favoriters_users(resp)
    assert len(entries) == 1
    user = extract_user_data(entries[0])
    assert user["screen_name"] == "charlie"


def test_parse_empty_response():
    """Empty / wrong-shape response should not raise."""
    entries, cursors = parse_retweeters_users({})
    assert entries == []
    assert cursors == {}

    entries, cursors = parse_favoriters_users({"data": {}})
    assert entries == []


def test_parse_with_cursor():
    """cursor-bottom should be extracted into cursors dict."""
    resp = _wrap_response("retweeters", [
        _make_user_entry("1", "alice"),
        {
            "entryId": "cursor-bottom-xyz",
            "content": {
                "entryType": "TimelineTimelineCursor",
                "cursorType": "Bottom",
                "value": "BOTTOM_CURSOR_VALUE",
            },
        },
    ])
    entries, cursors = parse_retweeters_users(resp)
    assert len(entries) == 1
    assert cursors.get("bottom") == "BOTTOM_CURSOR_VALUE"
