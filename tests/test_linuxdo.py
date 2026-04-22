# -*- coding: utf-8 -*-
"""LinuxDo / Discourse topic parsing tests."""

from feedgrab.fetchers.linuxdo import (
    _extract_first_image,
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


def test_linuxdo_html_to_markdown_simplifies_lightbox_images():
    html = (
        '<p><a class="lightbox" href="https://cdn3.linux.do/original/4X/c/a/7/demo.jpeg" '
        'title="封面-1-设计稿 (1)">'
        '<img src="https://cdn3.linux.do/optimized/4X/c/a/7/demo_2_690x388.jpeg" '
        'alt="封面-1-设计稿 (1)">'
        '<span class="meta">'
        '<span class="filename">封面-1-设计稿 (1)</span>'
        '<span class="informations">1920×1080 135 KB</span>'
        "</span>"
        "</a></p>"
    )
    md = _html_to_markdown(html)
    assert '![封面-1-设计稿 (1)](https://cdn3.linux.do/original/4X/c/a/7/demo.jpeg)' in md
    assert "optimized/4X" not in md
    assert "1920×1080 135 KB" not in md
    assert not md.startswith("[![")


def test_linuxdo_html_to_markdown_filters_avatar_images():
    html = (
        "<p>引用卡片保留正文。</p>"
        '<p><img src="https://cdn.ldstatic.com/user_avatar/linux.do/sandun/48/1505730_2.png" alt=""></p>'
        '<p><img src="https://cdn.ldstatic.com/letter_avatar/linux.do/koushuiwa/48/5_c16b2ee14fe83ed9a59fc65fbec00f85.png" alt=""></p>'
        '<p><a href="/t/topic/1782304">原帖链接</a></p>'
    )
    md = _html_to_markdown(html)
    assert "引用卡片保留正文。" in md
    assert "原帖链接" in md
    assert "https://linux.do/t/topic/1782304" in md
    assert "user_avatar" not in md
    assert "letter_avatar" not in md


def test_linuxdo_html_to_markdown_filters_emoji_images_in_links():
    html = (
        '<p><a href="/t/topic/1976476/1">'
        '尼区timon钱包成功订阅claude max20x 实付156'
        '<img src="https://cdn.ldstatic.com/images/emoji/twemoji/kitchen_knife.png?v=15" alt="kitchen_knife">'
        '(约1064 rmb),订阅经验分享'
        "</a></p>"
    )
    md = _html_to_markdown(html)
    assert "emoji/twemoji" not in md
    assert "kitchen_knife" not in md
    assert "(约1064 rmb),订阅经验分享" in md
    assert "https://linux.do/t/topic/1976476/1" in md


def test_linuxdo_html_to_markdown_filters_twemoji_keyword_images():
    html = (
        '<p><a href="/t/topic/1976476/1">'
        '链接标题'
        '<img src="https://cdn.ldstatic.com/assets/twemoji/kitchen_knife.png?v=15" alt="kitchen_knife">'
        '链接尾巴'
        "</a></p>"
    )
    md = _html_to_markdown(html)
    assert "assets/twemoji" not in md
    assert "kitchen_knife" not in md
    assert "链接标题链接尾巴" in md


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


def test_extract_first_image_prefers_lightbox_original():
    payload = {
        "image_url": "https://cdn3.ldstatic.com/optimized/4X/c/a/7/demo_2_1024x576.jpeg",
        "post_stream": {
            "posts": [
                {
                    "cooked": (
                        '<p><a class="lightbox" href="https://cdn3.linux.do/original/4X/c/a/7/demo.jpeg">'
                        '<img src="https://cdn3.linux.do/optimized/4X/c/a/7/demo_2_690x388.jpeg" alt="demo">'
                        "</a></p>"
                    )
                }
            ]
        }
    }
    assert _extract_first_image(payload) == "https://cdn3.linux.do/original/4X/c/a/7/demo.jpeg"


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
