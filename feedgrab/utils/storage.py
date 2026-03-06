# -*- coding: utf-8 -*-
"""
Storage utilities — save per-platform Markdown files.

- output/{Platform}/{title}.md (one file per item, for human reading)
"""

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger

from feedgrab.schema import UnifiedContent, SourceType


def _format_twitter_datetime(created_at: str) -> str:
    """Parse Twitter's RFC 2822 created_at into 'YYYY-MM-DD HH:MM' for display."""
    from feedgrab.config import parse_twitter_date_local
    return parse_twitter_date_local(created_at, "%Y-%m-%d %H:%M")


def _parse_xhs_date(raw: str) -> str:
    """Parse XHS date string into 'YYYY-MM-DD'.

    Formats:
      - "02-18 福建"             → MM-DD + location (assume current year)
      - "编辑于 2025-08-16"      → full date with year
      - "3天前 江苏"              → relative time (N天前/昨天/前天/N小时前/N分钟前)
      - "编辑于 昨天 10:17 福建"  → "编辑于" + relative time + HH:MM + location
      - "编辑于 3天前 福建"       → "编辑于" + relative time + location
    """
    if not raw:
        return ""
    text = raw.strip()

    # Strip "编辑于" prefix for uniform parsing
    text = re.sub(r"^编辑于\s*", "", text)

    # Format: full date "YYYY-MM-DD"
    full_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if full_match:
        return f"{full_match.group(1)}-{full_match.group(2)}-{full_match.group(3)}"

    # Format: relative time → convert to absolute date
    now = datetime.now()
    days_match = re.match(r"(\d+)\s*天前", text)
    if days_match:
        return (now - timedelta(days=int(days_match.group(1)))).strftime("%Y-%m-%d")
    if text.startswith("昨天"):
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if text.startswith("前天"):
        return (now - timedelta(days=2)).strftime("%Y-%m-%d")
    if re.match(r"\d+\s*小时前", text) or re.match(r"\d+\s*分钟前", text) or text.startswith("刚刚"):
        return now.strftime("%Y-%m-%d")

    # Format: "MM-DD ..." (no year)
    match = re.match(r"(\d{2})-(\d{2})", text)
    if not match:
        return ""
    month, day = int(match.group(1)), int(match.group(2))
    try:
        candidate = datetime(now.year, month, day)
        if candidate > now:
            candidate = datetime(now.year - 1, month, day)
        return candidate.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _parse_xhs_location(raw: str) -> str:
    """Extract location from XHS date string.

    '02-18 福建'    → '福建'
    '3天前 江苏'    → '江苏'
    '编辑于 2025-08-16' → '' (no location)
    """
    if not raw:
        return ""
    text = raw.strip()
    # "编辑于" format has no location
    if "编辑于" in text:
        return ""
    # "MM-DD location"
    match = re.match(r"\d{2}-\d{2}\s+(.+)", text)
    if match:
        return match.group(1).strip()
    # Relative time: "3天前 江苏", "昨天 21:33北京", "N小时前广东"
    rel_match = re.match(r"(?:\d+\s*[天小时分钟]+前|昨天.*?|前天|刚刚)\s*(\S+)$", text)
    if rel_match:
        loc = rel_match.group(1).strip()
        # Filter out time strings like "21:33" that aren't locations
        if not re.match(r"\d", loc):
            return loc
    return ""


# SourceType → subdirectory name
PLATFORM_FOLDER_MAP = {
    SourceType.TWITTER: "X",
    SourceType.XIAOHONGSHU: "XHS",
    SourceType.BILIBILI: "Bilibili",
    SourceType.WECHAT: "mpweixin",
    SourceType.YOUTUBE: "YouTube",
    SourceType.TELEGRAM: "Telegram",
    SourceType.RSS: "RSS",
    SourceType.MANUAL: "Manual",
}

# Windows reserved filenames (case-insensitive)
_WINDOWS_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})

# Characters illegal in filenames on Windows / most filesystems
_ILLEGAL_CHARS_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitize_filename(name: str) -> str:
    """Clean a string for use as a filename.

    - Strip control characters and illegal chars
    - Collapse whitespace
    - Guard against Windows reserved names
    - Truncate to 100 chars without cutting words
    """
    # Replace illegal chars with space
    name = _ILLEGAL_CHARS_RE.sub(" ", name)
    # Strip leading/trailing dots and spaces (Windows quirk)
    name = name.strip(". ")
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    # Guard against Windows reserved names
    stem = name.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        name = f"_{name}"
    # Truncate to 100 chars without cutting words
    if len(name) > 100:
        truncated = name[:100]
        last_space = truncated.rfind(" ")
        if last_space > 50:
            truncated = truncated[:last_space]
        name = truncated.rstrip(". ")
    return name


def _generate_filename(item: UnifiedContent) -> str:
    """Build a clean filename (without extension) from an item.

    Twitter format: "作者名_YYYY-MM-DD：标题"
    Other platforms: title → content prefix → id
    """
    extra = item.extra or {}

    # Determine the display title
    if item.title and item.title.strip():
        raw_title = item.title.strip()
    elif item.content and item.content.strip():
        # Strip leading ![cover](...) markdown image (e.g. WeChat prepends cover)
        text = re.sub(r'^!\[cover\]\([^)]*\)\s*', '', item.content.strip())
        raw_title = text[:50] if text else item.id
    else:
        raw_title = item.id

    # Twitter: prepend author display name + published date
    if item.source_type == SourceType.TWITTER:
        author_display = extra.get("author_name", "") or item.source_name or ""
        # Remove @ prefix for cleaner filename
        author_display = author_display.lstrip("@").strip()

        # Parse published date from Twitter's created_at
        published = ""
        if extra.get("created_at"):
            from feedgrab.config import parse_twitter_date_local
            published = parse_twitter_date_local(extra["created_at"])

        if author_display and published:
            raw = f"{author_display}_{published}：{raw_title}"
        elif author_display:
            raw = f"{author_display}：{raw_title}"
        else:
            raw = raw_title
    elif item.source_type == SourceType.XIAOHONGSHU:
        author_display = (item.source_name or "").strip()
        published = _parse_xhs_date(extra.get("date", ""))

        if author_display and published:
            raw = f"{author_display}_{published}：{raw_title}"
        elif author_display:
            raw = f"{author_display}：{raw_title}"
        else:
            raw = raw_title
    elif item.source_type == SourceType.WECHAT:
        author_display = (item.source_name or "").strip()
        # Only use date (no time) in filename
        published = extra.get("publish_date", "")[:10]

        if author_display and published:
            raw = f"{author_display}_{published}：{raw_title}"
        elif author_display:
            raw = f"{author_display}：{raw_title}"
        else:
            raw = raw_title
    else:
        raw = raw_title

    name = _sanitize_filename(raw)
    if not name:
        name = item.id
    return name


def _resolve_filepath(directory: Path, name: str, item_id: str) -> Path:
    """Return a unique .md path inside *directory*.

    If ``name.md`` already exists but was NOT produced by the same item
    (different item_id), append ``_<item_id>`` to disambiguate.
    Same item_id → same path (allows overwrite / update).
    """
    candidate = directory / f"{name}.md"
    if not candidate.exists():
        return candidate

    # Check if the existing file belongs to the same item (same id → overwrite)
    try:
        with open(candidate, "r", encoding="utf-8") as f:
            head = f.read(2048)
        if f"item_id: {item_id}" in head:
            return candidate
    except OSError:
        pass

    # Conflict: different item produced the same filename
    return directory / f"{name}_{item_id}.md"


def _format_markdown(item: UnifiedContent) -> str:
    """Build the full Markdown content with Obsidian-compatible YAML front matter."""
    is_twitter = item.source_type == SourceType.TWITTER
    is_xhs = item.source_type == SourceType.XIAOHONGSHU
    is_wechat = item.source_type == SourceType.WECHAT
    extra = item.extra or {}

    # --- Parse published date ---
    published = ""
    if extra.get("created_at"):
        # Twitter: RFC 2822 → local timezone
        from feedgrab.config import parse_twitter_date_local
        published = parse_twitter_date_local(extra["created_at"])
    elif is_xhs and extra.get("date"):
        # XHS: "02-18 福建"
        published = _parse_xhs_date(extra["date"])
    elif is_wechat and extra.get("publish_date"):
        published = extra["publish_date"]
    fetched_date = item.fetched_at[:10] if item.fetched_at else ""

    # --- Title (escape quotes for YAML) ---
    fm_title = (item.title or "").replace('"', '\\"')

    # --- YAML front matter (Obsidian Properties format) ---
    fm_lines = [
        "---",
        f'title: "{fm_title}"',
        f'source: "{item.url}"',
        f"author:",
        f'  - "{item.source_name}"',
    ]

    if extra.get("author_name") and not is_xhs:
        fm_lines.append(f'author_name: "{extra["author_name"]}"')
    if is_xhs and extra.get("author_url"):
        fm_lines.append(f'author_url: "{extra["author_url"]}"')

    if published:
        fm_lines.append(f"published: {published}")
    fm_lines.append(f"created: {fetched_date}")

    if extra.get("cover_image"):
        fm_lines.append(f'cover_image: "{extra["cover_image"]}"')

    # Twitter metrics (always show, including 0)
    if is_twitter:
        fm_lines.append(f'tweet_type: "{extra.get("tweet_type", "status")}"')
        fm_lines.append(f"tweet_count: {extra.get('tweet_count', 1)}")
        fm_lines.append(f"has_thread: {str(extra.get('has_thread', False)).lower()}")
        for metric in ("likes", "retweets", "replies", "bookmarks", "views"):
            fm_lines.append(f"{metric}: {extra.get(metric, 0)}")
        # New: quote_count (被引用次数)
        fm_lines.append(f"quotes: {extra.get('quote_count', 0)}")
        # New: author profile metadata
        if extra.get("is_blue_verified"):
            fm_lines.append(f"is_blue_verified: true")
        fm_lines.append(f"followers_count: {extra.get('followers_count', 0)}")
        fm_lines.append(f"statuses_count: {extra.get('statuses_count', 0)}")
        fm_lines.append(f"listed_count: {extra.get('listed_count', 0)}")
        # New: tweet metadata
        if extra.get("lang"):
            fm_lines.append(f'lang: "{extra["lang"]}"')
        if extra.get("source_app"):
            fm_lines.append(f'source_app: "{extra["source_app"]}"')
        if extra.get("possibly_sensitive"):
            fm_lines.append(f"possibly_sensitive: true")

    # XHS metrics (always show, including 0)
    if is_xhs:
        for metric in ("likes", "collects", "comments"):
            fm_lines.append(f"{metric}: {extra.get(metric, 0)}")
        location = _parse_xhs_location(extra.get("date", ""))
        if location:
            fm_lines.append(f'location: "{location}"')

    # WeChat metadata
    if is_wechat:
        # cover_image already handled by the generic block above;
        # only add thumbnail fallback when no cover_image exists
        if not extra.get("cover_image") and extra.get("thumbnail"):
            fm_lines.append(f'cover_image: "{extra["thumbnail"]}"')
        if extra.get("summary"):
            fm_summary = extra["summary"].replace('"', '\\"')[:200]
            fm_lines.append(f'summary: "{fm_summary}"')
        if extra.get("original_url"):
            fm_lines.append(f'original_url: "{extra["original_url"]}"')
        if extra.get("search_keyword"):
            fm_lines.append(f'search_keyword: "{extra["search_keyword"]}"')
        # Engagement metrics (only when available via authenticated session)
        if extra.get("reads"):
            fm_lines.append(f"reads: {extra['reads']}")
            fm_lines.append(f"likes: {extra.get('likes', 0)}")
            fm_lines.append(f"wow: {extra.get('wow', 0)}")
            fm_lines.append(f"shares: {extra.get('shares', 0)}")
            fm_lines.append(f"comments: {extra.get('comments', 0)}")

    # Bilibili extras
    if item.source_type == SourceType.BILIBILI:
        if extra.get("bvid"):
            fm_lines.append(f"bvid: {extra['bvid']}")
        if extra.get("duration"):
            fm_lines.append(f"duration: {extra['duration']}")

    # Tags (from tweet hashtags or other sources)
    if item.tags:
        # XHS: only top 3 tags in front matter (full list goes in body)
        fm_tags = item.tags[:3] if is_xhs else item.tags
        fm_lines.append("tags:")
        for tag in fm_tags:
            fm_lines.append(f'  - "{tag}"')

    # Internal tracking
    fm_lines.append(f"item_id: {item.id}")

    fm_lines.append("---")
    fm_lines.append("")  # blank line after front matter

    # WeChat images require no-referrer to avoid 403 from mmbiz.qpic.cn
    if is_wechat:
        fm_lines.append('<meta name="referrer" content="no-referrer">')
        fm_lines.append("")

    # --- body ---
    if is_twitter:
        # Twitter threads already formatted with [1/N], just output content
        fm_lines.append(item.content)

        # --- 作者回帖 (author replies to commenters) ---
        author_replies = extra.get("author_replies", [])
        if author_replies:
            fm_lines.append("")
            fm_lines.append("---")
            fm_lines.append("")
            fm_lines.append("## 作者回帖")
            fm_lines.append("")
            for idx, reply in enumerate(author_replies, 1):
                date_str = _format_twitter_datetime(reply.get("created_at", ""))
                text = reply.get("text", "").strip()
                if text:
                    fm_lines.append(f"**[回帖 {idx}]** {date_str}")
                    fm_lines.append(text)
                    fm_lines.append("")

        # --- 评论区 (other users' comments) ---
        comments = extra.get("comments", [])
        if comments:
            fm_lines.append("")
            fm_lines.append("---")
            fm_lines.append("")
            fm_lines.append(f"## 评论区 ({len(comments)}条)")
            fm_lines.append("")
            for c in comments:
                c_author = c.get("author", "")
                date_str = _format_twitter_datetime(c.get("created_at", ""))
                likes = c.get("likes", 0)
                text = c.get("text", "").strip()
                if text:
                    meta = [f"**@{c_author}**"]
                    if date_str:
                        meta.append(date_str)
                    if likes:
                        meta.append(f"❤️ {likes}")
                    fm_lines.append(" · ".join(meta))
                    fm_lines.append(text)
                    fm_lines.append("")
    elif is_xhs:
        # XHS: 文字在前，标签在中，图片相册在后（按翻页顺序）
        if item.title and item.title.strip():
            fm_lines.append(f"# {item.title.strip()}")
            fm_lines.append("")
        if item.content:
            fm_lines.append(item.content)
            fm_lines.append("")
        # 全部标签（保持小红书原始 #标签 格式）
        if item.tags:
            tag_line = " ".join(f"#{t}" for t in item.tags)
            fm_lines.append(tag_line)
            fm_lines.append("")
        images = extra.get("images", [])
        if images:
            for i, img in enumerate(images, 1):
                fm_lines.append(f"![{i}]({img})")
                fm_lines.append("")
    else:
        # Non-Twitter/XHS: add title heading + full content
        # WeChat: skip title heading (already in filename + front matter)
        if not is_wechat and item.title and item.title.strip():
            fm_lines.append(f"# {item.title.strip()}")
            fm_lines.append("")
        fm_lines.append(item.content)

    fm_lines.append("")  # trailing newline
    result = "\n".join(fm_lines)
    # Strip Twitter emoji SVG images (displayed oversized in Obsidian)
    # e.g. ![Image 1: 😄](https://abs-0.twimg.com/emoji/v2/svg/1f604.svg)
    result = re.sub(r'!\[[^\]]*\]\(https://abs-0\.twimg\.com/emoji/[^)]+\)', '', result)
    return result


# =========================================================================
# Public API
# =========================================================================

def save_to_markdown(item: UnifiedContent, filepath: str = None):
    """Save content as a standalone Markdown file in a platform subdirectory.

    Directory resolution (when *filepath* is None):
      1. OBSIDIAN_VAULT → {vault}/{Platform}/
      2. OUTPUT_DIR     → {output_dir}/{Platform}/
      3. Neither set    → skip

    Each item becomes one ``.md`` file.  Re-fetching the same URL
    overwrites the existing file (update in place).
    """
    if filepath:
        # Caller provided an explicit path — write directly (legacy compat)
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(_format_markdown(item))
        logger.info(f"Saved to Markdown: {path}")
        return

    # Determine base output directory
    vault_path = os.getenv("OBSIDIAN_VAULT", "")
    output_dir = os.getenv("OUTPUT_DIR", "")

    if vault_path:
        base_dir = Path(vault_path)
    elif output_dir:
        base_dir = Path(output_dir)
    else:
        return

    # Platform subdirectory
    folder = PLATFORM_FOLDER_MAP.get(item.source_type, "Other")
    platform_dir = base_dir / folder

    # Category subdirectory (e.g., "bookmarks/OpenClaw" for bookmark folders)
    if item.category:
        parts = item.category.split("/")
        safe_parts = [_sanitize_filename(p) for p in parts if p]
        if safe_parts:
            platform_dir = platform_dir / Path(*safe_parts)

    platform_dir.mkdir(parents=True, exist_ok=True)

    # Build filename and resolve conflicts
    name = _generate_filename(item)
    path = _resolve_filepath(platform_dir, name, item.id)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(_format_markdown(item))

    logger.info(f"Saved to Markdown: {path}")
