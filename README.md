# feedgrab

**[English](README_en.md)** | **中文**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

万能内容抓取器 — 从任意平台抓取、转录和消化内容。

给它一个 URL（文章、视频、播客、推文），返回结构化的内容。支持 CLI 命令行、Python 库、MCP 服务器和 Claude Code 技能四种使用方式。

> **项目来源**：feedgrab 是在 [@runes_leo](https://x.com/runes_leo) 的 [x-reader](https://github.com/runesleo/x-reader) 和 [@dotey](https://x.com/dotey)（宝玉）的 [baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown) Claude Code 技能基础上融合升级而来。继承了 x-reader 的多平台架构，融合了宝玉 skill 逆向工程的 X/Twitter GraphQL 深度抓取能力。

## 它能做什么

```
任意 URL → 平台检测 → 抓取内容 → 统一输出
              ↓                ↓
         自动识别          文本：Jina Reader
         7+ 平台           视频：yt-dlp 字幕
                           音频：Whisper 转录
                           API：Bilibili / RSS / Telegram
                           X/Twitter：GraphQL → oEmbed → Jina → Playwright
```

Python 层负责文本抓取和 YouTube 字幕提取。**Claude Code 技能**（可选）提供完整的 Whisper 视频/播客转录和 AI 内容分析功能。

## 三个层级

feedgrab 可自由组合，按需使用：

| 层级 | 功能 | 格式 | 安装方式 |
|------|------|------|----------|
| **Python CLI/库** | 基础内容抓取 + 统一数据结构 | 见 [安装](#安装) | 必需 |
| **Claude Code 技能** | 视频转录 + AI 分析 | 复制 `skills/` 到 `~/.claude/skills/` | 可选 |
| **MCP 服务器** | 将阅读能力暴露为 MCP 工具 | `python mcp_server.py` | 可选 |

### 第一层：Python CLI

```bash
# 抓取任意 URL
feedgrab https://mp.weixin.qq.com/s/abc123

# 抓取推文（配置好 Cookie 后自动走 GraphQL 深度抓取）
feedgrab https://x.com/elonmusk/status/123456

# 批量抓取多个 URL
feedgrab https://url1.com https://url2.com

# 登录某个平台（一次性操作，用于浏览器兜底）
feedgrab login xhs

# 查看收件箱
feedgrab list
```

### 第二层：Claude Code 技能

> 需要克隆仓库（pip install 不包含此部分）。

用于视频/播客转录和内容分析：

```
skills/
├── video/       # YouTube/B站/播客 → 通过 Whisper 生成完整转录
└── analyzer/    # 任意内容 → 结构化分析报告
```

安装：
```bash
cp -r skills/video ~/.claude/skills/video
cp -r skills/analyzer ~/.claude/skills/analyzer
```

安装后，在 Claude Code 中直接发送 YouTube/B站/播客链接，video 技能会自动触发并生成完整的转录 + 摘要。

### 第三层：MCP 服务器

> 需要克隆仓库（mcp_server.py 不包含在 pip install 中）。

```bash
git clone https://github.com/iBigQiang/feedgrab.git
cd feedgrab
pip install -e ".[mcp]"
python mcp_server.py
```

暴露的工具：
- `read_url(url)` — 抓取任意 URL
- `read_batch(urls)` — 批量并发抓取多个 URL
- `list_inbox()` — 查看已抓取的内容
- `detect_platform(url)` — 从 URL 识别平台

Claude Code 配置（`~/.claude/claude_desktop_config.json`）：
```json
{
    "mcpServers": {
        "feedgrab": {
            "command": "python",
            "args": ["/你的路径/feedgrab/mcp_server.py"]
        }
    }
}
```

## 支持的平台

| 平台 | 文本抓取 | 视频/音频转录 |
|------|---------|-------------|
| YouTube | Jina | yt-dlp 字幕 → Groq Whisper 兜底 |
| B 站 (Bilibili) | API | 通过 Claude Code 技能 |
| X / Twitter | **GraphQL** → oEmbed → Jina → Playwright | — |
| 微信公众号 | Jina → Playwright | — |
| 小红书 | Jina → Playwright* | — |
| Telegram | Telethon | — |
| RSS | feedparser | — |
| 小宇宙播客 | — | 通过 Claude Code 技能 |
| Apple Podcasts | — | 通过 Claude Code 技能 |
| 任意网页 | Jina 兜底 | — |

> \*小红书需要一次性登录：`feedgrab login xhs`（保存 session 供 Playwright 兜底使用）
>
> YouTube Whisper 转录需要 `GROQ_API_KEY` — 从 [Groq](https://console.groq.com/keys) 免费获取

### X/Twitter 四级兜底策略

feedgrab 对 X/Twitter 内容采用先进的四级兜底策略：

| 层级 | 方式 | 是否需要认证 | 能力 |
|------|------|-------------|------|
| 0 | **GraphQL API** | 需要 Cookie（`auth_token` + `ct0`） | 完整线程、图片、视频、引用推文、长文章 |
| 1 | oEmbed API | 不需要 | 单条推文文本（仅公开推文） |
| 2 | Jina Reader | 不需要 | 个人主页、非推文页面 |
| 3 | Playwright | 可选 session | 需要登录的内容，最后兜底 |

Tier 0（GraphQL）移植自 [baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown) 技能，特性包括：
- 动态 `queryId` 解析（从 X 前端 JS bundle 中提取）
- 完整线程重建（作者自回复链）
- 多阶段分页（向上 + 向下 + 续页）
- 完整媒体提取（图片、视频、引用推文）
- Markdown 渲染（含 YAML front matter）

## 安装

```bash
# 从 GitHub 安装（推荐）
pip install git+https://github.com/iBigQiang/feedgrab.git

# 带 Telegram 支持
pip install "feedgrab[telegram] @ git+https://github.com/iBigQiang/feedgrab.git"

# 带浏览器兜底（Playwright — 用于小红书/微信反爬）
pip install "feedgrab[browser] @ git+https://github.com/iBigQiang/feedgrab.git"
playwright install chromium

# 安装所有可选依赖
pip install "feedgrab[all] @ git+https://github.com/iBigQiang/feedgrab.git"
playwright install chromium
```

或克隆后本地安装：
```bash
git clone https://github.com/iBigQiang/feedgrab.git
cd feedgrab
pip install -e ".[all]"
playwright install chromium
```

### 视频/音频依赖（可选）

```bash
# macOS
brew install yt-dlp ffmpeg

# Linux
pip install yt-dlp
apt install ffmpeg
```

Whisper 转录需要从 [Groq](https://console.groq.com/keys) 免费获取 API 密钥并设置：
```bash
export GROQ_API_KEY=your_key_here
```

## 作为库使用

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

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

| 变量 | 必需 | 说明 |
|------|------|------|
| `X_AUTH_TOKEN` | 仅 X GraphQL | Twitter/X 认证 Cookie |
| `X_CT0` | 仅 X GraphQL | Twitter/X CSRF 令牌 Cookie |
| `X_GRAPHQL_ENABLED` | 否 | 启用/禁用 GraphQL 层（默认：`true`） |
| `X_THREAD_MAX_PAGES` | 否 | 线程最大分页数（默认：`20`） |
| `X_REQUEST_DELAY` | 否 | GraphQL 请求间隔秒数（默认：`1.5`） |
| `TG_API_ID` | 仅 Telegram | 从 https://my.telegram.org 获取 |
| `TG_API_HASH` | 仅 Telegram | 从 https://my.telegram.org 获取 |
| `GROQ_API_KEY` | 仅 Whisper | 从 https://console.groq.com/keys 免费获取 |
| `GEMINI_API_KEY` | 仅 AI 分析 | 从 Google AI Studio 获取 |
| `INBOX_FILE` | 否 | 收件箱 JSON 路径（默认：`./unified_inbox.json`） |
| `OUTPUT_DIR` | 否 | Markdown 输出目录（默认：`./output`） |
| `OBSIDIAN_VAULT` | 否 | Obsidian 笔记库路径（写入 `01-收集箱/feedgrab-inbox.md`） |

## 架构

```
feedgrab/
├── feedgrab/                  # Python 包
│   ├── cli.py                 # CLI 入口
│   ├── reader.py              # URL 调度器（UniversalReader）
│   ├── schema.py              # 统一数据模型（UnifiedContent + Inbox）
│   ├── login.py               # 浏览器登录管理器（保存 session）
│   ├── fetchers/
│   │   ├── jina.py            # Jina Reader（万能兜底）
│   │   ├── browser.py         # Playwright 无头浏览器（反爬兜底）
│   │   ├── bilibili.py        # B 站 API
│   │   ├── youtube.py         # yt-dlp 字幕提取
│   │   ├── rss.py             # RSS 解析（feedparser）
│   │   ├── telegram.py        # Telegram 频道（Telethon）
│   │   ├── twitter.py         # X/Twitter 四级兜底调度器
│   │   ├── twitter_cookies.py # Cookie 多源管理（环境变量/文件/Playwright/CDP）
│   │   ├── twitter_graphql.py # X GraphQL API 客户端（TweetDetail, 动态 queryId）
│   │   ├── twitter_thread.py  # 线程重建（分页 + 去重 + 根推文追溯）
│   │   ├── twitter_markdown.py# 线程 Markdown 渲染器（YAML front matter + 媒体）
│   │   ├── wechat.py          # Jina → Playwright 兜底
│   │   └── xhs.py             # Jina → Playwright + Session 兜底
│   └── utils/
│       └── storage.py         # JSON + Markdown 双重输出
├── skills/                    # Claude Code 技能
│   ├── video/                 # 视频/播客 → 转录 + 摘要
│   └── analyzer/              # 内容 → 结构化分析
├── mcp_server.py              # MCP 服务器入口
└── pyproject.toml
```

## 各层级协作方式

```
用户发送 URL
    │
    ├─ 文本内容（文章、推文、微信）
    │   └─ Python 抓取器 → UnifiedContent → 收件箱
    │
    ├─ X/Twitter 推文或线程
    │   └─ GraphQL（完整线程 + 媒体）→ oEmbed → Jina → Playwright
    │
    ├─ 视频（YouTube、B站、X 视频）
    │   ├─ Python 抓取器 → 元数据（标题、描述）
    │   └─ Video 技能 → 通过字幕/Whisper 生成完整转录
    │
    ├─ 播客（小宇宙、Apple Podcasts）
    │   └─ Video 技能 → 通过 Whisper 生成完整转录
    │
    └─ 需要分析
        └─ Analyzer 技能 → 结构化报告 + 行动建议
```

## 致谢

feedgrab 基于以下项目融合升级而来：

- **[x-reader](https://github.com/runesleo/x-reader)** — 由 [@runes_leo](https://x.com/runes_leo) 开发的多平台万能内容阅读器，提供了核心架构、CLI、MCP 服务器和 7+ 平台的抓取器。
- **[baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown)** — 由 [@dotey](https://x.com/dotey)（宝玉）开发的 X/Twitter 深度抓取技能，提供了逆向工程的 GraphQL API 访问、线程重建和 Markdown 渲染能力。

## 作者

由 [@iBigQiang](https://github.com/iBigQiang) 维护

## 许可证

MIT
