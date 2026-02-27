# -*- coding: utf-8 -*-
"""
Xiaohongshu (RED) User Notes batch fetcher — fetch all notes from an author's profile.

Supports:
    feedgrab https://www.xiaohongshu.com/user/profile/5eb416f000000000010010c2
    feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...?xsec_token=...

Design:
    - Playwright browser with saved session (reuse xhs.json)
    - Scroll profile page to collect note card URLs
    - Visit each note URL in same browser context, extract via JS evaluate
    - Stream-save each note immediately as Markdown
    - Date filtering: stop after 3 consecutive old notes
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from feedgrab.config import (
    xhs_user_note_max_scrolls,
    xhs_user_note_delay,
    xhs_user_notes_since,
)
from feedgrab.utils.dedup import (
    load_index,
    save_index,
    has_item,
    add_item,
    item_id_from_url,
    get_index_path,
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def _parse_profile_url(url: str) -> str:
    """Extract user_id from XHS profile URL.

    Examples:
        https://www.xiaohongshu.com/user/profile/5eb416f000000000010010c2
        → "5eb416f000000000010010c2"
    """
    match = re.search(r'xiaohongshu\.com/user/profile/([a-f0-9]+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"无法从 URL 提取小红书用户 ID: {url}")


# ---------------------------------------------------------------------------
# Profile page scrolling — collect note URLs
# ---------------------------------------------------------------------------

XHS_PROFILE_JS = """() => {
    // Author name from profile header
    const nameEl = document.querySelector('.user-name')
        || document.querySelector('.nickname')
        || document.querySelector('.user-nickname');
    const authorName = nameEl ? nameEl.innerText.trim().split('\\n')[0] : '';

    // Note cards in the waterfall grid — cover multiple selectors
    const links = Array.from(
        document.querySelectorAll(
            'section.note-item a[href*="/explore/"], '
            + 'section.note-item a[href*="/discovery/item/"], '
            + 'div.note-item a[href*="/explore/"], '
            + 'a.cover[href*="/explore/"], '
            + 'a.cover[href*="/discovery/item/"], '
            + 'a[href*="/explore/"][class*="cover"], '
            + '.feeds-container a[href*="/explore/"]'
        )
    );

    const urls = links.map(a => {
        try {
            const u = new URL(a.href, window.location.origin);
            return u.origin + u.pathname;
        } catch(e) { return ''; }
    }).filter(Boolean);

    // Deduplicate while preserving order
    const seen = new Set();
    const unique = [];
    for (const url of urls) {
        if (!seen.has(url)) {
            seen.add(url);
            unique.push(url);
        }
    }

    return { authorName, noteUrls: unique };
}"""


async def _scroll_and_collect(page, max_scrolls: int) -> Tuple[str, List[str]]:
    """Scroll the profile page to load all note cards.

    Returns:
        (author_name, note_urls) — author display name and ordered list of note URLs.
    """
    all_urls: List[str] = []
    seen = set()
    author_name = ""
    no_new_count = 0

    for scroll_idx in range(max_scrolls):
        data = await page.evaluate(XHS_PROFILE_JS)
        if not author_name:
            author_name = data.get("authorName", "")

        new_urls = [u for u in data["noteUrls"] if u not in seen]
        for u in new_urls:
            seen.add(u)
            all_urls.append(u)

        if not new_urls:
            no_new_count += 1
            if no_new_count >= 3:
                logger.info(f"[XHS-User] 连续 {no_new_count} 次无新笔记，停止滚动")
                break
        else:
            no_new_count = 0
            logger.info(
                f"[XHS-User] 滚动 {scroll_idx + 1}: "
                f"新增 {len(new_urls)} 篇，累计 {len(all_urls)} 篇"
            )

        # Scroll down
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(1500)

    return author_name, all_urls


# ---------------------------------------------------------------------------
# Batch record persistence
# ---------------------------------------------------------------------------

def _get_record_dir() -> Path:
    """Return the XHS index directory for batch records."""
    index_dir = get_index_path(platform="XHS").parent
    index_dir.mkdir(parents=True, exist_ok=True)
    return index_dir


def _save_batch_record(
    note_list: list, author_name: str, since_date: str = ""
) -> Path:
    """Save batch record to a JSON file in the XHS index/ directory."""
    out_dir = _get_record_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")

    safe_name = re.sub(r'[\\/:*?"<>|]', '_', author_name or "unknown")
    if since_date:
        filename = f"notes_{safe_name}_{since_date}_{today}_{ts}.json"
    else:
        filename = f"notes_{safe_name}_all_{ts}.json"

    path = out_dir / filename
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "author_name": author_name,
        "since": since_date or "",
        "total": len(note_list),
        "notes": note_list,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info(f"[XHS-User] 批量记录已保存: {path}")
    return path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_user_notes(profile_url: str) -> dict:
    """Batch-fetch all notes from an XHS user profile and save each as Markdown.

    Args:
        profile_url: XHS profile URL (with or without xsec_token).

    Returns:
        dict with keys: total, fetched, skipped, failed, list_path
    """
    from feedgrab.fetchers.browser import evaluate_xhs_note, get_session_path
    from feedgrab.schema import from_xiaohongshu
    from feedgrab.utils.storage import save_to_markdown, _parse_xhs_date

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            '  pip install "feedgrab[browser]"\n'
            "  playwright install chromium"
        )

    # 1. Verify session exists
    session_path = get_session_path("xhs")
    if not Path(session_path).exists():
        raise RuntimeError(
            "XHS 批量抓取需要登录 session。请先运行: feedgrab login xhs"
        )

    # 2. Parse user_id from URL
    xhs_user_id = _parse_profile_url(profile_url)
    logger.info(f"[XHS-User] 用户 ID: {xhs_user_id}")

    # 3. Config
    max_scrolls = xhs_user_note_max_scrolls()
    delay = xhs_user_note_delay()
    since_date = xhs_user_notes_since()
    if since_date:
        logger.info(f"[XHS-User] 日期过滤: 仅抓取 {since_date} 之后的笔记")

    # 4. Load dedup index (XHS platform)
    saved_ids = load_index(platform="XHS")
    initial_count = len(saved_ids)
    logger.info(f"[XHS-User] 已有 {initial_count} 条笔记索引")

    # 5. Launch browser (ONE context for entire batch)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            storage_state=session_path,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            # 5a. Navigate to profile page
            await page.goto(
                profile_url, wait_until="domcontentloaded", timeout=30_000
            )
            await page.wait_for_timeout(2000)

            # Session expiry check
            current_url = page.url
            if "login" in current_url:
                raise RuntimeError(
                    "XHS session 已过期。请重新运行: feedgrab login xhs"
                )

            # 5b. Scroll and collect note URLs
            logger.info("[XHS-User] 开始滚动收集笔记链接...")
            author_name, note_urls = await _scroll_and_collect(page, max_scrolls)

            if not author_name:
                author_name = f"user_{xhs_user_id[:8]}"

            total = len(note_urls)
            logger.info(
                f"[XHS-User] 作者: {author_name}, 共发现 {total} 篇笔记"
            )

            if total == 0:
                return {
                    "total": 0,
                    "fetched": 0,
                    "skipped": 0,
                    "failed": 0,
                    "list_path": "",
                }

            # 5c. Determine subfolder
            safe_author = re.sub(r'[\\/:*?"<>|]', '_', author_name)
            subfolder = f"notes_{safe_author}"

            # 5d. Process each note URL
            fetched = 0
            skipped = 0
            failed = 0
            note_list = []
            consecutive_old = 0
            OLD_THRESHOLD = 3

            for idx, note_url in enumerate(note_urls):
                item_id = item_id_from_url(note_url)

                # Dedup check
                if has_item(item_id, saved_ids):
                    logger.debug(
                        f"[XHS-User] [{idx+1}/{total}] 已存在，跳过: "
                        f"{note_url[-30:]}"
                    )
                    skipped += 1
                    note_list.append({
                        "url": note_url,
                        "item_id": item_id,
                        "status": "skipped",
                        "error": "已存在",
                    })
                    continue

                try:
                    # Navigate to note page (reuse same page/tab)
                    await page.goto(
                        note_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    # Extract note data using shared helper
                    data = await evaluate_xhs_note(page)
                    data["platform"] = "xhs"
                    data["url"] = note_url

                    # Date filtering
                    note_date = _parse_xhs_date(data.get("date", ""))
                    if since_date and note_date:
                        if note_date < since_date:
                            consecutive_old += 1
                            logger.debug(
                                f"[XHS-User] [{idx+1}/{total}] "
                                f"日期 {note_date} < {since_date}，跳过 "
                                f"(连续旧笔记: {consecutive_old}/{OLD_THRESHOLD})"
                            )
                            skipped += 1
                            note_list.append({
                                "url": note_url,
                                "item_id": item_id,
                                "date": note_date,
                                "status": "skipped",
                                "error": f"日期过滤 ({note_date})",
                            })
                            if consecutive_old >= OLD_THRESHOLD:
                                logger.info(
                                    f"[XHS-User] 连续 {OLD_THRESHOLD} 篇旧笔记，"
                                    f"停止处理"
                                )
                                break
                            continue
                        else:
                            consecutive_old = 0

                    # Convert to UnifiedContent and save
                    content = from_xiaohongshu(data)
                    content.category = subfolder
                    save_to_markdown(content)

                    # Update dedup index
                    add_item(item_id, note_url, saved_ids)
                    fetched += 1

                    note_title = (
                        data.get("title") or data.get("content", "")[:30]
                    )
                    note_list.append({
                        "url": note_url,
                        "item_id": item_id,
                        "author": data.get("author", ""),
                        "date": note_date,
                        "title": note_title[:80],
                        "status": "fetched",
                        "error": "",
                    })

                    # Progress log
                    if (idx + 1) % 5 == 0 or idx + 1 == total:
                        logger.info(
                            f"[XHS-User] 进度 [{idx+1}/{total}] "
                            f"成功:{fetched} 跳过:{skipped} 失败:{failed}"
                        )

                    # Rate limit delay
                    time.sleep(delay)

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(
                        f"[XHS-User] [{idx+1}/{total}] "
                        f"失败: {note_url[-30:]} - {error_msg[:80]}"
                    )
                    failed += 1
                    note_list.append({
                        "url": note_url,
                        "item_id": item_id,
                        "status": "failed",
                        "error": error_msg[:200],
                    })

        finally:
            await context.close()
            await browser.close()

    # 6. Persist dedup index
    save_index(saved_ids, platform="XHS")
    logger.info(f"[XHS-User] 索引更新: {initial_count} -> {len(saved_ids)} 条")

    # 7. Save batch record
    list_path = _save_batch_record(note_list, author_name, since_date)

    logger.info(
        f"[XHS-User] 批量抓取完成: "
        f"总计 {total}, 成功 {fetched}, 跳过 {skipped}, 失败 {failed}"
    )

    return {
        "total": total,
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "list_path": str(list_path),
    }
