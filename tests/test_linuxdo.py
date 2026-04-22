# -*- coding: utf-8 -*-
"""LinuxDo / Discourse topic parsing tests."""

from feedgrab.fetchers.linuxdo import (
    _html_to_markdown,
    _parse_topic_payload,
    is_linuxdo_url,
    parse_linuxdo_url,
)
from feedgrab.reader import UniversalReader
from feedgrab.schema import SourceType, from_linuxdo
from feedgrab.utils.storage import PLATFORM_FOLDER_MAP


def _sample_topic_payload():
    return {
        "id": 2032561,
        "title": "我需要问一个claude问题！",
        "slug": "topic",
        "posts_count": 2,
        "reply_count": 1,
        "like_count": 3,
        "views": 45,
        "created_at": "2026-04-22T14:20:25.368Z",
        "last_posted_at": "2026-04-22T14:32:34.693Z",
        "category_id": 4,
        "category_name": "开发调优",
        "tags": [
            {"name": "快问快答"},
            {"name": "人工智能"},
        ],
        "post_stream": {
            "posts": [
                {
                    "id": 17076763,
                    "username": "gekvap60",
                    "name": "",
                    "user_title": "一元复始",
                    "created_at": "2026-04-22T14:20:25.531Z",
                    "post_number": 1,
                    "reads": 55,
                    "reply_count": 1,
                    "quote_count": 0,
                    "cooked": (
                        "<p>这是首帖正文。</p>"
                        "<p><a href=\"/t/topic/2032561\">站内链接</a></p>"
                        "<pre><code class=\"lang-python\">print(1)\nprint(2)</code></pre>"
                        "<p><img src=\"/uploads/default/original/1X/demo.png\" alt=\"demo\"></p>"
                    ),
                },
                {
                    "id": 17077234,
                    "username": "reply_user",
                    "name": "Reply User",
                    "user_title": "热心佬友",
                    "created_at": "2026-04-22T14:32:34.693Z",
                    "post_number": 2,
                    "reads": 16,
                    "reply_count": 0,
                    "quote_count": 0,
                    "reply_to_post_number": 1,
                    "cooked": "<p>这是一个回复。</p>",
                },
            ]
        },
    }


def test_is_linuxdo_url():
    assert is_linuxdo_url("https://linux.do/t/topic/2032561")
    assert is_linuxdo_url("https://www.linux.do/t/slug/2032561/2")
    assert not is_linuxdo_url("https://example.com/t/topic/2032561")


def test_parse_linuxdo_url_variants():
    assert parse_linuxdo_url("https://linux.do/t/topic/2032561") == ("topic", "2032561", None)
    assert parse_linuxdo_url("https://linux.do/t/my-slug/2032561/2") == ("my-slug", "2032561", "2")
    assert parse_linuxdo_url("https://linux.do/t/2032561") == ("topic", "2032561", None)


def test_reader_detects_linuxdo_platform():
    reader = UniversalReader()
    assert reader._detect_platform("https://linux.do/t/topic/2032561") == "linuxdo"


def test_linuxdo_html_to_markdown_makes_links_absolute():
    html = (
        "<p>Hello <strong>LinuxDo</strong></p>"
        "<p><a href=\"/t/topic/2032561\">站内链接</a></p>"
        "<p><img src=\"/uploads/default/original/1X/demo.png\" alt=\"demo\"></p>"
    )
    md = _html_to_markdown(html)
    assert "Hello **LinuxDo**" in md
    assert "https://linux.do/t/topic/2032561" in md
    assert "https://linux.do/uploads/default/original/1X/demo.png" in md


def test_linuxdo_html_to_markdown_uses_callout_for_simple_details():
    html = (
        "<p>折叠前提示</p>"
        "<details><summary>点我展开</summary>"
        "<p>第一段</p><ul><li>第一项</li><li>第二项</li></ul>"
        "</details>"
    )
    md = _html_to_markdown(html)
    assert "> [!feedgrab-fold]- 点我展开" in md
    assert "> 第一段" in md
    assert "> - 第一项" in md
    assert "<details>" not in md


def test_linuxdo_html_to_markdown_preserves_complex_details_blocks():
    html = (
        "<p>折叠前提示</p>"
        "<details><summary>点我展开</summary>"
        "<h2>折叠标题</h2><p>折叠正文</p>"
        "</details>"
    )
    md = _html_to_markdown(html)
    assert '<details class="feedgrab-fold feedgrab-fold--complex">' in md
    assert '<summary class="feedgrab-fold__summary">点我展开</summary>' in md
    assert "<h2>折叠标题</h2>" in md
    assert "<p>折叠正文</p>" in md


def test_parse_topic_payload_builds_thread_markdown():
    data = _parse_topic_payload(
        _sample_topic_payload(),
        "https://linux.do/t/topic/2032561",
    )
    assert data["title"] == "我需要问一个claude问题！"
    assert data["author"] == "gekvap60"
    assert data["category"] == "开发调优"
    assert data["topic_id"] == "2032561"
    assert "这是首帖正文。" in data["content"]
    assert "## 回复 (1)" in data["content"]
    assert "### [2楼] Reply User" in data["content"]
    assert "```python" in data["content"]
    assert "https://linux.do/uploads/default/original/1X/demo.png" in data["content"]
    assert data["tags"] == ["快问快答", "人工智能"]


def test_from_linuxdo_builds_unified_content():
    uc = from_linuxdo(
        _parse_topic_payload(
            _sample_topic_payload(),
            "https://linux.do/t/topic/2032561",
        )
    )
    assert uc.source_type == SourceType.LINUXDO
    assert uc.title == "我需要问一个claude问题！"
    assert uc.source_name == "gekvap60"
    assert uc.extra["topic_id"] == "2032561"
    assert uc.extra["views"] == 45


def test_platform_folder_map_covers_linuxdo():
    assert PLATFORM_FOLDER_MAP[SourceType.LINUXDO] == "LinuxDo"
