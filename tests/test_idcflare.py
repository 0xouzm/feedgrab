# -*- coding: utf-8 -*-
"""IDCFlare / Discourse topic parsing tests."""

import asyncio
from pathlib import Path

from feedgrab.fetchers.idcflare import (
    _http_fetch_topic_json,
    _html_to_markdown,
    _parse_topic_payload,
    _warmup_idcflare_session_from_cdp,
    is_idcflare_url,
    parse_idcflare_url,
)
from feedgrab.reader import UniversalReader
from feedgrab.schema import SourceType, from_idcflare
from feedgrab.utils.storage import PLATFORM_FOLDER_MAP


def _sample_topic_payload():
    return {
        "id": 44294,
        "title": "IDCFlare 测试帖子",
        "slug": "topic",
        "posts_count": 2,
        "reply_count": 1,
        "like_count": 5,
        "views": 123,
        "created_at": "2026-04-22T10:20:25.368Z",
        "last_posted_at": "2026-04-22T11:12:34.693Z",
        "category_id": 9,
        "category_name": "VPS",
        "tags": [{"name": "测试"}, {"name": "Discourse"}],
        "post_stream": {
            "posts": [
                {
                    "id": 1,
                    "username": "demo_user",
                    "name": "",
                    "created_at": "2026-04-22T10:20:25.531Z",
                    "post_number": 1,
                    "cooked": (
                        "<p>首帖正文。</p>"
                        "<p><a href=\"/t/topic/44294\">站内链接</a></p>"
                        "<pre><code class=\"lang-bash\">echo hi</code></pre>"
                    ),
                },
                {
                    "id": 2,
                    "username": "reply_user",
                    "name": "Reply User",
                    "created_at": "2026-04-22T11:12:34.693Z",
                    "post_number": 2,
                    "reply_to_post_number": 1,
                    "cooked": "<p>这是回复。</p>",
                },
            ]
        },
    }


def test_is_idcflare_url():
    assert is_idcflare_url("https://idcflare.com/t/topic/44294")
    assert is_idcflare_url("https://www.idcflare.com/t/slug/44294/2")
    assert not is_idcflare_url("https://linux.do/t/topic/44294")


def test_parse_idcflare_url_variants():
    assert parse_idcflare_url("https://idcflare.com/t/topic/44294") == ("topic", "44294", None)
    assert parse_idcflare_url("https://idcflare.com/t/my-slug/44294/2") == ("my-slug", "44294", "2")
    assert parse_idcflare_url("https://idcflare.com/t/44294") == ("topic", "44294", None)


def test_reader_detects_idcflare_platform():
    reader = UniversalReader()
    assert reader._detect_platform("https://idcflare.com/t/topic/44294") == "idcflare"


def test_idcflare_html_to_markdown_makes_links_absolute():
    html = (
        "<p>Hello <strong>IDCFlare</strong></p>"
        "<p><a href=\"/t/topic/44294\">站内链接</a></p>"
    )
    md = _html_to_markdown(html)
    assert "Hello **IDCFlare**" in md
    assert "https://idcflare.com/t/topic/44294" in md


def test_parse_topic_payload_cleans_discourse_shortcode_title():
    payload = _sample_topic_payload()
    payload["title"] = ":fire: IDCFlare 线路汇总帖"
    data = _parse_topic_payload(payload, "https://idcflare.com/t/topic/44294")
    assert data["title"] == "IDCFlare 线路汇总帖"


def test_parse_topic_payload_defaults_to_author_replies_only(monkeypatch):
    payload = _sample_topic_payload()
    payload["post_stream"]["posts"].append(
        {
            "id": 3,
            "username": "demo_user",
            "name": "",
            "created_at": "2026-04-22T12:00:00.000Z",
            "post_number": 3,
            "reply_to_post_number": 2,
            "cooked": "<p>这是楼主补充。</p>",
        }
    )
    monkeypatch.setattr("feedgrab.config.idcflare_reply_mode", lambda: "author")
    data = _parse_topic_payload(payload, "https://idcflare.com/t/topic/44294")
    assert "## 楼主回复 (1)" in data["content"]
    assert "### [3楼] demo_user" in data["content"]
    assert "这是楼主补充。" in data["content"]
    assert "### [2楼] Reply User" not in data["content"]
    assert data["reply_mode"] == "author"
    assert data["rendered_reply_count"] == 1


def test_parse_topic_payload_supports_all_reply_mode(monkeypatch):
    monkeypatch.setattr("feedgrab.config.idcflare_reply_mode", lambda: "all")
    data = _parse_topic_payload(_sample_topic_payload(), "https://idcflare.com/t/topic/44294")
    assert data["title"] == "IDCFlare 测试帖子"
    assert data["author"] == "demo_user"
    assert data["category"] == "VPS"
    assert data["topic_id"] == "44294"
    assert "首帖正文。" in data["content"]
    assert "## 回复 (1)" in data["content"]
    assert "### [2楼] Reply User" in data["content"]
    assert "````bash" in data["content"]
    assert data["reply_mode"] == "all"
    assert data["rendered_reply_count"] == 1


def test_parse_topic_payload_supports_none_reply_mode(monkeypatch):
    monkeypatch.setattr("feedgrab.config.idcflare_reply_mode", lambda: "none")
    data = _parse_topic_payload(_sample_topic_payload(), "https://idcflare.com/t/topic/44294")
    assert "## 回复" not in data["content"]
    assert "## 楼主回复" not in data["content"]
    assert "### [2楼]" not in data["content"]
    assert data["reply_mode"] == "none"
    assert data["rendered_reply_count"] == 0


def test_idcflare_html_to_markdown_filters_custom_sticker_gif():
    html = (
        '<p><img src="https://cdn3.ldstatic.com/original/4X/5/f/1/5f11f27d7ec1ad2818db9a10b1a8a318ae0dffc2.gif" '
        'alt="快做啊,哈雷" width="398" height="376" class="animated"></p>'
        "<p>不是，今天怎么发这么多次帖…(⊙_⊙;)…</p>"
    )
    md = _html_to_markdown(html)
    assert "5f11f27d7ec1ad2818db9a10b1a8a318ae0dffc2.gif" not in md
    assert "快做啊,哈雷" not in md
    assert "不是，今天怎么发这么多次帖" in md


def test_idcflare_html_to_markdown_keeps_content_gif_with_filename_like_alt():
    html = (
        '<p><img src="https://cdn3.ldstatic.com/original/4X/f/1/a/f1aab7cf304e037dc060a30e2f22555a06a83a24.gif" '
        'alt="640 (5)" width="690" height="393" class="animated"></p>'
    )
    md = _html_to_markdown(html)
    assert '![640 (5)](https://cdn3.ldstatic.com/original/4X/f/1/a/f1aab7cf304e037dc060a30e2f22555a06a83a24.gif)' in md


def test_idcflare_html_to_markdown_keeps_code_fence_inside_blockquote():
    html = (
        "<blockquote><p>引用说明</p>"
        '<pre><code class="lang-bash">echo hi</code></pre>'
        "<p>引用收尾</p></blockquote>"
        "<p>尾部正文</p>"
    )
    md = _html_to_markdown(html)
    assert "> ````bash" in md
    assert "> echo hi" in md
    assert "> ````" in md
    assert "\n> 引用收尾" in md
    assert md.rstrip().endswith("尾部正文")


def test_from_idcflare_builds_unified_content():
    uc = from_idcflare(_parse_topic_payload(_sample_topic_payload(), "https://idcflare.com/t/topic/44294"))
    assert uc.source_type == SourceType.IDCFLARE
    assert uc.title == "IDCFlare 测试帖子"
    assert uc.source_name == "demo_user"
    assert uc.extra["topic_id"] == "44294"
    assert uc.extra["views"] == 123
    assert uc.extra["reply_mode"] == "author"


def test_platform_folder_map_covers_idcflare():
    assert PLATFORM_FOLDER_MAP[SourceType.IDCFLARE] == "IDCFlare"


def test_http_fetch_topic_json_skips_terminal_404_after_challenge(monkeypatch):
    class _Resp:
        def __init__(self, status_code, text, headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

        def json(self):
            return {}

    responses = [_Resp(403, "Just a moment..."), _Resp(404, "")]

    def _fake_get(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr("feedgrab.config.get_stealth_headers", lambda: {})
    monkeypatch.setattr("feedgrab.fetchers.idcflare._cookie_header_from_session", lambda: "")
    monkeypatch.setattr("feedgrab.fetchers.idcflare.http_client.get", _fake_get)

    payload, terminal_error = _http_fetch_topic_json("https://idcflare.com/t/topic/44294")
    assert payload is None
    assert terminal_error is None


def test_http_fetch_topic_json_detects_cf_header_challenge(monkeypatch):
    class _Resp:
        def __init__(self, status_code, text, headers=None):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}

        def json(self):
            return {}

    responses = [
        _Resp(403, "page not found", {"Cf-Mitigated": "challenge"}),
        _Resp(404, "", {}),
    ]

    def _fake_get(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr("feedgrab.config.get_stealth_headers", lambda: {})
    monkeypatch.setattr("feedgrab.fetchers.idcflare._cookie_header_from_session", lambda: "")
    monkeypatch.setattr("feedgrab.fetchers.idcflare.http_client.get", _fake_get)

    payload, terminal_error = _http_fetch_topic_json("https://idcflare.com/t/topic/44294")
    assert payload is None
    assert terminal_error is None


def test_warmup_idcflare_session_syncs_once(monkeypatch):
    session_file = Path.cwd() / "sessions" / "_test_idcflare_warmup.json"
    if session_file.exists():
        session_file.unlink()
    calls = {"cdp": 0}

    monkeypatch.setattr("feedgrab.fetchers.idcflare._session_path", lambda: session_file)
    monkeypatch.setattr("feedgrab.config.idcflare_cdp_enabled", lambda: True)

    async def _fake_connect():
        calls["cdp"] += 1
        session_file.write_text(
            '{"cookies":[{"name":"_forum_session","value":"ok","domain":".idcflare.com"}],"origins":[]}',
            encoding="utf-8",
        )
        return None

    monkeypatch.setattr("feedgrab.fetchers.idcflare._connect_idcflare_cdp", _fake_connect)

    asyncio.run(_warmup_idcflare_session_from_cdp())
    assert calls["cdp"] == 1
    assert session_file.exists()

    asyncio.run(_warmup_idcflare_session_from_cdp())
    assert calls["cdp"] == 1

    if session_file.exists():
        session_file.unlink()
