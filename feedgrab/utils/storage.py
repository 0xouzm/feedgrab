# -*- coding: utf-8 -*-
"""
Storage utilities — save per-platform Markdown files.

- output/{Platform}/{title}.md (one file per item, for human reading)
"""

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from loguru import logger

from feedgrab.schema import UnifiedContent, SourceType


def _format_twitter_datetime(created_at: str) -> str:
    """Parse Twitter's RFC 2822 created_at into 'YYYY-MM-DD HH:MM' for display."""
    if not created_at:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(created_at)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return created_at[:16] if len(created_at) >= 16 else created_at


# SourceType → subdirectory name
PLATFORM_FOLDER_MAP = {
    SourceType.TWITTER: "X",
    SourceType.XIAOHONGSHU: "XHS",
    SourceType.BILIBILI: "Bilibili",
    SourceType.WECHAT: "WeChat",
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
        raw_title = item.content.strip()[:50]
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
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(extra["created_at"])
                published = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

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
            head = f.read(512)
        if f"item_id: {item_id}" in head:
            return candidate
    except OSError:
        pass

    # Conflict: different item produced the same filename
    return directory / f"{name}_{item_id}.md"


def _format_markdown(item: UnifiedContent) -> str:
    """Build the full Markdown content with Obsidian-compatible YAML front matter."""
    is_twitter = item.source_type == SourceType.TWITTER
    extra = item.extra or {}

    # --- Parse published date from Twitter's created_at ---
    published = ""
    if extra.get("created_at"):
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(extra["created_at"])
            published = dt.strftime("%Y-%m-%d")
        except Exception:
            pass
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

    if extra.get("author_name"):
        fm_lines.append(f'author_name: "{extra["author_name"]}"')

    if published:
        fm_lines.append(f"published: {published}")
    fm_lines.append(f"created: {fetched_date}")

    if extra.get("cover_image"):
        fm_lines.append(f'cover_image: "{extra["cover_image"]}"')

    # Twitter metrics (only non-zero values)
    if is_twitter:
        fm_lines.append(f"tweet_count: {extra.get('tweet_count', 1)}")
        fm_lines.append(f"has_thread: {str(extra.get('has_thread', False)).lower()}")
        for metric in ("likes", "retweets", "replies", "bookmarks", "views"):
            val = extra.get(metric, 0)
            if val and str(val) != "0":
                fm_lines.append(f"{metric}: {val}")

    # Bilibili extras
    if item.source_type == SourceType.BILIBILI:
        if extra.get("bvid"):
            fm_lines.append(f"bvid: {extra['bvid']}")
        if extra.get("duration"):
            fm_lines.append(f"duration: {extra['duration']}")

    # Tags (from tweet hashtags or other sources)
    if item.tags:
        fm_lines.append("tags:")
        for tag in item.tags:
            fm_lines.append(f'  - "{tag}"')

    # Internal tracking
    fm_lines.append(f"item_id: {item.id}")

    fm_lines.append("---")
    fm_lines.append("")  # blank line after front matter

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
    else:
        # Non-Twitter: add a title heading + full content
        if item.title and item.title.strip():
            fm_lines.append(f"# {item.title.strip()}")
            fm_lines.append("")
        fm_lines.append(item.content)

    fm_lines.append("")  # trailing newline
    return "\n".join(fm_lines)


# =========================================================================
# Public API
# =========================================================================

def save_to_markdown(item: UnifiedContent, filepath: str = None):
    """Save content as a standalone Markdown file in a platform subdirectory.

    Directory resolution (when *filepath* is None):
      1. OBSIDIAN_VAULT → {vault}/01-收集箱/{Platform}/
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
        base_dir = Path(vault_path) / "01-收集箱"
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
