# -*- coding: utf-8 -*-
"""Unit tests for P1 platforms: xiaoyuzhou / ximalaya / bilibili / transcribe."""

import json

import pytest

from feedgrab.fetchers.bilibili import (
    _extract_bvid,
    _pick_best_subtitle,
)
from feedgrab.fetchers.xiaoyuzhou import (
    _extract_episode_id,
    _extract_next_data,
    _format_duration as _xyz_format_duration,
    _shownotes_to_markdown,
)
from feedgrab.fetchers.ximalaya import (
    _extract_track_id,
    _format_duration as _xmly_format_duration,
)
from feedgrab.schema import (
    SourceType,
    from_bilibili,
    from_ximalaya,
    from_xiaoyuzhou,
)
from feedgrab.utils.bilibili_wbi import (
    MIXIN_KEY_ENC_TAB,
    _extract_key_from_url,
    get_mixin_key,
    sign_wbi_params,
)
from feedgrab.utils.storage import PLATFORM_FOLDER_MAP
from feedgrab.utils.transcribe import (
    _guess_audio_ext,
    format_transcript,
    subtitle_body_to_snippets,
)


# ---------------------------------------------------------------------------
# Xiaoyuzhou URL & HTML parsing
# ---------------------------------------------------------------------------

def test_xyz_extract_episode_id_basic():
    assert _extract_episode_id("https://www.xiaoyuzhoufm.com/episode/67abc123") == "67abc123"


def test_xyz_extract_episode_id_with_query():
    assert _extract_episode_id("https://www.xiaoyuzhoufm.com/episode/abc123?utm=wx") == "abc123"


def test_xyz_extract_episode_id_nested():
    assert _extract_episode_id("https://www.xiaoyuzhoufm.com/podcast/xxx/episode/def456") == "def456"


def test_xyz_extract_episode_id_missing_raises():
    with pytest.raises(ValueError):
        _extract_episode_id("https://www.xiaoyuzhoufm.com/")


def test_xyz_extract_next_data_happy_path():
    payload = {"props": {"pageProps": {"episode": {"title": "Hi"}}}}
    html = f'<html><head><script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script></head></html>'
    got = _extract_next_data(html)
    assert got == payload


def test_xyz_extract_next_data_html_entities():
    # Shownotes may contain &quot; etc.; JSON.loads rejects &quot; but html.unescape fixes it
    payload = {"x": 'hello "world"'}
    escaped = json.dumps(payload).replace('"', "&quot;")
    html = f'<script id="__NEXT_DATA__">{escaped}</script>'
    got = _extract_next_data(html)
    assert got == payload


def test_xyz_extract_next_data_missing():
    assert _extract_next_data("<html>no data</html>") is None


def test_xyz_format_duration_hours():
    assert _xyz_format_duration(3725) == "1:02:05"


def test_xyz_format_duration_minutes():
    assert _xyz_format_duration(605) == "10:05"


def test_xyz_format_duration_zero():
    assert _xyz_format_duration(0) == ""


def test_xyz_shownotes_markdown_basic():
    md = _shownotes_to_markdown("<p>Hello <strong>world</strong></p>")
    assert "Hello" in md and "world" in md


def test_xyz_shownotes_markdown_empty():
    assert _shownotes_to_markdown("") == ""


# ---------------------------------------------------------------------------
# Ximalaya URL parsing
# ---------------------------------------------------------------------------

def test_xmly_sound_url():
    assert _extract_track_id("https://www.ximalaya.com/sound/1234567") == "1234567"


def test_xmly_sound_url_with_query():
    assert _extract_track_id("https://www.ximalaya.com/sound/999/?from=wx") == "999"


def test_xmly_category_album_track():
    assert _extract_track_id("https://www.ximalaya.com/shangye/393603/7843596") == "7843596"


def test_xmly_mobile_url():
    assert _extract_track_id("https://m.ximalaya.com/sound/7777777") == "7777777"


def test_xmly_missing_raises():
    with pytest.raises(ValueError):
        _extract_track_id("https://www.ximalaya.com/")


def test_xmly_format_duration():
    assert _xmly_format_duration(3720) == "1:02:00"
    assert _xmly_format_duration(45) == "0:45"
    assert _xmly_format_duration(None) == ""


# ---------------------------------------------------------------------------
# Bilibili URL + subtitle picker
# ---------------------------------------------------------------------------

def test_bili_bvid_from_url():
    assert _extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD") == "BV1xx411c7mD"


def test_bili_bvid_from_shortlink():
    assert _extract_bvid("https://b23.tv/BV1abc?share=wx") == "BV1abc"


def test_bili_bvid_raw():
    assert _extract_bvid("BV1xyz") == "BV1xyz"


def test_bili_subtitle_picker_prefers_exact_match():
    subs = [
        {"lan": "ai-zh", "subtitle_url": "u0"},
        {"lan": "zh-CN", "subtitle_url": "u1"},
        {"lan": "en", "subtitle_url": "u2"},
    ]
    best = _pick_best_subtitle(subs, preferred_lang="zh-CN")
    assert best["lan"] == "zh-CN"


def test_bili_subtitle_picker_falls_back():
    subs = [{"lan": "en", "subtitle_url": "u2"}, {"lan": "ai-zh", "subtitle_url": "u3"}]
    # Preferred not in list; falls back through preference chain
    best = _pick_best_subtitle(subs, preferred_lang="zh-CN")
    assert best["lan"] in ("ai-zh", "en")  # first preference hit from fallback chain


def test_bili_subtitle_picker_empty():
    assert _pick_best_subtitle([], "zh-CN") is None


# ---------------------------------------------------------------------------
# WBI signing
# ---------------------------------------------------------------------------

def test_wbi_mixin_key_tab_length():
    assert len(MIXIN_KEY_ENC_TAB) == 64
    assert set(MIXIN_KEY_ENC_TAB) == set(range(64))


def test_wbi_extract_key_from_url():
    assert _extract_key_from_url("https://i0.hdslb.com/bfs/wbi/abc123.png") == "abc123"
    assert _extract_key_from_url("https://i0.hdslb.com/bfs/wbi/key.with.dots.png") == "key.with.dots"
    assert _extract_key_from_url("") == ""


def test_wbi_get_mixin_key_deterministic():
    img = "7cd084941338484aae1ad9425b84077c"
    sub = "4932caff0ff746eab6f01bf08b70ac45"
    mk = get_mixin_key(img, sub)
    assert len(mk) == 32
    # Community-documented golden value
    assert mk == "ea1db124af3c7062474693fa704f4ff8"


def test_wbi_sign_params_produces_wts_and_wrid():
    signed = sign_wbi_params(
        {"aid": 12345, "cid": 67890},
        img_key="7cd084941338484aae1ad9425b84077c",
        sub_key="4932caff0ff746eab6f01bf08b70ac45",
    )
    assert set(signed) == {"aid", "cid", "wts", "w_rid"}
    assert len(signed["w_rid"]) == 32
    # wts is stringified (per WBI spec — all values go through str() before urlencode)
    assert int(signed["wts"]) > 0


def test_wbi_sign_strips_forbidden_chars():
    signed = sign_wbi_params(
        {"q": "hello!()*'world"},
        img_key="7cd084941338484aae1ad9425b84077c",
        sub_key="4932caff0ff746eab6f01bf08b70ac45",
    )
    assert signed["q"] == "helloworld"


# ---------------------------------------------------------------------------
# transcribe helpers
# ---------------------------------------------------------------------------

def test_transcribe_subtitle_body_basic():
    body = [
        {"from": 0.0, "to": 2.5, "content": "Hello"},
        {"from": 2.5, "to": 5.0, "content": "World"},
    ]
    snippets = subtitle_body_to_snippets(body)
    assert snippets == [
        {"text": "Hello", "start": 0.0, "duration": 2.5},
        {"text": "World", "start": 2.5, "duration": 2.5},
    ]


def test_transcribe_subtitle_body_skips_empty():
    body = [
        {"from": 0, "to": 1, "content": ""},
        {"from": 1, "to": 2, "content": "   "},
        {"from": 2, "to": 3, "content": "real"},
    ]
    assert len(subtitle_body_to_snippets(body)) == 1


def test_transcribe_subtitle_body_empty_input():
    assert subtitle_body_to_snippets([]) == []
    assert subtitle_body_to_snippets(None) == []


def test_transcribe_guess_extension():
    assert _guess_audio_ext("https://x/foo.m4a") == ".m4a"
    assert _guess_audio_ext("https://x/foo.mp3?token=abc") == ".mp3"
    assert _guess_audio_ext("https://x/foo.aac") == ".aac"
    assert _guess_audio_ext("https://x/nobase") == ".m4a"


def test_transcribe_format_empty():
    assert format_transcript([]) == ""


def test_transcribe_format_with_snippets():
    # Full pipeline: format → youtube._segment_into_sentences → _format_transcript_markdown
    snippets = [
        {"text": "Hello world.", "start": 0.0, "duration": 2.0},
        {"text": "This is a test.", "start": 2.0, "duration": 3.0},
    ]
    md = format_transcript(snippets)
    assert "Hello world" in md or "This is a test" in md


# ---------------------------------------------------------------------------
# Schema factories
# ---------------------------------------------------------------------------

def test_from_xiaoyuzhou_basic():
    uc = from_xiaoyuzhou({
        "title": "Ep 1",
        "podcast_name": "Show",
        "author": "Host",
        "episode_id": "abc",
        "url": "https://www.xiaoyuzhoufm.com/episode/abc",
        "shownotes": "Some notes",
        "transcript": "Full transcript here",
        "duration_seconds": 1800,
    })
    assert uc.source_type == SourceType.XIAOYUZHOU
    assert "Some notes" in uc.content
    assert "Full transcript here" in uc.content
    assert uc.extra["episode_id"] == "abc"


def test_from_xiaoyuzhou_no_transcript():
    uc = from_xiaoyuzhou({
        "title": "Ep 1",
        "shownotes": "just shownotes",
        "url": "https://x/",
    })
    assert "just shownotes" in uc.content
    assert "完整转录" not in uc.content


def test_from_ximalaya_basic():
    uc = from_ximalaya({
        "title": "Track 1",
        "album_name": "Album",
        "author": "Speaker",
        "track_id": "123",
        "url": "https://www.ximalaya.com/sound/123",
        "description": "intro",
        "can_play": True,
    })
    assert uc.source_type == SourceType.XIMALAYA
    assert uc.extra["can_play"] is True
    assert uc.extra["track_id"] == "123"


def test_from_bilibili_with_transcript():
    uc = from_bilibili({
        "title": "Video",
        "author": "UP",
        "url": "https://b/",
        "description": "desc",
        "transcript": "lyrics",
        "has_transcript": True,
        "bvid": "BV1",
        "aid": 1,
        "cid": 2,
    })
    assert uc.source_type == SourceType.BILIBILI
    assert "desc" in uc.content
    assert "lyrics" in uc.content
    assert uc.extra["has_transcript"] is True


def test_from_bilibili_without_transcript_regression():
    # Regression: old shape (no transcript key) must still work
    uc = from_bilibili({
        "title": "Video",
        "author": "UP",
        "url": "https://b/",
        "description": "desc only",
        "bvid": "BV1",
    })
    assert uc.content == "desc only"


# ---------------------------------------------------------------------------
# PLATFORM_FOLDER_MAP coverage
# ---------------------------------------------------------------------------

def test_platform_folder_map_covers_new_types():
    assert PLATFORM_FOLDER_MAP[SourceType.XIAOYUZHOU] == "Xiaoyuzhou"
    assert PLATFORM_FOLDER_MAP[SourceType.XIMALAYA] == "Ximalaya"
    assert PLATFORM_FOLDER_MAP[SourceType.BILIBILI] == "Bilibili"
