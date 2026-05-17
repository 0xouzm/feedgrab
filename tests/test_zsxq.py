# -*- coding: utf-8 -*-
"""Zsxq (知识星球) fetcher tests — URL parsing, HTML→MD, terminal judging."""

import json

import pytest

from feedgrab.fetchers.zsxq import (
    _looks_like_login_required,
    _looks_like_not_found,
    _parse_article_html,
    _parse_topic_payload,
    _ql_editor_to_markdown,
    _select_comments,
    is_zsxq_url,
    parse_zsxq_url,
)
from feedgrab.reader import UniversalReader
from feedgrab.schema import SourceType, from_zsxq
from feedgrab.utils.storage import PLATFORM_FOLDER_MAP


# ---------------------------------------------------------------------------
# URL detection / parsing
# ---------------------------------------------------------------------------

def test_is_zsxq_url_recognises_all_subdomains():
    assert is_zsxq_url("https://articles.zsxq.com/id_sz9kew31q6we.html")
    assert is_zsxq_url("https://wx.zsxq.com/group/123/topic/456")
    assert is_zsxq_url("https://t.zsxq.com/yUX3P")
    assert is_zsxq_url("https://api.zsxq.com/v2/topics/1/info")
    assert not is_zsxq_url("https://example.com/zsxq.com")


def test_parse_zsxq_url_article():
    kind, primary_id, group_id = parse_zsxq_url(
        "https://articles.zsxq.com/id_sz9kew31q6we.html"
    )
    assert kind == "article"
    assert primary_id == "sz9kew31q6we"
    assert group_id == ""


def test_parse_zsxq_url_topic_group_path():
    kind, primary_id, group_id = parse_zsxq_url(
        "https://wx.zsxq.com/group/48885124524228/topic/82255821121544822"
    )
    assert kind == "topic"
    assert primary_id == "82255821121544822"
    assert group_id == "48885124524228"


def test_parse_zsxq_url_topic_dweb2():
    kind, primary_id, group_id = parse_zsxq_url(
        "https://wx.zsxq.com/dweb2/index/topic_detail/82255821121544822"
    )
    assert kind == "topic"
    assert primary_id == "82255821121544822"
    assert group_id == ""


def test_parse_zsxq_url_topic_hash_routed():
    kind, primary_id, group_id = parse_zsxq_url(
        "https://wx.zsxq.com/dweb/#/group/48885124524228/topic/82255821121544822"
    )
    assert kind == "topic"
    assert primary_id == "82255821121544822"
    assert group_id == "48885124524228"


def test_parse_zsxq_url_invalid_raises():
    with pytest.raises(ValueError):
        parse_zsxq_url("https://wx.zsxq.com/group/123/")
    with pytest.raises(ValueError):
        parse_zsxq_url("https://articles.zsxq.com/random.html")


def test_universal_reader_routes_zsxq():
    r = UniversalReader()
    assert r._detect_platform("https://articles.zsxq.com/id_sz9kew31q6we.html") == "zsxq"
    assert (
        r._detect_platform("https://wx.zsxq.com/group/48885124524228/topic/82255821121544822")
        == "zsxq"
    )
    assert r._detect_platform("https://t.zsxq.com/yUX3P") == "zsxq"


# ---------------------------------------------------------------------------
# HTML → Markdown
# ---------------------------------------------------------------------------

def test_ql_editor_extracts_paragraphs_and_code():
    html = (
        '<div class="ql-editor">'
        "<h1>测试标题</h1>"
        "<p>第一段内容。</p>"
        "<p>第二段，包含 <strong>加粗</strong> 文字。</p>"
        '<pre class="ql-syntax" spec-language="python">'
        "def hello():\n    print('hi')</pre>"
        "<p>结束段。</p>"
        "</div>"
    )
    md = _ql_editor_to_markdown(html)
    assert "测试标题" in md
    assert "第一段内容" in md
    assert "**加粗**" in md
    # 4 反引号代码围栏（与 LinuxDo / Feishu 对齐）
    assert "````python" in md
    assert "def hello()" in md
    assert "结束段" in md


def test_ql_editor_handles_empty():
    assert _ql_editor_to_markdown("") == ""


def test_parse_article_html_falls_back_to_login_error_when_no_ql_editor():
    html = "<html><head><title>登录 - 知识星球</title></head><body>请先登录</body></html>"
    with pytest.raises(RuntimeError, match=r"登录|加入"):
        _parse_article_html(html, "https://articles.zsxq.com/id_x.html", "x")


def test_parse_article_html_extracts_metadata():
    html = (
        "<html><head>"
        "<title>第 7 期分享 - 强子手记 - 知识星球</title>"
        '<meta name="author" content="强子">'
        '<meta property="og:site_name" content="强子手记">'
        '<meta property="og:image" content="https://images.zsxq.com/cover.jpg">'
        '<meta name="article:published_time" content="2026-05-08T10:00:00+08:00">'
        "</head><body>"
        '<div class="ql-editor"><p>正文段落一。</p><p>正文段落二。</p></div>'
        "<div>阅读 1234 · 点赞 56 · 评论 7</div>"
        "</body></html>"
    )
    data = _parse_article_html(
        html, "https://articles.zsxq.com/id_sz9kew31q6we.html", "sz9kew31q6we"
    )
    # 标题清理掉了 “- 知识星球” 后缀
    assert data["title"].endswith("强子手记")
    assert "知识星球" not in data["title"]
    assert data["author"] == "强子"
    assert data["group_name"] == "强子手记"
    assert data["cover_image"].endswith("cover.jpg")
    assert data["zsxq_type"] == "article"
    assert data["article_id"] == "sz9kew31q6we"
    assert data["likes"] == 56
    assert data["comments"] == 7
    assert data["reads"] == 1234
    assert "正文段落一" in data["content"]
    assert "正文段落二" in data["content"]


# ---------------------------------------------------------------------------
# JSON → Markdown (topic)
# ---------------------------------------------------------------------------

def _sample_topic_payload(text="今天分享一个关于 LLM 的小技巧。"):
    return {
        "succeeded": True,
        "resp_data": {
            "topic": {
                "topic_id": 82255821121544822,
                "type": "talk",
                "create_time": "2026-04-30T15:20:11.234+0800",
                "likes_count": 12,
                "comments_count": 3,
                "reading_count": 456,
                "rewards_count": 0,
                "talk": {
                    "owner": {"user_id": 9001, "name": "强子"},
                    "text": text,
                    "images": [
                        {"large": {"url": "https://images.zsxq.com/large.jpg"}},
                    ],
                },
                "group": {"group_id": 48885124524228, "name": "AI 编程方法论"},
            }
        },
    }


def test_parse_topic_payload_talk_form():
    payload = _sample_topic_payload()
    data = _parse_topic_payload(
        payload, "https://wx.zsxq.com/group/48885124524228/topic/82255821121544822",
        "82255821121544822", "48885124524228",
    )
    assert data["zsxq_type"] == "topic"
    assert data["author"] == "强子"
    assert data["group_id"] == "48885124524228"
    assert data["group_name"] == "AI 编程方法论"
    assert data["likes"] == 12
    assert data["comments"] == 3
    assert data["reads"] == 456
    assert "LLM" in data["content"]
    assert "https://images.zsxq.com/large.jpg" in data["content"]


def test_parse_topic_payload_qa_form():
    payload = {
        "succeeded": True,
        "resp_data": {
            "topic": {
                "topic_id": 1,
                "type": "q&a",
                "create_time": "2026-05-01T10:00:00+0800",
                "likes_count": 5,
                "comments_count": 0,
                "question": {"owner": {"user_id": 1, "name": "提问者"}, "text": "怎么用 Claude？"},
                "answer": {"owner": {"user_id": 9001, "name": "强子"}, "text": "先 newup。"},
                "group": {"group_id": 999, "name": "圈子"},
            }
        },
    }
    data = _parse_topic_payload(payload, "https://wx.zsxq.com/x", "1", "999")
    assert "❓" in data["content"]
    assert "💡" in data["content"]
    assert "提问者" in data["content"]
    assert "强子" in data["content"]
    assert "先 newup" in data["content"]


# ---------------------------------------------------------------------------
# Terminal-error sniffing
# ---------------------------------------------------------------------------

def test_login_required_hint_sniffer():
    assert _looks_like_login_required("您未加入该星球")
    assert _looks_like_login_required("登录已过期")
    assert _looks_like_login_required("无权访问")
    assert not _looks_like_login_required("正常文章正文内容")


def test_not_found_hint_sniffer():
    assert _looks_like_not_found("话题不存在")
    assert _looks_like_not_found("文章不存在或已被删除")
    assert not _looks_like_not_found("阅读 1234")


# ---------------------------------------------------------------------------
# Comment three-state filtering (mirrors LinuxDo)
# ---------------------------------------------------------------------------

def _comments_fixture():
    return [
        {"owner": {"user_id": 9001, "name": "强子"}, "text": "owner reply"},
        {"owner": {"user_id": 1234, "name": "fan"}, "text": "fan reply"},
        {"owner": {"user_id": 9001, "name": "强子"}, "text": "owner second"},
    ]


def test_select_comments_none_returns_empty():
    assert _select_comments(_comments_fixture(), 9001, "none") == []


def test_select_comments_all_returns_all():
    assert len(_select_comments(_comments_fixture(), 9001, "all")) == 3


def test_select_comments_author_filters_by_owner():
    out = _select_comments(_comments_fixture(), 9001, "author")
    assert len(out) == 2
    assert all((c.get("owner") or {}).get("user_id") == 9001 for c in out)


def test_select_comments_author_without_owner_id_returns_empty():
    assert _select_comments(_comments_fixture(), None, "author") == []


# ---------------------------------------------------------------------------
# Schema + storage integration
# ---------------------------------------------------------------------------

def test_from_zsxq_factory_preserves_extras():
    data = {
        "title": "测试",
        "author": "强子",
        "content": "正文",
        "url": "https://articles.zsxq.com/id_x.html",
        "zsxq_type": "article",
        "article_id": "x",
        "topic_id": "",
        "group_id": "g",
        "group_name": "圈",
        "likes": 1,
        "comments": 2,
        "reads": 3,
        "rewards": 4,
        "comment_mode": "author",
        "rendered_comment_count": 5,
        "created_at": "2026-05-08T10:00:00+08:00",
        "cover_image": "https://images.zsxq.com/c.jpg",
        "images": ["https://images.zsxq.com/1.jpg"],
        "tags": ["AI"],
        "is_silent": False,
    }
    item = from_zsxq(data)
    assert item.source_type == SourceType.ZSXQ
    assert item.title == "测试"
    assert item.source_name == "强子"
    assert item.extra["zsxq_type"] == "article"
    assert item.extra["article_id"] == "x"
    assert item.extra["group_name"] == "圈"
    assert item.extra["likes"] == 1
    assert item.extra["comment_mode"] == "author"
    assert item.extra["rendered_comment_count"] == 5


def test_platform_folder_map_zsxq():
    assert PLATFORM_FOLDER_MAP[SourceType.ZSXQ] == "Zsxq"
