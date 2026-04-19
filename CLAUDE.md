# feedgrab 项目指令

## 项目概述

feedgrab 是一个万能内容抓取器，从任意平台抓取内容并输出为 Obsidian 兼容的结构化 Markdown。

- **仓库**：https://github.com/iBigQiang/feedgrab
- **作者**：[@iBigQiang](https://github.com/iBigQiang)（强子手记）
- **当前版本**：v0.17.0
- **Python**：≥3.10
- **许可证**：MIT

### 项目来源

- **[x-reader](https://github.com/runesleo/x-reader)**（@runes_leo）— 多平台架构、CLI、MCP 服务器
- **[baoyu-danger-x-to-markdown](https://github.com/JimLiu/baoyu-skills)**（@dotey 宝玉）— X/Twitter GraphQL 逆向工程深度抓取

### 三层架构

| 层级 | 功能 | 入口 |
|------|------|------|
| Python CLI/库 | 基础内容抓取 + 统一数据结构 | `feedgrab <url>` |
| Claude Code 技能 | 视频转录 + AI 分析 | `skills/video/` `skills/analyzer/` |
| MCP 服务器 | 将抓取能力暴露为 MCP 工具 | `mcp_server.py` |

### 支持的平台（抓取方式一览）

| 平台 | 抓取方式 |
|------|---------|
| X/Twitter | GraphQL → FxTwitter → Syndication → oEmbed → Jina → Playwright（六级兜底） |
| 小红书 | API (xhshow) → Pinia Store 注入 → Jina → Playwright（+ 作者/搜索批量 + `xhs-so`） |
| YouTube | InnerTube API → yt-dlp 字幕 → Groq Whisper + Data API v3 搜索 + yt-dlp 下载 |
| B站 | view API 元数据 + 字幕 3 级兜底（`player/v2` → `player/wbi/v2` WBI → Whisper 可选） |
| 微信公众号 | Playwright JS 提取 → Jina 兜底（单篇 + 搜狗搜索 + MP 账号批量 + 专辑批量） |
| GitHub | REST API（仓库元数据 + 中文 README 优先 + 摘要提取） |
| 飞书/Lark | Open API → CDP 直连 → Playwright PageMain → Jina（+ 知识库批量 + 嵌入表格 + 图片） |
| 金山文档 | Playwright ProseMirror DOM（虚拟滚动 + 代码块 + shapes API 图片 + CDP 直连） |
| 有道云笔记 | JSON API → Playwright iframe DOM → Jina（+ 图片下载） |
| 知乎 | API v4 → Playwright CDP/DOM → Jina（+ 问答前 3 楼 + 专栏 + `zhihu-so`） |
| Telegram | Telethon |
| 小宇宙 | SSR `__NEXT_DATA__` + Groq Whisper 转录 |
| 喜马拉雅 | Web Revision API + canPlay 降级 + Groq Whisper（免费节目） |
| RSS | feedparser |
| 付费新闻（300+） | 7 级 Tier 绕过（JSON-LD → Googlebot/Bingbot UA → AMP → EU IP → archive.today → Google Cache → Jina） |
| 任意网页 | JSON-LD 前置探测 → Jina 兜底 |

## 语言规范

- 对话、文档一律使用**中文**
- 代码注释可英文
- Git commit：英文前缀（feat/fix/docs/chore）+ 英文描述

## 开发工作流

完成功能开发并测试通过后：

1. 更新 DEVLOG.md（顶部新增版本条目）
2. 更新 README.md / README_EN.md（同步新功能使用说明）
3. `git commit` + `git push origin main`

> 使用 `/ship` 命令一键完成上述流程。

## 版本号规范

- 主要新功能：递增次版本号（v0.16.0 → v0.17.0）
- 小功能/修复：递增补丁号（v0.17.0 → v0.17.1）

## 核心架构

```
feedgrab/
├── feedgrab/
│   ├── cli.py                 # CLI 入口（命令路由 + setup + clip）
│   ├── config.py              # 集中配置（get_user_agent/get_stealth_headers）
│   ├── reader.py              # URL 调度器（UniversalReader 平台检测 + 路由 + URL 规范化）
│   ├── schema.py              # 统一数据模型（UnifiedContent）
│   ├── login.py               # 浏览器登录管理 + CDP Cookie 提取
│   ├── fetchers/              # 各平台 fetcher（见"关键文件速查"）
│   └── utils/                 # storage / dedup / http_client / jsonld / transcribe / bilibili_wbi / media
├── skills/                    # Claude Code 技能
├── mcp_server.py              # MCP 服务器入口
├── DEVLOG.md                  # 开发日志（迭代方案、决策、状态）— 详细实现历史见此
├── README.md / README_EN.md   # 用户文档
├── .env.example               # 配置模板
└── pyproject.toml
```

## 跨模块核心约定

> 详细实现细节、每个平台的抓取逻辑见 **DEVLOG.md** 对应版本条目。
> 本节只记录架构性的、跨模块的、易忘记的核心约定。

### 输出格式

- 每条内容 → 独立 `.md`，按平台分目录（`X/`、`XHS/`、`mpweixin/`、`Web/` 等）
- Obsidian 兼容 YAML front matter（title/source/author/published/likes/tags 等）
- `utils/storage.py → _format_markdown()` 统一过滤垃圾内容（如 Twitter emoji SVG），新增规则加 `re.sub()` 即可

### 去重索引

- `{OUTPUT_DIR}/{Platform}/index/item_id_url.json`
- 跨模式统一（单篇/书签/用户推文/搜索补充/作者批量共享）

### HTTP 层

- `utils/http_client.py`：curl_cffi `Session(impersonate="chrome")` TLS 指纹 → requests fallback
- 所有 fetcher 的 `requests.get()`/`urllib` 均走 `http_client.get/post`
- 异常兼容：`except requests.Timeout`/`except requests.RequestException` 无需改动

### User-Agent 与指纹

- `config.py → get_user_agent() + get_stealth_headers()` 集中管理（UA + sec-ch-ua + Accept + Sec-Fetch 全套一致）
- `feedgrab detect-ua` 自动检测本机 Chrome UA
- 依赖 browserforge（未装优雅降级）

### 隐身浏览器引擎（`fetchers/browser.py`）

- 所有 Playwright 抓取统一入口：patchright Tier 1 → playwright Tier 3
- 52 条 Chrome stealth launch args + context 级资源拦截（7 类资源 + 11 tracking 域名）
- 统一 viewport 1920x1080 + locale zh-CN + DPR 2
- `generate_referer(url)` 中国平台→百度，其他→Google
- **例外**：飞书必须用 vanilla `playwright.async_api`（patchright 触发 ERR_CONNECTION_CLOSED）
- 技术方案参考 [Scrapling](https://github.com/D4Vinci/Scrapling)

### CDP 直连（复用运行中 Chrome）

- Cookie 提取：`CHROME_CDP_LOGIN=true` + `CHROME_CDP_PORT=9222`（login.py）
- 飞书：`FEISHU_CDP_ENABLED=true`（复用 Feishu cookie context + localStorage）
- 金山：`KDOCS_CDP_ENABLED=true`
- 关键：`browser.close()` 在 CDP 模式下只断 WebSocket 不杀 Chrome

### 微信 URL 规范化

- `reader.py → _normalize_wechat_url` 剥离追踪参数（`scene`/`click_id`/`sessionid`/`chksm`）
- 只保留 `__biz`/`mid`/`idx`/`sn`
- 短链格式剥离全部 query + fragment
- `feedgrab clip` 从剪贴板读 URL 绕过 PowerShell `&` 报错

### 媒体文件本地化

- `X_DOWNLOAD_MEDIA` / `XHS_DOWNLOAD_MEDIA` / `MPWEIXIN_DOWNLOAD_MEDIA` / `FEISHU_DOWNLOAD_IMAGES` / `KDOCS_DOWNLOAD_IMAGES` / `YOUDAO_DOWNLOAD_IMAGES`
- 下载到 `{md_dir}/attachments/{item_id}/`，MD 中替换为相对路径
- Referer 防盗链：Twitter `name=orig` / XHS 去 `!nd_*` + xiaohongshu referer / WeChat http→https + mp.weixin referer / Feishu 浏览器三阶段预下载

### 分平台关键约定

| 平台 | 关键点 |
|------|--------|
| X/Twitter | `x-client-transaction-id` 签名头必需（SearchTimeline）；queryId 四级解析（disk→community→JS→hardcoded）；feature flags 动态更新 + 紧凑编码；Cookie 多账号轮换（`sessions/twitter.json + x_2.json + ...`）；Article 优先 GraphQL `content_state` 原生渲染 |
| 小红书 | xhshow 签名配置用真实 `platform.system()` + `get_user_agent()`；Cookie 从 `sessions/xhs.json`；xsec_token LRU 缓存 500 条；Pinia Store 注入作为 Tier 0.5 兜底（`XHS_PINIA_ENABLED` 默认 true） |
| 飞书 | 必用 vanilla playwright；标题清理零宽字符（U+200B-U+206F, U+FEFF）；Block→MD 支持 20+ 类型；嵌入表格用 Protobuf 5 层 wire format 解码 + Sheet 懒加载分段预热；图片数据在 `snapshot.image.token`（非 `image.token`） |
| 微信 | Browser 优先（Jina 对 mmbiz 几乎总超时）；Markdown 插入 `<meta name="referrer" content="no-referrer">` 防 mmbiz.qpic.cn 403；评论 API 需微信客户端 session（普通浏览器 "no session" 优雅降级） |
| B站 WBI | `img_key + sub_key`（64 char）按 `MIXIN_KEY_ENC_TAB` 置换取前 32 char = `mixin_key`；值过滤 `!()*'`；`w_rid = md5(query + mixin_key)`；`(img_key, sub_key)` 磁盘缓存 5 分钟 |
| YouTube | InnerTube ANDROID 客户端绕过部分限制；yt-dlp 默认 `YTDLP_COOKIES_BROWSER=chrome` 绕 bot 检测；智能断句：标点拆分→跨 snippet 合并（CJK 无空格/拉丁加空格）→段落分组；标点率 <10% 跳过断句 |
| 付费墙 | 7 级 Tier 级联（JSON-LD/Googlebot/Bingbot/Generic/AMP/EU IP/archive.today/Google Cache）；`PAYWALL_JSONLD_FOR_ALL=true` 让 Tier 0 对 generic URL 都跑；Googlebot/Bingbot 每次覆盖 UA + Referer + `X-Forwarded-For` + `cookies={}` |
| Whisper 共享 | `utils/transcribe.py` 4 个公开函数（`groq_transcribe_file`/`groq_transcribe_url`/`format_transcript`/`subtitle_body_to_snippets`）委托 youtube.py 内部函数，不重构 youtube.py |

### 诊断命令

- `feedgrab doctor` — 所有平台
- `feedgrab doctor x` / `xhs` / `mpweixin` / `feishu` — 按平台分区检查 Cookie/依赖/网络
- 别名：`twitter`→`x`，`wechat`→`mpweixin`

## 迭代历史摘要

> 完整记录见 `DEVLOG.md`。以下仅列最近版本。

| 版本 | 功能 |
|------|------|
| v0.17.0 | 小宇宙 / 喜马拉雅 / B 站字幕三平台 + WBI 签名自研 + Whisper 共享薄层 |
| v0.16.0 | 付费墙 7 级绕过 + JSON-LD articleBody 提取 + `SourceType.WEB` |
| v0.15.x | 飞书嵌入表格错位修复 + YouTube Whisper 时间戳 + 知乎平台 |
| v0.14.x | 金山文档 + 有道云笔记 平台支持 |
| v0.13.x | x-so 三级兜底 + Article 超链接完整保存 + GraphQL 热路径优化 + XHS Pinia 注入 + 飞书 CDP |
| v0.12.x | CDP Cookie 提取 + 微信专辑批量 + 媒体文件本地化 + 微信视频提取 + GitHub 中文 README 增强 |
| v0.11.x | 飞书平台支持（+ 知识库批量 + 嵌入表格 + 图片下载） |
| v0.10.x | 小红书 API 层（xhshow）+ `xhs-so` 搜索 + 多关键词批量 |
| v0.9.x | GraphQL 冷启动加速 + 微信 MP 账号批量 + curl_cffi 统一 + YouTube 搜索/下载 + GitHub README |
| v0.8.x | 隐身浏览器引擎 + browserforge + FxTwitter + 搜狗微信搜索 |
| v0.7.x | GraphQL 数据完整提取 + 引用推文 + richtext + 扩展 front matter |
| v0.6.x | Twitter Article 原生渲染 + List 批量 + Syndication |
| v0.5.x | TwitterAPI.io + Cookie 多账号轮换 + 断点续传 |
| v0.1-0.4 | 初始版本 + 书签/用户推文批量 + XHS 深度抓取 + Article 检测 |

## 关键文件速查

| 需求 | 看哪个文件 |
|------|-----------|
| 新增 CLI 命令 | `cli.py → main()` 路由 + `cmd_xxx()` |
| 新增环境变量 | `config.py` + `.env.example` |
| 新增平台 fetcher | `fetchers/xxx.py` + `reader.py` 路由 |
| 修改输出格式 | `utils/storage.py` |
| 修改数据模型 | `schema.py` |
| 去重逻辑 | `utils/dedup.py` |
| X/Twitter | `twitter*.py`（11 个文件） |
| YouTube | `youtube.py`（字幕/转录）+ `youtube_search.py`（搜索/下载） |
| GitHub | `github.py`（REST API + 中文 README 优先） |
| 小红书 | `xhs*.py`（5 个文件）+ `browser.py` |
| 飞书 | `feishu.py` + `feishu_wiki.py` + `browser.py` |
| 金山文档 | `kdocs.py` |
| 有道云笔记 | `youdao.py` |
| 知乎 | `zhihu.py` + `zhihu_search.py` |
| 小宇宙 / 喜马拉雅 | `xiaoyuzhou.py` + `ximalaya.py` + `utils/transcribe.py` |
| B站字幕 / WBI | `bilibili.py` + `utils/bilibili_wbi.py` |
| 付费墙 / 通用网页 | `paywall.py` + `utils/jsonld.py` |
| 隐身浏览器 | `fetchers/browser.py`（52 条 stealth args + 资源拦截） |
| CDP Cookie | `login.py`（5 平台支持） |
