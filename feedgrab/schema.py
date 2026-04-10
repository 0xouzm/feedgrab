# -*- coding: utf-8 -*-
"""
Unified content schema for feedgrab.

Defines the standard data format for all content sources:
- Telegram channels
- RSS feeds
- Bilibili videos
- Xiaohongshu (RED) notes
- WeChat articles
- X/Twitter posts
- YouTube videos
- Manual input
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum
import hashlib
import json
import re


class SourceType(str, Enum):
    """Content source types."""
    TELEGRAM = "telegram"
    RSS = "rss"
    BILIBILI = "bilibili"
    XIAOHONGSHU = "xhs"
    TWITTER = "twitter"
    WECHAT = "wechat"
    YOUTUBE = "youtube"
    GITHUB = "github"
    FEISHU = "feishu"
    KDOCS = "kdocs"
    YOUDAO = "youdao"
    ZHIHU = "zhihu"
    MANUAL = "manual"


class MediaType(str, Enum):
    """Media types."""
    TEXT = "text"
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"


class Priority(str, Enum):
    """Content priority levels."""
    HOT = "hot"
    QUALITY = "quality"
    DEEP = "deep"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class UnifiedContent:
    """Unified content format across all platforms."""

    # === Required ===
    source_type: SourceType
    source_name: str
    title: str
    content: str
    url: str

    # === Auto-generated ===
    id: str = ""
    fetched_at: str = ""

    # === Media ===
    media_type: MediaType = MediaType.TEXT
    media_url: Optional[str] = None

    # === Scoring ===
    score: int = 0
    priority: Priority = Priority.NORMAL
    category: str = ""
    tags: List[str] = field(default_factory=list)

    # === Processing state ===
    processed: bool = False
    digest_date: Optional[str] = None

    # === Translation ===
    title_cn: Optional[str] = None
    content_cn: Optional[str] = None

    # === Metadata ===
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = hashlib.md5(self.url.encode()).hexdigest()[:12]
        if not self.fetched_at:
            self.fetched_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d['source_type'] = self.source_type.value
        d['media_type'] = self.media_type.value
        d['priority'] = self.priority.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'UnifiedContent':
        if isinstance(data.get('source_type'), str):
            data['source_type'] = SourceType(data['source_type'])
        if isinstance(data.get('media_type'), str):
            data['media_type'] = MediaType(data['media_type'])
        if isinstance(data.get('priority'), str):
            data['priority'] = Priority(data['priority'])
        known = {f.name for f in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in data.items() if k in known}
        return cls(**data)


# =============================================================================
# Converters: platform-specific dict → UnifiedContent
# =============================================================================

def from_telegram(msg: dict, channel_name: str, channel_username: str) -> UnifiedContent:
    return UnifiedContent(
        source_type=SourceType.TELEGRAM,
        source_name=channel_name,
        title=msg.get('text', '')[:100],
        content=msg.get('text', ''),
        url=msg.get('url', f"https://t.me/{channel_username}"),
        extra={"views": msg.get('views', 0), "channel_username": channel_username},
    )


def from_rss(article: dict) -> UnifiedContent:
    return UnifiedContent(
        source_type=SourceType.RSS,
        source_name=article.get('source', ''),
        title=article.get('title', ''),
        content=article.get('summary', ''),
        url=article.get('url', article.get('link', '')),
        score=article.get('score', 0),
        category=article.get('category', ''),
        title_cn=article.get('title_cn'),
        content_cn=article.get('summary_cn'),
    )


def from_bilibili(video: dict) -> UnifiedContent:
    return UnifiedContent(
        source_type=SourceType.BILIBILI,
        source_name=video.get('author', ''),
        title=video.get('title', ''),
        content=video.get('description', ''),
        url=video.get('url', ''),
        media_type=MediaType.VIDEO,
        media_url=video.get('cover', ''),
        extra={
            "bvid": video.get('bvid', ''),
            "duration": video.get('duration', 0),
            "view_count": video.get('view_count', 0),
        },
    )


def _render_quoted_tweet(qt: dict) -> str:
    """Render a quoted tweet as a Markdown blockquote with full content."""
    if not qt or not qt.get("text"):
        return ""
    lines = []
    author = qt.get("author", "")
    author_name = qt.get("author_name", "")
    qt_url = qt.get("url", "")
    # Header line
    if author_name:
        lines.append(f"> **{author_name}** (@{author})")
    else:
        lines.append(f"> **@{author}**")
    if qt_url:
        lines.append(f"> {qt_url}")
    lines.append(">")
    # Text body
    for line in qt["text"].split("\n"):
        lines.append(f"> {line}")
    # Images
    for img in qt.get("images", []):
        if img:
            lines.append(f">\n> ![image]({img})")
    # Videos
    for vid in qt.get("videos", []):
        if vid:
            lines.append(f">\n> [▶ video]({vid})")
    return "\n".join(lines)


def from_twitter(data: dict) -> UnifiedContent:
    # If thread data is present, assemble rich content from all tweets
    tweets = data.get("thread_tweets", [])
    article_data = data.get("article_data") or {}
    is_article = False

    if tweets:
        root_text = tweets[0].get("text", "")
        # Detect Article: root tweet text is long (Jina-fetched body), don't wrap in [1/N]
        is_article = len(root_text) > 500 and len(tweets) <= 3
        if is_article:
            content = root_text
            # Append author replies as footnotes if any
            if len(tweets) > 1:
                replies = []
                for t in tweets[1:]:
                    reply_text = t.get("text", "").strip()
                    if reply_text:
                        replies.append(reply_text)
                if replies:
                    content += "\n\n---\n\n" + "\n\n".join(replies)
            # Article: append images at the end
            for t in tweets:
                for img_url in t.get("images", []):
                    content += f"\n\n![image]({img_url})"
            # Article: append videos
            for t in tweets:
                for video_url in t.get("videos", []):
                    if video_url:
                        content += f"\n\n[▶ video]({video_url})"
            # Article: prepend cover image at the top
            article_cover = article_data.get("cover_image", "")
            if article_cover:
                content = f"![cover]({article_cover})\n\n{content}"
        else:
            parts = []
            rest_count = len(tweets) - 1
            for i, t in enumerate(tweets):
                text = t.get('text', '')
                # First tweet (main post): no prefix
                # Subsequent tweets: [1/N]...[N/N]
                if len(tweets) > 1 and i > 0:
                    part = f"**[{i}/{rest_count}]** {text}"
                else:
                    part = text
                # Inline images
                for img_url in t.get("images", []):
                    part += f"\n\n![image]({img_url})"
                # Inline videos
                for video_url in t.get("videos", []):
                    if video_url:
                        part += f"\n\n[▶ video]({video_url})"
                # Quoted tweet — full blockquote with media
                qt = t.get("quoted_tweet")
                qt_block = _render_quoted_tweet(qt)
                if qt_block:
                    part += f"\n\n{qt_block}"
                parts.append(part)
            content = "\n\n---\n\n".join(parts)
    else:
        content = data.get("text", "")

    # cover_image: article cover > explicit cover_image > first image
    cover_image = article_data.get("cover_image", "") if is_article else ""
    if not cover_image:
        cover_image = data.get("cover_image", "")
    if not cover_image and data.get("images"):
        cover_image = data["images"][0]

    # Classify tweet type: article / thread / status
    if is_article or article_data.get("has_content"):
        tweet_type = "article"
    elif tweets and len(tweets) > 1:
        tweet_type = "thread"
    else:
        tweet_type = "status"

    return UnifiedContent(
        source_type=SourceType.TWITTER,
        source_name=data.get("author", ""),
        title=data.get("title", re.sub(r'[\r\n\t]+', '', data.get("text", ""))[:50]),
        content=content,
        url=data.get("url", ""),
        tags=data.get("hashtags", []),
        extra={
            "tweet_type": tweet_type,
            "tweet_count": len(tweets) if tweets else 1,
            "has_thread": bool(tweets),
            "author_name": data.get("author_name", ""),
            "created_at": data.get("created_at", ""),
            "cover_image": cover_image,
            "likes": data.get("likes", 0),
            "retweets": data.get("retweets", 0),
            "replies": data.get("replies", 0),
            "bookmarks": data.get("bookmarks", 0),
            "views": data.get("views", "0"),
            "images": data.get("images", []),
            "videos": data.get("videos", []),
            "quoted_tweets": data.get("quoted_tweets", []),
            "author_replies": data.get("author_replies", []),
            "comments": data.get("comments", []),
            # New metadata
            "quote_count": data.get("quote_count", 0),
            "lang": data.get("lang", ""),
            "source_app": data.get("source_app", ""),
            "possibly_sensitive": data.get("possibly_sensitive", False),
            "is_blue_verified": data.get("is_blue_verified", False),
            "followers_count": data.get("followers_count", 0),
            "statuses_count": data.get("statuses_count", 0),
            "listed_count": data.get("listed_count", 0),
        },
    )


def from_wechat(article: dict) -> UnifiedContent:
    # Best cover image: article page cover > sogou thumbnail
    cover_image = article.get('cover_image', '') or article.get('thumbnail', '')
    content_text = article.get('content', '')

    # Extract video URLs from JS evaluate data
    raw_videos = article.get('videos', [])
    video_urls = [v['src'] for v in raw_videos if v.get('src')]
    image_urls = []  # WeChat images are inline in HTML, not separate list

    # Prepend cover image at top of content
    if cover_image and content_text:
        content_text = f"![cover]({cover_image})\n\n{content_text}"
    elif cover_image:
        content_text = f"![cover]({cover_image})"

    return UnifiedContent(
        source_type=SourceType.WECHAT,
        source_name=article.get('author', ''),
        title=article.get('title', ''),
        content=content_text,
        url=article.get('url', ''),
        tags=article.get('tags', []),
        extra={
            "publish_date": article.get('publish_date', ''),
            "cover_image": cover_image,
            "thumbnail": article.get('thumbnail', ''),
            "summary": article.get('summary', ''),
            "original_url": article.get('original_url', ''),
            "search_keyword": article.get('search_keyword', ''),
            "reads": article.get('reads', 0),
            "likes": article.get('likes', 0),
            "wow": article.get('wow', 0),
            "shares": article.get('shares', 0),
            "comments": article.get('comments', 0),
            "comment_list": article.get('comment_list', []),
            "videos": video_urls,
            "images": image_urls,
        },
    )


def from_xiaohongshu(note: dict) -> UnifiedContent:
    images = note.get('images', [])
    note_type = note.get('note_type', '')
    media = MediaType.VIDEO if note_type == 'video' else (MediaType.IMAGE if images else MediaType.TEXT)
    return UnifiedContent(
        source_type=SourceType.XIAOHONGSHU,
        source_name=note.get('author', ''),
        title=note.get('title', ''),
        content=note.get('content', ''),
        url=note.get('url', ''),
        media_type=media,
        tags=note.get('tags', []),
        extra={
            "author_url": note.get('author_url', ''),
            "cover_image": images[0] if images else "",
            "likes": note.get('likes', 0),
            "collects": note.get('collects', 0),
            "comments": note.get('comments', 0),
            "share_count": note.get('share_count', 0),
            "note_type": note_type,
            "images": images,
            "date": note.get('date', ''),
            "comment_list": note.get('comment_list', []),
        },
    )


def from_youtube(video: dict) -> UnifiedContent:
    published = video.get("published_at", "")
    if published:
        # ISO 8601 → YYYY-MM-DD HH:MM
        try:
            dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
            published = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            published = published[:10]

    return UnifiedContent(
        source_type=SourceType.YOUTUBE,
        source_name=video.get('author', '') or video.get('channel_title', ''),
        title=video.get('title', ''),
        content=video.get('description', ''),
        url=video.get('url', ''),
        media_type=MediaType.VIDEO,
        tags=video.get('tags', []),
        extra={
            "video_id": video.get('video_id', ''),
            "duration": video.get('duration', ''),
            "duration_seconds": video.get('duration_seconds', 0),
            "view_count": video.get('view_count', 0),
            "like_count": video.get('like_count', 0),
            "comment_count": video.get('comment_count', 0),
            "channel_id": video.get('channel_id', ''),
            "published_at": published,
            "category_id": video.get('category_id', ''),
            "definition": video.get('definition', ''),
            "has_caption": video.get('has_caption', False),
            "has_transcript": video.get('has_transcript', False),
            "thumbnail": video.get('thumbnail', ''),
        },
    )


def from_github(data: dict) -> UnifiedContent:
    """Convert GitHub repo data dict to UnifiedContent."""
    owner = data.get("owner", "")
    repo = data.get("repo", "")
    repo_key = f"{owner}/{repo}"
    item_id = hashlib.md5(repo_key.encode()).hexdigest()[:12]

    title = data.get("title", repo)

    return UnifiedContent(
        source_type=SourceType.GITHUB,
        source_name=owner,
        title=title,
        content=data.get("content", ""),
        url=data.get("url", f"https://github.com/{owner}/{repo}"),
        id=item_id,
        tags=data.get("topics", []),
        extra={
            "owner": owner,
            "repo": repo,
            "full_name": data.get("full_name", repo_key),
            "description": data.get("description", ""),
            "stars": data.get("stars", 0),
            "forks": data.get("forks", 0),
            "language": data.get("language", ""),
            "license": data.get("license", ""),
            "default_branch": data.get("default_branch", "main"),
            "open_issues": data.get("open_issues", 0),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""),
            "pushed_at": data.get("pushed_at", ""),
            "owner_avatar": data.get("owner_avatar", ""),
            "readme_file": data.get("readme_file", "README.md"),
        },
    )


def from_feishu(data: dict) -> UnifiedContent:
    return UnifiedContent(
        source_type=SourceType.FEISHU,
        source_name=data.get("author", ""),
        title=data.get("title", ""),
        content=data.get("content", ""),
        url=data.get("url", ""),
        tags=data.get("tags", []),
        extra={
            "doc_type": data.get("doc_type", ""),
            "doc_token": data.get("doc_token", ""),
            "word_count": data.get("word_count", 0),
            "create_time": data.get("create_time", ""),
            "edit_time": data.get("edit_time", ""),
            "cover_image": data.get("cover_image", ""),
            "images": data.get("images", []),
            "images_info": data.get("images_info", []),
            "img_subdir": data.get("img_subdir", ""),
        },
    )


def from_kdocs(data: dict) -> UnifiedContent:
    """Convert KDocs (WPS) data dict to UnifiedContent."""
    return UnifiedContent(
        source_type=SourceType.KDOCS,
        source_name=data.get("author", ""),
        title=data.get("title", ""),
        content=data.get("content", ""),
        url=data.get("url", ""),
        tags=data.get("tags", []),
        extra={
            "doc_token": data.get("doc_token", ""),
            "word_count": data.get("word_count", 0),
            "create_time": data.get("create_time", ""),
            "edit_time": data.get("edit_time", ""),
            "creator_id": data.get("creator_id", ""),
            "images_info": data.get("images_info", []),
            "img_subdir": data.get("img_subdir", ""),
        },
    )


def from_youdao(data: dict) -> UnifiedContent:
    """Convert Youdao Note data dict to UnifiedContent."""
    return UnifiedContent(
        source_type=SourceType.YOUDAO,
        source_name=data.get("author", ""),
        title=data.get("title", ""),
        content=data.get("content", ""),
        url=data.get("url", ""),
        tags=data.get("tags", []),
        extra={
            "share_key": data.get("share_key", ""),
            "page_views": data.get("page_views", 0),
            "create_time": data.get("create_time", ""),
            "edit_time": data.get("edit_time", ""),
            "images_info": data.get("images_info", []),
            "img_subdir": data.get("img_subdir", ""),
        },
    )


def from_zhihu(data: dict) -> UnifiedContent:
    """Convert Zhihu data dict to UnifiedContent."""
    return UnifiedContent(
        source_type=SourceType.ZHIHU,
        source_name=data.get("author", ""),
        title=data.get("title", ""),
        content=data.get("content", ""),
        url=data.get("url", ""),
        tags=data.get("tags", []),
        extra={
            "content_type": data.get("content_type", ""),
            "question_id": data.get("question_id", ""),
            "answer_id": data.get("answer_id", ""),
            "article_id": data.get("article_id", ""),
            "question_title": data.get("question_title", ""),
            "question_detail": data.get("question_detail", ""),
            "upvotes": data.get("upvotes", 0),
            "comments": data.get("comments", 0),
            "thanks": data.get("thanks", 0),
            "collected": data.get("collected", 0),
            "views": data.get("views", 0),
            "author_url": data.get("author_url", ""),
            "publish_date": data.get("publish_date", ""),
            "img_subdir": data.get("img_subdir", ""),
            "answers_list": data.get("answers_list", []),
        },
    )


def from_manual(title: str, content: str, url: str = "") -> UnifiedContent:
    return UnifiedContent(
        source_type=SourceType.MANUAL,
        source_name="manual",
        title=title,
        content=content,
        url=url or f"manual://{hashlib.md5(title.encode()).hexdigest()[:8]}",
    )


# =============================================================================
# Unified Inbox
# =============================================================================

class UnifiedInbox:
    """JSON-based content inbox with dedup."""

    def __init__(self, filepath: str = "unified_inbox.json"):
        self.filepath = filepath
        self.items: List[UnifiedContent] = []
        self.load()

    def load(self):
        import os
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.items = [UnifiedContent.from_dict(d) for d in data]
            except (json.JSONDecodeError, IOError):
                self.items = []

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump([item.to_dict() for item in self.items], f,
                      ensure_ascii=False, indent=2)

    def add(self, item: UnifiedContent) -> bool:
        if any(i.id == item.id for i in self.items):
            return False
        self.items.append(item)
        return True

    def add_batch(self, items: List[UnifiedContent]) -> int:
        return sum(1 for item in items if self.add(item))

    def get_unprocessed(self) -> List[UnifiedContent]:
        return [i for i in self.items if not i.processed]

    def get_by_source(self, source_type: SourceType) -> List[UnifiedContent]:
        return [i for i in self.items if i.source_type == source_type]

    def mark_processed(self, item_id: str, digest_date: str = None):
        for item in self.items:
            if item.id == item_id:
                item.processed = True
                if digest_date:
                    item.digest_date = digest_date
                break

    def clear_old(self, days: int = 7):
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self.items = [i for i in self.items if i.fetched_at > cutoff]
