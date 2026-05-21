# -*- coding: utf-8 -*-
"""Twitter/X People-tab search (v0.23.0).

CLI:
    feedgrab x-so <keyword> --people

Borrowed from prinsss/twitter-web-exporter (SearchTimeline with product=People).

Output:
    {OUTPUT_DIR}/X/search-people/{keyword}_{date}.{md,csv}
"""

import csv
import os
import re
import time as _time
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Optional, List, Dict, Any

from feedgrab.fetchers.twitter_graphql import (
    fetch_search_timeline_page,
    parse_search_people_entries,
    extract_user_data,
)


def _max_pages() -> int:
    try:
        return int(os.getenv("X_SEARCH_PEOPLE_MAX_PAGES", "3"))
    except ValueError:
        return 3


def _delay_between_pages() -> float:
    try:
        return float(os.getenv("X_SEARCH_PEOPLE_DELAY", "2.0"))
    except ValueError:
        return 2.0


def _per_page_count() -> int:
    try:
        return int(os.getenv("X_SEARCH_PEOPLE_PER_PAGE", "20"))
    except ValueError:
        return 20


def _output_dir() -> Path:
    base = os.getenv("OUTPUT_DIR", "output").strip() or "output"
    return Path(base) / "X" / "search-people"


def _sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:80] or "unknown"


def search_people(keyword: str, cookies: dict) -> Dict[str, Any]:
    """Search Twitter People tab for users matching keyword.

    Returns:
        dict: {keyword, total, summary_path, csv_path}
    """
    logger.info(f"[SearchPeople] 开始搜索人物: keyword='{keyword}'")

    all_users: List[Dict[str, Any]] = []
    seen_ids: set = set()
    cursor: Optional[str] = None
    max_pages = _max_pages()
    delay = _delay_between_pages()
    per_page = _per_page_count()

    for page in range(max_pages):
        from feedgrab.fetchers.twitter_cookies import (
            fetch_with_cookie_rotation,
            count_total_accounts,
        )
        response, rotated_cookies = fetch_with_cookie_rotation(
            fetch_search_timeline_page,
            label="SearchPeople",
            raw_query=keyword,
            cursor=cursor,
            count=per_page,
            product="People",
        )
        if rotated_cookies:
            cookies = rotated_cookies
        if not response:
            total_accounts = count_total_accounts()
            logger.warning(
                f"[SearchPeople] >>> 第 {page + 1} 页所有 {total_accounts} 个账号均失败 <<< "
                f"累计 {len(all_users)} 个，终止"
            )
            break

        entries, cursors = parse_search_people_entries(response)
        if not entries:
            logger.info(
                f"[SearchPeople] 第 {page + 1} 页无更多条目，累计 {len(all_users)} 个"
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
            f"[SearchPeople] 第 {page + 1} 页新增 {page_users} 个用户，"
            f"累计 {len(all_users)}"
        )

        cursor = cursors.get("bottom")
        if not cursor:
            logger.info("[SearchPeople] 无下一页 cursor，分页结束")
            break

        if page < max_pages - 1:
            _time.sleep(delay)

    summary_path, csv_path = _save_outputs(keyword, all_users)

    logger.info(
        f"[SearchPeople] 完成: keyword='{keyword}' — {len(all_users)} 个用户"
    )

    return {
        "keyword": keyword,
        "total": len(all_users),
        "summary_path": str(summary_path),
        "csv_path": str(csv_path),
    }


def _save_outputs(keyword: str, users: List[Dict[str, Any]]) -> tuple:
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = _output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{_sanitize(keyword)}_{date_str}"
    md_path = out_dir / f"{stem}.md"
    csv_path = out_dir / f"{stem}.csv"

    # --- Markdown ---
    lines = [
        "---",
        f'title: "人物搜索 — {keyword}"',
        f'keyword: "{keyword}"',
        f"total: {len(users)}",
        f"fetched_at: {date_str}",
        "cssclasses: wide",
        "---",
        "",
    ]

    if not users:
        lines.append(f"*未找到与 {keyword} 相关的用户。*")
    else:
        users_sorted = sorted(
            users, key=lambda u: int(u.get("followers_count", 0) or 0),
            reverse=True,
        )
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
            user_url = u.get("url", "") or (
                f"https://x.com/{screen_name}" if screen_name else ""
            )
            link = f"[查看]({user_url})" if user_url else ""

            lines.append(
                f"| {i} | @{screen_name} | {name} | {bio} | "
                f"{followers} | {friends} | {statuses} | {blue} | {link} |"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(f"[SearchPeople] 汇总表保存: {md_path}")

    # --- CSV ---
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "user_id", "screen_name", "name", "description", "location",
            "followers_count", "friends_count", "statuses_count",
            "favourites_count", "listed_count",
            "verified", "is_blue_verified", "protected",
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
    logger.info(f"[SearchPeople] CSV 保存: {csv_path}")

    return md_path, csv_path
