# feedgrab 项目指令

## 项目概述

feedgrab 是一个万能内容抓取器，从任意平台抓取内容并输出为 Obsidian 兼容的结构化 Markdown。

- **仓库**：https://github.com/iBigQiang/feedgrab
- **作者**：[@iBigQiang](https://github.com/iBigQiang)（强子手记）
- **当前版本**：v0.8.0
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
| X/Twitter | GraphQL → FxTwitter → Syndication → oEmbed → Jina → Playwright（六级兜底） |
| 小红书 | Jina → Playwright 深度抓取（单篇 + 作者批量 + 搜索批量） |
| YouTube | Jina + yt-dlp 字幕 |
| B站 | API |
| 微信公众号 | Jina → Playwright（单篇）/ 搜狗搜索 → Playwright 跳转 → 全文抓取（关键词搜索） |
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
│   │   ├── twitter.py         # X/Twitter 六级兜底调度器
│   │   ├── twitter_cookies.py # Cookie 多源管理 + 多账号轮换（429 自动切换）
│   │   ├── twitter_fxtwitter.py # FxTwitter API 客户端（Tier 0.3 兜底 + circuit breaker）
│   │   ├── twitter_graphql.py # GraphQL API（TweetDetail/UserTweets/Bookmarks/SearchTimeline/动态queryId）
│   │   ├── twitter_thread.py  # 线程重建 + 评论分类
│   │   ├── twitter_bookmarks.py  # 书签批量抓取
│   │   ├── twitter_user_tweets.py # 用户推文批量抓取
│   │   ├── twitter_list_tweets.py # List 列表批量抓取（按天数过滤+会话去重）
│   │   ├── twitter_search_tweets.py # 浏览器搜索补充抓取（突破 UserTweets 800 条限制）
│   │   ├── twitter_api.py     # TwitterAPI.io 付费 API 客户端
│   │   ├── twitter_api_user_tweets.py # 付费 API 批量抓取（max_id 分页+断点续传+智能直保）
│   │   ├── twitter_markdown.py   # Markdown 渲染器
│   │   ├── wechat.py          # Jina → Playwright
│   │   ├── wechat_search.py   # 搜狗微信搜索（关键词 → 文章发现 + 抓取）
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

### X/Twitter 六级兜底

Tier 0 GraphQL（需Cookie）→ Tier 0.3 FxTwitter（免费无认证，第三方公共API）→ Tier 0.5 Syndication（免费无认证）→ Tier 1 oEmbed → Tier 2 Jina → Tier 3 Playwright

FxTwitter 数据完整度接近 GraphQL（有 views/bookmarks/Article Draft.js），缺少 blue_verified/listed_count/线程展开。批量模式连续 3 次失败触发 circuit breaker 临时跳过。

Article 长文在 Tier 0 命中后优先用 GraphQL `content_state` 原生渲染，仅当渲染结果不足 200 字时回退 Jina。

### 小红书三层抓取策略

Tier 0 `__INITIAL_STATE__`（SSR数据，~40篇）→ Tier 1 XHR拦截+滚动加载 → Tier 2 逐篇深度抓取

### User-Agent 集中管理

`config.py` → `get_user_agent()`，所有浏览器交互统一 UA，避免 session 失效。`feedgrab detect-ua` 自动检测本机 Chrome UA。

### 全局去重索引

`{OUTPUT_DIR}/{Platform}/index/item_id_url.json`，跨模式统一去重（单篇/书签/用户推文/搜索补充/作者笔记/搜索共享）。

### 浏览器搜索补充抓取

UserTweets API 受服务端限制（~800条），通过 Playwright 浏览器按月分片搜索补充历史推文。使用 `page.on("response")` 在 Python 层面拦截 SearchTimeline GraphQL 响应，跨导航持久有效。两阶段共享去重索引。

### TwitterAPI.io 付费 API

替代浏览器搜索补充的服务器友好方案（$0.15/千条）。配置 `TWITTERAPI_IO_KEY` 后超过 800 条时自动走 API 替代浏览器搜索。`X_API_PROVIDER=api` 可全量走付费 API（无需 Cookie）。使用 max_id 分页（Snowflake ID 递增），断点续传（JSONL 缓存），智能直保（普通推文直接保存，长文/线程走 GraphQL）。注意：TwitterAPI.io 的 `since:`/`until:`/直接 `max_id` 跳转操作符均不可靠，日期过滤在代码层完成。

### Cookie 多账号轮换

`sessions/` 目录支持多个 Cookie 文件（`twitter.json` + `x_2.json` + `x_3.json`...），GraphQL 429 时自动切换到未限流账号，15 分钟冷却后恢复。

### 输出格式

每条内容 → 独立 `.md` 文件，按平台分目录（`X/`、`XHS/`、`YouTube/` 等），Obsidian 兼容 YAML front matter（title/source/author/published/likes/tags 等）。

### Markdown 输出过滤（`utils/storage.py` → `_format_markdown`）

`_format_markdown()` 在最终输出 Markdown 前统一过滤已知的垃圾内容，所有平台生效：
- **Twitter emoji SVG 图片**：`![...](https://abs-0.twimg.com/emoji/...)` → 移除（Obsidian 中显示尺寸过大）
- 如需新增过滤规则，在 `_format_markdown()` 的 `return result` 前添加 `re.sub()` 即可

### Article 误判防护（`fetchers/twitter.py` → `_try_fetch_article_body`）

判定推文是否为 Article stub 的逻辑：去掉所有 `t.co` 链接后，**剩余文字少于 30 字符**才算 article stub，避免正常含链接推文被误判后走 Jina 覆盖正文。

### Twitter Article 原生渲染

GraphQL 返回的 Article 数据包含 `content_state`（Draft.js 格式），`_render_article_body()` 将其原生转换为 Markdown，零额外网络请求。支持的 block 类型：unstyled（段落）、header-two（##）、ordered-list-item（有序列表）、atomic（图片/代码块）、code-block（代码块）。entityMap 是 `[{key, value}]` 列表格式（非 dict）。优先级：GraphQL content_state > Jina Reader 兜底。

### Jina 空洞修补（`fetchers/twitter_bookmarks.py`）

Jina Markdown 模式可能丢失 inline link 元素（cashtag、@mention），产生"空洞"（句尾标点后紧跟空行再接下文）。`_patch_jina_hollows()` 检测空洞后用 Jina text 模式获取完整文本，通过锚点匹配定位缺失内容并回填。

### 引用推文完整提取

`extract_tweet_data()` 从 `quoted_status_result` 中提取完整数据：`note_tweet.text`（不截断）、展开 t.co、提取图片/视频、互动指标。`_render_quoted_tweet()` 渲染为 Markdown blockquote。

### richtext_tags 富文本标记

`_apply_richtext_tags()` 将 note_tweet 中的 Draft.js 索引式 `richtext_tags`（Bold/Italic）转换为 Markdown `**bold**`/`*italic*`。从末尾向前插入避免索引偏移。

### 扩展 front matter 元数据

Twitter 推文输出包含完整作者画像（`is_blue_verified`、`followers_count`、`statuses_count`、`listed_count`）和推文元数据（`quotes`、`lang`、`source_app`、`possibly_sensitive`）。

## 迭代历史摘要

> 完整记录见 `DEVLOG.md`

| 版本 | 功能 |
|------|------|
| v0.8.0 | FxTwitter Tier 0.3 兜底（circuit breaker）+ 搜狗微信搜索（`mpweixin-so` 命令） |
| v0.7.1 | tweet_type 分类（status/thread/article）+ 日期解析修复（Tue/Thu 误匹配） |
| v0.7.0 | GraphQL 数据完整提取 + 引用推文增强 + richtext 富文本 + 作者/推文元数据 |
| v0.6.2 | Twitter Article 原生渲染（GraphQL content_state → Markdown）+ Jina 空洞修补 |
| v0.6.1 | 元数据完整性优化（指标全量输出包括 0 值） |
| v0.6.0 | Twitter List 列表批量抓取（按天数过滤+会话去重） |
| v0.5.2 | Syndication API (Tier 0.5) 免费兜底 + cover_image 三级回退 + ISO 8601 日期支持 |
| v0.5.1 | 修复 API 补充搜索操作符不可靠问题（代码层日期过滤+索引空洞检测） |
| v0.5.0 | TwitterAPI.io 付费 API 接入 + Cookie 多账号轮换 + 断点续传 |
| v0.4.0 | 浏览器搜索补充抓取（突破 UserTweets 800 条限制）+ 新版 API 格式兼容 |
| v0.3.2 | Article 正文垃圾检测 + article URL 优先 + GraphQL 单篇重试 |
| v0.3.1 | 日期时区修复（UTC→本地）+ 视频嵌入 Markdown + 分页扩容（200页）+ 重试 |
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
| X/Twitter 相关 | `twitter*.py`（10个文件） |
| 小红书相关 | `xhs*.py`（3个文件）+ `browser.py` |
