# -*- coding: utf-8 -*-
"""
Feishu Wiki batch fetcher – recursively fetch all documents in a wiki space.

Tier 0: Open API – wiki/v2 node traversal + docx blocks per document
Tier 1: Playwright – sidebar DOM parsing + per-page PageMain extraction
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from feedgrab.config import (
    feishu_app_id,
    feishu_app_secret,
    feishu_download_images,
    feishu_page_load_timeout,
    feishu_wiki_batch_enabled,
    feishu_wiki_delay,
    feishu_wiki_since,
    get_data_dir,
)
from feedgrab.fetchers.feishu import (
    _decode_sheet_client_vars,
    _merge_sheet_snapshot_blocks,
    _fetch_document_blocks,
    _get_lark_client,
    _is_api_available,
    _PLAYWRIGHT_SHEET_CACHE,
    _resolve_wiki_node,
    blocks_to_markdown,
    download_feishu_images,
    parse_feishu_url,
)
from feedgrab.utils.dedup import add_item, has_item, load_index
from feedgrab.utils.storage import save_to_markdown
from feedgrab.schema import from_feishu

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress / checkpoint
# ---------------------------------------------------------------------------

def _progress_path(token: str) -> Path:
    return Path(get_data_dir()) / f"_progress_feishu_wiki_{token}.json"


def _load_progress(token: str) -> dict:
    p = _progress_path(token)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"done": []}


def _save_progress(token: str, progress: dict):
    p = _progress_path(token)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(progress, ensure_ascii=False), encoding="utf-8")


def _clear_progress(token: str):
    p = _progress_path(token)
    if p.exists():
        p.unlink()


# ---------------------------------------------------------------------------
# Tier 0: Open API wiki node traversal
# ---------------------------------------------------------------------------

def _list_wiki_children(space_id: str, parent_node_token: str) -> List[dict]:
    """List all child nodes under a parent in a wiki space via Open API."""
    from lark_oapi.api.wiki.v2 import ListSpaceNodeRequest

    client = _get_lark_client()
    all_nodes: List[dict] = []
    page_token: Optional[str] = None

    while True:
        builder = (
            ListSpaceNodeRequest.builder()
            .space_id(space_id)
            .parent_node_token(parent_node_token)
            .page_size(50)
        )
        if page_token:
            builder = builder.page_token(page_token)
        req = builder.build()
        resp = client.wiki.v2.space_node.list(req)

        if not resp.success():
            raise RuntimeError(
                f"wiki list_nodes failed: code={resp.code} msg={resp.msg}"
            )
        if resp.data and resp.data.items:
            for node in resp.data.items:
                all_nodes.append({
                    "node_token": node.node_token or "",
                    "obj_token": node.obj_token or "",
                    "obj_type": node.obj_type or "",
                    "title": node.title or "",
                    "has_child": getattr(node, "has_child", False),
                    "obj_create_time": getattr(node, "obj_create_time", "") or "",
                    "obj_edit_time": getattr(node, "obj_edit_time", "") or "",
                })
        if resp.data and resp.data.has_more:
            page_token = resp.data.page_token
        else:
            break

    return all_nodes


def _collect_all_nodes(
    space_id: str,
    root_token: str,
    since: str = "",
    depth: int = 0,
) -> List[dict]:
    """Recursively collect all document nodes in a wiki tree."""
    if depth > 20:
        return []

    children = _list_wiki_children(space_id, root_token)
    result: List[dict] = []

    for node in children:
        # Apply date filter if configured
        if since and node.get("obj_edit_time"):
            try:
                edit_ts = int(node["obj_edit_time"])
                since_ts = int(datetime.strptime(since, "%Y-%m-%d").timestamp())
                if edit_ts < since_ts:
                    continue
            except (ValueError, TypeError):
                pass

        node["depth"] = depth
        result.append(node)

        if node.get("has_child"):
            sub = _collect_all_nodes(
                space_id, node["node_token"], since, depth + 1
            )
            result.extend(sub)

    return result


async def _fetch_wiki_via_api(
    url: str,
    root_token: str,
) -> Dict[str, Any]:
    """Tier 0 – Batch fetch entire wiki tree via Open API."""
    # Resolve root node to get space_id
    root_info = _resolve_wiki_node(root_token)
    space_id = root_info["space_id"]
    wiki_title = root_info.get("title", root_token)

    if not space_id:
        raise RuntimeError("Cannot determine space_id from wiki root node")

    # Collect all nodes recursively
    since = feishu_wiki_since()
    print(f"📂 Scanning wiki tree: {wiki_title}")
    all_nodes = _collect_all_nodes(space_id, root_token, since)
    doc_nodes = [n for n in all_nodes if n["obj_type"] in ("docx", "doc")]
    print(f"📄 Found {len(doc_nodes)} documents ({len(all_nodes)} total nodes)")

    if not doc_nodes:
        return {
            "wiki_title": wiki_title,
            "total": 0,
            "fetched": 0,
            "skipped": 0,
            "failed": 0,
            "docs": [],
        }

    # Load dedup index + progress
    dedup_idx = load_index("Feishu")
    progress = _load_progress(root_token)
    done_set = set(progress.get("done", []))
    delay = feishu_wiki_delay()

    fetched = 0
    skipped = 0
    failed = 0

    for i, node in enumerate(doc_nodes, 1):
        node_token = node["node_token"]
        obj_token = node["obj_token"]
        title = node.get("title", obj_token)

        # Skip if already done in this run
        if node_token in done_set:
            skipped += 1
            continue

        # Skip if already in dedup index
        item_id = hashlib.md5(node_token.encode()).hexdigest()[:12]
        if has_item(item_id, dedup_idx):
            skipped += 1
            done_set.add(node_token)
            continue

        print(f"  [{i}/{len(doc_nodes)}] {title}")

        try:
            doc_url = url.rsplit("/wiki/", 1)[0] + f"/wiki/{node_token}"
            _img_subdir = hashlib.md5(doc_url.encode()).hexdigest()[:12]

            doc_title, blocks = _fetch_document_blocks(obj_token)
            images_list: List[dict] = []
            content = blocks_to_markdown(blocks, images=images_list,
                                         img_subdir=_img_subdir)

            data = {
                "title": title or doc_title,
                "content": content,
                "url": doc_url,
                "author": "",
                "doc_type": node["obj_type"],
                "doc_token": obj_token,
                "images": [img.get("token", "") for img in images_list],
                "images_info": images_list,
                "img_subdir": _img_subdir,
                "tags": [],
            }

            # Save via standard pipeline
            uc = from_feishu(data)
            uc.category = wiki_title
            saved_path = save_to_markdown(uc)
            add_item(item_id, data["url"], dedup_idx)

            # Download images if enabled
            if saved_path and images_list and feishu_download_images():
                download_feishu_images(saved_path, images_list, doc_url,
                                       img_subdir=_img_subdir)

            fetched += 1
            done_set.add(node_token)

            # Save progress periodically
            if fetched % 5 == 0:
                progress["done"] = list(done_set)
                _save_progress(root_token, progress)

        except Exception as e:
            logger.warning(f"[Feishu Wiki] Failed to fetch {title}: {e}")
            failed += 1

        if i < len(doc_nodes):
            time.sleep(delay)

    # Cleanup progress file on success
    if not failed:
        _clear_progress(root_token)
    else:
        progress["done"] = list(done_set)
        _save_progress(root_token, progress)

    return {
        "wiki_title": wiki_title,
        "total": len(doc_nodes),
        "fetched": fetched,
        "skipped": skipped,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Tier 1: Playwright sidebar extraction
# ---------------------------------------------------------------------------

FEISHU_WIKI_SIDEBAR_JS = """
(() => {
  // Extract all wiki page links from the left sidebar navigation
  const links = [];
  const sidebar = document.querySelector('.wiki-sidebar-tree')
    || document.querySelector('[class*="catalogue"]')
    || document.querySelector('[class*="tree-node"]')?.closest('[class*="sidebar"]')
    || document.querySelector('nav');

  if (!sidebar) return { error: 'Sidebar not found', links: [] };

  const anchors = sidebar.querySelectorAll('a[href*="/wiki/"]');
  const seen = new Set();
  anchors.forEach(a => {
    const href = a.href;
    const match = href.match(/\\/wiki\\/([A-Za-z0-9]+)/);
    if (match && !seen.has(match[1])) {
      seen.add(match[1]);
      links.push({
        title: (a.textContent || '').trim(),
        url: href,
        token: match[1]
      });
    }
  });
  return { links };
})()
"""


async def _fetch_wiki_via_playwright(
    url: str,
    root_token: str,
) -> Dict[str, Any]:
    """Tier 1/2 – Batch fetch wiki documents via Playwright sidebar scraping.

    Tries CDP direct connect first (zero startup, reuses Chrome login),
    then falls back to launching a new browser instance.
    """
    from feedgrab.fetchers.browser import (
        evaluate_feishu_doc,
        get_session_path,
        get_stealth_context_options,
        _connect_feishu_cdp,
        FEISHU_DOC_JS_EVALUATE,
        FEISHU_SHEET_FETCH_JS,
        _find_sheet_tokens,
    )

    # ── Try CDP direct connect first ─────────────────────────
    pw_cdp, browser_cdp, page_cdp, via_cdp = await _connect_feishu_cdp()
    if via_cdp:
        pw = pw_cdp
        browser = browser_cdp
        page = page_cdp
        skip_warmup = True
        logger.info("[Feishu Wiki] Using CDP direct connect")
    else:
        # ── Fall back to launching new browser ───────────────
        skip_warmup = False

        # Use vanilla playwright — patchright causes ERR_CONNECTION_CLOSED
        try:
            from playwright.async_api import async_playwright as _pw_factory
        except ImportError:
            from feedgrab.fetchers.browser import get_async_playwright
            _pw_factory = get_async_playwright()

        session_path = get_session_path("feishu")
        if not Path(session_path).exists():
            raise RuntimeError("Feishu session not found. Run: feedgrab login feishu")

        pw = await _pw_factory().start()
        browser = await pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx_opts = get_stealth_context_options(storage_state=session_path)
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

    browser_launched = not via_cdp  # Track for cleanup

    try:

        # Disable copy restrictions (same as evaluate_feishu_doc)
        await page.add_init_script("""
            if (window.copyControl && window.copyControl.enable) {
                window.copyControl.enable();
            }
        """)

        # Sheet data interceptor — captures client_vars + lazy block payloads
        sheet_cv_data: dict = {}
        sheet_block_data: dict = {}

        async def _capture_sheet_response(response):
            try:
                if response.status != 200:
                    return
                if "client_vars" in response.url:
                    body = await response.json()
                    if (
                        body.get("code") == 0
                        and body.get("data", {}).get("snapshot")
                    ):
                        token = body["data"].get("token", "")
                        sheet_id = body["data"].get("sheetId", "")
                        key = f"{token}_{sheet_id}" if sheet_id else token
                        if key:
                            sheet_cv_data[key] = body["data"]
                            logger.info(
                                f"[Feishu Wiki PW] Intercepted sheet data: {key}"
                            )
                    return
                if "/space/api/v3/sheet/block" in response.url:
                    body = await response.json()
                    blocks = body.get("data", {}).get("blocks", {})
                    if blocks:
                        sheet_block_data.update(blocks)
                        logger.info(
                            f"[Feishu Wiki PW] Intercepted sheet blocks: +{len(blocks)} "
                            f"(total {len(sheet_block_data)})"
                        )
            except Exception:
                pass

        page.on("response", _capture_sheet_response)

        # Navigate to wiki root
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)  # Wait for sidebar to render

        # Extract sidebar links
        sidebar_data = await page.evaluate(FEISHU_WIKI_SIDEBAR_JS)
        if not sidebar_data or sidebar_data.get("error"):
            raise RuntimeError(
                f"Sidebar extraction failed: {sidebar_data.get('error', 'unknown')}"
            )

        links = sidebar_data.get("links", [])
        wiki_title = (await page.title()).replace(" - 飞书云文档", "").strip()
        print(f"📂 Wiki: {wiki_title}")
        print(f"📄 Found {len(links)} pages in sidebar")

        if not links:
            return {
                "wiki_title": wiki_title,
                "total": 0,
                "fetched": 0,
                "skipped": 0,
                "failed": 0,
            }

        # Load dedup + progress
        dedup_idx = load_index("Feishu")
        progress = _load_progress(root_token)
        done_set = set(progress.get("done", []))
        delay = feishu_wiki_delay()

        fetched = 0
        skipped = 0
        failed = 0

        for i, link in enumerate(links, 1):
            token = link["token"]
            title = link.get("title", token)
            link_url = link["url"]

            if token in done_set:
                skipped += 1
                continue

            item_id = hashlib.md5(token.encode()).hexdigest()[:12]
            if has_item(item_id, dedup_idx):
                skipped += 1
                done_set.add(token)
                continue

            print(f"  [{i}/{len(links)}] {title}")

            try:
                # Clear per-page sheet data
                sheet_cv_data.clear()
                sheet_block_data.clear()

                # Navigate to each page
                await page.goto(link_url, wait_until="domcontentloaded", timeout=30000)

                # Wait for editor — use author selector as full-render signal
                try:
                    await page.wait_for_function(
                        "() => window.PageMain?.blockManager?.rootBlockModel != null"
                        " || document.querySelector('div[role=\"document\"]') != null",
                        timeout=10000,
                    )
                except Exception:
                    pass

                try:
                    await page.wait_for_selector(
                        ".docs-info-avatar-name-text, .docs-info-avatar-name",
                        timeout=feishu_page_load_timeout(),
                    )
                except Exception:
                    await page.wait_for_timeout(2000)

                data = await page.evaluate(FEISHU_DOC_JS_EVALUATE)
                if not data or data.get("error"):
                    raise RuntimeError(data.get("error", "extraction failed"))

                # Sheet processing: intercepted data + active fetch
                sheet_tokens = _find_sheet_tokens(data.get("blockTree"))
                merged_sheet_data = dict(sheet_cv_data)
                if sheet_tokens:
                    logger.info(
                        f"[Feishu Wiki PW] Preloading {len(sheet_tokens)} embedded sheet(s) via stepped scroll"
                    )
                    try:
                        await page.evaluate(
                            """async () => {
                                const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                                const doc = document.documentElement;
                                const total = Math.max(doc?.scrollHeight || 0, document.body?.scrollHeight || 0);
                                const step = Math.max(Math.floor((window.innerHeight || 800) * 0.8), 640);
                                window.scrollTo(0, 0);
                                await sleep(250);
                                for (let y = 0; y <= total; y += step) {
                                    window.scrollTo(0, y);
                                    await sleep(450);
                                }
                                window.scrollTo(0, 0);
                                await sleep(250);
                                return true;
                            }"""
                        )
                        await page.wait_for_timeout(2000)
                    except Exception as e:
                        logger.debug(f"[Feishu Wiki PW] Sheet preload scroll failed: {e}")

                    merged_sheet_data = dict(sheet_cv_data)
                    missing_tokens = sorted(
                        tk for tk in sheet_tokens if tk not in merged_sheet_data
                    )
                    if merged_sheet_data:
                        logger.info(
                            f"[Feishu Wiki PW] Intercepted "
                            f"{len(merged_sheet_data)}/{len(sheet_tokens)} "
                            f"sheet(s); missing {len(missing_tokens)}"
                        )
                    if missing_tokens:
                        logger.info(
                            f"[Feishu Wiki PW] Fetching {len(missing_tokens)} "
                            f"missing sheet(s) via internal API: "
                            f"{missing_tokens}"
                        )
                        fetched_sheets = await page.evaluate(
                            FEISHU_SHEET_FETCH_JS, missing_tokens
                        )
                        if fetched_sheets:
                            merged_sheet_data.update(fetched_sheets)
                            still_missing = sorted(
                                tk for tk in sheet_tokens
                                if tk not in merged_sheet_data
                            )
                            logger.info(
                                f"[Feishu Wiki PW] Active fetch got "
                                f"{len(fetched_sheets)} sheet(s); "
                                f"still missing {len(still_missing)}"
                            )
                if merged_sheet_data:
                    data["sheet_client_vars"] = merged_sheet_data
                if sheet_block_data:
                    data["sheet_blocks"] = dict(sheet_block_data)

                # Populate sheet cache for blocks_to_markdown()
                _PLAYWRIGHT_SHEET_CACHE.clear()
                prefer_api_for_sparse = _is_api_available()
                extra_sheet_blocks = data.get("sheet_blocks") or {}
                for tk, cv in (data.get("sheet_client_vars") or {}).items():
                    try:
                        merged_cv = _merge_sheet_snapshot_blocks(
                            cv, extra_sheet_blocks
                        )
                        table_md = _decode_sheet_client_vars(
                            merged_cv,
                            allow_sparse_blocks=not prefer_api_for_sparse,
                        )
                        if table_md:
                            _PLAYWRIGHT_SHEET_CACHE[tk] = table_md
                            logger.info(
                                f"[Feishu Wiki PW] Pre-decoded sheet: {tk}"
                            )
                        else:
                            _PLAYWRIGHT_SHEET_CACHE[tk] = ""
                            logger.info(
                                f"[Feishu Wiki PW] Sheet decode deferred to fallback: {tk}"
                            )
                    except Exception as e:
                        _PLAYWRIGHT_SHEET_CACHE[tk] = ""
                        logger.debug(
                            f"[Feishu Wiki PW] Sheet decode failed for {tk}: {e}"
                        )

                # Convert block tree to Markdown with image collection
                _img_subdir = hashlib.md5(link_url.encode()).hexdigest()[:12]
                images_list: List[dict] = []
                block_tree = data.get("blockTree")
                if block_tree:
                    children = block_tree.get("children", [])
                    content = blocks_to_markdown(children, images=images_list,
                                                 img_subdir=_img_subdir)
                else:
                    content = data.get("content", "")

                _PLAYWRIGHT_SHEET_CACHE.clear()

                # Pre-download images via JS fetch (page security context)
                if images_list and feishu_download_images():
                    img_tokens = [
                        img.get("token", "") for img in images_list
                        if img.get("token")
                    ]
                    if img_tokens:
                        from feedgrab.fetchers.browser import (
                            _FEISHU_IMAGE_CDN_DISCOVER_JS,
                            _FEISHU_IMAGE_FETCH_JS,
                        )
                        try:
                            cdn_info = await page.evaluate(
                                _FEISHU_IMAGE_CDN_DISCOVER_JS
                            )
                            if cdn_info:
                                import base64 as _b64
                                batch_size = 10
                                for s in range(
                                    0, len(img_tokens), batch_size
                                ):
                                    batch = img_tokens[s:s + batch_size]
                                    fetched_imgs = await page.evaluate(
                                        _FEISHU_IMAGE_FETCH_JS,
                                        {
                                            "tokens": batch,
                                            "cdn": cdn_info["cdn"],
                                            "mount_token": cdn_info[
                                                "mount_token"
                                            ],
                                        },
                                    )
                                    if not fetched_imgs:
                                        continue
                                    for img_info in images_list:
                                        tk = img_info.get("token", "")
                                        b64 = fetched_imgs.get(tk, "")
                                        if (b64
                                                and not b64.startswith(
                                                    "error:")):
                                            try:
                                                raw = _b64.b64decode(b64)
                                                if len(raw) > 100:
                                                    img_info["_bytes"] = raw
                                            except Exception:
                                                pass
                        except Exception as e:
                            logger.debug(
                                f"[Feishu Wiki PW] JS image fetch: {e}"
                            )

                doc_data = {
                    "title": title or data.get("title", ""),
                    "content": content,
                    "url": link_url,
                    "author": data.get("author", ""),
                    "doc_type": "wiki",
                    "doc_token": token,
                    "images": [img.get("token", "") for img in images_list],
                    "images_info": images_list,
                    "img_subdir": _img_subdir,
                    "tags": [],
                }

                uc = from_feishu(doc_data)
                uc.category = wiki_title
                saved_path = save_to_markdown(uc)
                add_item(item_id, link_url, dedup_idx)

                # Download images if enabled
                if saved_path and images_list and feishu_download_images():
                    download_feishu_images(saved_path, images_list, link_url,
                                           img_subdir=_img_subdir)

                fetched += 1
                done_set.add(token)

                if fetched % 5 == 0:
                    progress["done"] = list(done_set)
                    _save_progress(root_token, progress)

            except Exception as e:
                logger.warning(f"[Feishu Wiki PW] Failed {title}: {e}")
                failed += 1

            if i < len(links):
                await asyncio.sleep(delay)

        if not failed:
            _clear_progress(root_token)
        else:
            progress["done"] = list(done_set)
            _save_progress(root_token, progress)

        return {
            "wiki_title": wiki_title,
            "total": len(links),
            "fetched": fetched,
            "skipped": skipped,
            "failed": failed,
        }

    finally:
        if via_cdp:
            # CDP: close tab only, don't kill user's Chrome
            try:
                await page.close()
            except Exception:
                pass
            try:
                await browser.close()
            except Exception:
                pass
        elif browser:
            await browser.close()
        await pw.stop()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def fetch_feishu_wiki(url: str) -> Dict[str, Any]:
    """Batch fetch all documents in a Feishu wiki space.

    Returns a summary dict with counts.
    """
    if not feishu_wiki_batch_enabled():
        raise ValueError(
            "Wiki batch is disabled. Set FEISHU_WIKI_BATCH_ENABLED=true "
            "or use the feishu-wiki CLI command."
        )

    parsed = parse_feishu_url(url)
    if not parsed or parsed["type"] != "wiki":
        raise ValueError(f"Not a Feishu wiki URL: {url}")

    root_token = parsed["token"]

    # Tier 0: Open API
    if _is_api_available():
        try:
            logger.info("[Feishu Wiki] Tier 0: Open API batch")
            return await _fetch_wiki_via_api(url, root_token)
        except Exception as e:
            logger.warning(f"[Feishu Wiki] Tier 0 failed ({e}), falling back")

    # Tier 1: Playwright
    try:
        logger.info("[Feishu Wiki] Tier 1: Playwright sidebar")
        return await _fetch_wiki_via_playwright(url, root_token)
    except Exception as e:
        raise RuntimeError(
            f"Wiki batch failed: {e}. "
            "Options: 1) Set FEISHU_APP_ID + FEISHU_APP_SECRET, "
            "2) Run 'feedgrab login feishu'"
        )
