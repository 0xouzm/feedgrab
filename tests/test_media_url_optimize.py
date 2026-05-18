# -*- coding: utf-8 -*-
"""v0.23.0 utils.media — URL 优化测试 (P2-1: Twitter avatar 原图)"""

from feedgrab.utils.media import _optimize_url


# ---------------------------------------------------------------------------
# P2-1: Twitter avatar 原图替换 (_normal/_bigger/_mini/_400x400 → 原图)
# ---------------------------------------------------------------------------


def test_twitter_avatar_normal_to_original():
    url = "https://pbs.twimg.com/profile_images/1234567890/abc_normal.jpg"
    assert _optimize_url(url, "twitter") == (
        "https://pbs.twimg.com/profile_images/1234567890/abc.jpg"
    )


def test_twitter_avatar_bigger_to_original():
    url = "https://pbs.twimg.com/profile_images/9876/xyz_bigger.png"
    assert _optimize_url(url, "twitter") == (
        "https://pbs.twimg.com/profile_images/9876/xyz.png"
    )


def test_twitter_avatar_mini_to_original():
    url = "https://pbs.twimg.com/profile_images/55/foo_mini.jpeg"
    assert _optimize_url(url, "twitter") == (
        "https://pbs.twimg.com/profile_images/55/foo.jpeg"
    )


def test_twitter_avatar_400x400_to_original():
    url = "https://pbs.twimg.com/profile_images/77/bar_400x400.webp"
    assert _optimize_url(url, "twitter") == (
        "https://pbs.twimg.com/profile_images/77/bar.webp"
    )


def test_twitter_avatar_with_query_preserves_query():
    url = "https://pbs.twimg.com/profile_images/77/bar_normal.jpg?foo=bar"
    assert _optimize_url(url, "twitter") == (
        "https://pbs.twimg.com/profile_images/77/bar.jpg?foo=bar"
    )


def test_twitter_media_url_unchanged_by_avatar_logic():
    # 媒体 URL 走 name=orig 分支，不受头像分支影响
    url = "https://pbs.twimg.com/media/GxYz.jpg?name=small"
    out = _optimize_url(url, "twitter")
    assert "name=orig" in out
    assert "profile_images" not in out


def test_twitter_non_avatar_url_unchanged():
    url = "https://example.com/some/profile_images/x_normal.jpg"
    # 非 pbs.twimg.com 不应被替换
    assert _optimize_url(url, "twitter") == url
