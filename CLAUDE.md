# feedgrab 项目指令

## 项目概述

feedgrab 是一个万能内容抓取器，从任意平台抓取内容并输出为 Obsidian 兼容的结构化 Markdown。

- **仓库**：https://github.com/iBigQiang/feedgrab
- **作者**：[@iBigQiang](https://github.com/iBigQiang)（强子手记）
- **当前版本**：v0.11.0
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
| 小红书 | API (xhshow) → Jina → Playwright 深度抓取（单篇 + 作者批量 + 搜索批量 + xhs-so 搜索） |
| YouTube | YouTube Data API v3 搜索 + yt-dlp 字幕/视频/音频下载 |
| B站 | API |
| 微信公众号 | Playwright WeChat JS 提取 → Jina 兜底（单篇 + markdownify 富文本）/ 搜狗搜索（关键词搜索）/ MP 后台 API（按账号批量） |
| GitHub | REST API（仓库元数据 + 中文 README 优先 + 摘要提取） |
| 飞书/Lark | Open API → Playwright PageMain Block 树 → Jina（单篇 + 知识库批量 + 嵌入表格 + 图片下载） |
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
│   ├── config.py              # 集中配置（路径、开关、get_user_agent() + get_stealth_headers()）
│   ├── reader.py              # URL 调度器（UniversalReader — 平台检测 + 路由 + URL 规范化）
│   ├── schema.py              # 统一数据模型（UnifiedContent）
│   ├── login.py               # 浏览器登录管理器
│   ├── fetchers/
│   │   ├── jina.py            # Jina Reader（万能兜底）
│   │   ├── browser.py         # 隐身浏览器引擎（patchright Tier 1 → playwright Tier 3 + stealth flags）
│   │   ├── bilibili.py        # B站 API
│   │   ├── youtube.py         # yt-dlp 字幕提取 + API 优先元数据
│   │   ├── youtube_search.py  # YouTube Data API v3 搜索 + yt-dlp 下载（视频/音频/字幕）
│   │   ├── github.py          # GitHub REST API（仓库元数据 + 中文 README 优先）
│   │   ├── rss.py             # RSS 解析
│   │   ├── telegram.py        # Telegram 频道
│   │   ├── twitter.py         # X/Twitter 六级兜底调度器
│   │   ├── twitter_cookies.py # Cookie 多源管理 + 多账号轮换（429 自动切换）
│   │   ├── twitter_fxtwitter.py # FxTwitter API 客户端（Tier 0.3 兜底 + circuit breaker）
│   │   ├── twitter_graphql.py # GraphQL API（TweetDetail/UserTweets/Bookmarks/SearchTimeline/动态queryId + x-client-transaction-id）
│   │   ├── twitter_thread.py  # 线程重建 + 评论分类
│   │   ├── twitter_bookmarks.py  # 书签批量抓取
│   │   ├── twitter_user_tweets.py # 用户推文批量抓取
│   │   ├── twitter_list_tweets.py # List 列表批量抓取（按天数过滤+会话去重）
│   │   ├── twitter_search_tweets.py # 浏览器搜索补充抓取（突破 UserTweets 800 条限制）
│   │   ├── twitter_keyword_search.py # 关键词搜索（x-so 命令，纯 GraphQL + 互动排序表格）
│   │   ├── twitter_api.py     # TwitterAPI.io 付费 API 客户端
│   │   ├── twitter_api_user_tweets.py # 付费 API 批量抓取（max_id 分页+断点续传+智能直保）
│   │   ├── twitter_markdown.py   # Markdown 渲染器
│   │   ├── wechat.py          # Playwright → Jina（Browser 优先）
│   │   ├── wechat_search.py   # 搜狗微信搜索（关键词 → 文章发现 + 抓取）
│   │   ├── mpweixin_account.py # 微信公众号按账号批量（MP 后台 API + 断点续传）
│   │   ├── xhs.py             # 小红书单篇（API → Jina → Playwright）
│   │   ├── xhs_api.py         # 小红书 API 客户端（xhshow 签名 + 评论 + xsec_token 缓存）
│   │   ├── xhs_user_notes.py  # 小红书作者批量（API cursor → 浏览器三层策略）
│   │   ├── xhs_search_notes.py # 小红书搜索批量 + xhs-so 关键词搜索
│   │   ├── feishu.py          # 飞书单篇（Open API → Playwright PageMain → Jina + Block→MD + Sheet Protobuf 解码 + 图片下载）
│   │   └── feishu_wiki.py     # 飞书知识库批量（Open API 递归 + Playwright 兜底 + 断点续传）
│   └── utils/
│       ├── storage.py         # 按平台分目录 Markdown 输出 + YAML front matter
│       ├── dedup.py           # 全局去重索引
│       └── http_client.py     # 统一 HTTP 客户端（curl_cffi TLS 指纹 → requests fallback）
├── skills/                    # Claude Code 技能
├── mcp_server.py              # MCP 服务器入口
├── DEVLOG.md                  # 开发日志（迭代方案、决策、状态）
├── README.md                  # 用户文档（中文）
├── README_EN.md               # 用户文档（英文）
├── .env.example               # 配置模板
└── pyproject.toml             # 包定义
```

## 关键设计决策

### GitHub 仓库 README 抓取（`fetchers/github.py`）

3 次 API 调用完成抓取：`/repos/{owner}/{repo}`（元数据）→ `/repos/{owner}/{repo}/contents/`（根目录列表）→ README 内容。中文 README 优先：从根目录列表匹配 8 种变体（`README_CN.md`、`README.zh-CN.md` 等），命中则获取中文版，否则用默认 README。`_extract_readme_summary()` 从 README 提取第一行有意义的描述文本作为标题（跳过 heading、badge、HTML、blockquote、短于 15 字符的行）。`parse_github_url()` 统一处理仓库首页/blob/tree/issues 等 URL，取前两段 path 为 owner/repo。`item_id = MD5("{owner}/{repo}")[:12]` 保证仓库级别去重。无 Token 60 次/小时，有 Token 5000 次/小时。

### Twitter 关键词搜索（`twitter_keyword_search.py`）

`feedgrab x-so <keyword>` 通过纯 GraphQL SearchTimeline 端点搜索 Twitter，输出按查看数降序排列的 Markdown 汇总表格 + CSV。支持逗号分隔多关键词批量搜索（`feedgrab x-so "k1,k2,k3"`），`--merge` 合并结果到一个文件（含关键词列），默认分开生成。直接调用 `fetch_search_timeline_page()` 分页获取结果（无需浏览器），`extract_tweet_data()` 提取结构化数据。`build_search_query()` 自动拼接高级搜索运算符（lang/since/min_faves/-is:retweet 等），关键词自动包引号。MD 表格中内容摘要为超链接（无独立链接列），CSV 保留明文链接列。`_generate_summary_table()` 同时输出 `.md`（Obsidian `cssclasses: wide`）和 `.csv`（UTF-8 BOM），合并模式下按查看数全局排序 + 添加关键词列。11 个 `X_SEARCH_*` 配置函数提供默认值。`--raw` 模式让用户完全控制查询语法。`X_SEARCH_SAVE_TWEETS=true` 可选保存单篇推文 .md 到子目录。输出路径：`X/search/{days}day_{new|hot}/{keyword}_{date}.{md,csv}`。

### x-client-transaction-id 反检测（`twitter_graphql.py`）

Twitter 对 SearchTimeline 等 GraphQL 端点强制要求 `x-client-transaction-id` 签名头（缺失返回 404）。`_get_transaction_id()` 使用 `XClientTransaction` 库纯 Python 生成此值：从 x.com 主页提取 SVG 动画帧数据 + `twitter-site-verification` 密钥 + `ondemand.s` JS 索引，经 Cubic Bezier 插值 + SHA-256 签名 + XOR 混淆 + Base64 编码。生成器实例内存缓存 30 分钟复用（`_TRANSACTION_TTL = 1800`），**源数据磁盘缓存 1 小时**（`{data_dir}/cache/twitter_transaction_cache.json`），进程重启时零 HTTP 冷启动。在 `_execute_graphql()` 中自动注入所有 GraphQL 请求。未安装 `XClientTransaction` 时优雅降级并输出安装提示。依赖 `pip install XClientTransaction beautifulsoup4`。

### queryId 四级解析（`twitter_graphql.py`）

`resolve_query_ids()` 从四个来源按优先级解析 GraphQL 操作的 queryId：Tier 0 磁盘缓存（`{data_dir}/cache/twitter_queryid_cache.json`，1 小时 TTL）→ Tier 1 社区源（`fa0311/twitter-openapi` GitHub 仓库，单次 HTTP 获取 87 个 queryId）→ Tier 2 JS bundle 扫描（x.com 首页 HTML → JS chunk 下载 → 正则提取）→ Tier 3 硬编码回退常量。社区源命中时跳过 JS bundle 扫描（省多次 HTTP）。磁盘缓存命中时零 HTTP 请求。硬编码回退值定期从社区源同步更新。

### X/Twitter 六级兜底

Tier 0 GraphQL（需Cookie）→ Tier 0.3 FxTwitter（免费无认证，第三方公共API）→ Tier 0.5 Syndication（免费无认证）→ Tier 1 oEmbed → Tier 2 Jina → Tier 3 Playwright

FxTwitter 数据完整度接近 GraphQL（有 views/bookmarks/Article Draft.js），缺少 blue_verified/listed_count/线程展开。批量模式连续 3 次失败触发 circuit breaker 临时跳过。

Article 长文在 Tier 0 命中后优先用 GraphQL `content_state` 原生渲染，仅当渲染结果不足 200 字时回退 Jina。

### 小红书 API 层 + 多层兜底（`fetchers/xhs_api.py` + `xhs.py`）

**单篇**：Tier 0 API Feed (xhshow) → Tier 1 Jina → Tier 2 Playwright。`xhshow` 签名库生成 `x-s`/`x-s-common`/`x-t` 等反爬头，纯 HTTP 调用 `edith.xiaohongshu.com` API，单篇 <1s。签名配置使用真实系统平台和 UA（`platform.system()` + `get_user_agent()`），避免 Windows 环境用 macOS UA 被反爬识别。Cookie 从 `sessions/xhs.json` Playwright storage_state 提取（`a1`/`web_session` 等）。

**作者批量**：API cursor 自动分页（30条/页）→ 逐篇 Feed API → 浏览器三层策略兜底。

**搜索批量**：API page 分页（20条/页）+ 排序/类型筛选 → 浏览器 Tier 0/1/2 兜底。

**浏览器批量策略**（降级后）：Tier 0 `__INITIAL_STATE__`（SSR数据，~40篇）→ Tier 1 XHR拦截+滚动加载 → Tier 2 逐篇深度抓取。

**xhs-so 搜索命令**：`feedgrab xhs-so <keyword>` 纯 API 搜索 + 互动排序汇总表（MD + CSV），仿 `x-so` 模式。支持逗号分隔多关键词批量搜索（`feedgrab xhs-so "k1,k2,k3"`），`--merge` 合并结果到一个文件（含关键词列），默认分开生成。支持 `--sort popular/latest`、`--type video/image`、`--save` 保存单篇。合并模式下按点赞数全局排序 + 添加关键词列。

**评论抓取**：`XHS_FETCH_COMMENTS=true` 时调用评论 API（cursor 分页），提取评论全文 + 子评论，渲染为 Markdown blockquote。

**xsec_token 缓存**：LRU 磁盘缓存 500 条（`sessions/cache/xhs_token_cache.json`），搜索/作者批量结果自动缓存 token。

**反检测**：Gaussian 抖动（base ± gauss(0.3, 0.15)）+ 5% 长暂停 + 验证码冷却（461/471 → 5→10→20→30s 递增）+ 指数退避重试。

`xhshow` 为可选依赖（`pip install xhshow`），未安装时跳过 API 层，完全不影响现有浏览器模式。

### 隐身浏览器引擎（`fetchers/browser.py`）

所有 Playwright 浏览器抓取统一使用隐身引擎：patchright（Tier 1）→ playwright（Tier 3）。patchright 在 Chromium CDP 协议层移除 `navigator.webdriver` 和 `Runtime.enable` 等自动化检测标记。52 条 Chrome 隐身启动参数（STEALTH_LAUNCH_ARGS）覆盖反检测、指纹伪装、性能优化；5 条有害默认参数（HARMFUL_DEFAULT_ARGS）被屏蔽。Context 配置统一 viewport 1920x1080 + screen + locale zh-CN + dark color_scheme + DPR 2。`generate_referer(url)` 自动生成搜索引擎 referer（中国平台→百度、其他→Google），首次导航时设置。`setup_resource_blocking(context)` 在 context 级别拦截 7 类非必要资源 + 11 个 tracking 域名，加速批量抓取。安装 `pip install patchright` 后自动启用，无需配置变更。技术方案适配自 [Scrapling](https://github.com/D4Vinci/Scrapling)。

### User-Agent 集中管理

`config.py` → `get_user_agent()` + `get_stealth_headers()`，所有浏览器交互统一 UA，避免 session 失效。`feedgrab detect-ua` 自动检测本机 Chrome UA。`get_stealth_headers()` 通过 browserforge 生成全套一致 header（UA + sec-ch-ua + Accept + Sec-Fetch 等），按 Chrome 版本号 pin 生成，会话级缓存。未安装 browserforge 时优雅降级并输出安装提示。

### curl_cffi TLS 指纹统一

`utils/http_client.py` 提供统一 HTTP 客户端：curl_cffi `Session(impersonate="chrome")` 模拟 Chrome TLS 指纹（JA3/JA4 完全匹配），fallback 到标准 requests。所有 fetcher 的 `requests.get()`/`urllib.request.urlopen()` 均已迁移到 `http_client.get()`/`http_client.post()`。异常兼容层确保现有 `except requests.Timeout`/`except requests.RequestException` 代码无需改动。`raise_for_status()` 辅助函数包装 curl_cffi 的状态码异常为 `requests.HTTPError`。

### 全局去重索引

`{OUTPUT_DIR}/{Platform}/index/item_id_url.json`，跨模式统一去重（单篇/书签/用户推文/搜索补充/作者笔记/搜索共享）。

### 浏览器搜索补充抓取

UserTweets API 受服务端限制（~800条），通过 Playwright 浏览器按月分片搜索补充历史推文。使用 `page.on("response")` 在 Python 层面拦截 SearchTimeline GraphQL 响应，跨导航持久有效。两阶段共享去重索引。

### TwitterAPI.io 付费 API

替代浏览器搜索补充的服务器友好方案（$0.15/千条）。配置 `TWITTERAPI_IO_KEY` 后超过 800 条时自动走 API 替代浏览器搜索。`X_API_PROVIDER=api` 可全量走付费 API（无需 Cookie）。使用 max_id 分页（Snowflake ID 递增），断点续传（JSONL 缓存），智能直保（普通推文直接保存，长文/线程走 GraphQL）。注意：TwitterAPI.io 的 `since:`/`until:`/直接 `max_id` 跳转操作符均不可靠，日期过滤在代码层完成。

### Cookie 多账号轮换

`sessions/` 目录支持多个 Cookie 文件（`twitter.json` + `x_2.json` + `x_3.json`...），GraphQL 429 时自动切换到未限流账号，15 分钟冷却后恢复。

### 输出格式

每条内容 → 独立 `.md` 文件，按平台分目录（`X/`、`XHS/`、`mpweixin/`、`YouTube/` 等），Obsidian 兼容 YAML front matter（title/source/author/published/likes/tags 等）。

### 搜狗微信搜索（`mpweixin-so`）

`feedgrab mpweixin-so <keyword>` 通过搜狗微信搜索发现公众号文章。配置开关 `MPWEIXIN_SOGOU_ENABLED`（默认 false）。每页 10 条，最多 100 条（10 页），通过 `MPWEIXIN_SOGOU_MAX_RESULTS` 或 `--limit N` 控制。

流程：HTTP 搜索 → headed 浏览器获取搜狗 Cookie → 新标签页跟随跳转获取 `mp.weixin.qq.com` 真实 URL → 同浏览器提取 `#js_content` HTML → `_html_to_markdown()` 转换富文本（headings/bold/italic/images/links/lists/blockquotes）。输出到 `mpweixin/search_sogou/{keyword}/` 目录。

### 微信公众号按账号批量抓取（`mpweixin-id`）

`feedgrab mpweixin-id "公众号名"` 通过 MP 后台 API 枚举公众号全部历史文章。需要先 `feedgrab login wechat` 获取 MP 后台 session（有效期约 4 天）。

流程：加载 `sessions/wechat.json` → 导航 `mp.weixin.qq.com` 建立会话 → `searchbiz` API 搜索账号获取 fakeid → `appmsgpublish` API 分页枚举文章列表（每页 5 条）→ 逐篇在新标签页打开 → `evaluate_wechat_article()` + `_html_to_markdown()` 提取全文 → 保存到 `mpweixin/account/{公众号名}/`。

配置项：`MPWEIXIN_ID_SINCE`（日期过滤，YYYY-MM-DD）、`MPWEIXIN_ID_DELAY`（间隔秒数，默认 3）。断点续传：`_progress_mpweixin_id_*.json` 缓存文件，完成后自动清理。去重：复用 `mpweixin` 平台索引。API title fallback：当浏览器 title 为空时（小绿书图片帖），使用 API 返回的 title → digest 作为回退。

### 微信单篇抓取（`fetchers/wechat.py` + `browser.py`）

Tier 1 Playwright WeChat JS 提取 → Tier 2 Jina 兜底 → Tier 3 Browser retry。Browser 优先策略：Jina 对微信 CDN 几乎总超时（30s 浪费），Browser 使用 `WECHAT_ARTICLE_JS_EVALUATE` 在 JS 层面一次性提取 9 类数据（DOM 元素 + OG meta + JS 脚本变量 + `#js_content` HTML），数据完整度最高。`create_time` 通过三层正则从页面 JS 脚本提取（JsDecode 格式 / 单引号 / 双引号），精确到秒。`msg_cdn_url` 比 `og:image` 质量更高。`_html_to_markdown()` 使用 markdownify + BeautifulSoup 预处理（lazy image 转换、SVG 过滤、WeChat 代码块占位符策略）。输出的 Markdown 在 front matter 后插入 `<meta name="referrer" content="no-referrer">`，避免 mmbiz.qpic.cn 图片 Referer 校验 403。小绿书图片帖（`itemShowType=16`）的 `#activity-name` 和 `#js_name` 不存在，标题回退链：`#activity-name` → `og:title` → `.rich_media_title`，作者回退链：`#js_name` → JS 脚本 `nick_name` → `cgiDataNew.nick_name`。代码块预处理：`<br>` → `\n` 转换 + 占位符反向还原（防前缀碰撞）+ fence 前后 `\n\n` 间距。

### 微信 URL 规范化（`reader.py` → `_normalize_wechat_url`）

`reader.py` 在平台检测后自动清理微信文章 URL：剥离 `scene`/`click_id`/`sessionid`/`chksm` 等追踪参数，仅保留 `__biz`/`mid`/`idx`/`sn` 四个文章标识参数。解决两个问题：(1) PowerShell 中 `&` 被解析为管道操作符导致命令失败；(2) 同一篇文章因不同追踪参数产生不同 `item_id`（MD5(url)）导致去重索引失效。短链格式（`mp.weixin.qq.com/s/xxx`）不含 query 参数，原样返回。

### Markdown 输出过滤（`utils/storage.py` → `_format_markdown`）

`_format_markdown()` 在最终输出 Markdown 前统一过滤已知的垃圾内容，所有平台生效：
- **Twitter emoji SVG 图片**：`![...](https://abs-0.twimg.com/emoji/...)` → 移除（Obsidian 中显示尺寸过大）
- 如需新增过滤规则，在 `_format_markdown()` 的 `return result` 前添加 `re.sub()` 即可

### 飞书文档抓取（`fetchers/feishu.py` + `feishu_wiki.py`）

**多级兜底**：Tier 0 Open API（`lark-oapi`）→ Tier 1 Playwright `window.PageMain` Block 树 → Tier 1.5 内部导出 API → Tier 2 Jina。patchright 与飞书不兼容（ERR_CONNECTION_CLOSED），必须用 vanilla `playwright.async_api`。

**Block→Markdown 转换器**（`_block_to_md()`）：支持 20+ 种 block 类型，有序列表 `_calc_ordered_label()` 处理 `seq` 字段（`"1"`/`"auto"`/`"a"`/`"i"` 四种序列类型）。

**嵌入电子表格**：Canvas 渲染无 DOM，通过 `POST /space/api/v3/sheet/client_vars` 内部 API 获取 JSON（Protobuf gzip+base64 编码的单元格数据），5 层 wire format 解码（`L0[1]→L1[2]→L2[12]→L3[2]→L4[repeated 2]`）提取 cell 字符串，reshape 为 2D 数组渲染 GFM 表格。`browser.py` 中 `FEISHU_SHEET_FETCH_JS` 和 `_capture_sheet_response()` 拦截器提供多策略数据获取。

**图片下载**（`FEISHU_DOWNLOAD_IMAGES=true`）：Open API `drive/v1/medias/{token}/download`（Tier 0）→ CDN `/space/api/box/stream/download/all/{token}/`（Tier 1）。`_sanitize_filename()` 清理文件名中的 `()@#%[]{}|<>!` 和空格，保证 Markdown 图片语法不断裂。

**标题清理**：`_clean_feishu_title()` 过滤零宽字符（U+200B-U+206F, U+FEFF）+ 折叠换行 + 去 ` - 飞书云文档` 等后缀。DOM selectors → rootBlock snapshot.title → document.title 三级回退。

**知识库批量**：`feishu-wiki` CLI 命令，Open API 递归节点树 + 逐篇 blocks API + Playwright 兜底。断点续传缓存文件 + 去重索引。

**配置项**：`FEISHU_APP_ID`/`FEISHU_APP_SECRET`（Open API）、`FEISHU_DOWNLOAD_IMAGES`（图片下载）、`FEISHU_CUSTOM_DOMAINS`（私有化部署域名）、`FEISHU_PAGE_LOAD_TIMEOUT`（页面等待超时）、`FEISHU_WIKI_*`（批量配置）。

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

### YouTube Data API v3 搜索（`youtube_search.py`）

`feedgrab ytb-so <keyword>` 通过 YouTube Data API v3 搜索视频。两阶段查询：`search.list`（100 quota）→ videoId list → `videos.list` 批量详情（1 quota）。支持频道限定（`--channel @handle`）、排序（`--order viewCount/date`）、日期范围、时长过滤。频道搜索跳过 `regionCode`/`relevanceLanguage` 参数（否则返回空结果）。

### YouTube 单视频 API 优先（`youtube.py`）

单视频抓取策略：API 元数据（1 quota）→ 多语言字幕（`[sub_lang, zh-CN, zh-Hans, zh-Hant, zh, en, en-US]`）→ Groq Whisper 转录 → API description → Jina 兜底。API `has_caption` 提示跳过无字幕视频的 yt-dlp 超时。

### yt-dlp JS 运行时（`_js_runtime_args()`）

yt-dlp 默认只启用 deno。`_js_runtime_args()` 自动检测 deno/node/bun 并传入 `--js-runtimes` + `--remote-components ejs:github`。两个文件各有一份（`youtube.py` 和 `youtube_search.py`）。

### YouTube 下载命令（`ytb-dlv`/`ytb-dla`/`ytb-dlz`）

三个 CLI 命令下载视频(MP4)/音频(MP3)/字幕(SRT)到 `{OUTPUT_DIR}/YouTube/` 目录。先通过 API 获取元数据构建统一文件名前缀（`author_date：title`），与 MD 输出保持一致。长链接和 youtu.be 短分享链接都兼容。

## 迭代历史摘要

> 完整记录见 `DEVLOG.md`

| 版本 | 功能 |
|------|------|
| v0.11.0 | 飞书文档抓取（Open API → Playwright PageMain → Jina 三级兜底 + Block→MD 转换器 + 嵌入表格 Protobuf 解码 + 图片下载 + 知识库批量） |
| v0.10.1 | 多关键词批量搜索（`x-so`/`xhs-so` 逗号分隔 + `--merge` 合并模式）+ 搜索结果质量修复 |
| v0.10.0 | 小红书 API 层集成（xhshow 签名 + 三级兜底）+ `xhs-so` 搜索命令 + 评论抓取 + doctor xhs 增强 |
| v0.9.14 | 批量抓取数据完整性（扩展元数据 8 字段）+ 线程退化保护（全 5 个 fetcher 覆盖） |
| v0.9.13 | 批量 Article 优先 GraphQL content_state（5 个 fetcher 统一，消除 Jina 瓶颈，3 分钟→30 秒） |
| v0.9.12 | `feedgrab doctor` 诊断命令（按平台分区：x/xhs/mpweixin/feishu，一键检查 Cookie/依赖/网络） |
| v0.9.11 | Feature Flags 动态更新（从 x.com HTML 提取当前 feature 值，零额外 HTTP 请求） |
| v0.9.10 | Feature Flags 紧凑编码（只发 True 值，URL 缩短 ~30%） |
| v0.9.9 | GraphQL 冷启动加速（transaction-id 磁盘缓存 + 社区 queryId 源 + fallback 更新） |
| v0.9.8 | x-so 纯 GraphQL 升级（消除浏览器依赖）+ x-client-transaction-id 反检测签名 |
| v0.9.7 | Twitter 关键词搜索（`x-so` 命令，互动排序汇总表格 + 11 个配置项） |
| v0.9.6 | GitHub 仓库 README 抓取（REST API + 中文 README 优先 + 摘要提取 + 仓库级去重） |
| v0.9.5 | YouTube Data API v3 搜索（`ytb-so`）+ 单视频下载命令（`ytb-dlv`/`ytb-dla`/`ytb-dlz`）+ API 优先元数据 + JS 运行时修复 |
| v0.9.4 | 微信单篇抓取策略反转：Browser 优先（Browser→Jina→Browser retry，消除 Jina 30s 超时浪费） |
| v0.9.3 | 微信代码块修复（`<br>`换行 + 占位符碰撞 + 围栏间距）+ 小绿书元数据回退（og:title + cgiDataNew.nick_name） |
| v0.9.2 | 微信公众号按账号批量抓取（MP 后台 API + 断点续传 + cgiDataNew 元数据管线） |
| v0.9.1 | 微信公众号抓取增强（JS 元数据提取 + markdownify 富文本 + 图片防盗链 no-referrer） |
| v0.9.0 | curl_cffi TLS 指纹统一 + 搜狗搜索浏览器统一（消除指纹分裂） |
| v0.8.4 | Referer 伪装（百度/Google）+ 资源拦截（7 类资源 + 11 个 tracking 域名） |
| v0.8.3 | browserforge 浏览器指纹一致性（全套 header 生成 + UA 统一 + 降级提示） |
| v0.8.2 | 隐身浏览器引擎升级（patchright Tier 1 + 52 条 stealth flags + 环境伪装 + playwright Tier 3 兜底） |
| v0.8.1 | 搜狗微信搜索增强（mpweixin 目录 + 配置开关 + 多页搜索 + 富文本 Markdown） |
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
| X/Twitter 相关 | `twitter*.py`（11个文件） |
| YouTube 相关 | `youtube.py`（字幕/转录）+ `youtube_search.py`（搜索/下载） |
| GitHub 相关 | `github.py`（REST API + 中文 README 优先） |
| 小红书相关 | `xhs*.py`（4个文件）+ `browser.py` |
| 飞书相关 | `feishu.py`（单篇 + Block→MD + 图片）+ `feishu_wiki.py`（知识库批量）+ `browser.py` |
