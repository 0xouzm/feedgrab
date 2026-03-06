# -*- coding: utf-8 -*-
"""
Xiaohongshu (RED) User Notes batch fetcher — fetch all notes from an author's profile.

Supports:
    feedgrab https://www.xiaohongshu.com/user/profile/5eb416f000000000010010c2
    feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...?xsec_token=...

Strategy (tiered, with fallback):
    Tier 0 — Extract notes from __INITIAL_STATE__ (Vue SSR data, ~30 notes, zero API calls)
    Tier 1 — Inject XHR interceptor + auto-scroll to capture user_posted API responses
             (falls back to Tier 0 only if API returns 461 / blocked)
    Tier 2 — Navigate to each note detail page (with xsec_token) for full content extraction
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

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


def _build_note_url(note_id: str, xsec_token: str) -> str:
    """Construct a full XHS note URL with xsec_token for access."""
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        return f"{base}?xsec_token={xsec_token}&xsec_source=pc_user"
    return base


# ---------------------------------------------------------------------------
# Tier 0 — Extract from __INITIAL_STATE__ (Vue SSR data)
# ---------------------------------------------------------------------------

XHS_INITIAL_STATE_JS = """() => {
    const state = window.__INITIAL_STATE__;
    if (!state || !state.user) return { found: false };

    // Author name from userPageData
    let authorName = '';
    try {
        const upd = state.user.userPageData;
        const raw = upd._rawValue || upd._value || upd;
        if (raw && raw.basicInfo) authorName = raw.basicInfo.nickname || '';
    } catch(e) {}

    // Notes from Vue 3 ref
    const notesRef = state.user.notes;
    if (!notesRef) return { found: true, authorName, notes: [] };

    const rawNotes = notesRef._rawValue || notesRef._value || notesRef;
    if (!rawNotes) return { found: true, authorName, notes: [] };

    // rawNotes is [[...notes...], ...] (array of arrays)
    const innerArr = Array.isArray(rawNotes[0]) ? rawNotes[0] : rawNotes;
    if (!Array.isArray(innerArr)) return { found: true, authorName, notes: [] };

    const notes = [];
    for (const item of innerArr) {
        const nc = item.noteCard || {};
        const user = nc.user || {};
        const interact = nc.interactInfo || {};

        notes.push({
            noteId: item.id || nc.noteId || '',
            xsecToken: item.xsecToken || nc.xsecToken || '',
            displayTitle: nc.displayTitle || '',
            type: nc.type || '',
            nickname: user.nickname || '',
            userId: user.userId || user.user_id || '',
            likedCount: interact.likedCount || 0,
        });
    }

    return { found: true, authorName, notes };
}"""


async def _extract_initial_state(page) -> Tuple[str, List[Dict]]:
    """Tier 0: Extract notes from Vue SSR __INITIAL_STATE__.

    Returns:
        (author_name, note_items) where each note_item is a dict with
        noteId, xsecToken, displayTitle, type, nickname, userId, likedCount.
    """
    data = await page.evaluate(XHS_INITIAL_STATE_JS)
    if not data.get("found"):
        return "", []

    author_name = data.get("authorName", "")
    notes = data.get("notes", [])
    # Filter out items without noteId
    notes = [n for n in notes if n.get("noteId")]
    return author_name, notes


# ---------------------------------------------------------------------------
# Tier 1 — XHR interceptor + auto-scroll for paginated data
# ---------------------------------------------------------------------------

XHS_XHR_INTERCEPTOR_JS = """() => {
    // Only inject once
    if (window.__xhs_xhr_intercepted) return;
    window.__xhs_xhr_intercepted = true;
    window.__xhs_intercepted_notes = [];

    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function() {
        const url = arguments[1] || '';
        this.addEventListener('readystatechange', function() {
            if (this.readyState === 4 && url.includes('/api/sns/web/v1/user_posted')) {
                try {
                    const resp = JSON.parse(this.responseText);
                    if (resp.code === 0 && resp.data && resp.data.notes) {
                        for (const note of resp.data.notes) {
                            window.__xhs_intercepted_notes.push({
                                noteId: note.note_id || '',
                                xsecToken: note.xsec_token || '',
                                displayTitle: note.display_title || '',
                                type: note.type || '',
                                nickname: (note.user || {}).nickname || '',
                                userId: (note.user || {}).user_id || '',
                                likedCount: ((note.interact_info || {}).liked_count) || 0,
                            });
                        }
                    }
                } catch(e) {}
            }
        });
        return origOpen.apply(this, arguments);
    };
}"""

XHS_COLLECT_INTERCEPTED_JS = """() => {
    const notes = window.__xhs_intercepted_notes || [];
    // Clear after reading
    window.__xhs_intercepted_notes = [];
    return notes;
}"""


async def _scroll_and_collect(
    page, initial_notes: List[Dict], max_scrolls: int
) -> List[Dict]:
    """Tier 1: Auto-scroll with XHR interception to collect more notes.

    Starts with Tier 0 initial notes, then scrolls to trigger user_posted API.
    Falls back gracefully if API is blocked (461).

    Returns:
        Combined list of note items (deduped by noteId).
    """
    # Inject XHR interceptor
    await page.evaluate(XHS_XHR_INTERCEPTOR_JS)

    all_notes: Dict[str, Dict] = {}
    for n in initial_notes:
        all_notes[n["noteId"]] = n

    no_new_count = 0

    for scroll_idx in range(max_scrolls):
        # Scroll down
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(2000)

        # Collect intercepted API responses
        new_notes = await page.evaluate(XHS_COLLECT_INTERCEPTED_JS)
        added = 0
        for n in new_notes:
            nid = n.get("noteId", "")
            if nid and nid not in all_notes:
                all_notes[nid] = n
                added += 1

        if added == 0:
            no_new_count += 1
            if no_new_count >= 3:
                logger.info(
                    f"[XHS-User] 连续 {no_new_count} 次滚动无新笔记，停止"
                )
                break
        else:
            no_new_count = 0
            logger.info(
                f"[XHS-User] 滚动 {scroll_idx + 1}: "
                f"新增 {added} 篇，累计 {len(all_notes)} 篇"
            )

    # Return in order: initial notes first, then scrolled notes
    ordered = []
    seen = set()
    for n in initial_notes:
        nid = n["noteId"]
        if nid not in seen:
            seen.add(nid)
            ordered.append(all_notes.get(nid, n))
    # Append any additional notes from scrolling
    for nid, n in all_notes.items():
        if nid not in seen:
            seen.add(nid)
            ordered.append(n)

    return ordered


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
# Captcha / login redirect handling
# ---------------------------------------------------------------------------

CAPTCHA_WAIT_TIMEOUT = 120  # seconds

async def _handle_captcha_or_login(page, target_url: str, session_path: str, context):
    """Handle captcha or login redirect by waiting for user to solve it.

    If captcha is detected, waits up to CAPTCHA_WAIT_TIMEOUT seconds for user
    to solve it manually in the visible browser window. After solving, saves
    the updated session and navigates back to the target page.

    Works for both profile pages and search result pages.
    """
    current_url = page.url
    if "captcha" in current_url:
        logger.info(
            "[XHS] *** 检测到验证码，请在浏览器窗口中手动完成验证 ***"
        )
        for _ in range(CAPTCHA_WAIT_TIMEOUT // 2):
            await page.wait_for_timeout(2000)
            current_url = page.url
            if "captcha" not in current_url and "login" not in current_url:
                logger.info("[XHS] 验证码已通过!")
                # Save updated session with captcha-verified state
                await context.storage_state(path=session_path)
                logger.info(f"[XHS] Session 已更新: {session_path}")
                break
        else:
            raise RuntimeError(
                f"验证码等待超时 ({CAPTCHA_WAIT_TIMEOUT}s)。请重试。"
            )
    elif "login" in current_url:
        logger.info(
            "[XHS] *** Session 已过期，请在浏览器窗口中重新登录 ***"
        )
        for _ in range(150):  # 5 min for login
            await page.wait_for_timeout(2000)
            current_url = page.url
            if "login" not in current_url and "captcha" not in current_url:
                logger.info("[XHS] 登录成功!")
                await context.storage_state(path=session_path)
                logger.info(f"[XHS] Session 已更新: {session_path}")
                break
        else:
            raise RuntimeError("登录等待超时 (5min)。请重试。")

    # Navigate back to target page if redirected away
    if "captcha" not in page.url and "login" not in page.url:
        # Check if we're already on a relevant XHS page
        on_target = (
            "/user/profile/" in page.url or
            "/search_result" in page.url or
            "/search" in page.url
        )
        if not on_target:
            await page.goto(
                target_url, wait_until="domcontentloaded", timeout=30_000
            )
            await page.wait_for_timeout(3000)
            if "captcha" in page.url or "login" in page.url:
                raise RuntimeError(
                    "验证后仍无法访问目标页面。请检查账号状态或稍后重试。"
                )


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
    from feedgrab.fetchers.browser import (
        evaluate_xhs_note, get_session_path,
        get_async_playwright, stealth_launch, get_stealth_context_options,
        get_stealth_engine_name, setup_resource_blocking, generate_referer,
    )
    from feedgrab.schema import from_xiaohongshu
    from feedgrab.utils.storage import save_to_markdown, _parse_xhs_date

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
    # Use headed mode so user can solve captcha if needed
    async_pw = get_async_playwright()
    logger.info(f"[XHS-User] Stealth engine: {get_stealth_engine_name()}")
    async with async_pw() as p:
        browser = await stealth_launch(p, headless=False)
        context = await browser.new_context(
            **get_stealth_context_options(storage_state=session_path)
        )
        page = await context.new_page()
        await setup_resource_blocking(context)

        try:
            # 5a. Navigate to profile page
            await page.goto(
                profile_url, wait_until="domcontentloaded", timeout=30_000,
                referer=generate_referer(profile_url),
            )
            await page.wait_for_timeout(3000)

            # Session / captcha check
            current_url = page.url
            if "captcha" in current_url or "login" in current_url:
                await _handle_captcha_or_login(
                    page, profile_url, session_path, context
                )

            # 5b. Tier 0: Extract from __INITIAL_STATE__
            logger.info("[XHS-User] Tier 0: 从 __INITIAL_STATE__ 提取笔记列表...")
            author_name, initial_notes = await _extract_initial_state(page)

            if not author_name:
                author_name = f"user_{xhs_user_id[:8]}"

            logger.info(
                f"[XHS-User] Tier 0: 作者 {author_name}, "
                f"首页 {len(initial_notes)} 篇笔记"
            )

            # 5c. Tier 1: Scroll for more (if max_scrolls > 0)
            if max_scrolls > 0 and initial_notes:
                logger.info("[XHS-User] Tier 1: 滚动加载更多笔记...")
                all_note_items = await _scroll_and_collect(
                    page, initial_notes, max_scrolls
                )
            else:
                all_note_items = initial_notes

            total = len(all_note_items)
            logger.info(
                f"[XHS-User] 共收集 {total} 篇笔记 "
                f"(Tier 0: {len(initial_notes)}, "
                f"Tier 1 追加: {total - len(initial_notes)})"
            )

            if total == 0:
                return {
                    "total": 0,
                    "fetched": 0,
                    "skipped": 0,
                    "failed": 0,
                    "list_path": "",
                }

            # 5d. Determine subfolder
            safe_author = re.sub(r'[\\/:*?"<>|]', '_', author_name)
            subfolder = f"notes_{safe_author}"

            # 5e. Tier 2: Process each note — navigate to detail page for full content
            fetched = 0
            skipped = 0
            failed = 0
            note_list = []
            consecutive_old = 0
            OLD_THRESHOLD = 3

            for idx, note_item in enumerate(all_note_items):
                note_id = note_item["noteId"]
                xsec_token = note_item.get("xsecToken", "")
                note_url = _build_note_url(note_id, xsec_token)
                item_id = item_id_from_url(note_url.split("?")[0])

                # Dedup check
                if has_item(item_id, saved_ids):
                    logger.debug(
                        f"[XHS-User] [{idx+1}/{total}] 已存在，跳过: "
                        f"{note_item.get('displayTitle', '')[:30]}"
                    )
                    skipped += 1
                    note_list.append({
                        "url": note_url,
                        "item_id": item_id,
                        "title": note_item.get("displayTitle", ""),
                        "status": "skipped",
                        "error": "已存在",
                    })
                    continue

                try:
                    # Navigate to note detail page (with xsec_token)
                    await page.goto(
                        note_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    # Extract full note data using shared Playwright helper
                    data = await evaluate_xhs_note(page)
                    data["platform"] = "xhs"
                    data["url"] = note_url  # keep xsec_token so URL is accessible

                    # Use displayTitle from Tier 0 as fallback if DOM extraction empty
                    if not data.get("title") and note_item.get("displayTitle"):
                        data["title"] = note_item["displayTitle"]
                    if not data.get("author") and note_item.get("nickname"):
                        data["author"] = note_item["nickname"]

                    # Date: try DOM first, fall back to today
                    if not data.get("date"):
                        data["date"] = datetime.now().strftime("%Y-%m-%d")

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
                                "title": data.get("title", ""),
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
                    add_item(item_id, note_url.split("?")[0], saved_ids)
                    fetched += 1

                    note_title = (
                        data.get("title") or data.get("content", "")[:30]
                    )
                    note_list.append({
                        "url": note_url.split("?")[0],
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
                        f"失败: {note_item.get('displayTitle', '')[:30]} "
                        f"- {error_msg[:80]}"
                    )
                    failed += 1
                    note_list.append({
                        "url": note_url,
                        "item_id": item_id,
                        "title": note_item.get("displayTitle", ""),
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
