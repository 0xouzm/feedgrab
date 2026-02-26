# feedgrab

**English** | **[中文](README.md)**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Universal content grabber — fetch, transcribe, and digest content from any platform.

Give it a URL (article, video, podcast, tweet), get back structured content. Works as CLI, Python library, MCP server, or Claude Code skills.

> **Origin**: feedgrab is a fusion upgrade based on [x-reader](https://github.com/runesleo/x-reader) by [@runes_leo](https://x.com/runes_leo) and the [baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown) Claude Code skill by [@dotey](https://x.com/dotey). It inherits x-reader's multi-platform architecture and integrates baoyu's reverse-engineered X/Twitter GraphQL capabilities for deep tweet/thread fetching.

## What It Does

```
Any URL → Platform Detection → Fetch Content → Unified Output
              ↓                      ↓                ↓
         auto-detect           text: Jina Reader    → output/X/Author：Title.md
         7+ platforms          video: yt-dlp subs    → output/YouTube/Title.md
                               audio: Whisper transcription
                               API: Bilibili / RSS / Telegram
                               X/Twitter: GraphQL → oEmbed → Jina → Playwright
```

The Python layer handles text fetching and YouTube subtitle extraction. The **Claude Code skills** (optional) add full Whisper transcription for video/podcast and AI-powered content analysis.

## Three Layers

feedgrab is composable. Use the layers you need:

| Layer | What | Format | Install |
|-------|------|--------|---------|
| **Python CLI/Library** | Basic content fetching + unified schema | See [Install](#install) | Required |
| **Claude Code Skills** | Video transcription + AI analysis | Copy `skills/` to `~/.claude/skills/` | Optional |
| **MCP Server** | Expose reading as MCP tools | `python mcp_server.py` | Optional |

### Layer 1: Python CLI

```bash
# Fetch any URL
feedgrab https://mp.weixin.qq.com/s/abc123

# Fetch a tweet (with GraphQL deep fetch if cookies configured)
feedgrab https://x.com/elonmusk/status/123456

# Fetch multiple URLs
feedgrab https://url1.com https://url2.com

# Login to a platform (one-time, for browser fallback)
feedgrab login xhs

# View inbox
feedgrab list
```

### Layer 2: Claude Code Skills

> Requires cloning the repo (not included in pip install).

For video/podcast transcription and content analysis:

```
skills/
├── video/       # YouTube/Bilibili/podcast → full transcript via Whisper
└── analyzer/    # Any content → structured analysis report
```

Install:
```bash
cp -r skills/video ~/.claude/skills/video
cp -r skills/analyzer ~/.claude/skills/analyzer
```

Then in Claude Code, just send a YouTube/Bilibili/podcast link — the video skill auto-triggers and produces a full transcript + summary.

### Layer 3: MCP Server

> Requires cloning the repo (mcp_server.py is not included in pip install).

```bash
git clone https://github.com/iBigQiang/feedgrab.git
cd feedgrab
pip install -e ".[mcp]"
python mcp_server.py
```

Tools exposed:
- `read_url(url)` — fetch any URL
- `read_batch(urls)` — fetch multiple URLs concurrently
- `list_inbox()` — view previously fetched content
- `detect_platform(url)` — identify platform from URL

Claude Code config (`~/.claude/claude_desktop_config.json`):
```json
{
    "mcpServers": {
        "feedgrab": {
            "command": "python",
            "args": ["/path/to/feedgrab/mcp_server.py"]
        }
    }
}
```

## Supported Platforms

| Platform | Text Fetch | Video/Audio Transcript |
|----------|-----------|----------------------|
| YouTube | Jina | yt-dlp subtitles → Groq Whisper fallback |
| Bilibili (B站) | API | via Claude Code skill |
| X / Twitter | **GraphQL** → oEmbed → Jina → Playwright | — |
| WeChat (微信公众号) | Jina → Playwright | — |
| Xiaohongshu (小红书) | Jina → Playwright* | — |
| Telegram | Telethon | — |
| RSS | feedparser | — |
| 小宇宙 (Xiaoyuzhou) | — | via Claude Code skill |
| Apple Podcasts | — | via Claude Code skill |
| Any web page | Jina fallback | — |

> \*XHS requires a one-time login: `feedgrab login xhs` (saves session for Playwright fallback)
>
> YouTube Whisper transcription requires `GROQ_API_KEY` — get a free key from [Groq](https://console.groq.com/keys)

### X/Twitter Four-Tier Fallback

feedgrab uses an advanced four-tier strategy for X/Twitter content:

| Tier | Method | Auth Required | Capabilities |
|------|--------|--------------|-------------|
| 0 | **GraphQL API** | Cookie (`auth_token` + `ct0`) | Complete threads, images, videos, quoted tweets, articles |
| 1 | oEmbed API | None | Single tweet text (public tweets only) |
| 2 | Jina Reader | None | Profiles, non-tweet pages |
| 3 | Playwright | Optional session | Login-required content, last resort |

Tier 0 (GraphQL) is ported from the [baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown) skill, featuring:
- Dynamic `queryId` resolution from X's frontend JS bundles
- Complete thread reconstruction (author self-reply chains)
- Multi-phase pagination (upward + downward + continuation)
- Full media extraction (images, videos, quoted tweets)
- Engagement metrics (likes / retweets / replies / bookmarks / views)
- Author replies + comments collection (opt-in toggles)

### Output Format

Each fetched item is saved as an individual Markdown file, organized by platform:

```
output/
├── X/                    # Twitter/X
│   └── AuthorName：Tweet Title.md
├── XHS/                  # Xiaohongshu
├── WeChat/               # WeChat articles
├── YouTube/
├── Bilibili/
├── Telegram/
└── RSS/
```

Files use Obsidian-compatible YAML front matter:

```yaml
---
title: "OpenClaw Beginner Guide"
source: "https://x.com/AI_Jasonyu/status/123"
author:
  - "@AI_Jasonyu"
author_name: "鱼总聊AI"
published: 2026-02-25
created: 2026-02-26
cover_image: "https://pbs.twimg.com/media/xxx.jpg"
likes: 1075
retweets: 315
replies: 41
bookmarks: 2180
views: 426321
tags:
  - "clippings"
  - "twitter"
---
```

> Set `OBSIDIAN_VAULT` to write directly into your Obsidian vault under platform subdirectories.

## Install

```bash
# From GitHub (recommended)
pip install git+https://github.com/iBigQiang/feedgrab.git

# With Telegram support
pip install "feedgrab[telegram] @ git+https://github.com/iBigQiang/feedgrab.git"

# With browser fallback (Playwright — for XHS/WeChat anti-scraping)
pip install "feedgrab[browser] @ git+https://github.com/iBigQiang/feedgrab.git"
playwright install chromium

# With all optional dependencies
pip install "feedgrab[all] @ git+https://github.com/iBigQiang/feedgrab.git"
playwright install chromium
```

Or clone and install locally:
```bash
git clone https://github.com/iBigQiang/feedgrab.git
cd feedgrab
pip install -e ".[all]"
playwright install chromium
```

### Dependencies for video/audio (optional)

```bash
# macOS
brew install yt-dlp ffmpeg

# Linux
pip install yt-dlp
apt install ffmpeg
```

For Whisper transcription, get a free API key from [Groq](https://console.groq.com/keys) and set:
```bash
export GROQ_API_KEY=your_key_here
```

## Use as Library

```python
import asyncio
from feedgrab.reader import UniversalReader

async def main():
    reader = UniversalReader()
    content = await reader.read("https://mp.weixin.qq.com/s/abc123")
    print(content.title)
    print(content.content[:200])

asyncio.run(main())
```

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `X_AUTH_TOKEN` | X GraphQL only | Twitter/X auth cookie |
| `X_CT0` | X GraphQL only | Twitter/X CSRF token cookie |
| `X_GRAPHQL_ENABLED` | No | Enable/disable GraphQL tier (default: `true`) |
| `X_THREAD_MAX_PAGES` | No | Max pagination for threads (default: `20`) |
| `X_REQUEST_DELAY` | No | Delay between GraphQL requests in seconds (default: `1.5`) |
| `X_FETCH_AUTHOR_REPLIES` | No | Collect author's replies to commenters (default: `false`) |
| `X_FETCH_ALL_COMMENTS` | No | Collect all comments under tweet (default: `false`) |
| `X_MAX_COMMENTS` | No | Max comments to collect (default: `50`) |
| `TG_API_ID` | Telegram only | From https://my.telegram.org |
| `TG_API_HASH` | Telegram only | From https://my.telegram.org |
| `GROQ_API_KEY` | Whisper only | From https://console.groq.com/keys (free) |
| `GEMINI_API_KEY` | AI analysis only | From Google AI Studio |
| `FEEDGRAB_DATA_DIR` | No | Cookie/session storage directory (default: `sessions`) |
| `INBOX_FILE` | No | Path to inbox JSON (default: `./unified_inbox.json`) |
| `OUTPUT_DIR` | No | Directory for Markdown output (default: `./output`) |
| `OBSIDIAN_VAULT` | No | Path to Obsidian vault (writes to platform subdirectories) |

## Architecture

```
feedgrab/
├── feedgrab/                  # Python package
│   ├── cli.py                 # CLI entry point
│   ├── config.py              # Centralized config (paths, feature flags)
│   ├── reader.py              # URL dispatcher (UniversalReader)
│   ├── schema.py              # Unified data model (UnifiedContent + Inbox)
│   ├── login.py               # Browser login manager (saves sessions)
│   ├── fetchers/
│   │   ├── jina.py            # Jina Reader (universal fallback)
│   │   ├── browser.py         # Playwright headless (anti-scraping fallback)
│   │   ├── bilibili.py        # Bilibili API
│   │   ├── youtube.py         # yt-dlp subtitle extraction
│   │   ├── rss.py             # RSS (feedparser)
│   │   ├── telegram.py        # Telegram (Telethon)
│   │   ├── twitter.py         # X/Twitter four-tier dispatcher
│   │   ├── twitter_cookies.py # Cookie multi-source management (env/file/Playwright/CDP)
│   │   ├── twitter_graphql.py # X GraphQL API client (TweetDetail, dynamic queryId)
│   │   ├── twitter_thread.py  # Thread reconstruction + comment classification
│   │   ├── twitter_markdown.py# Thread Markdown renderer (YAML front matter + media)
│   │   ├── wechat.py          # Jina → Playwright fallback
│   │   └── xhs.py             # Jina → Playwright + session fallback
│   └── utils/
│       └── storage.py         # Per-platform Markdown + JSON dual output
├── sessions/                  # Cookie/session storage (auto-created, git-ignored)
├── skills/                    # Claude Code skills
│   ├── video/                 # Video/podcast → transcript + summary
│   └── analyzer/              # Content → structured analysis
├── mcp_server.py              # MCP server entry point
└── pyproject.toml
```

## How the Layers Work Together

```
User sends URL
    │
    ├─ Text content (article, tweet, WeChat)
    │   └─ Python fetcher → UnifiedContent → inbox
    │
    ├─ X/Twitter tweet or thread
    │   └─ GraphQL (full thread + media) → oEmbed → Jina → Playwright
    │
    ├─ Video (YouTube, Bilibili, X video)
    │   ├─ Python fetcher → metadata (title, description)
    │   └─ Video skill → full transcript via subtitles/Whisper
    │
    ├─ Podcast (小宇宙, Apple Podcasts)
    │   └─ Video skill → full transcript via Whisper
    │
    └─ Analysis requested
        └─ Analyzer skill → structured report + action items
```

## Credits

feedgrab is built upon:

- **[x-reader](https://github.com/runesleo/x-reader)** by [@runes_leo](https://x.com/runes_leo) — the original multi-platform content reader providing the core architecture, CLI, MCP server, and fetchers for 7+ platforms.
- **[baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown)** by [@dotey](https://x.com/dotey) (宝玉) — the X/Twitter deep fetching skill providing reverse-engineered GraphQL API access, thread reconstruction, and Markdown rendering.

## Author

Maintained by [@iBigQiang](https://github.com/iBigQiang)

## License

MIT
