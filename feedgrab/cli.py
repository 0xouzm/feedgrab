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
        base_dir = Path(vault) / "01-\u6536\u96c6\u7bb1"
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


def main():
    if len(sys.argv) < 2:
        print("""
\U0001f4d6 feedgrab \u2014 Universal content grabber

Usage:
    feedgrab <url>              Fetch content from any URL
    feedgrab <url1> <url2>      Fetch multiple URLs
    feedgrab login <platform>   Login to a platform (saves session for browser fallback)
    feedgrab list               Show content statistics

Supported platforms:
    WeChat, Telegram, X/Twitter, YouTube,
    Bilibili, Xiaohongshu, RSS, and any web page

Examples:
    feedgrab https://mp.weixin.qq.com/s/abc123
    feedgrab https://x.com/elonmusk/status/123456
    feedgrab https://x.com/i/bookmarks
    feedgrab https://x.com/iBigQiang
    feedgrab login xhs
""")
        return

    cmd = sys.argv[1].lower()

    if cmd == "login":
        if len(sys.argv) < 3:
            print("\u274c Usage: feedgrab login <platform> [--headless]")
            print("   Supported: xhs, wechat, twitter")
            sys.exit(1)
        headless = "--headless" in sys.argv
        cmd_login(sys.argv[2], headless=headless)
    elif cmd == "list":
        cmd_list()
    elif cmd.startswith("http") or cmd.startswith("www.") or "." in cmd:
        urls = [arg for arg in sys.argv[1:] if arg.startswith(("http", "www.")) or "." in arg]
        cmd_fetch(urls)
    else:
        print(f"\u274c Unknown command: {cmd}")
        print("   Run 'feedgrab' with no args for help")


if __name__ == "__main__":
    main()
