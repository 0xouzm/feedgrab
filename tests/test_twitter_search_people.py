# -*- coding: utf-8 -*-
"""v0.23.0 P2-4: SearchTimeline product=People parser tests."""

from feedgrab.fetchers.twitter_graphql import (
    parse_search_people_entries,
    extract_user_data,
)


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


def _make_tweet_entry(rest_id: str):
    """Build a TimelineTweet entry — should be filtered out by people parser."""
    return {
        "entryId": f"tweet-{rest_id}",
        "sortIndex": "20000",
        "content": {
            "entryType": "TimelineTimelineItem",
            "itemContent": {
                "itemType": "TimelineTweet",
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": rest_id,
                    }
                }
            }
        }
    }


def _wrap_people_response(entries: list):
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {"type": "TimelineAddEntries", "entries": entries}
                        ]
                    }
                }
            }
        }
    }


def test_people_parser_keeps_user_entries():
    resp = _wrap_people_response([
        _make_user_entry("1", "alice", followers=1000),
        _make_user_entry("2", "bob", followers=2000),
    ])
    entries, cursors = parse_search_people_entries(resp)
    assert len(entries) == 2
    user_data = [extract_user_data(e) for e in entries]
    assert all(u is not None for u in user_data)
    assert {u["screen_name"] for u in user_data} == {"alice", "bob"}


def test_people_parser_drops_tweet_entries():
    """If response accidentally mixes TimelineTweet items, drop them."""
    resp = _wrap_people_response([
        _make_user_entry("1", "alice"),
        _make_tweet_entry("999"),
        _make_user_entry("2", "bob"),
    ])
    entries, cursors = parse_search_people_entries(resp)
    assert len(entries) == 2  # tweet entry filtered out


def test_people_parser_handles_cursor():
    resp = _wrap_people_response([
        _make_user_entry("1", "alice"),
        {
            "entryId": "cursor-bottom-xyz",
            "content": {
                "entryType": "TimelineTimelineCursor",
                "cursorType": "Bottom",
                "value": "NEXT_PAGE",
            }
        }
    ])
    entries, cursors = parse_search_people_entries(resp)
    assert len(entries) == 1
    assert cursors.get("bottom") == "NEXT_PAGE"


def test_people_parser_empty():
    entries, cursors = parse_search_people_entries({})
    assert entries == []
    assert cursors == {}
