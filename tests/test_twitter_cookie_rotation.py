# -*- coding: utf-8 -*-
"""Tests for fetch_with_cookie_rotation — 多账号 cookie 轮换 helper。"""

import pytest
from unittest.mock import patch
from feedgrab.fetchers import twitter_cookies


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    """每个用例前后清空模块级限流状态，避免污染。"""
    twitter_cookies._rate_limited_accounts.clear()
    twitter_cookies._current_account_key = ""
    yield
    twitter_cookies._rate_limited_accounts.clear()
    twitter_cookies._current_account_key = ""


def _make_cookies(token: str) -> dict:
    """构造一个合法的 cookie dict（auth_token + ct0 都 ≥20 chars）。"""
    return {"auth_token": token, "ct0": "c" * 32}


def test_helper_returns_response_on_first_success():
    """正常情况：第 1 个账号直接成功，无重试日志。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20)), ("acct2", _make_cookies("a2" * 20))]
    calls = []

    def fake_fetch(user_id, cookies=None, cursor=None):
        calls.append(cookies["auth_token"][:4])
        return {"data": {"ok": True}}

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", cursor=None,
        )
    assert response == {"data": {"ok": True}}
    assert len(calls) == 1, "成功后不应继续重试"
    assert used == cookie_sets[0][1]


def test_helper_rotates_to_second_account_when_first_returns_none():
    """第 1 个账号失败 → helper 自动切到第 2 个账号继续。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20)), ("acct2", _make_cookies("a2" * 20))]
    calls = []

    def fake_fetch(user_id, cookies=None, cursor=None):
        calls.append(cookies["auth_token"][:4])
        if cookies["auth_token"].startswith("a1"):
            twitter_cookies.mark_cookie_rate_limited(cookies)
            return None
        return {"data": {"ok": True}}

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", network_retry_delay=0,
        )
    assert response == {"data": {"ok": True}}
    assert len(calls) == 2, "应该尝试 2 个账号"
    assert used == cookie_sets[1][1]


def test_helper_returns_none_when_all_accounts_rate_limited():
    """所有账号都限流时，返回 (None, last_cookies) 并打印明确日志。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20)), ("acct2", _make_cookies("a2" * 20))]
    calls = []

    def fake_fetch(user_id, cookies=None, cursor=None):
        calls.append(cookies["auth_token"][:4])
        twitter_cookies.mark_cookie_rate_limited(cookies)
        return None

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", network_retry_delay=0,
        )
    assert response is None
    # Both accounts should have been tried before giving up
    assert len(calls) == 2
    assert used  # last_cookies returned for context


def test_helper_avoids_infinite_loop_on_single_account():
    """只有 1 个账号且失败时，至少试 1 次但不死循环。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20))]
    calls = []

    def fake_fetch(user_id, cookies=None, cursor=None):
        calls.append(1)
        return None

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", network_retry_delay=0,
        )
    assert response is None
    assert len(calls) == 1, "单账号失败应尽快终止，不重试同一账号"


def test_helper_returns_none_when_no_accounts_loaded():
    """完全没有 cookie 时，应快速失败。"""
    def fake_fetch(*args, **kwargs):
        raise AssertionError("无 cookie 时不应调用 fetcher")

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=[]):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", network_retry_delay=0,
        )
    assert response is None
    assert used == {}


def test_helper_swallows_exception_and_tries_next_account():
    """fetcher 抛异常时不能崩溃，应继续尝试下一个账号。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20)), ("acct2", _make_cookies("a2" * 20))]
    calls = []

    def fake_fetch(user_id, cookies=None, cursor=None):
        calls.append(cookies["auth_token"][:4])
        if cookies["auth_token"].startswith("a1"):
            twitter_cookies.mark_cookie_rate_limited(cookies)
            raise RuntimeError("simulated network blowup")
        return {"data": {"ok": True}}

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        response, used = twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123", label="TestOps", network_retry_delay=0,
        )
    assert response == {"data": {"ok": True}}
    assert len(calls) == 2
    assert used == cookie_sets[1][1]


def test_helper_passes_kwargs_to_fetcher():
    """关键字参数（cursor / count / product 等）应正确透传给 fetcher。"""
    cookie_sets = [("acct1", _make_cookies("a1" * 20))]
    captured = {}

    def fake_fetch(user_id, cookies=None, cursor=None, count=None, product=None):
        captured.update(cursor=cursor, count=count, product=product)
        return {"data": {"ok": True}}

    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        twitter_cookies.fetch_with_cookie_rotation(
            fake_fetch, "user_123",
            label="TestOps",
            cursor="cur_abc",
            count=40,
            product="Latest",
        )
    assert captured == {"cursor": "cur_abc", "count": 40, "product": "Latest"}


def test_count_available_decreases_when_account_limited():
    """count_available_accounts() 应实时反映限流变化。"""
    cookie_sets = [("a", _make_cookies("a" * 40)), ("b", _make_cookies("b" * 40))]
    with patch.object(twitter_cookies, "_load_all_cookie_sets", return_value=cookie_sets):
        assert twitter_cookies.count_total_accounts() == 2
        assert twitter_cookies.count_available_accounts() == 2
        twitter_cookies.mark_cookie_rate_limited(cookie_sets[0][1])
        assert twitter_cookies.count_available_accounts() == 1
        twitter_cookies.mark_cookie_rate_limited(cookie_sets[1][1])
        assert twitter_cookies.count_available_accounts() == 0
        assert twitter_cookies.earliest_rate_limit_recovery_seconds() > 0
