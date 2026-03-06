# -*- coding: utf-8 -*-
"""
Xiaohongshu (RED) Search Notes batch fetcher — fetch notes from search results.

Supports:
    feedgrab "https://www.xiaohongshu.com/search_result?keyword=开学第一课&source=..."

Strategy (tiered, same as user notes):
    Tier 0 — Extract notes from __INITIAL_STATE__.search.feeds (~40 notes, zero API calls)
    Tier 1 — Inject XHR interceptor + auto-scroll to capture search/notes API responses
    Tier 2 — Navigate to each note detail page (with xsec_token) for full content extraction
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple
from urllib.parse import urlparse, parse_qs, unquote

from loguru import logger

from feedgrab.config import (
    xhs_search_max_scrolls,
    xhs_search_delay,
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

def _parse_search_url(url: str) -> str:
    """Extract decoded keyword from XHS search URL.

    Examples:
        https://www.xiaohongshu.com/search_result?keyword=%E5%BC%80%E5%AD%A6%E7%AC%AC%E4%B8%80%E8%AF%BE
        → "开学第一课"
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    keyword_list = params.get("keyword", [])
    if not keyword_list:
        raise ValueError(f"搜索 URL 中未找到 keyword 参数: {url}")
    # URL may be double-encoded (%25xx), decode until stable
    keyword = keyword_list[0]
    for _ in range(3):
        decoded = unquote(keyword)
        if decoded == keyword:
            break
        keyword = decoded
    return keyword.strip()


def _build_note_url(note_id: str, xsec_token: str) -> str:
    """Construct a full XHS note URL with xsec_token for access."""
    base = f"https://www.xiaohongshu.com/explore/{note_id}"
    if xsec_token:
        return f"{base}?xsec_token={xsec_token}&xsec_source=pc_search"
    return base


# ---------------------------------------------------------------------------
# Tier 0 — Extract from __INITIAL_STATE__ (search.feeds)
# ---------------------------------------------------------------------------

XHS_SEARCH_INITIAL_STATE_JS = """() => {
    const state = window.__INITIAL_STATE__;
    if (!state || !state.search) return { found: false };

    // Keyword from searchContext
    let keyword = '';
    try {
        const ctx = state.search.searchContext;
        const raw = ctx._rawValue || ctx._value || ctx;
        keyword = raw.keyword || '';
    } catch(e) {}

    // Notes from search.feeds
    const feedsRef = state.search.feeds;
    if (!feedsRef) return { found: true, keyword, notes: [] };

    const rawFeeds = feedsRef._rawValue || feedsRef._value || feedsRef;
    if (!Array.isArray(rawFeeds)) return { found: true, keyword, notes: [] };

    const notes = [];
    for (const item of rawFeeds) {
        if (item.modelType !== 'note') continue;
        const nc = item.noteCard || {};
        const user = nc.user || {};
        const interact = nc.interactInfo || {};

        notes.push({
            noteId: item.id || '',
            xsecToken: item.xsecToken || '',
            displayTitle: nc.displayTitle || '',
            type: nc.type || '',
            nickname: user.nickname || '',
            userId: user.userId || '',
            likedCount: interact.likedCount || 0,
        });
    }

    return { found: true, keyword, notes };
}"""


async def _extract_search_initial_state(page) -> Tuple[str, List[Dict]]:
    """Tier 0: Extract notes from search page __INITIAL_STATE__.

    Returns:
        (keyword, note_items) where each note_item has
        noteId, xsecToken, displayTitle, type, nickname, userId, likedCount.
    """
    data = await page.evaluate(XHS_SEARCH_INITIAL_STATE_JS)
    if not data.get("found"):
        return "", []

    keyword = data.get("keyword", "")
    notes = data.get("notes", [])
    notes = [n for n in notes if n.get("noteId")]
    return keyword, notes


# ---------------------------------------------------------------------------
# Tier 1 — XHR interceptor + auto-scroll for search pagination
# ---------------------------------------------------------------------------

XHS_SEARCH_XHR_INTERCEPTOR_JS = """() => {
    if (window.__xhs_search_intercepted) return;
    window.__xhs_search_intercepted = true;
    window.__xhs_search_intercepted_notes = [];

    const origOpen = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function() {
        const url = arguments[1] || '';
        this.addEventListener('readystatechange', function() {
            if (this.readyState === 4 && url.includes('/api/sns/web/v1/search/notes')) {
                try {
                    const resp = JSON.parse(this.responseText);
                    if (resp.code === 0 && resp.data && resp.data.items) {
                        for (const item of resp.data.items) {
                            if (item.model_type !== 'note') continue;
                            const nc = item.note_card || {};
                            const user = nc.user || {};
                            const interact = nc.interact_info || {};

                            window.__xhs_search_intercepted_notes.push({
                                noteId: item.id || '',
                                xsecToken: item.xsec_token || '',
                                displayTitle: nc.display_title || '',
                                type: nc.type || '',
                                nickname: user.nickname || '',
                                userId: user.user_id || '',
                                likedCount: interact.liked_count || 0,
                            });
                        }
                    }
                } catch(e) {}
            }
        });
        return origOpen.apply(this, arguments);
    };
}"""

XHS_SEARCH_COLLECT_INTERCEPTED_JS = """() => {
    const notes = window.__xhs_search_intercepted_notes || [];
    window.__xhs_search_intercepted_notes = [];
    return notes;
}"""


async def _scroll_and_collect_search(
    page, initial_notes: List[Dict], max_scrolls: int
) -> List[Dict]:
    """Tier 1: Auto-scroll search results with XHR interception.

    Returns:
        Combined list of note items (deduped by noteId).
    """
    await page.evaluate(XHS_SEARCH_XHR_INTERCEPTOR_JS)

    all_notes: Dict[str, Dict] = {}
    for n in initial_notes:
        all_notes[n["noteId"]] = n

    no_new_count = 0

    for scroll_idx in range(max_scrolls):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
        await page.wait_for_timeout(2000)

        new_notes = await page.evaluate(XHS_SEARCH_COLLECT_INTERCEPTED_JS)
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
                    f"[XHS-Search] 连续 {no_new_count} 次滚动无新笔记，停止"
                )
                break
        else:
            no_new_count = 0
            logger.info(
                f"[XHS-Search] 滚动 {scroll_idx + 1}: "
                f"新增 {added} 篇，累计 {len(all_notes)} 篇"
            )

    # Preserve order: initial first, then scrolled
    ordered = []
    seen = set()
    for n in initial_notes:
        nid = n["noteId"]
        if nid not in seen:
            seen.add(nid)
            ordered.append(all_notes.get(nid, n))
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


def _save_batch_record(note_list: list, keyword: str) -> Path:
    """Save batch record to a JSON file in the XHS index/ directory."""
    out_dir = _get_record_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    safe_keyword = re.sub(r'[\\/:*?"<>|]', '_', keyword or "unknown")
    filename = f"search_{safe_keyword}_all_{ts}.json"

    path = out_dir / filename
    payload = {
        "fetched_at": datetime.now().isoformat(),
        "keyword": keyword,
        "total": len(note_list),
        "notes": note_list,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    logger.info(f"[XHS-Search] 批量记录已保存: {path}")
    return path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_search_notes(search_url: str) -> dict:
    """Batch-fetch notes from XHS search results and save each as Markdown.

    Args:
        search_url: XHS search URL with keyword parameter.

    Returns:
        dict with keys: total, fetched, skipped, failed, list_path, keyword
    """
    from feedgrab.fetchers.browser import (
        evaluate_xhs_note, get_session_path,
        get_async_playwright, stealth_launch, get_stealth_context_options,
        get_stealth_engine_name,
    )
    from feedgrab.fetchers.xhs_user_notes import _handle_captcha_or_login
    from feedgrab.schema import from_xiaohongshu
    from feedgrab.utils.storage import save_to_markdown, _parse_xhs_date

    # 1. Verify session exists
    session_path = get_session_path("xhs")
    if not Path(session_path).exists():
        raise RuntimeError(
            "XHS 搜索批量抓取需要登录 session。请先运行: feedgrab login xhs"
        )

    # 2. Parse keyword from URL
    keyword = _parse_search_url(search_url)
    logger.info(f"[XHS-Search] 搜索关键词: {keyword}")

    # 3. Config
    max_scrolls = xhs_search_max_scrolls()
    delay = xhs_search_delay()

    # 4. Load dedup index (XHS platform)
    saved_ids = load_index(platform="XHS")
    initial_count = len(saved_ids)
    logger.info(f"[XHS-Search] 已有 {initial_count} 条笔记索引")

    # 5. Launch browser (ONE context for entire batch)
    async_pw = get_async_playwright()
    logger.info(f"[XHS-Search] Stealth engine: {get_stealth_engine_name()}")
    async with async_pw() as p:
        browser = await stealth_launch(p, headless=False)
        context = await browser.new_context(
            **get_stealth_context_options(storage_state=session_path)
        )
        page = await context.new_page()

        try:
            # 5a. Navigate to search results page
            await page.goto(
                search_url, wait_until="domcontentloaded", timeout=30_000
            )
            await page.wait_for_timeout(5000)

            # Captcha / login check
            current_url = page.url
            if "captcha" in current_url or "login" in current_url:
                await _handle_captcha_or_login(
                    page, search_url, session_path, context
                )

            # 5b. Tier 0: Extract from __INITIAL_STATE__
            logger.info(
                "[XHS-Search] Tier 0: 从 __INITIAL_STATE__ 提取搜索结果..."
            )
            state_keyword, initial_notes = await _extract_search_initial_state(
                page
            )

            # Use keyword from state if URL parse failed
            if state_keyword and not keyword:
                keyword = state_keyword

            logger.info(
                f"[XHS-Search] Tier 0: 关键词 '{keyword}', "
                f"首页 {len(initial_notes)} 篇笔记"
            )

            # 5c. Tier 1: Scroll for more
            if max_scrolls > 0 and initial_notes:
                logger.info("[XHS-Search] Tier 1: 滚动加载更多搜索结果...")
                all_note_items = await _scroll_and_collect_search(
                    page, initial_notes, max_scrolls
                )
            else:
                all_note_items = initial_notes

            total = len(all_note_items)
            logger.info(
                f"[XHS-Search] 共收集 {total} 篇笔记 "
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
                    "keyword": keyword,
                }

            # 5d. Determine subfolder
            safe_keyword = re.sub(r'[\\/:*?"<>|]', '_', keyword)
            subfolder = f"search_{safe_keyword}"

            # 5e. Tier 2: Process each note
            fetched = 0
            skipped = 0
            failed = 0
            note_list = []

            for idx, note_item in enumerate(all_note_items):
                note_id = note_item["noteId"]
                xsec_token = note_item.get("xsecToken", "")
                note_url = _build_note_url(note_id, xsec_token)
                item_id = item_id_from_url(note_url.split("?")[0])

                # Dedup check
                if has_item(item_id, saved_ids):
                    logger.debug(
                        f"[XHS-Search] [{idx+1}/{total}] 已存在，跳过: "
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
                    # Navigate to note detail page
                    await page.goto(
                        note_url,
                        wait_until="domcontentloaded",
                        timeout=30_000,
                    )

                    # Extract full note data
                    data = await evaluate_xhs_note(page)
                    data["platform"] = "xhs"
                    data["url"] = note_url  # keep xsec_token

                    # Fallback fields from Tier 0
                    if not data.get("title") and note_item.get("displayTitle"):
                        data["title"] = note_item["displayTitle"]
                    if not data.get("author") and note_item.get("nickname"):
                        data["author"] = note_item["nickname"]

                    # Date fallback
                    if not data.get("date"):
                        data["date"] = datetime.now().strftime("%Y-%m-%d")

                    note_date = _parse_xhs_date(data.get("date", ""))

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
                            f"[XHS-Search] 进度 [{idx+1}/{total}] "
                            f"成功:{fetched} 跳过:{skipped} 失败:{failed}"
                        )

                    # Rate limit delay
                    time.sleep(delay)

                except Exception as e:
                    error_msg = str(e)
                    logger.warning(
                        f"[XHS-Search] [{idx+1}/{total}] "
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
    logger.info(f"[XHS-Search] 索引更新: {initial_count} -> {len(saved_ids)} 条")

    # 7. Save batch record
    list_path = _save_batch_record(note_list, keyword)

    logger.info(
        f"[XHS-Search] 搜索批量抓取完成: "
        f"总计 {total}, 成功 {fetched}, 跳过 {skipped}, 失败 {failed}"
    )

    return {
        "total": total,
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
        "list_path": str(list_path),
        "keyword": keyword,
    }
