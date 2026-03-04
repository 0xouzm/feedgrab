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
              ↓                ↓          ↓
         自动识别          文本：Jina Reader    → output/X/作者_日期：标题.md
         7+ 平台           视频：yt-dlp 字幕    → output/YouTube/标题.md
                           音频：Whisper 转录
                           API：Bilibili / RSS / Telegram
                           X/Twitter：GraphQL → Syndication → oEmbed → Jina → Playwright
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

# 批量抓取书签（需要 X_BOOKMARKS_ENABLED=true）
feedgrab https://x.com/i/bookmarks
feedgrab https://x.com/i/bookmarks/2015311287715340624  # 指定书签文件夹

# 批量抓取用户推文（需要 X_USER_TWEETS_ENABLED=true）
feedgrab https://x.com/iBigQiang                        # 抓取全部推文
X_USER_TWEETS_SINCE=2026-02-01 feedgrab https://x.com/iBigQiang  # 指定日期之后
# ↑ 超过 ~800 条时自动启动浏览器搜索补充（需 feedgrab login twitter）

# 批量抓取小红书作者笔记（需要 XHS_USER_NOTES_ENABLED=true + feedgrab login xhs）
feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...
XHS_USER_NOTES_SINCE=2026-02-01 feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...  # 指定日期之后

# 批量抓取小红书搜索结果（需要 XHS_SEARCH_ENABLED=true + feedgrab login xhs）
feedgrab "https://www.xiaohongshu.com/search_result?keyword=开学第一课&source=web_explore_feed"

# 批量抓取多个 URL
feedgrab https://url1.com https://url2.com

# 登录某个平台（一次性操作，用于浏览器兜底）
feedgrab login xhs

# 自动检测本机 Chrome UA 并写入 .env（推荐首次部署时运行）
feedgrab detect-ua

# 查看内容统计
feedgrab list

# 重置子目录（删除 .md 文件 + 清理去重索引，方便重新抓取）
feedgrab reset bookmarks_OpenClaw     # 重置书签文件夹
feedgrab reset status_强子手记         # 重置账号推文目录
feedgrab reset bookmarks_Polymarket   # 重置指定书签文件夹
```

> `feedgrab reset` 会扫描目标目录下所有 `.md` 文件的 YAML front matter，提取 `item_id` 并从去重索引中移除，然后删除文件。执行前会显示待删除数量并要求确认。找不到目录时会自动列出所有可用的子目录。

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
| X / Twitter | **GraphQL** → **Syndication** → oEmbed → Jina → Playwright | — |
| 微信公众号 | Jina → Playwright | — |
| 小红书 | Jina → **Playwright 深度抓取** (单篇 + **作者批量** + **搜索批量**) | — |
| Telegram | Telethon | — |
| RSS | feedparser | — |
| 小宇宙播客 | — | 通过 Claude Code 技能 |
| Apple Podcasts | — | 通过 Claude Code 技能 |
| 任意网页 | Jina 兜底 | — |

> \*小红书需要一次性登录：`feedgrab login xhs`。支持单篇抓取（图片、互动数据、标签、日期等完整元数据）、**作者主页批量抓取**和**搜索结果批量抓取**（均采用 Tier 0 首页提取 + Tier 1 滚动加载 + Tier 2 逐篇深度抓取策略）
>
> YouTube Whisper 转录需要 `GROQ_API_KEY` — 从 [Groq](https://console.groq.com/keys) 免费获取

### X/Twitter 五级兜底策略

feedgrab 对 X/Twitter 内容采用先进的五级兜底策略：

| 层级 | 方式 | 是否需要认证 | 能力 |
|------|------|-------------|------|
| 0 | **GraphQL API** | 需要 Cookie（`auth_token` + `ct0`） | 完整线程、图片、视频、引用推文、长文章 |
| 0.5 | **Syndication API** | 不需要 | 文本、图片、视频、互动数据（likes/replies）、article 检测 |
| 1 | oEmbed API | 不需要 | 单条推文文本（仅公开推文） |
| 2 | Jina Reader | 不需要 | 个人主页、非推文页面 |
| 3 | Playwright | 可选 session | 需要登录的内容，最后兜底 |

> **Syndication API 的价值**：有 Cookie 时 GraphQL 自动切换，正常使用基本不会降级到 Syndication。Syndication 的价值在于：当 Cookie 全部过期/失效时，用户不需要立刻重新登录，仍能拿到 80% 的数据（缺 retweets/bookmarks/views 三项），而不是降级到只有纯文本的 oEmbed。

Tier 0（GraphQL）移植自 [baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills/tree/main/skills/baoyu-danger-x-to-markdown) 技能，特性包括：
- 动态 `queryId` 解析（从 X 前端 JS bundle 中提取）
- 完整线程重建（作者自回复链）
- 多阶段分页（向上 + 向下 + 续页）
- 完整媒体提取（图片、视频、引用推文）
- 互动数据（likes / retweets / replies / bookmarks / views）
- 作者回帖 + 评论区采集（可选开关）
- **书签批量抓取**（全部书签 / 指定文件夹）
- **用户推文批量抓取**（全部 / 按日期过滤，自动跳过 RT + 会话去重）
- **浏览器搜索补充**（突破 UserTweets ~800 条限制，自动按月分片搜索补充历史推文）
- **全局去重索引**（跨模式统一去重）

### X/Twitter Cookie 配置

Tier 0（GraphQL）需要 Twitter Cookie 才能获取完整数据。**未配置 Cookie 时会自动降级**，但将导致：
- 无法获取 likes / views / bookmarks 等互动指标
- 无法获取作者回帖和评论
- 无法使用书签批量抓取和账号批量抓取
- 仅能获取基础正文内容（oEmbed + Jina 兜底）

**配置方法（任选其一）：**

#### 方式 1：浏览器登录（推荐）

```bash
feedgrab login twitter
```

自动打开浏览器，登录 X 账号后 Cookie 会保存到 `sessions/twitter.json`，后续自动读取。

#### 方式 2：`.env` 环境变量

从浏览器 DevTools 手动复制 Cookie 值：

1. 打开 https://x.com 并登录
2. 按 F12 打开开发者工具 → Application → Cookies → `https://x.com`
3. 找到 `auth_token` 和 `ct0` 两个值
4. 写入 `.env` 文件：

```env
X_AUTH_TOKEN=你的auth_token值
X_CT0=你的ct0值
```

> 环境变量优先级最高，设置后会覆盖其他来源的 Cookie。

#### 方式 3：手动创建 Cookie 文件

创建 `sessions/x.json`（路径受 `FEEDGRAB_DATA_DIR` 控制，默认 `sessions/`）：

```json
{
  "auth_token": "你的auth_token值",
  "ct0": "你的ct0值"
}
```

> 还支持方式 4：Chrome CDP 自动提取（需启动 Chrome `--remote-debugging-port=9222`），适合高级用户。

**Cookie 优先级**：环境变量 > Playwright session (`twitter.json`) > Cookie 文件 (`x.json`) > Chrome CDP

#### 多账号 Cookie 轮换（防 429 限流）

批量抓取时 GraphQL 容易触发 429 限流。配置多个 X 账号的 Cookie 可自动轮换：

```
sessions/
├── twitter.json    ← 主账号（feedgrab login twitter 自动生成）
├── x_2.json        ← 第二个账号（手动创建）
├── x_3.json        ← 第三个账号...
```

额外账号的 Cookie 文件格式同方式 3。获取方法：

1. 用 Chrome/Edge 打开 https://x.com 并登录目标账号
2. 按 F12 → **Application** 标签 → 左侧展开 **Cookies** → 点击 `https://x.com`
3. 找到 `auth_token` 和 `ct0` 两行，复制值填入 `sessions/x_2.json`

> Cookie 不绑定 IP/设备，可跨电脑使用。只要不在浏览器上退出登录，Cookie 就一直有效。
>
> 429 时自动切换到下一个未限流账号，15 分钟冷却后自动恢复。

### TwitterAPI.io 付费 API（可选）

替代浏览器搜索补充的服务器友好方案，无推文数量限制，$0.15/千条。

**使用场景**：
- 推文超过 800 条时自动替代 Playwright 浏览器搜索（配置 API Key 即可）
- 服务器部署：`X_API_PROVIDER=api` 全量走付费 API，无需 Cookie 和浏览器

```env
# .env 配置
TWITTERAPI_IO_KEY=your_api_key       # 从 https://twitterapi.io 获取
# X_API_PROVIDER=graphql             # graphql(默认) | api(全量付费API)
# X_API_SAVE_DIRECTLY=false          # true=直接保存(快,无图片) | false=GraphQL补全(推荐)
# X_API_MIN_LIKES=                   # 最低点赞数（留空=不过滤，三项为 OR 关系）
# X_API_MIN_RETWEETS=                # 最低转发数
# X_API_MIN_VIEWS=                   # 最低阅读量
```

**智能直保模式** (`X_API_SAVE_DIRECTLY=true`)：普通推文用 API 数据直接保存（快速），长文(article)和线程(thread)仍走 GraphQL 获取完整媒体。

**断点续传**：发现阶段实时写入缓存文件，中断后重新运行从断点继续，不重复消耗 API 额度。

### 输出格式

每条内容保存为独立的 Markdown 文件，按平台分目录存放：

```
output/
├── X/                    # Twitter/X
│   ├── index/            #   去重索引 + 批量抓取记录
│   ├── status/           #   单篇推文
│   ├── status_xxx/       #   用户推文（按 display_name）
│   ├── bookmarks/        #   全部书签
│   └── bookmarks_xxx/    #   书签文件夹（按名称）
├── XHS/                  # 小红书
│   ├── index/            #   去重索引 + 批量抓取记录
│   ├── notes_xxx/        #   作者笔记（按作者名分目录）
│   └── search_xxx/       #   搜索笔记（按关键词分目录）
├── WeChat/               # 微信公众号
├── YouTube/              # YouTube
├── Bilibili/             # B 站
├── Telegram/             # Telegram
└── RSS/                  # RSS
```

文件命名格式（Twitter）：`作者名_YYYY-MM-DD：标题.md`（如 `强子手记_2026-02-24：最近看到好多新蓝V都成功✅认证了创作者身份。.md`）

文件命名格式（小红书）：`作者名_YYYY-MM-DD：标题.md`（如 `墨客老师资料库_2026-02-18：开学第一课还没思路的班主任看过来👀.md`）

文件使用 Obsidian 兼容的 YAML front matter：

**Twitter 示例：**

```yaml
---
title: "OpenClaw新手完整学习路径"
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

**小红书示例：**

```yaml
---
title: "开学第一课还没思路的班主任看过来👀"
source: "https://www.xiaohongshu.com/explore/69948f62..."
author:
  - "墨客老师资料库"
author_url: "https://www.xiaohongshu.com/user/profile/5eb416f..."
published: 2026-02-18
created: 2026-02-27
cover_image: "https://sns-webpic-qc.xhscdn.com/..."
likes: 179
collects: 242
comments: 28
location: "福建"
tags:
  - "开学第一课ppt"
  - "开学第一课"
  - "教师开学第一课"
item_id: db22cbe3d9c0
---
```

> 设置 `OBSIDIAN_VAULT` 后，内容会直接写入 Obsidian 笔记库对应的平台子目录。

## 安装

```bash
# 从 GitHub 安装（推荐）
pip install git+https://github.com/iBigQiang/feedgrab.git

# 带浏览器兜底（Playwright — 用于小红书/微信反爬）
pip install "feedgrab[browser] @ git+https://github.com/iBigQiang/feedgrab.git"

# 安装所有可选依赖
pip install "feedgrab[all] @ git+https://github.com/iBigQiang/feedgrab.git"
```

### 快速开始

安装完成后，运行一键部署引导：

```bash
feedgrab setup
```

按提示完成 5 个步骤：环境检查 → 配置文件 → UA 检测 → 平台登录 → 功能启用，即可开始使用。每步可跳过，重复运行自动跳过已完成项。
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
| `X_FETCH_AUTHOR_REPLIES` | 否 | 采集作者回帖（默认：`false`） |
| `X_FETCH_ALL_COMMENTS` | 否 | 采集全部评论（默认：`false`） |
| `X_MAX_COMMENTS` | 否 | 最大评论采集数（默认：`50`） |
| `X_BOOKMARKS_ENABLED` | 否 | 启用书签批量抓取（默认：`false`） |
| `X_BOOKMARK_MAX_PAGES` | 否 | 书签最大分页数（默认：`50`） |
| `X_BOOKMARK_DELAY` | 否 | 书签处理间隔秒数（默认：`2.0`） |
| `X_USER_TWEETS_ENABLED` | 否 | 启用用户推文批量抓取（默认：`false`） |
| `X_USER_TWEET_MAX_PAGES` | 否 | 用户推文最大分页数（默认：`50`） |
| `X_USER_TWEET_DELAY` | 否 | 用户推文处理间隔秒数（默认：`2.0`） |
| `X_USER_TWEETS_SINCE` | 否 | 仅抓取该日期之后的推文（如 `2025-10-01`，留空=全部） |
| `X_SEARCH_SUPPLEMENTARY` | 否 | 搜索补充开关，UserTweets 不够时自动按月搜索补充（默认：`true`） |
| `X_SEARCH_MAX_PAGES_PER_CHUNK` | 否 | 每个月度搜索分片最大分页数（默认：`50`） |
| `TWITTERAPI_IO_KEY` | 否 | TwitterAPI.io 付费 API Key，从 https://twitterapi.io 获取 |
| `X_API_PROVIDER` | 否 | `graphql`（默认）或 `api`（全量走付费 API） |
| `X_API_SAVE_DIRECTLY` | 否 | `true`=直接保存 API 数据 / `false`=GraphQL 补全（默认） |
| `X_API_MIN_LIKES` | 否 | 最低点赞数过滤（留空=不过滤，三项 OR 关系） |
| `X_API_MIN_RETWEETS` | 否 | 最低转发数过滤（留空=不过滤） |
| `X_API_MIN_VIEWS` | 否 | 最低阅读量过滤（留空=不过滤） |
| `FORCE_REFETCH` | 否 | 强制重新抓取，跳过去重并覆盖已有文件（默认：`false`） |
| `XHS_USER_NOTES_ENABLED` | 否 | 启用小红书作者批量抓取（默认：`false`） |
| `XHS_USER_NOTE_MAX_SCROLLS` | 否 | 作者主页最大滚动次数（默认：`50`） |
| `XHS_USER_NOTE_DELAY` | 否 | 笔记处理间隔秒数（默认：`3.0`） |
| `XHS_USER_NOTES_SINCE` | 否 | 仅抓取该日期之后的笔记（如 `2026-02-01`，留空=全部） |
| `XHS_SEARCH_ENABLED` | 否 | 启用小红书搜索批量抓取（默认：`false`） |
| `XHS_SEARCH_MAX_SCROLLS` | 否 | 搜索页最大滚动次数（默认：`30`） |
| `XHS_SEARCH_DELAY` | 否 | 搜索笔记处理间隔秒数（默认：`3.0`） |
| `BROWSER_USER_AGENT` | 否 | 全局浏览器 UA（推荐 `feedgrab detect-ua` 自动检测） |
| `TG_API_ID` | 仅 Telegram | 从 https://my.telegram.org 获取 |
| `TG_API_HASH` | 仅 Telegram | 从 https://my.telegram.org 获取 |
| `GROQ_API_KEY` | 仅 Whisper | 从 https://console.groq.com/keys 免费获取 |
| `GEMINI_API_KEY` | 仅 AI 分析 | 从 Google AI Studio 获取 |
| `FEEDGRAB_DATA_DIR` | 否 | Cookie/Session 存储目录（默认：`sessions`） |
| `OUTPUT_DIR` | 否 | Markdown 输出目录（默认：`./output`） |
| `OBSIDIAN_VAULT` | 否 | Obsidian 笔记库路径（内容写入对应平台子目录） |

## 架构

```
feedgrab/
├── feedgrab/                  # Python 包
│   ├── cli.py                 # CLI 入口
│   ├── config.py              # 集中配置（路径、开关）
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
│   │   ├── twitter.py         # X/Twitter 五级兜底调度器
│   │   ├── twitter_cookies.py # Cookie 多源管理（环境变量/文件/Playwright/CDP）
│   │   ├── twitter_graphql.py # X GraphQL API 客户端（TweetDetail, UserTweets, Bookmarks, SearchTimeline, 动态 queryId）
│   │   ├── twitter_thread.py  # 线程重建 + 评论分类（分页 + 去重 + 根推文追溯）
│   │   ├── twitter_bookmarks.py# 书签批量抓取（全部/文件夹，分页+去重+分类）
│   │   ├── twitter_user_tweets.py# 用户推文批量抓取（分页+日期过滤+会话去重+RT跳过）
│   │   ├── twitter_search_tweets.py# 浏览器搜索补充（突破 UserTweets 800 条限制，按月分片+响应拦截）
│   │   ├── twitter_api.py       # TwitterAPI.io 付费 API 客户端（搜索+用户推文）
│   │   ├── twitter_api_user_tweets.py# 付费 API 补充/全量抓取（替代浏览器搜索）
│   │   ├── twitter_markdown.py# 线程 Markdown 渲染器（YAML front matter + 媒体）
│   │   ├── wechat.py          # Jina → Playwright 兜底
│   │   ├── xhs.py             # Jina → Playwright + Session 兜底
│   │   ├── xhs_user_notes.py  # 小红书作者批量抓取（__INITIAL_STATE__ + XHR 拦截 + 滚动加载）
│   │   └── xhs_search_notes.py# 小红书搜索批量抓取（搜索结果页滚动 + 逐篇深度抓取）
│   └── utils/
│       ├── storage.py         # 按平台分目录 Markdown + JSON 双重输出
│       └── dedup.py           # 全局去重索引（跨模式统一 item_id 追踪）
├── sessions/                  # Cookie/Session 存储（自动创建，git 忽略）
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
    │   └─ Python 抓取器 → UnifiedContent → Markdown
    │
    ├─ X/Twitter 推文或线程
    │   └─ GraphQL（完整线程 + 媒体）→ Syndication → oEmbed → Jina → Playwright
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
