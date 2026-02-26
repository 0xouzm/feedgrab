# -*- coding: utf-8 -*-
"""
Twitter/X thread Markdown renderer.

Ported from baoyu-danger-x-to-markdown thread-markdown.ts + tweet-to-markdown.ts.

Converts thread tweet data into well-formatted Markdown with:
    - YAML front matter (author, tweet_count, url)
    - Numbered tweet sections with full text
    - Inline images and video links
    - Quoted tweets as blockquotes
    - Tweet URLs for each entry
"""

from typing import Dict, Any, List, Optional


def render_thread_markdown(thread: Dict[str, Any], requested_url: str = "") -> str:
    """
    Render a complete thread as Markdown.

    Matches baoyu tweet-to-markdown.ts tweetToMarkdown() output format.

    Args:
        thread: Result from fetch_tweet_thread() with 'tweets', 'root_tweet', etc.
        requested_url: The original URL the user requested.

    Returns:
        Complete Markdown string with front matter and formatted thread.
    """
    tweets = thread.get("tweets", [])
    root = thread.get("root_tweet", {})
    author = thread.get("author", "")
    author_name = thread.get("author_name", "")

    if not tweets:
        return ""

    root_id = root.get("id", tweets[0].get("id", ""))
    root_url = f"https://x.com/{author}/status/{root_id}"

    parts = []

    # YAML front matter (matches baoyu tweet-to-markdown.ts)
    parts.append("---")
    parts.append(f"url: {root_url}")
    if requested_url and requested_url != root_url:
        parts.append(f"requested_url: {requested_url}")
    parts.append(f"author: \"{author_name} (@{author})\"")
    parts.append(f"author_name: \"{author_name}\"")
    parts.append(f"author_username: \"@{author}\"")
    parts.append(f"author_url: https://x.com/{author}")
    parts.append(f"tweet_count: {len(tweets)}")
    parts.append("---")
    parts.append("")

    # Thread body
    parts.append(format_thread_tweets(tweets, author, heading_level=2))

    return "\n".join(parts)


def format_thread_tweets(
    tweets: List[Dict[str, Any]],
    author: str,
    heading_level: int = 2,
    include_urls: bool = True,
) -> str:
    """
    Format a list of tweets as numbered Markdown sections.

    Matches baoyu thread-markdown.ts formatThreadTweetsMarkdown().

    Args:
        tweets: List of tweet dicts from thread fetcher.
        author: Author screen name.
        heading_level: Markdown heading level (2 = ##, 3 = ###).
        include_urls: Whether to include tweet URLs.

    Returns:
        Formatted Markdown string.
    """
    heading = "#" * heading_level
    parts = []

    for i, tweet in enumerate(tweets, start=1):
        tweet_id = tweet.get("id", "")
        tweet_url = f"https://x.com/{author}/status/{tweet_id}"

        # Section heading with index
        if len(tweets) > 1:
            parts.append(f"{heading} {i}")
        else:
            parts.append(f"{heading} Tweet")

        # Tweet URL
        if include_urls and tweet_id:
            parts.append(tweet_url)

        parts.append("")

        # Tweet text
        text = tweet.get("text", "").strip()
        if text:
            parts.append(text)
            parts.append("")

        # Images
        for img_url in tweet.get("images", []):
            if img_url:
                parts.append(f"![image]({img_url})")
        if tweet.get("images"):
            parts.append("")

        # Videos
        for video_url in tweet.get("videos", []):
            if video_url:
                parts.append(f"[video]({video_url})")
        if tweet.get("videos"):
            parts.append("")

        # Quoted tweet (as blockquote, matches baoyu thread-markdown.ts)
        qt = tweet.get("quoted_tweet")
        if qt and qt.get("text"):
            qt_author = qt.get("author", "")
            qt_name = qt.get("author_name", "")
            qt_id = qt.get("id", "")
            qt_url = f"https://x.com/{qt_author}/status/{qt_id}" if qt_author and qt_id else ""

            parts.append(f"> **{qt_name}** (@{qt_author})")
            if qt_url:
                parts.append(f"> URL: {qt_url}")
            parts.append(">")
            # Indent quoted text
            for line in qt["text"].split("\n"):
                parts.append(f"> {line}")
            parts.append("")

        parts.append("")

    return "\n".join(parts).strip()


def render_single_tweet_markdown(tweet: Dict[str, Any]) -> str:
    """
    Render a single tweet as Markdown (no thread context).

    Used when GraphQL returns a single tweet without thread data.

    Args:
        tweet: Tweet dict from extract_tweet_data().

    Returns:
        Markdown string.
    """
    author = tweet.get("author", "")
    author_name = tweet.get("author_name", "")
    tweet_id = tweet.get("id", "")
    tweet_url = f"https://x.com/{author}/status/{tweet_id}"

    parts = []

    # Front matter
    parts.append("---")
    parts.append(f"url: {tweet_url}")
    parts.append(f"author: \"{author_name} (@{author})\"")
    parts.append(f"tweet_count: 1")
    parts.append("---")
    parts.append("")

    # Tweet text
    text = tweet.get("text", "").strip()
    if text:
        parts.append(text)
        parts.append("")

    # Images
    for img_url in tweet.get("images", []):
        if img_url:
            parts.append(f"![image]({img_url})")
    if tweet.get("images"):
        parts.append("")

    # Videos
    for video_url in tweet.get("videos", []):
        if video_url:
            parts.append(f"[video]({video_url})")
    if tweet.get("videos"):
        parts.append("")

    # Quoted tweet
    qt = tweet.get("quoted_tweet")
    if qt and qt.get("text"):
        qt_author = qt.get("author", "")
        qt_name = qt.get("author_name", "")
        qt_id = qt.get("id", "")
        qt_url = f"https://x.com/{qt_author}/status/{qt_id}" if qt_author and qt_id else ""

        parts.append(f"> **{qt_name}** (@{qt_author})")
        if qt_url:
            parts.append(f"> URL: {qt_url}")
        parts.append(">")
        for line in qt["text"].split("\n"):
            parts.append(f"> {line}")
        parts.append("")

    # Engagement metrics
    likes = tweet.get("likes", 0)
    retweets = tweet.get("retweets", 0)
    views = tweet.get("views", "0")
    if any([likes, retweets, views != "0"]):
        parts.append("---")
        metrics = []
        if likes:
            metrics.append(f"Likes: {likes:,}")
        if retweets:
            metrics.append(f"Retweets: {retweets:,}")
        if views and views != "0":
            metrics.append(f"Views: {int(views):,}")
        parts.append(" | ".join(metrics))

    return "\n".join(parts)
