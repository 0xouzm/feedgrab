# -*- coding: utf-8 -*-
"""
feedgrab CLI — fetch content from any platform.

Usage:
    feedgrab <url>                     # Fetch a single URL
    feedgrab <url1> <url2> ...         # Fetch multiple URLs
    feedgrab list                      # Show content statistics
"""

import sys
import os
import re
import shutil
import time
import asyncio
from pathlib import Path

# Fix Windows console encoding — force UTF-8 instead of GBK
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from feedgrab.reader import UniversalReader


def cmd_fetch(urls: list):
    """Fetch one or more URLs."""
    reader = UniversalReader()

    async def run():
        if len(urls) == 1:
            # Bookmark batch mode: special output
            if "/i/bookmarks" in urls[0]:
                item = await reader.read(urls[0])
                print(f"\n\u2705 {item.content}")
                return

            # List tweets batch mode: special output
            if "/i/lists/" in urls[0] and "x.com" in urls[0]:
                item = await reader.read(urls[0])
                print(f"\n\u2705 {item.content}")
                return

            # XHS user notes batch mode or Twitter user tweets batch mode
            if ("/user/profile/" in urls[0] and "xiaohongshu.com" in urls[0]) or \
               ("/search_result" in urls[0] and "xiaohongshu.com" in urls[0]) or \
               ("x.com/" in urls[0] and "/status/" not in urls[0] and "/i/" not in urls[0]):
                item = await reader.read(urls[0])
                print(f"\n\u2705 {item.content}")
                return

            item = await reader.read(urls[0])
            print(f"\u2705 [{item.source_type.value}] {item.title[:60]}")
            print(f"   {item.url}")
            print(f"   {item.content[:200]}...")
        else:
            items = await reader.read_batch(urls)
            for item in items:
                print(f"\u2705 [{item.source_type.value}] {item.title[:60]}")
            print(f"\n\U0001f4e6 Fetched {len(items)}/{len(urls)} URLs")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\u23f9 Cancelled")
    except Exception as e:
        print(f"\u274c {e}")
        sys.exit(1)


def cmd_list():
    """Show content statistics by scanning output directories."""
    vault = os.getenv("OBSIDIAN_VAULT", "").strip()
    output_dir = os.getenv("OUTPUT_DIR", "").strip()

    if vault:
        base_dir = Path(vault)
    elif output_dir:
        base_dir = Path(output_dir)
    else:
        print("\u274c OUTPUT_DIR \u6216 OBSIDIAN_VAULT \u672a\u914d\u7f6e")
        return

    if not base_dir.exists():
        print(f"\u274c \u76ee\u5f55\u4e0d\u5b58\u5728: {base_dir}")
        return

    # Platform emoji map
    emoji_map = {
        "X": "\U0001f426", "XHS": "\U0001f4d5", "Bilibili": "\U0001f3ac",
        "WeChat": "\U0001f4ac", "YouTube": "\u25b6\ufe0f", "Telegram": "\U0001f4e2",
        "RSS": "\U0001f4f0", "Manual": "\u270f\ufe0f",
    }

    total = 0
    platform_stats = []

    # Scan each platform directory
    for platform_dir in sorted(base_dir.iterdir()):
        if not platform_dir.is_dir():
            continue

        name = platform_dir.name
        # Count .md files in this platform (non-recursive first level)
        top_level_mds = list(platform_dir.glob("*.md"))
        sub_dirs = []

        for sub in sorted(platform_dir.iterdir()):
            if sub.is_dir() and sub.name != "index":
                count = len(list(sub.glob("*.md")))
                if count > 0:
                    sub_dirs.append((sub.name, count))

        platform_total = len(top_level_mds) + sum(c for _, c in sub_dirs)
        if platform_total == 0:
            continue

        total += platform_total
        emoji = emoji_map.get(name, "\U0001f4c4")
        platform_stats.append((name, emoji, platform_total, top_level_mds, sub_dirs))

    if not platform_stats:
        print("\U0001f4e6 \u8fd8\u6ca1\u6709\u62d3\u53d6\u4efb\u4f55\u5185\u5bb9")
        return

    print(f"\U0001f4e6 feedgrab \u5185\u5bb9\u7edf\u8ba1 ({base_dir})\n")

    for name, emoji, platform_total, top_mds, sub_dirs in platform_stats:
        print(f"  {emoji} {name}: {platform_total} \u7bc7")

        if top_mds and sub_dirs:
            # Has both top-level files and subdirectories
            print(f"     (root)  {len(top_mds)} \u7bc7")
        for sub_name, count in sub_dirs:
            print(f"     {sub_name}/  {count} \u7bc7")

    print(f"\n  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    print(f"  \u603b\u8ba1: {total} \u7bc7")


def cmd_login(platform: str, headless: bool = False):
    """Open browser for manual login to a platform."""
    from feedgrab.login import login
    login(platform, headless=headless)


def cmd_reset(folder_name: str):
    """Reset a subfolder: delete .md files and remove their item_ids from dedup index."""
    vault = os.getenv("OBSIDIAN_VAULT", "").strip()
    output_dir = os.getenv("OUTPUT_DIR", "").strip()

    if vault:
        base_dir = Path(vault)
    elif output_dir:
        base_dir = Path(output_dir)
    else:
        print("\u274c OUTPUT_DIR \u6216 OBSIDIAN_VAULT \u672a\u914d\u7f6e")
        return

    # Find matching subfolder under any platform directory
    target = None
    for platform_dir in base_dir.iterdir():
        if not platform_dir.is_dir():
            continue
        candidate = platform_dir / folder_name
        if candidate.is_dir():
            target = candidate
            break

    if not target:
        print(f"\u274c \u627e\u4e0d\u5230\u76ee\u5f55: {folder_name}")
        # Show available folders
        print("\n\u53ef\u7528\u76ee\u5f55:")
        for platform_dir in sorted(base_dir.iterdir()):
            if not platform_dir.is_dir():
                continue
            for sub in sorted(platform_dir.iterdir()):
                if sub.is_dir() and sub.name != "index":
                    count = len(list(sub.glob("*.md")))
                    if count > 0:
                        print(f"  {sub.name}/  ({count} \u7bc7)")
        return

    # Scan .md files and extract item_ids from front matter
    md_files = list(target.glob("*.md"))
    if not md_files:
        print(f"\u274c {folder_name}/ \u4e2d\u6ca1\u6709 .md \u6587\u4ef6")
        return

    item_ids = []
    for md_file in md_files:
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                in_frontmatter = False
                for line in f:
                    stripped = line.strip()
                    if stripped == "---":
                        if not in_frontmatter:
                            in_frontmatter = True
                            continue
                        else:
                            break  # end of front matter
                    if in_frontmatter and stripped.startswith("item_id:"):
                        iid = stripped.split(":", 1)[1].strip()
                        if iid:
                            item_ids.append(iid)
                        break
        except OSError:
            pass

    print(f"\U0001f4c1 {folder_name}/")
    print(f"   {len(md_files)} \u4e2a .md \u6587\u4ef6")
    print(f"   {len(item_ids)} \u4e2a item_id \u5c06\u4ece\u53bb\u91cd\u7d22\u5f15\u4e2d\u79fb\u9664")
    confirm = input("\n\u786e\u8ba4\u91cd\u7f6e? (y/N) ")
    if confirm.lower() != "y":
        print("\u274f \u5df2\u53d6\u6d88")
        return

    # Remove from dedup index (platform-aware)
    from feedgrab.utils.dedup import load_index, save_index
    platform_name = target.parent.name  # "X" or "XHS"
    platform_key = platform_name if platform_name in ("X", "XHS") else "X"
    index = load_index(platform=platform_key)
    removed = 0
    for iid in item_ids:
        if iid in index:
            del index[iid]
            removed += 1
    save_index(index, platform=platform_key)

    # Delete .md files
    deleted = 0
    for md_file in md_files:
        try:
            md_file.unlink()
            deleted += 1
        except OSError:
            pass

    print(f"\n\u2705 \u91cd\u7f6e\u5b8c\u6210:")
    print(f"   \u5220\u9664 {deleted} \u4e2a .md \u6587\u4ef6")
    print(f"   移除 {removed} 个去重索引条目")
    print(f"   现在可以重新拓取了")


def cmd_clean_index(skip_confirm: bool = False):
    """Clean up batch records and cache files from index directories.

    Preserves item_id_url.json (global dedup index), removes everything else:
    - status_*.json       (UserTweets batch records)
    - api_status_*.json   (API batch records)
    - bookmarks_*.json    (Bookmarks batch records)
    - list_*.json         (List batch records)
    - .api_discovery_*.jsonl (API checkpoint caches)
    """
    from feedgrab.utils.dedup import get_index_path

    # Collect index dirs from all platforms
    platforms = ["X", "XHS"]
    cleaned_files = 0
    cleaned_bytes = 0
    index_dirs_checked = []

    for plat in platforms:
        index_dir = get_index_path(platform=plat).parent
        if not index_dir.exists():
            continue
        index_dirs_checked.append(index_dir)

        for f in index_dir.iterdir():
            if f.name == "item_id_url.json":
                continue  # preserve global dedup index
            if f.is_file():
                size = f.stat().st_size
                cleaned_files += 1
                cleaned_bytes += size

    if cleaned_files == 0:
        print("✅ 索引目录已经很干净，无需清理")
        return

    # Show summary before confirming
    print(f"🗂  扫描到 {cleaned_files} 个可清理文件 ({cleaned_bytes / 1024 / 1024:.1f} MB)")
    print(f"   保留: item_id_url.json (全局去重索引)")
    print(f"   清理: 批量记录 + 断点缓存")
    for d in index_dirs_checked:
        print(f"   目录: {d}")

    confirm = "y" if skip_confirm else input("\n确认清理? (y/N) ")
    if confirm.lower() != "y":
        print("✗ 已取消")
        return

    # Delete files
    deleted = 0
    freed = 0
    for plat in platforms:
        index_dir = get_index_path(platform=plat).parent
        if not index_dir.exists():
            continue
        for f in index_dir.iterdir():
            if f.name == "item_id_url.json":
                continue
            if f.is_file():
                size = f.stat().st_size
                try:
                    f.unlink()
                    deleted += 1
                    freed += size
                except OSError as e:
                    print(f"   ⚠ 无法删除 {f.name}: {e}")

    print(f"\n✅ 清理完成: 删除 {deleted} 个文件，释放 {freed / 1024 / 1024:.1f} MB")


def cmd_detect_ua():
    """Detect real Chrome User-Agent and save to .env file."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\u274c Playwright is not installed. Run:\n"
              '   pip install "feedgrab[browser]"\n'
              "   playwright install chromium")
        return

    print("\U0001f50d Detecting real Chrome User-Agent...")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                channel="chrome",
            )
            page = browser.new_page()
            ua = page.evaluate("navigator.userAgent")
            browser.close()
    except Exception as e:
        print(f"\u274c Failed to detect UA: {e}")
        print("   Falling back: trying without channel='chrome'...")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                ua = page.evaluate("navigator.userAgent")
                browser.close()
        except Exception as e2:
            print(f"\u274c Detection failed: {e2}")
            return

    # Headless mode reports "HeadlessChrome" — normalize to "Chrome"
    ua = ua.replace("HeadlessChrome", "Chrome")

    print(f"\n   Detected: {ua}")

    # Write to .env
    env_path = Path.cwd() / ".env"
    key_line = f"BROWSER_USER_AGENT={ua}"

    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        if "BROWSER_USER_AGENT=" in content:
            # Replace existing line
            import re
            content = re.sub(
                r"^#?\s*BROWSER_USER_AGENT=.*$",
                key_line,
                content,
                flags=re.MULTILINE,
            )
            env_path.write_text(content, encoding="utf-8")
            print(f"\n\u2705 Updated BROWSER_USER_AGENT in {env_path}")
        else:
            # Append
            with open(env_path, "a", encoding="utf-8") as f:
                f.write(f"\n# Auto-detected by: feedgrab detect-ua\n{key_line}\n")
            print(f"\n\u2705 Appended BROWSER_USER_AGENT to {env_path}")
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"# Auto-detected by: feedgrab detect-ua\n{key_line}\n")
        print(f"\n\u2705 Created {env_path} with BROWSER_USER_AGENT")

    print(f"   All browser interactions will now use this UA.")


# ---------------------------------------------------------------------------
# Setup helpers
# ---------------------------------------------------------------------------

def _set_env_value(env_path: Path, key: str, value: str):
    """Set or update a key=value in .env file."""
    content = env_path.read_text(encoding="utf-8")
    pattern = rf"^#?\s*{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"
    env_path.write_text(content, encoding="utf-8")


def _get_env_value(content: str, key: str) -> str:
    """Extract a key's value from .env content string (strips inline comments)."""
    m = re.search(rf"^{re.escape(key)}=(.*)$", content, re.MULTILINE)
    if not m:
        return ""
    val = m.group(1).strip()
    # Strip inline comments: OUTPUT_DIR=./output  # comment → ./output
    if "  #" in val:
        val = val.split("  #")[0].strip()
    return val


def _session_age_str(session_file: Path) -> str:
    """Return human-readable age of a session file."""
    age_sec = time.time() - session_file.stat().st_mtime
    if age_sec < 3600:
        return f"{int(age_sec / 60)} 分钟前"
    elif age_sec < 86400:
        return f"{int(age_sec / 3600)} 小时前"
    else:
        return f"{int(age_sec / 86400)} 天前"


# ---------------------------------------------------------------------------
# Setup steps
# ---------------------------------------------------------------------------

def _step_check_env():
    """[1/5] Check Python, feedgrab, Playwright, Chromium."""
    print("\n[1/5] 检查运行环境...")

    # Python
    print(f"  \u2705 Python {sys.version.split()[0]}")

    # feedgrab
    try:
        from importlib.metadata import version as pkg_version
        v = pkg_version("feedgrab")
        print(f"  \u2705 feedgrab {v}")
    except Exception:
        print("  \u2705 feedgrab (dev mode)")

    # Playwright
    pw_ok = False
    try:
        import playwright  # noqa: F401
        print("  \u2705 Playwright 已安装")
        pw_ok = True
    except ImportError:
        print("  \u26a0\ufe0f  Playwright 未安装")
        ans = input("     \u2192 是否自动安装？(Y/n) ").strip().lower()
        if ans in ("", "y", "yes"):
            import subprocess
            print("     \u2192 正在安装 playwright...")
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"],
                           check=True, capture_output=True)
            print("     \u2192 正在安装 Chromium 浏览器...")
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                           check=True, capture_output=True)
            print("  \u2705 Playwright + Chromium 已就绪")
            pw_ok = True
        else:
            print("  \u23ed 已跳过（浏览器功能不可用）")

    if not pw_ok:
        return

    # Check Chromium is installed
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel="chrome")
            browser.close()
        print("  \u2705 Chrome 浏览器可用")
    except Exception:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            print("  \u2705 Chromium 浏览器可用")
        except Exception:
            print("  \u26a0\ufe0f  Chromium 未安装")
            ans = input("     \u2192 是否自动安装？(Y/n) ").strip().lower()
            if ans in ("", "y", "yes"):
                import subprocess
                subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                               check=True, capture_output=True)
                print("  \u2705 Chromium 已安装")
            else:
                print("  \u23ed 已跳过")


def _step_create_dotenv():
    """[2/5] Create .env and set OUTPUT_DIR."""
    print("\n[2/5] 配置文件...")

    env_path = Path.cwd() / ".env"
    example_path = Path.cwd() / ".env.example"

    if env_path.exists():
        print("  \u2705 .env 文件已存在")
    elif example_path.exists():
        shutil.copy(example_path, env_path)
        print("  \u2705 已从 .env.example 创建 .env")
    else:
        env_path.touch()
        print("  \u2705 已创建空 .env")

    # Check OUTPUT_DIR
    content = env_path.read_text(encoding="utf-8")
    current = _get_env_value(content, "OUTPUT_DIR")
    if current and current != "./output":
        print(f"  \u2705 OUTPUT_DIR = {current}")
    else:
        default = "./output"
        ans = input(f"  请输入内容输出目录 (直接回车使用默认 {default}): ").strip()
        output_dir = ans or default
        _set_env_value(env_path, "OUTPUT_DIR", output_dir)
        print(f"  \u2705 OUTPUT_DIR = {output_dir}")


def _step_detect_ua():
    """[3/5] Detect UA — reuse cmd_detect_ua logic."""
    print("\n[3/5] 检测浏览器指纹...")

    # Reload .env to check current value
    from dotenv import load_dotenv
    load_dotenv(override=True)
    current_ua = os.getenv("BROWSER_USER_AGENT", "").strip()
    if current_ua:
        short = current_ua.split("Chrome/")[1][:10] if "Chrome/" in current_ua else current_ua[-30:]
        print(f"  \u2705 已配置: Chrome/{short}...")
        return

    # Run detection
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("  \u23ed Playwright 未安装，跳过 UA 检测")
        return

    cmd_detect_ua()


_SETUP_PLATFORMS = [
    ("xhs", "小红书", "请在弹出的浏览器窗口中扫码登录"),
    ("twitter", "Twitter/X", "请在弹出的浏览器窗口中登录"),
    ("wechat", "微信公众号", "请在弹出的浏览器窗口中登录"),
]


def _step_platform_login():
    """[4/5] Interactive platform login."""
    print("\n[4/5] 平台登录")

    from feedgrab.config import get_session_dir

    session_dir = get_session_dir()
    canonical_map = {"xhs": "xhs", "twitter": "twitter", "wechat": "wechat"}

    for key, name, desc in _SETUP_PLATFORMS:
        canonical = canonical_map[key]
        session_file = session_dir / f"{canonical}.json"

        if session_file.exists():
            age = _session_age_str(session_file)
            print(f"  \u2705 {name} session 已存在 ({age})")
            ans = input(f"     \u2192 重新登录？(y/N) ").strip().lower()
            if ans not in ("y", "yes"):
                continue
        else:
            ans = input(f"  \U0001f511 登录{name}？(Y/n) ").strip().lower()
            if ans not in ("", "y", "yes"):
                print(f"     \u23ed 已跳过")
                continue

        print(f"     \U0001f310 {desc}...")
        try:
            from feedgrab.login import login
            login(key, headless=False)
        except Exception as e:
            print(f"     \u274c 登录失败: {e}")


def _step_enable_features():
    """[5/5] Enable batch features based on available sessions."""
    print("\n[5/5] 启用批量功能")

    from feedgrab.config import get_session_dir

    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    session_dir = get_session_dir()

    # XHS batch
    xhs_session = session_dir / "xhs.json"
    if xhs_session.exists():
        content = env_path.read_text(encoding="utf-8")
        xhs_enabled = _get_env_value(content, "XHS_USER_NOTES_ENABLED")
        if xhs_enabled.lower() == "true":
            print("  \u2705 小红书批量抓取已启用")
        else:
            ans = input("  启用小红书批量抓取（作者主页 + 搜索）？(Y/n) ").strip().lower()
            if ans in ("", "y", "yes"):
                _set_env_value(env_path, "XHS_USER_NOTES_ENABLED", "true")
                _set_env_value(env_path, "XHS_SEARCH_ENABLED", "true")
                print("  \u2705 XHS_USER_NOTES_ENABLED=true")
                print("  \u2705 XHS_SEARCH_ENABLED=true")
            else:
                print("  \u23ed 已跳过")
    else:
        print("  \u23ed 小红书未登录，跳过批量功能配置")

    # Twitter batch
    twitter_session = session_dir / "twitter.json"
    if twitter_session.exists():
        content = env_path.read_text(encoding="utf-8")
        x_enabled = _get_env_value(content, "X_BOOKMARKS_ENABLED")
        if x_enabled.lower() == "true":
            print("  \u2705 Twitter 批量抓取已启用")
        else:
            ans = input("  启用 Twitter 批量抓取（书签 + 账号推文）？(Y/n) ").strip().lower()
            if ans in ("", "y", "yes"):
                _set_env_value(env_path, "X_BOOKMARKS_ENABLED", "true")
                _set_env_value(env_path, "X_USER_TWEETS_ENABLED", "true")
                print("  \u2705 X_BOOKMARKS_ENABLED=true")
                print("  \u2705 X_USER_TWEETS_ENABLED=true")
            else:
                print("  \u23ed 已跳过")
    else:
        print("  \u23ed Twitter 未登录，跳过批量功能配置")


def cmd_setup():
    """Interactive first-time deployment guide."""
    print("\n\U0001f4e6 feedgrab 首次部署引导")
    print("=" * 40)

    _step_check_env()
    _step_create_dotenv()
    _step_detect_ua()
    _step_platform_login()
    _step_enable_features()

    print("\n" + "=" * 40)
    print("\U0001f389 部署完成！\n")
    print("试试：")
    print('  feedgrab https://www.xiaohongshu.com/explore/xxx')
    print('  feedgrab "https://www.xiaohongshu.com/search_result?keyword=..."')
    print('  feedgrab list')
    print()


def cmd_mpweixin_account(account_name: str):
    """Fetch all articles from a WeChat public account via MP backend API."""
    from feedgrab.config import mpweixin_id_since, mpweixin_id_delay
    from feedgrab.fetchers.mpweixin_account import fetch_account_articles

    since = mpweixin_id_since()
    delay = mpweixin_id_delay()

    async def run():
        result = await fetch_account_articles(
            account_name, since=since, delay=delay,
        )
        print(f"\n\u2705 WeChat account fetch complete: '{account_name}'")
        print(f"   Total: {result['total']}, Fetched: {result['fetched']}, "
              f"Skipped: {result['skipped']}, Failed: {result['failed']}")
        if result['articles']:
            print("\n   Articles:")
            for art in result['articles']:
                title = art.get('title', 'untitled')[:50]
                date = art.get('publish_date', '')
                print(f"   - [{date}] {title}")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\u23f9 Cancelled")
    except SystemExit:
        raise
    except Exception as e:
        print(f"\u274c {e}")
        sys.exit(1)


def cmd_wechat_search(keyword: str, max_results: int = 0):
    """Search WeChat articles by keyword via Sogou."""
    from feedgrab.config import mpweixin_sogou_enabled, mpweixin_sogou_max_results, mpweixin_sogou_delay

    if not mpweixin_sogou_enabled():
        print("\u274c Sogou WeChat search is disabled.")
        print("   Set MPWEIXIN_SOGOU_ENABLED=true in .env to enable.")
        return

    # Use config default if not specified via --limit
    if max_results <= 0:
        max_results = mpweixin_sogou_max_results()
    delay = mpweixin_sogou_delay()

    from feedgrab.fetchers.wechat_search import search_wechat_articles

    async def run():
        result = await search_wechat_articles(
            keyword, max_results=max_results, fetch_content=True, delay=delay
        )
        print(f"\n\u2705 WeChat search complete: '{keyword}'")
        print(f"   Found: {result['total']}, Fetched: {result['fetched']}, "
              f"Skipped: {result['skipped']}, Failed: {result['failed']}")
        if result['articles']:
            print("\n   Articles:")
            for art in result['articles']:
                title = art.get('title', 'untitled')[:50]
                author = art.get('author', '')
                date = art.get('publish_date', '')
                print(f"   - [{date}] {title} ({author})")

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n\u23f9 Cancelled")
    except SystemExit:
        raise
    except Exception as e:
        print(f"\u274c {e}")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("""
\U0001f4d6 feedgrab \u2014 Universal content grabber

Usage:
    feedgrab setup              First-time deployment guide (recommended for new users)
    feedgrab <url>              Fetch content from any URL
    feedgrab <url1> <url2>      Fetch multiple URLs
    feedgrab mpweixin-id <name> Fetch all articles from a WeChat public account
    feedgrab mpweixin-so <keyword>  Search WeChat articles by keyword
    feedgrab login <platform>   Login to a platform (saves session for browser fallback)
    feedgrab detect-ua          Detect real Chrome UA and save to .env
    feedgrab list               Show content statistics
    feedgrab reset <folder>     Reset a subfolder (delete files + clear dedup index)
    feedgrab clean-index        Clean up batch records and cache files from index

Supported platforms:
    WeChat, Telegram, X/Twitter, YouTube,
    Bilibili, Xiaohongshu, RSS, and any web page

Examples:
    feedgrab https://mp.weixin.qq.com/s/abc123
    feedgrab https://x.com/elonmusk/status/123456
    feedgrab https://x.com/i/bookmarks
    feedgrab https://x.com/iBigQiang
    feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...
    feedgrab "https://www.xiaohongshu.com/search_result?keyword=..."
    feedgrab mpweixin-id "饼干哥哥AGI"
    feedgrab mpweixin-so "AI Agent"
    feedgrab login xhs
    feedgrab setup              # First-time setup wizard
""")
        return

    cmd = sys.argv[1].lower()

    if cmd == "setup":
        cmd_setup()
    elif cmd == "login":
        if len(sys.argv) < 3:
            print("\u274c Usage: feedgrab login <platform> [--headless]")
            print("   Supported: xhs, wechat, twitter")
            sys.exit(1)
        headless = "--headless" in sys.argv
        cmd_login(sys.argv[2], headless=headless)
    elif cmd == "detect-ua":
        cmd_detect_ua()
    elif cmd == "list":
        cmd_list()
    elif cmd == "reset":
        if len(sys.argv) < 3:
            print("\u274c Usage: feedgrab reset <folder>")
            print("   Example: feedgrab reset bookmarks/OpenClaw")
            print("   Example: feedgrab reset status_author/强子手记")
            sys.exit(1)
        cmd_reset(sys.argv[2])
    elif cmd == "clean-index":
        skip = "--yes" in sys.argv or "-y" in sys.argv
        cmd_clean_index(skip_confirm=skip)
    elif cmd == "mpweixin-id":
        if len(sys.argv) < 3:
            print("\u274c Usage: feedgrab mpweixin-id <account_name>")
            print('   Example: feedgrab mpweixin-id "饼干哥哥AGI"')
            print("   Requires: feedgrab login wechat (MP backend session)")
            sys.exit(1)
        cmd_mpweixin_account(sys.argv[2])
    elif cmd == "mpweixin-so":
        if len(sys.argv) < 3:
            print("\u274c Usage: feedgrab mpweixin-so <keyword> [--limit N]")
            print('   Example: feedgrab mpweixin-so "AI Agent"')
            sys.exit(1)
        keyword = sys.argv[2]
        limit = 0  # 0 means use config default
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                try:
                    limit = int(sys.argv[idx + 1])
                except ValueError:
                    pass
        cmd_wechat_search(keyword, max_results=limit)
    elif cmd.startswith("http") or cmd.startswith("www.") or "." in cmd:
        urls = [arg for arg in sys.argv[1:] if arg.startswith(("http", "www.")) or "." in arg]
        cmd_fetch(urls)
    else:
        print(f"\u274c Unknown command: {cmd}")
        print("   Run 'feedgrab' with no args for help")


if __name__ == "__main__":
    main()
