# -*- coding: utf-8 -*-
"""
Global dedup index — unified item_id tracking across all fetch modes.

Index file: {OUTPUT_DIR}/X/index/item_id_url.json
Format:
    {
        "b38937597c3b": ["2026-02-27", "https://x.com/user/status/123"],
        ...
    }

Used by:
    - Single tweet fetch (write-only, never skip)
    - Bookmark batch fetch (read+write, skip duplicates)
    - Future: author batch fetch
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from loguru import logger


def _get_base_dir(platform: str = "X") -> Path:
    """Return the platform base directory."""
    vault_path = os.getenv("OBSIDIAN_VAULT", "")
    output_dir = os.getenv("OUTPUT_DIR", "")
    if vault_path:
        return Path(vault_path) / platform
    elif output_dir:
        return Path(output_dir) / platform
    else:
        return Path("output") / platform


def get_index_path(platform: str = "X") -> Path:
    """Return path to the global dedup index file."""
    index_dir = _get_base_dir(platform) / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir / "item_id_url.json"


def item_id_from_url(url: str) -> str:
    """Compute item_id from URL (same as schema.py __post_init__)."""
    return hashlib.md5(url.encode()).hexdigest()[:12]


def load_index(platform: str = "X") -> dict:
    """Load the global dedup index.

    Returns:
        dict mapping item_id → [date_str, url]

    Handles:
        - New format: {"id": ["date", "url"]}
        - Old format: ["id1", "id2", ...] (auto-migrated)
    """
    index_path = get_index_path(platform)

    # Try new location first
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            # Old format (list) at new location — shouldn't happen but handle
            if isinstance(data, list):
                return {item_id: ["unknown", ""] for item_id in data}
        except (json.JSONDecodeError, OSError):
            pass

    # Try migrating from old location
    old_path = _get_base_dir(platform) / ".item_id_index.json"
    if old_path.exists():
        logger.info(f"[Dedup] 发现旧索引文件: {old_path}，开始迁移...")
        migrated = _migrate_old_index(old_path)
        if migrated:
            save_index(migrated)
            # Remove old file after successful migration
            try:
                old_path.unlink()
                logger.info(f"[Dedup] 旧索引文件已删除: {old_path}")
            except OSError:
                pass
            return migrated

    return {}


def save_index(index: dict, platform: str = "X"):
    """Persist the dedup index to disk.

    Format: one entry per line for compact readability.
        {"item_id": ["date", "url"], ...}
    """
    index_path = get_index_path(platform)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_items = sorted(index.items())
    lines = ["{"]
    for i, (k, v) in enumerate(sorted_items):
        comma = "," if i < len(sorted_items) - 1 else ""
        lines.append(f'  "{k}": {json.dumps(v, ensure_ascii=False)}{comma}')
    lines.append("}")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def has_item(item_id: str, index: dict) -> bool:
    """Check if an item_id exists in the index."""
    return item_id in index


def add_item(item_id: str, url: str, index: dict):
    """Add an item to the in-memory index (caller must persist via save_index)."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    index[item_id] = [date_str, url]


def _migrate_old_index(old_path: Path) -> dict:
    """Migrate old format (list of item_ids) to new format (dict).

    Old: ["b38937597c3b", "f5786c0b11b0", ...]
    New: {"b38937597c3b": ["2026-02-27", ""], ...}

    Note: URLs are lost in old format, stored as empty string.
    """
    try:
        with open(old_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            today = datetime.now().strftime("%Y-%m-%d")
            migrated = {item_id: [today, ""] for item_id in data if isinstance(item_id, str)}
            logger.info(f"[Dedup] 迁移完成: {len(migrated)} 条记录")
            return migrated
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[Dedup] 迁移失败: {e}")
    return {}
