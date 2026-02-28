# feedgrab 项目指令

## 项目概述

feedgrab 是一个万能内容抓取器，从任意平台抓取内容并输出为 Obsidian 兼容的结构化 Markdown。

- **仓库**：https://github.com/iBigQiang/feedgrab
- **作者**：[@iBigQiang](https://github.com/iBigQiang)（强子手记）
- **当前版本**：v0.3.0
- **Python**：≥3.10
- **许可证**：MIT

### 项目来源

feedgrab 由两个项目融合升级而来：
- **[x-reader](https://github.com/runesleo/x-reader)**（@runes_leo）— 提供多平台架构、CLI、MCP 服务器
- **[baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills)**（@dotey 宝玉）— 提供逆向工程的 X/Twitter GraphQL 深度抓取能力

### 三层架构

| 层级 | 功能 | 入口 |
|------|------|------|
| Python CLI/库 | 基础内容抓取 + 统一数据结构 | `feedgrab <url>` |
| Claude Code 技能 | 视频转录 + AI 分析 | `skills/video/` `skills/analyzer/` |
| MCP 服务器 | 将抓取能力暴露为 MCP 工具 | `mcp_server.py` |

### 支持的平台

| 平台 | 抓取方式 |
|------|---------|
| X/Twitter | GraphQL → oEmbed → Jina → Playwright（四级兜底） |
| 小红书 | Jina → Playwright 深度抓取（单篇 + 作者批量 + 搜索批量） |
| YouTube | Jina + yt-dlp 字幕 |
| B站 | API |
| 微信公众号 | Jina → Playwright |
| Telegram | Telethon |
| RSS | feedparser |
| 任意网页 | Jina 兜底 |

## 语言规范

- 所有对话、文档内容一律使用**中文**
- 代码注释可以用英文
- Git commit message 使用英文前缀（feat/fix/docs/chore）+ 英文描述

## 开发工作流

完成功能开发并测试通过后，执行以下收尾流程：

1. **更新 DEVLOG.md** — 在文件顶部（第一个 `---` 分隔线之前）新增版本条目
2. **更新 README.md** — 同步新功能的使用说明、配置项、架构图等
3. **提交代码** — 使用 conventional commit 格式
4. **推送到 GitHub** — `git push origin main`

> 提示：可以使用 `/ship` 命令一键完成上述收尾流程。

## 版本号规范

- 主要新功能：递增次版本号（如 v0.2.9 → v0.3.0）
- 小功能/修复：递增补丁号（如 v0.3.0 → v0.3.1）
- 版本号记录在 DEVLOG.md 的条目标题中

## 核心架构

```
feedgrab/
├── feedgrab/                  # Python 包
│   ├── cli.py                 # CLI 入口（命令路由 + feedgrab setup 引导）
│   ├── config.py              # 集中配置（路径、开关、get_user_agent()）
│   ├── reader.py              # URL 调度器（UniversalReader — 平台检测 + 路由）
│   ├── schema.py              # 统一数据模型（UnifiedContent）
│   ├── login.py               # 浏览器登录管理器
│   ├── fetchers/
│   │   ├── jina.py            # Jina Reader（万能兜底）
│   │   ├── browser.py         # Playwright 无头浏览器 + XHS JS evaluate
│   │   ├── bilibili.py        # B站 API
│   │   ├── youtube.py         # yt-dlp 字幕提取
│   │   ├── rss.py             # RSS 解析
│   │   ├── telegram.py        # Telegram 频道
│   │   ├── twitter.py         # X/Twitter 四级兜底调度器
│   │   ├── twitter_cookies.py # Cookie 多源管理
│   │   ├── twitter_graphql.py # GraphQL API（TweetDetail/UserTweets/Bookmarks/动态queryId）
│   │   ├── twitter_thread.py  # 线程重建 + 评论分类
│   │   ├── twitter_bookmarks.py  # 书签批量抓取
│   │   ├── twitter_user_tweets.py # 用户推文批量抓取
│   │   ├── twitter_markdown.py   # Markdown 渲染器
│   │   ├── wechat.py          # Jina → Playwright
│   │   ├── xhs.py             # 小红书单篇（Jina → Playwright）
│   │   ├── xhs_user_notes.py  # 小红书作者批量（三层策略）
│   │   └── xhs_search_notes.py # 小红书搜索批量
│   └── utils/
│       ├── storage.py         # 按平台分目录 Markdown 输出 + YAML front matter
│       └── dedup.py           # 全局去重索引
├── skills/                    # Claude Code 技能
├── mcp_server.py              # MCP 服务器入口
├── DEVLOG.md                  # 开发日志（迭代方案、决策、状态）
├── README.md                  # 用户文档（中文）
├── README_EN.md               # 用户文档（英文）
├── .env.example               # 配置模板
└── pyproject.toml             # 包定义
```

## 关键设计决策

### X/Twitter 四级兜底

Tier 0 GraphQL（需Cookie）→ Tier 1 oEmbed → Tier 2 Jina → Tier 3 Playwright

### 小红书三层抓取策略

Tier 0 `__INITIAL_STATE__`（SSR数据，~40篇）→ Tier 1 XHR拦截+滚动加载 → Tier 2 逐篇深度抓取

### User-Agent 集中管理

`config.py` → `get_user_agent()`，所有浏览器交互统一 UA，避免 session 失效。`feedgrab detect-ua` 自动检测本机 Chrome UA。

### 全局去重索引

`{OUTPUT_DIR}/{Platform}/index/item_id_url.json`，跨模式统一去重（单篇/书签/用户推文/作者笔记/搜索共享）。

### 输出格式

每条内容 → 独立 `.md` 文件，按平台分目录（`X/`、`XHS/`、`YouTube/` 等），Obsidian 兼容 YAML front matter（title/source/author/published/likes/tags 等）。

## 迭代历史摘要

> 完整记录见 `DEVLOG.md`

| 版本 | 功能 |
|------|------|
| v0.3.0 | `feedgrab setup` 一键部署引导（5步交互式向导） |
| v0.2.9 | 小红书搜索批量抓取 + UA 集中管理 + `feedgrab detect-ua` |
| v0.2.8 | 小红书作者批量抓取（三层策略 + 验证码处理） |
| v0.2.7 | 小红书深度抓取（图片/互动/标签/日期） |
| v0.2.6 | Twitter 用户推文批量 + 书签文件夹 + 统一去重 + 文件名优化 |
| v0.2.5 | Twitter 书签批量抓取 |
| v0.2.4 | 标题截断 + 图片修复 + 标签提取 + 评论采集 + t.co展开 |
| v0.2.3 | Cookie 集中管理 + 评论/回帖开关 |
| v0.2.2 | 元数据断层修复 + Obsidian front matter |
| v0.2.1 | 按平台分目录保存 |
| v0.2.0 | X/Twitter GraphQL 融合升级（从 baoyu 技能移植） |
| v0.1.0 | 初始版本（继承 x-reader） |

## 关键文件速查

| 需求 | 看哪个文件 |
|------|-----------|
| 新增 CLI 命令 | `cli.py` → `main()` 路由 + `cmd_xxx()` |
| 新增环境变量 | `config.py` + `.env.example` |
| 新增平台 fetcher | `fetchers/xxx.py` + `reader.py` 路由 |
| 修改输出格式 | `utils/storage.py` |
| 修改数据模型 | `schema.py` |
| 去重逻辑 | `utils/dedup.py` |
| X/Twitter 相关 | `twitter*.py`（6个文件） |
| 小红书相关 | `xhs*.py`（3个文件）+ `browser.py` |
