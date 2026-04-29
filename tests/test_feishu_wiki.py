from feedgrab.fetchers.feishu import blocks_to_markdown
from feedgrab.fetchers.feishu_wiki import _normalize_sidebar_nodes


def test_normalize_sidebar_nodes_extracts_tokens_from_tree_node_uid():
    raw_nodes = [
        {
            "text": "📌 使用指南：如何最高效地学完这套教程（持续更新中）",
            "node_uid": "level=1&rootNodeId=TOC-ROOT&wikiToken=B8VDwLOcdiE3ybkoABMcpGbrn3g",
        },
        {
            "text": "知识猫图解：内容拆解 Agent 提示词",
            "node_uid": "firstLevelWikiToken=UpT6wphAiicrMFkvN0ncZYelnfd&level=2&rootNodeId=TOC-ROOT&wikiToken=ZFJswuByOi5okdkW9qZcrJEwn3b",
        },
    ]

    links = _normalize_sidebar_nodes(
        raw_nodes,
        base_url="https://ycnj2htgnvdy.feishu.cn",
    )

    assert links == [
        {
            "title": "📌 使用指南：如何最高效地学完这套教程（持续更新中）",
            "url": "https://ycnj2htgnvdy.feishu.cn/wiki/B8VDwLOcdiE3ybkoABMcpGbrn3g",
            "token": "B8VDwLOcdiE3ybkoABMcpGbrn3g",
        },
        {
            "title": "知识猫图解：内容拆解 Agent 提示词",
            "url": "https://ycnj2htgnvdy.feishu.cn/wiki/ZFJswuByOi5okdkW9qZcrJEwn3b",
            "token": "ZFJswuByOi5okdkW9qZcrJEwn3b",
        },
    ]


def test_normalize_sidebar_nodes_dedupes_virtual_tree_repeats_and_cleans_titles():
    raw_nodes = [
        {
            "text": "‍⁢​​⁣‌​一、先导篇：为什么应该选 GPT-Image2？ - 飞书云文档",
            "node_uid": "level=1&rootNodeId=TOC-ROOT&wikiToken=Eq4wwiM1piCB7Skqsn9cjUBqnNe",
        },
        {
            "text": "一、先导篇：为什么应该选 GPT-Image2？",
            "node_uid": "level=1&rootNodeId=TOC-ROOT&wikiToken=Eq4wwiM1piCB7Skqsn9cjUBqnNe",
        },
        {
            "title": "旧版锚点节点",
            "url": "https://ycnj2htgnvdy.feishu.cn/wiki/C3pdwDDqPizKjekwXvUcx2sCnNd",
        },
    ]

    links = _normalize_sidebar_nodes(
        raw_nodes,
        base_url="https://ycnj2htgnvdy.feishu.cn",
    )

    assert links == [
        {
            "title": "一、先导篇：为什么应该选 GPT-Image2？",
            "url": "https://ycnj2htgnvdy.feishu.cn/wiki/Eq4wwiM1piCB7Skqsn9cjUBqnNe",
            "token": "Eq4wwiM1piCB7Skqsn9cjUBqnNe",
        },
        {
            "title": "旧版锚点节点",
            "url": "https://ycnj2htgnvdy.feishu.cn/wiki/C3pdwDDqPizKjekwXvUcx2sCnNd",
            "token": "C3pdwDDqPizKjekwXvUcx2sCnNd",
        },
    ]


def test_blocks_to_markdown_renders_feishu_fallback_code_snapshot_as_fenced_code():
    blocks = [
        {
            "type": "fallback",
            "children": [],
            "snapshot": {
                "type": "code",
                "language": "Plain Text",
                "text": {
                    "initialAttributedTexts": {
                        "text": {
                            "0": "主标题：\"为什么你的知识卡片没人收藏\"\n",
                            "1": "模块 1：\"信息太散\"",
                        }
                    }
                },
            },
        }
    ]

    md = blocks_to_markdown(blocks)

    assert md == (
        "````plaintext\n"
        "主标题：\"为什么你的知识卡片没人收藏\"\n"
        "模块 1：\"信息太散\"\n"
        "````"
    )


def test_blocks_to_markdown_uses_four_backticks_for_regular_code_blocks():
    blocks = [
        {
            "type": "code",
            "zoneState": {
                "allText": "帮我做一张关于时间管理的图。\n",
                "content": {
                    "ops": [
                        {"insert": "帮我做一张关于时间管理的图。", "attributes": {}},
                        {"insert": "\n", "attributes": {"fixEnter": "true"}},
                    ]
                },
            },
            "snapshot": {"type": "code", "language": "Plain Text"},
        }
    ]

    md = blocks_to_markdown(blocks)

    assert md == "````plaintext\n帮我做一张关于时间管理的图。\n````"


def test_blocks_to_markdown_uses_snapshot_row_and_column_ids_for_feishu_tables():
    def text_block(text: str):
        return {
            "type": "text",
            "children": [],
            "zoneState": {
                "allText": text + "\n",
                "content": {
                    "ops": [
                        {"insert": text, "attributes": {}},
                        {"insert": "\n", "attributes": {"fixEnter": "true"}},
                    ]
                },
            },
            "snapshot": {"type": "text"},
        }

    def cell(text: str):
        return {
            "type": "table_cell",
            "children": [text_block(text)],
            "snapshot": {"type": "table_cell"},
        }

    blocks = [
        {
            "type": "table",
            "children": [
                cell("列1"),
                cell("列2"),
                cell("列3"),
                cell("值A"),
                cell("值B"),
                cell("值C"),
            ],
            "snapshot": {
                "type": "table",
                "rows_id": ["row1", "row2"],
                "columns_id": ["col1", "col2", "col3"],
            },
        }
    ]

    md = blocks_to_markdown(blocks)

    assert md == (
        "| 列1 | 列2 | 列3 |\n"
        "| --- | --- | --- |\n"
        "| 值A | 值B | 值C |"
    )
