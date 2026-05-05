# -*- coding: utf-8 -*-
"""Twitter/X schema rendering regressions."""

from feedgrab.schema import from_twitter


def test_long_thread_with_quoted_tweet_is_not_misclassified_as_article():
    long_root = "看了4篇教程，终于成为土耳其ChatGPT用户！" + "补充说明" * 130
    data = {
        "text": long_root,
        "author": "@daodao166888",
        "author_name": "刀刀",
        "url": "https://x.com/daodao166888/status/2051640789206499666",
        "title": "看了4篇教程，终于成为土耳其ChatGPT用户！",
        "platform": "twitter",
        "thread_tweets": [
            {
                "id": "2051640789206499666",
                "text": long_root,
                "author": "daodao166888",
                "author_name": "刀刀",
                "images": [],
                "videos": [],
            },
            {
                "id": "2051641511692108146",
                "text": "参考的4条X推文（感谢三位大佬的无私分享！❤️）",
                "author": "daodao166888",
                "author_name": "刀刀",
                "images": [],
                "videos": [],
                "quoted_tweet": {
                    "id": "2050951612546638254",
                    "text": "土耳其 Apple ID 礼品卡充值教程原文",
                    "author": "yanhua1010",
                    "author_name": "烟花",
                    "url": "https://x.com/yanhua1010/status/2050951612546638254",
                    "images": [],
                    "videos": [],
                },
            },
            {
                "id": "2051673715340107821",
                "text": "Authenticator App 二次验证操作补充",
                "author": "daodao166888",
                "author_name": "刀刀",
                "images": [],
                "videos": [],
                "quoted_tweet": {
                    "id": "2051672318968320149",
                    "text": "OpenAI 账号安全设置补充说明",
                    "author": "daodao166888",
                    "author_name": "刀刀",
                    "url": "https://x.com/daodao166888/status/2051672318968320149",
                    "images": [],
                    "videos": [],
                },
            },
        ],
        "article_data": {},
    }

    content = from_twitter(data)

    assert content.extra["tweet_type"] == "thread"
    assert "土耳其 Apple ID 礼品卡充值教程原文" in content.content
    assert "OpenAI 账号安全设置补充说明" in content.content
    assert "> **烟花** (@yanhua1010)" in content.content
