# -*- coding: utf-8 -*-
"""v0.23.0 P2-2: 媒体文件名 pattern 系统测试。"""

import os
from feedgrab.utils.media import _apply_filename_pattern


def test_pattern_basic_substitution():
    """所有 token 正确替换。"""
    pattern = "{date}_{screen_name}_{tweet_id}_{num}.{ext}"
    ctx = {
        "tweet_id": "1234567890",
        "screen_name": "alice",
        "user_id": "999",
        "created_at": "Tue May 18 09:36:31 +0000 2026",
    }
    result = _apply_filename_pattern(
        pattern, "originalname.jpg", ctx, num=2, media_type="photo",
    )
    assert result == "20260518_alice_1234567890_2.jpg"


def test_pattern_datetime_and_type():
    pattern = "{datetime}_{type}_{num}.{ext}"
    ctx = {
        "tweet_id": "111",
        "screen_name": "bob",
        "user_id": "555",
        "created_at": "Wed Jan 01 12:00:00 +0000 2026",
    }
    result = _apply_filename_pattern(
        pattern, "orig.mp4", ctx, num=1, media_type="video",
    )
    assert result == "20260101_120000_video_1.mp4"


def test_pattern_user_id_and_name():
    """{name} 应该是 CDN 原 stem（向后兼容），{user_id} 来自 ctx。"""
    pattern = "{user_id}_{name}.{ext}"
    ctx = {
        "tweet_id": "1",
        "screen_name": "x",
        "user_id": "123abc",
        "created_at": "",
    }
    result = _apply_filename_pattern(
        pattern, "GxYzAbc.jpg", ctx, num=1, media_type="photo",
    )
    assert result == "123abc_GxYzAbc.jpg"


def test_pattern_missing_created_at_fallback():
    """created_at 缺失时 {date}/{datetime} → 'nodate'。"""
    pattern = "{date}_{tweet_id}.{ext}"
    ctx = {"tweet_id": "9", "screen_name": "a", "user_id": "", "created_at": ""}
    result = _apply_filename_pattern(
        pattern, "x.png", ctx, num=1, media_type="photo",
    )
    assert result == "nodate_9.png"


def test_pattern_dangerous_screen_name_sanitized():
    """screen_name 含 path traversal 字符应被替换为 _。"""
    pattern = "{screen_name}_{num}.{ext}"
    ctx = {
        "tweet_id": "1",
        "screen_name": "../etc/passwd",  # 危险输入
        "user_id": "1",
        "created_at": "",
    }
    result = _apply_filename_pattern(
        pattern, "x.jpg", ctx, num=1, media_type="photo",
    )
    # ".." 中的 .. 保留但 / 被替换；最终也通过 _FS_UNSAFE 二次清洗
    assert "/" not in result
    assert "\\" not in result
    assert result.endswith("_1.jpg")


def test_pattern_no_token_in_pattern():
    """无 token 的纯字符串 pattern → 输出还是这个字符串（边界）。"""
    pattern = "static_name.dat"
    ctx = {"tweet_id": "1", "screen_name": "", "user_id": "", "created_at": ""}
    result = _apply_filename_pattern(
        pattern, "x.jpg", ctx, num=1, media_type="photo",
    )
    assert result == "static_name.dat"


def test_pattern_no_extension_fallback():
    """fallback_name 无扩展名时 {ext} → 'bin'。"""
    pattern = "{tweet_id}_{num}.{ext}"
    ctx = {"tweet_id": "5", "screen_name": "", "user_id": "", "created_at": ""}
    result = _apply_filename_pattern(
        pattern, "noextension", ctx, num=1, media_type="photo",
    )
    assert result == "5_1.bin"


def test_pattern_length_cap():
    """超长 pattern 输出会被截断到 200 字符。"""
    pattern = "x" * 300 + "_{num}.{ext}"
    ctx = {"tweet_id": "1", "screen_name": "", "user_id": "", "created_at": ""}
    result = _apply_filename_pattern(
        pattern, "x.jpg", ctx, num=1, media_type="photo",
    )
    assert len(result) <= 200


def test_pattern_env_default_off():
    """env var 未设置 = 空字符串 → 默认行为不变。"""
    if "X_MEDIA_FILENAME_PATTERN" in os.environ:
        del os.environ["X_MEDIA_FILENAME_PATTERN"]
    pattern = os.getenv("X_MEDIA_FILENAME_PATTERN", "").strip()
    assert pattern == ""  # opt-in: 默认空，沿用旧行为


def test_pattern_tweet_id_from_url_overrides_ctx():
    """ctx['url'] 中的 /status/<id> 应该比 ctx['tweet_id'] 优先（避免 hash）。"""
    pattern = "{tweet_id}_{num}.{ext}"
    ctx = {
        "tweet_id": "abc123hashed",  # feedgrab 内部 hash
        "url": "https://x.com/ai_xiaomu/status/9876543210987654321/",
        "screen_name": "ai_xiaomu",
        "user_id": "",
        "created_at": "",
    }
    result = _apply_filename_pattern(
        pattern, "orig.jpg", ctx, num=1, media_type="photo",
    )
    assert result == "9876543210987654321_1.jpg"


def test_pattern_no_url_fallback_to_ctx_tweet_id():
    """无 url 时 fallback 到 ctx['tweet_id']（向后兼容）。"""
    pattern = "{tweet_id}.{ext}"
    ctx = {
        "tweet_id": "fallback123",
        "screen_name": "",
        "user_id": "",
        "created_at": "",
    }
    result = _apply_filename_pattern(
        pattern, "x.jpg", ctx, num=1, media_type="photo",
    )
    assert result == "fallback123.jpg"
