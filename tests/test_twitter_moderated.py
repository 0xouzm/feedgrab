# -*- coding: utf-8 -*-
"""v0.23.0 P1-3: ModeratedTimeline 接入 thread 主路径测试。"""

import os
from unittest.mock import patch, MagicMock

from feedgrab.fetchers.twitter_thread import _fetch_moderated_replies
from feedgrab.config import (
    x_fetch_moderated_replies, x_moderated_replies_max_pages,
)


# ---------------------------------------------------------------------------
# Config switches
# ---------------------------------------------------------------------------

def test_moderated_default_off():
    """X_FETCH_MODERATED_REPLIES 默认 false。"""
    if "X_FETCH_MODERATED_REPLIES" in os.environ:
        del os.environ["X_FETCH_MODERATED_REPLIES"]
    assert x_fetch_moderated_replies() is False


def test_moderated_enable_via_env():
    os.environ["X_FETCH_MODERATED_REPLIES"] = "true"
    try:
        assert x_fetch_moderated_replies() is True
    finally:
        del os.environ["X_FETCH_MODERATED_REPLIES"]


def test_moderated_max_pages_default():
    if "X_MODERATED_REPLIES_MAX_PAGES" in os.environ:
        del os.environ["X_MODERATED_REPLIES_MAX_PAGES"]
    assert x_moderated_replies_max_pages() == 3


# ---------------------------------------------------------------------------
# Fetcher 行为
# ---------------------------------------------------------------------------

def test_fetch_moderated_empty_response_safe():
    """空响应应该不抛异常，返回 []."""
    with patch(
        "feedgrab.fetchers.twitter_thread.fetch_moderated_timeline_page",
        return_value=None,
    ):
        result = _fetch_moderated_replies("123456", {"auth_token": "x", "ct0": "y"})
    assert result == []


def test_fetch_moderated_no_entries():
    """有 response 但 parse 出 0 entries → 空 list + 单页退出。"""
    fake_resp = {"data": {"tweet": {"result": {}}}}

    with patch(
        "feedgrab.fetchers.twitter_thread.fetch_moderated_timeline_page",
        return_value=fake_resp,
    ), patch(
        "feedgrab.fetchers.twitter_thread.parse_moderated_timeline_entries",
        return_value=([], {}),
    ):
        result = _fetch_moderated_replies("123456", {"auth_token": "x", "ct0": "y"})
    assert result == []


def test_fetch_moderated_with_entries():
    """parse 出 entries → extract_tweet_data 处理后返回 tweet dict list。"""
    fake_resp = {"data": {"some": "thing"}}
    fake_entries = [{"entryId": "tweet-1"}, {"entryId": "tweet-2"}]
    fake_cursors = {"bottom": None}  # 一页就停

    with patch(
        "feedgrab.fetchers.twitter_thread.fetch_moderated_timeline_page",
        return_value=fake_resp,
    ), patch(
        "feedgrab.fetchers.twitter_thread.parse_moderated_timeline_entries",
        return_value=(fake_entries, fake_cursors),
    ), patch(
        "feedgrab.fetchers.twitter_thread.extract_tweet_data",
        side_effect=[
            {"id": "1", "text": "hidden 1", "author": "x"},
            {"id": "2", "text": "hidden 2", "author": "x"},
        ],
    ):
        result = _fetch_moderated_replies("99", {"auth_token": "x", "ct0": "y"})

    assert len(result) == 2
    assert result[0]["text"] == "hidden 1"
    assert result[1]["text"] == "hidden 2"


def test_fetch_moderated_paginated():
    """有 cursor 时翻页，第二页空就停。"""
    page1_resp = {"data": "p1"}
    page2_resp = {"data": "p2"}
    page1_entries = [{"entryId": "tweet-A"}]
    page2_entries = []  # 第二页空

    with patch(
        "feedgrab.fetchers.twitter_thread.fetch_moderated_timeline_page",
        side_effect=[page1_resp, page2_resp],
    ), patch(
        "feedgrab.fetchers.twitter_thread.parse_moderated_timeline_entries",
        side_effect=[
            (page1_entries, {"bottom": "CURSOR_2"}),
            (page2_entries, {}),
        ],
    ), patch(
        "feedgrab.fetchers.twitter_thread.extract_tweet_data",
        return_value={"id": "A", "text": "hidden A"},
    ):
        result = _fetch_moderated_replies("99", {"auth_token": "x", "ct0": "y"})

    assert len(result) == 1
    assert result[0]["text"] == "hidden A"


def test_fetch_moderated_exception_safe():
    """fetcher 抛异常应被吞掉，返回 []."""
    with patch(
        "feedgrab.fetchers.twitter_thread.fetch_moderated_timeline_page",
        side_effect=RuntimeError("network failed"),
    ):
        result = _fetch_moderated_replies("99", {"auth_token": "x", "ct0": "y"})
    assert result == []
