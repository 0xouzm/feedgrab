# -*- coding: utf-8 -*-
"""Twitter/X tweet-level user-list fetcher (v0.23.0).

Borrowed from prinsss/twitter-web-exporter (modules/retweeters/api.ts).

Supports two modes via a single unified fetcher:
    - retweeters  (x.com/<user>/status/<id>/retweets)
    - favoriters  (x.com/<user>/status/<id>/likes)

Output:
    - {OUTPUT_DIR}/X/users/{mode}/{tweet_id}_{date}.md  — table of users
    - {OUTPUT_DIR}/X/users/{mode}/{tweet_id}_{date}.csv — same data as CSV
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
    fetch_retweeters_page, fetch_favoriters_page,
    parse_retweeters_users, parse_favoriters_users,
    extract_user_data,
)


_MODE_CONFIG = {
    "retweeters": {
        "fetcher": fetch_retweeters_page,
        "parser": parse_retweeters_users,
        "label": "转推者",
    },
    "favoriters": {
        "fetcher": fetch_favoriters_page,
        "parser": parse_favoriters_users,
        "label": "点赞者",
    },
}


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def parse_tweet_user_list_url(url: str) -> tuple:
    """Detect mode + tweet_id from a Twitter URL.

    Returns:
        (mode, tweet_id) or (None, None) if URL doesn't match.
    """
    # /status/<id>/retweets → retweeters
    m = re.search(
        r'https?://(?:x|twitter)\.com/[^/]+/status/(\d+)/retweets/?',
        url,
    )
    if m:
        return ("retweeters", m.group(1))

    # /status/<id>/likes → favoriters (tweet-level likes, not user-level Likes)
    m = re.search(
        r'https?://(?:x|twitter)\.com/[^/]+/status/(\d+)/likes/?',
        url,
    )
    if m:
        return ("favoriters", m.group(1))

    return (None, None)


def extract_tweet_id(value: str) -> Optional[str]:
    """Accept either a numeric tweet_id or a Twitter URL containing /status/<id>."""
    if not value:
        return None
    if value.isdigit():
        return value
    m = re.search(r'/status/(\d+)', value)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _max_pages() -> int:
    try:
        return int(os.getenv("X_TWEET_USER_LIST_MAX_PAGES", "5"))
    except ValueError:
        return 5


def _delay_between_pages() -> float:
    try:
        return float(os.getenv("X_TWEET_USER_LIST_DELAY", "2.0"))
    except ValueError:
        return 2.0


def _per_page_count() -> int:
    try:
        return int(os.getenv("X_TWEET_USER_LIST_PER_PAGE", "40"))
    except ValueError:
        return 40


def _output_dir() -> Path:
    base = os.getenv("OUTPUT_DIR", "output").strip() or "output"
    return Path(base) / "X" / "users"


def _sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)[:80] or "unknown"


# ---------------------------------------------------------------------------
# Main fetcher
# ---------------------------------------------------------------------------

async def fetch_tweet_user_list(url_or_id: str, cookies: dict) -> Dict[str, Any]:
    """Batch-fetch users who retweeted / liked a tweet.

    Args:
        url_or_id: Twitter URL (with /retweets or /likes suffix) OR pre-parsed
                   "<mode>:<tweet_id>" string for CLI use.
        cookies: Twitter session cookies.

    Returns:
        dict with mode, tweet_id, total, summary_path, csv_path.
    """
    # CLI may pass "<mode>:<tweet_id>"
    if ":" in url_or_id and not url_or_id.startswith("http"):
        mode, tweet_id = url_or_id.split(":", 1)
        if mode not in _MODE_CONFIG:
            raise ValueError(f"未知模式: {mode}（应为 retweeters/favoriters）")
    else:
        mode, tweet_id = parse_tweet_user_list_url(url_or_id)
        if not mode or not tweet_id:
            raise ValueError(f"无法识别推文用户列表 URL: {url_or_id}")

    cfg = _MODE_CONFIG[mode]
    fetcher = cfg["fetcher"]
    parser = cfg["parser"]
    label = cfg["label"]

    logger.info(f"[TweetUserList:{mode}] 开始抓取 {label}: tweet_id={tweet_id}")

    # --- Pagination loop ---
    all_users: List[Dict[str, Any]] = []
    seen_ids: set = set()
    cursor: Optional[str] = None
    max_pages = _max_pages()
    delay = _delay_between_pages()
    per_page = _per_page_count()

    for page in range(max_pages):
        response = fetcher(tweet_id, cookies, cursor=cursor, count=per_page)
        if not response:
            logger.warning(
                f"[TweetUserList:{mode}] 第 {page + 1} 页响应为空，终止"
            )
            break

        entries, cursors = parser(response)
        if not entries:
            logger.info(
                f"[TweetUserList:{mode}] 第 {page + 1} 页无更多条目，"
                f"累计 {len(all_users)} 个"
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
            f"[TweetUserList:{mode}] 第 {page + 1} 页新增 {page_users} 个，"
            f"累计 {len(all_users)}"
        )

        cursor = cursors.get("bottom")
        if not cursor:
            logger.info(f"[TweetUserList:{mode}] 无下一页 cursor，分页结束")
            break

        if page < max_pages - 1:
            _time.sleep(delay)

    # --- Tier-1 fallback: Twitter 公开 Retweeters/Favoriters 端点对未登录或
    # 部分账号可能返回空（受推文可见性限制）。若 0 条 + 模式为 favoriters，
    # 提示用户可能被设为私密。
    if not all_users and mode == "favoriters":
        logger.warning(
            f"[TweetUserList:{mode}] 该推文未抓到点赞用户 — "
            f"可能作者隐藏了点赞列表，或当前 Cookie 无访问权限。"
        )

    # --- Output ---
    summary_path, csv_path = _save_outputs(mode, label, tweet_id, all_users)

    logger.info(
        f"[TweetUserList:{mode}] 完成: tweet_id={tweet_id} — "
        f"{len(all_users)} 个用户"
    )

    return {
        "mode": mode,
        "tweet_id": tweet_id,
        "total": len(all_users),
        "fetched": len(all_users),
        "summary_path": str(summary_path),
        "csv_path": str(csv_path),
    }


# ---------------------------------------------------------------------------
# Output generation (MD + CSV)
# ---------------------------------------------------------------------------

def _save_outputs(
    mode: str, label: str, tweet_id: str,
    users: List[Dict[str, Any]],
) -> tuple:
    """Generate {OUTPUT_DIR}/X/users/{mode}/{tweet_id}_{date}.{md,csv}."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = _output_dir() / mode
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{_sanitize(tweet_id)}_{date_str}"
    md_path = out_dir / f"{stem}.md"
    csv_path = out_dir / f"{stem}.csv"

    # --- Markdown ---
    lines = [
        "---",
        f'title: "{label} — Tweet {tweet_id}"',
        f'mode: "{mode}"',
        f'tweet_id: "{tweet_id}"',
        f"total: {len(users)}",
        f"fetched_at: {date_str}",
        "cssclasses: wide",
        "---",
        "",
    ]

    if not users:
        lines.append(f"*未找到{label}。*")
    else:
        # Sort by followers_count desc (most influential first)
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
    logger.info(f"[TweetUserList:{mode}] 汇总表保存: {md_path}")

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
    logger.info(f"[TweetUserList:{mode}] CSV 保存: {csv_path}")

    return md_path, csv_path
