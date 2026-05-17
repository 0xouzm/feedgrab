# -*- coding: utf-8 -*-
"""Twitter/X user-list batch fetcher (v0.22.0).

Borrowed from prinsss/twitter-web-exporter (modules/followers, list-members, etc).

Supports five modes via a single unified fetcher:
    - followers              (x.com/<user>/followers)
    - following              (x.com/<user>/following)
    - blue_verified_followers (x.com/<user>/verified_followers)
    - list_members           (x.com/i/lists/<id>/members)
    - list_subscribers       (x.com/i/lists/<id>/subscribers)

Output:
    - {OUTPUT_DIR}/X/users/{mode}/{owner}_{date}.md  — table of users
    - {OUTPUT_DIR}/X/users/{mode}/{owner}_{date}.csv — same data as CSV
"""

import csv
import json
import os
import re
import time as _time
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Optional, List, Dict, Any

from feedgrab.fetchers.twitter_graphql import (
    fetch_user_by_screen_name,
    fetch_followers_page, fetch_following_page,
    fetch_blue_verified_followers_page,
    fetch_list_members_page, fetch_list_subscribers_page,
    parse_user_timeline_users,
    parse_list_members_users, parse_list_subscribers_users,
    extract_user_data,
)


# Mode → (fetcher, parser, label, url_pattern)
_MODE_CONFIG = {
    "followers": {
        "fetcher": fetch_followers_page,
        "parser": parse_user_timeline_users,
        "label": "粉丝列表",
        "needs_user_id": True,
    },
    "following": {
        "fetcher": fetch_following_page,
        "parser": parse_user_timeline_users,
        "label": "关注列表",
        "needs_user_id": True,
    },
    "blue_verified_followers": {
        "fetcher": fetch_blue_verified_followers_page,
        "parser": parse_user_timeline_users,
        "label": "蓝V粉丝",
        "needs_user_id": True,
    },
    "list_members": {
        "fetcher": fetch_list_members_page,
        "parser": parse_list_members_users,
        "label": "列表成员",
        "needs_user_id": False,
    },
    "list_subscribers": {
        "fetcher": fetch_list_subscribers_page,
        "parser": parse_list_subscribers_users,
        "label": "列表订阅者",
        "needs_user_id": False,
    },
}


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def parse_user_list_url(url: str) -> tuple:
    """Detect mode + identifier from a Twitter URL.

    Returns:
        (mode, identifier) where identifier is screen_name or list_id.
        Returns (None, None) if URL doesn't match.
    """
    # List URLs first (more specific)
    m = re.search(r'/i/lists/(\d+)/members', url)
    if m:
        return ("list_members", m.group(1))
    m = re.search(r'/i/lists/(\d+)/subscribers', url)
    if m:
        return ("list_subscribers", m.group(1))

    # User URLs
    m = re.match(r'https?://(?:x|twitter)\.com/([^/]+)/followers/?$', url)
    if m:
        return ("followers", m.group(1))
    m = re.match(r'https?://(?:x|twitter)\.com/([^/]+)/following/?$', url)
    if m:
        return ("following", m.group(1))
    m = re.match(r'https?://(?:x|twitter)\.com/([^/]+)/verified_followers/?$', url)
    if m:
        return ("blue_verified_followers", m.group(1))

    return (None, None)


# ---------------------------------------------------------------------------
# Main fetcher (mode-driven)
# ---------------------------------------------------------------------------

def _max_pages() -> int:
    try:
        return int(os.getenv("X_USER_LIST_MAX_PAGES", "20"))
    except ValueError:
        return 20


def _delay_between_pages() -> float:
    try:
        return float(os.getenv("X_USER_LIST_DELAY", "2.0"))
    except ValueError:
        return 2.0


def _per_page_count() -> int:
    try:
        return int(os.getenv("X_USER_LIST_PER_PAGE", "20"))
    except ValueError:
        return 20


def _output_dir() -> Path:
    base = os.getenv("OUTPUT_DIR", "output").strip() or "output"
    return Path(base) / "X" / "users"


def _sanitize(name: str) -> str:
    """Strip filesystem-unsafe chars from filename component."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:80] or "unknown"


async def fetch_user_list(url: str, cookies: dict) -> Dict[str, Any]:
    """Batch-fetch a Twitter user list (followers/following/list members/etc).

    Returns:
        dict: {
            "mode": str,
            "owner": str,            # screen_name or list_id
            "total": int,
            "fetched": int,
            "summary_path": str,     # MD file path
            "csv_path": str,
        }
    """
    mode, identifier = parse_user_list_url(url)
    if not mode:
        raise ValueError(f"无法识别用户列表 URL: {url}")

    cfg = _MODE_CONFIG[mode]
    fetcher = cfg["fetcher"]
    parser = cfg["parser"]
    label = cfg["label"]

    # Resolve user_id if needed
    if cfg["needs_user_id"]:
        screen_name = identifier
        user_info = fetch_user_by_screen_name(screen_name, cookies)
        user_id = user_info.get("user_id")
        owner_display = user_info.get("name", "") or screen_name
        if not user_id:
            raise RuntimeError(f"无法解析 @{screen_name} 的 user_id（账号不存在或受限）")
        target_id = user_id
        owner_slug = screen_name
    else:
        target_id = identifier  # list_id
        owner_display = f"List {identifier}"
        owner_slug = identifier

    logger.info(f"[UserList:{mode}] 开始抓取 {label}: {owner_display}")

    # --- Pagination loop ---
    all_users: List[Dict[str, Any]] = []
    seen_ids: set = set()
    cursor: Optional[str] = None
    max_pages = _max_pages()
    delay = _delay_between_pages()
    per_page = _per_page_count()

    for page in range(max_pages):
        response = fetcher(target_id, cookies, cursor=cursor, count=per_page)
        if not response:
            logger.warning(f"[UserList:{mode}] 第 {page + 1} 页响应为空，终止")
            break

        entries, cursors = parser(response)
        if not entries:
            logger.info(
                f"[UserList:{mode}] 第 {page + 1} 页无更多条目，累计 {len(all_users)} 个"
            )
            break

        page_users = 0
        for entry in entries:
            ud = extract_user_data(entry)
            if not ud:
                continue
            uid = ud.get("user_id", "")
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            all_users.append(ud)
            page_users += 1

        logger.info(
            f"[UserList:{mode}] 第 {page + 1} 页新增 {page_users} 个用户，"
            f"累计 {len(all_users)}"
        )

        cursor = cursors.get("bottom")
        if not cursor:
            logger.info(f"[UserList:{mode}] 无下一页 cursor，分页结束")
            break

        if page < max_pages - 1:
            _time.sleep(delay)

    # --- Output ---
    summary_path, csv_path = _save_outputs(mode, label, owner_slug, owner_display, all_users)

    logger.info(
        f"[UserList:{mode}] 完成 {label} 抓取: {owner_display} — {len(all_users)} 个用户"
    )

    return {
        "mode": mode,
        "owner": owner_slug,
        "owner_display": owner_display,
        "total": len(all_users),
        "fetched": len(all_users),
        "summary_path": str(summary_path),
        "csv_path": str(csv_path),
    }


# ---------------------------------------------------------------------------
# Output generation (MD + CSV)
# ---------------------------------------------------------------------------

def _save_outputs(
    mode: str, label: str, owner_slug: str, owner_display: str,
    users: List[Dict[str, Any]],
) -> tuple:
    """Generate {OUTPUT_DIR}/X/users/{mode}/{owner}_{date}.{md,csv}."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = _output_dir() / mode
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{_sanitize(owner_slug)}_{date_str}"
    md_path = out_dir / f"{stem}.md"
    csv_path = out_dir / f"{stem}.csv"

    # --- Markdown ---
    lines = [
        "---",
        f'title: "{label} — {owner_display}"',
        f'mode: "{mode}"',
        f'owner: "{owner_slug}"',
        f"total: {len(users)}",
        f"fetched_at: {date_str}",
        "cssclasses: wide",
        "---",
        "",
    ]

    if not users:
        lines.append("*未找到用户。*")
    else:
        # Sort by followers_count desc (most influential first)
        users_sorted = sorted(users, key=lambda u: int(u.get("followers_count", 0) or 0), reverse=True)

        lines.append(
            "| # | 用户 | 显示名 | 简介 | 关注者 | 关注 | 推文 | 蓝V | 链接 |"
        )
        lines.append(
            "|:---:|------|--------|------|:---:|:---:|:---:|:---:|:---:|"
        )

        for i, u in enumerate(users_sorted, 1):
            screen_name = u.get("screen_name", "")
            name = (u.get("name", "") or "").replace("|", "\\|").replace("\n", " ")
            bio = (u.get("description", "") or "").replace("|", "\\|").replace("\n", " ")
            bio = bio[:60] + "…" if len(bio) > 60 else bio
            bio = bio.replace("[", "\\[").replace("]", "\\]")
            blue = "✅" if u.get("is_blue_verified") else ""
            followers = int(u.get("followers_count", 0) or 0)
            friends = int(u.get("friends_count", 0) or 0)
            statuses = int(u.get("statuses_count", 0) or 0)
            user_url = u.get("url", "") or (f"https://x.com/{screen_name}" if screen_name else "")
            link = f"[查看]({user_url})" if user_url else ""

            lines.append(
                f"| {i} | @{screen_name} | {name} | {bio} | "
                f"{followers} | {friends} | {statuses} | {blue} | {link} |"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[UserList:{mode}] 汇总表保存: {md_path}")

    # --- CSV ---
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "user_id", "screen_name", "name", "description", "location",
            "followers_count", "friends_count", "statuses_count", "favourites_count",
            "listed_count", "verified", "is_blue_verified", "protected",
            "created_at", "url", "profile_image_url",
        ])
        for u in users:
            writer.writerow([
                u.get("user_id", ""),
                u.get("screen_name", ""),
                u.get("name", ""),
                u.get("description", ""),
                u.get("location", ""),
                u.get("followers_count", 0),
                u.get("friends_count", 0),
                u.get("statuses_count", 0),
                u.get("favourites_count", 0),
                u.get("listed_count", 0),
                u.get("verified", False),
                u.get("is_blue_verified", False),
                u.get("protected", False),
                u.get("created_at", ""),
                u.get("url", ""),
                u.get("profile_image_url", ""),
            ])
    logger.info(f"[UserList:{mode}] CSV 保存: {csv_path}")

    return md_path, csv_path
