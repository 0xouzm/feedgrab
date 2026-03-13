# -*- coding: utf-8 -*-
"""
Feishu Wiki batch fetcher – recursively fetch all documents in a wiki space.

Tier 0: Open API – wiki/v2 node traversal + docx blocks per document
Tier 1: Playwright – sidebar DOM parsing + per-page PageMain extraction
"""

import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from feedgrab.config import (
    feishu_app_id,
    feishu_app_secret,
    feishu_wiki_batch_enabled,
    feishu_wiki_delay,
    feishu_wiki_since,
    get_data_dir,
)
from feedgrab.fetchers.feishu import (
    _fetch_document_blocks,
    _get_lark_client,
    _is_api_available,
    _resolve_wiki_node,
    blocks_to_markdown,
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
        import hashlib
        item_id = hashlib.md5(node_token.encode()).hexdigest()[:12]
        if has_item(dedup_idx, item_id):
            skipped += 1
            done_set.add(node_token)
            continue

        print(f"  [{i}/{len(doc_nodes)}] {title}")

        try:
            doc_title, blocks = _fetch_document_blocks(obj_token)
            content = blocks_to_markdown(blocks)

            data = {
                "title": title or doc_title,
                "content": content,
                "url": url.rsplit("/wiki/", 1)[0] + f"/wiki/{node_token}",
                "author": "",
                "doc_type": node["obj_type"],
                "doc_token": obj_token,
                "images": [],
                "tags": [],
            }

            # Save via standard pipeline
            uc = from_feishu(data)
            save_to_markdown(uc, subdir=f"Feishu/{wiki_title}")
            add_item(dedup_idx, item_id, data["url"], "Feishu")

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
    """Tier 1 – Batch fetch wiki documents via Playwright sidebar scraping."""
    from feedgrab.fetchers.browser import (
        evaluate_feishu_doc,
        get_async_playwright,
        get_session_path,
        get_stealth_context_options,
        setup_resource_blocking,
        stealth_launch,
    )

    session_path = get_session_path("feishu")
    if not Path(session_path).exists():
        raise RuntimeError("Feishu session not found. Run: feedgrab login feishu")

    pw_cls = get_async_playwright()
    pw = await pw_cls().start()
    browser = None

    try:
        browser = await stealth_launch(pw)
        ctx_opts = get_stealth_context_options(storage_state=session_path)
        context = await browser.new_context(**ctx_opts)
        setup_resource_blocking(context)
        page = await context.new_page()

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

            import hashlib
            item_id = hashlib.md5(token.encode()).hexdigest()[:12]
            if has_item(dedup_idx, item_id):
                skipped += 1
                done_set.add(token)
                continue

            print(f"  [{i}/{len(links)}] {title}")

            try:
                # Navigate to each page
                await page.goto(link_url, wait_until="domcontentloaded", timeout=30000)

                # Wait for editor
                try:
                    await page.wait_for_function(
                        "() => window.PageMain?.blockManager?.rootBlockModel != null"
                        " || document.querySelector('div[role=\"document\"]') != null",
                        timeout=10000,
                    )
                except Exception:
                    pass

                await page.wait_for_timeout(1000)

                from feedgrab.fetchers.browser import FEISHU_DOC_JS_EVALUATE
                data = await page.evaluate(FEISHU_DOC_JS_EVALUATE)
                if not data or data.get("error"):
                    raise RuntimeError(data.get("error", "extraction failed"))

                block_tree = data.get("blockTree")
                if block_tree:
                    children = block_tree.get("children", [])
                    content = blocks_to_markdown(children)
                else:
                    content = data.get("content", "")

                doc_data = {
                    "title": title or data.get("title", ""),
                    "content": content,
                    "url": link_url,
                    "author": data.get("author", ""),
                    "doc_type": "wiki",
                    "doc_token": token,
                    "images": [],
                    "tags": [],
                }

                uc = from_feishu(doc_data)
                save_to_markdown(uc, subdir=f"Feishu/{wiki_title}")
                add_item(dedup_idx, item_id, link_url, "Feishu")

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
        if browser:
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
