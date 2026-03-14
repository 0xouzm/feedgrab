# feedgrab DEVLOG

开发日志 — 记录每次升级迭代的确定方案、实施细节和状态追踪，作为项目演进的记忆文件。

## 2026-03-14 · v0.11.1 · 浏览器层 3 处 bug 修复（微信指标丢失 + Twitter 隐身引擎统一）

### 背景
分析 Lightpanda 浏览器融合方案时（结论：不适合 feedgrab），顺带审查了 `browser.py` 和 Twitter 浏览器路径，发现 3 处遗留问题。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/browser.py` | 修改 | `_build_wechat_result` 死代码修复 — `return` 前移至 cgiMetrics 处理之后，恢复微信阅读量/点赞/在看/分享/评论数输出 |
| `feedgrab/fetchers/twitter.py` | 修改 | Tier 3 Playwright 改用 `stealth_launch` + `get_stealth_context_options` + `setup_resource_blocking`（原仅 1 条启动参数） |
| `feedgrab/fetchers/twitter_search_tweets.py` | 修改 | 搜索补充抓取改用隐身引擎 + context 级资源拦截（原 vanilla playwright + 无拦截） |

### 验证结果
- 三个文件 `py_compile` 编译通过 ✅
- `_build_wechat_result` 不再提前 return，cgiMetrics 数据正常追加 ✅
- Twitter Tier 3 + 搜索补充统一走 52 条隐身参数 + 7 类资源拦截 + 11 个 tracking 域名拦截 ✅

### 状态：已完成 ✅

---

## 2026-03-14 · v0.11.0 · 飞书文档抓取（单篇 + 知识库批量 + 嵌入表格 + 图片下载）

### 背景
feedgrab 新增第 9 个平台 — 飞书/Lark。支持单篇文档抓取和知识库批量抓取，输出 Obsidian 兼容 Markdown。

### 方案决策
- **多级兜底架构**：Tier 0 Open API（`lark-oapi`）→ Tier 1 Playwright `window.PageMain` Block 树提取 → Tier 1.5 内部导出 API → Tier 2 Jina Reader
- **patchright 不兼容飞书**：飞书 ERR_CONNECTION_CLOSED，必须用 vanilla `playwright.async_api`（headed Chrome）
- **Block→Markdown 转换器**：支持 20+ 种 block 类型（heading/list/code/quote/table/image/equation/todo/callout/divider/grid/iframe/embed）
- **嵌入电子表格二级提取**：Canvas 渲染的 Sheet 无 DOM 可抓，通过 `client_vars` 内部 API + Protobuf 5 层解码提取单元格数据，渲染为 GFM 表格
- **图片文件名清理**：`_sanitize_filename()` 替换 `()@#%[]{}|<>!` 和空格，避免 Markdown 图片语法断裂
- **标题清理**：`_clean_feishu_title()` 过滤零宽字符（U+200B-U+206F, U+FEFF）+ 折叠换行 + 去后缀
- **知识库批量**：Open API 递归节点树 → 逐篇 blocks API → Playwright 兜底。断点续传 + 去重索引

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/feishu.py` | 新建 | 单篇抓取（三级兜底）+ Block→Markdown 转换器 + Protobuf Sheet 解码 + 图片下载 |
| `feedgrab/fetchers/feishu_wiki.py` | 新建 | 知识库批量抓取（Open API 递归 + Playwright 兜底 + 断点续传） |
| `feedgrab/fetchers/browser.py` | 修改 | `FEISHU_DOC_JS_EVALUATE` + `evaluate_feishu_doc()` + Sheet 内部 API 拦截/调用 |
| `feedgrab/reader.py` | 修改 | 飞书域名检测 + `from_feishu` 路由 + 图片下载集成 + 去重索引 |
| `feedgrab/schema.py` | 修改 | `SourceType.FEISHU` + `from_feishu()` 工厂函数 |
| `feedgrab/config.py` | 修改 | 7 个飞书配置函数（APP_ID/SECRET/WIKI_*/DOWNLOAD_IMAGES/CUSTOM_DOMAINS/PAGE_LOAD_TIMEOUT） |
| `feedgrab/cli.py` | 修改 | `feishu-wiki` 命令 + `cmd_feishu_wiki()` |
| `feedgrab/login.py` | 修改 | `feishu`/`lark` 登录入口 |
| `feedgrab/utils/storage.py` | 修改 | Feishu 平台目录映射 + 文件名格式 + front matter + 跳过标题 heading + `save_to_markdown()` 返回路径 |
| `pyproject.toml` | 修改 | `feishu` 可选依赖组（`lark-oapi>=1.5`） |
| `.env.example` | 修改 | 飞书配置项说明 |

### 验证结果
- 单篇 Playwright 抓取 ✅ — `feedgrab https://my.feishu.cn/wiki/Eaf3wWF51igr9gkKYShcHyfAnMd`
- 嵌入电子表格提取 ✅ — 12×4 MacBook 对比表正确渲染为 GFM 表格
- 图片下载 ✅ — `FEISHU_DOWNLOAD_IMAGES=true` 保存到 `attachments/` 子目录
- 图片文件名清理 ✅ — `Apple (中国大陆).jpg` → `Apple-中国大陆.jpg`
- YAML front matter 格式 ✅ — 标题单行、无重复 heading
- 知识库批量 ✅ — `feishu-wiki` 命令递归抓取

### 状态：已完成 ✅

---

## 2026-03-13 · v0.10.1 · 多关键词批量搜索 + 搜索结果质量修复

### 背景
用户使用 `xhs-so` 和 `x-so` 搜索时，每次只能搜一个关键词。日常场景常需一次性搜多个关键词（如 "claude code,openclaw,DeepSeek"），依次手动跑效率低。同时搜索结果存在非笔记 item 混入（广告/推荐词）和合并排序缺失等质量问题。

### 方案决策
- **逗号分隔格式**：`feedgrab xhs-so "k1,k2,k3"` — 双引号包裹，逗号分隔（支持中英文逗号），关键词内可含空格
- **双模式**：默认独立模式（各关键词各自一个文件），`--merge` 或环境变量开启合并模式（所有结果到一个文件，加"关键词"列）
- **合并模式全局排序**：Twitter 按查看数、XHS 按点赞数全局排序（非分段排序）
- **搜索质量修复**：API 层 `model_type` 过滤 + 表格层空行过滤

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/cli.py` | 修改 | `_split_keywords()` 辅助函数 + 两个 cmd 函数支持多关键词循环/合并 + `--merge` CLI flag + help 文本 |
| `feedgrab/config.py` | 修改 | 新增 `x_search_merge_keywords()` + `xhs_search_merge_keywords()` |
| `feedgrab/fetchers/xhs_api.py` | 修改 | `get_all_search_notes()` 新增 `model_type` 过滤（与浏览器模式一致）+ 跳过无 note_id 的残缺 item |
| `feedgrab/fetchers/xhs_search_notes.py` | 修改 | `_generate_xhs_summary_table()` 加 `show_keyword` 参数 + 空行过滤 + `search_xhs_keyword()` 返回 notes + `skip_summary` |
| `feedgrab/fetchers/twitter_keyword_search.py` | 修改 | `_generate_summary_table()` 加 `show_keyword` 参数 + 内置全局排序 + 返回 tweets + `skip_summary` |
| `.env.example` | 修改 | 新增 `X_SEARCH_MERGE_KEYWORDS` + `XHS_SEARCH_MERGE_KEYWORDS` + 多关键词用法示例 |

### 验证结果
- `feedgrab xhs-so "claude code,openclaw" --limit 20` — 独立模式生成 2 个文件 ✅
- `feedgrab xhs-so "claude code,openclaw" --limit 20 --merge` — 合并模式生成 1 个文件，"关键词"列正确，按点赞全局排序 ✅
- `feedgrab xhs-so "claude code"` — 单关键词兼容，169→161 条（过滤 8 条非 note 垃圾）✅
- `feedgrab x-so "梯子,VPN,v2ray,小火箭,openclash"` — Twitter 5 关键词合并模式 ✅

### 状态：已完成 ✅

---

## 2026-03-13 · v0.10.0 · 小红书 API 层集成 + xhs-so 搜索命令

### 背景
feedgrab 的小红书功能完全依赖 Jina Reader 和 Playwright 浏览器自动化，速度慢（每篇 ~5s）、需要 headed 模式、依赖 DOM 结构稳定。参考 [jackwener/xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) 的逆向 API 方案，通过 `xhshow` 签名库实现纯 HTTP 调用，单篇 <1s、无需浏览器、数据更完整。

### 方案决策
- 将 xiaohongshu-cli 的 API 能力作为新 Tier 0 集成到 feedgrab 三层兜底架构
- 签名配置使用真实系统平台和 UA（通过 `platform.system()` + `get_user_agent()` 自动检测），避免 Windows 环境用 macOS UA 被反爬识别
- Cookie 来源复用 `sessions/xhs.json` Playwright storage_state（零成本，无需新登录流程）
- `xhshow` 为可选依赖，未安装时自动降级到浏览器模式

### 新增功能

| 功能 | 说明 |
|------|------|
| 单篇 API 抓取 | API → Jina → Playwright 三级兜底（~0.5s vs 原 ~5s） |
| 作者批量 API | cursor 自动分页（30条/页），失败降级到浏览器三层策略 |
| 搜索批量 API | page 分页 + 排序/类型筛选，失败降级到浏览器 |
| `xhs-so` 命令 | 关键词搜索汇总表（MD + CSV），仿 `x-so` 模式 |
| 评论抓取 | `XHS_FETCH_COMMENTS=true` 时提取评论全文 + 子评论 |
| xsec_token 缓存 | LRU 磁盘缓存 500 条（`sessions/cache/xhs_token_cache.json`） |
| doctor xhs 增强 | xhshow 安装检测 + API 连通性 + Cookie 有效性 |

### 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `XHS_API_ENABLED` | true | API 优先模式开关 |
| `XHS_API_DELAY` | 1.0 | API 请求间隔秒数 |
| `XHS_FETCH_COMMENTS` | false | 单篇时获取评论全文 |
| `XHS_MAX_COMMENTS` | 5 | 评论最大页数（~20条/页） |
| `XHS_SEARCH_SORT` | general | 搜索排序: general/popular/latest |
| `XHS_SEARCH_NOTE_TYPE` | all | 搜索类型: all/video/image |
| `XHS_SEARCH_MAX_PAGES` | 10 | 搜索最大页数（每页 20 条） |

### 改动范围

| 文件 | 操作 | 说明 |
|------|------|------|
| `feedgrab/fetchers/xhs_api.py` | **新建** | XHS API 客户端核心（~550 行） |
| `feedgrab/fetchers/xhs.py` | 修改 | 加入 API Tier 0 + 评论抓取 |
| `feedgrab/fetchers/xhs_user_notes.py` | 修改 | API cursor 分页优先 |
| `feedgrab/fetchers/xhs_search_notes.py` | 修改 | API page 分页 + xhs-so 搜索函数 |
| `feedgrab/cli.py` | 修改 | xhs-so 命令 + doctor xhs 增强 |
| `feedgrab/config.py` | 修改 | 7 个 XHS API 配置函数 |
| `feedgrab/schema.py` | 修改 | from_xiaohongshu 扩展 extra 字段 |
| `feedgrab/utils/storage.py` | 修改 | 评论渲染到 Markdown 末尾 |
| `pyproject.toml` | 修改 | xhs 可选依赖组 |
| `.env.example` | 修改 | XHS API 配置项说明 |

### xhs-so 用法
```
feedgrab xhs-so "AI Agent"                           # 综合搜索
feedgrab xhs-so "AI Agent" --sort popular             # 按热门排序
feedgrab xhs-so "AI Agent" --type video               # 只搜视频
feedgrab xhs-so "AI Agent" --sort latest --limit 50   # 最新 50 条
feedgrab xhs-so "AI Agent" --save                     # 同时保存单篇 .md
```

输出：`{OUTPUT_DIR}/XHS/search/{排序}/{关键词}_{日期}.{md,csv}`

### 移植来源
从 [jackwener/xiaohongshu-cli](https://github.com/jackwener/xiaohongshu-cli) v0.6.0 移植核心能力：
- 请求/重试/限速逻辑（Gaussian 抖动 + 验证码冷却 + 指数退避）
- API 端点定义（Feed/UserPosted/SearchNotes/Comments）
- xsec_token LRU 缓存
- 签名配置（适配 feedgrab 真实 UA/平台）

**不集成**的部分：写操作、QR 登录、通知系统、创作者平台。

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.14 · 批量抓取数据完整性 + 线程退化保护

### 背景
全面审计所有 Twitter 批量抓取路径后发现两个问题：
1. `_build_single_tweet_data()` 缺少 8 个扩展元数据字段（`quote_count`/`lang`/`source_app`/`possibly_sensitive`/`is_blue_verified`/`followers_count`/`statuses_count`/`listed_count`），导致批量模式单条保存的推文 front matter 不如 GraphQL 全线程抓取完整
2. 书签/用户推文/搜索补充/列表抓取中，线程推文 `_fetch_via_graphql()` 失败时异常冒泡，导致整条推文被跳过而非退化为单条保存

### 方案决策
- **扩展元数据**：在 `_build_single_tweet_data()` 中补齐 8 个字段，全部 5 个批量 fetcher 共用此函数，改一处全部生效
- **线程退化保护**：在 4 个文件的 thread 分支中加 try/except，GraphQL 线程重建失败时退化为 `_build_single_tweet_data()` 单条保存（`api_user_tweets` 已有统一 GraphQL try/except 无需改动）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | `_build_single_tweet_data()` 新增 8 个扩展元数据 + thread 退化保护 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | thread 退化保护 |
| `feedgrab/fetchers/twitter_search_tweets.py` | 修改 | thread 退化保护 |
| `feedgrab/fetchers/twitter_list_tweets.py` | 修改 | thread 退化保护 |

### 验证结果
- 代码审查确认 `extract_tweet_data()` 已填充全部 8 个字段 ✅
- 5 个批量 fetcher 全部 import `_build_single_tweet_data()`，改一处全部受益 ✅
- 线程退化：4 个文件 + `api_user_tweets` 已有 = 全部 5 个批量 fetcher 覆盖 ✅

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.13 · 批量 Article 优先 GraphQL content_state（消除 Jina 瓶颈）

### 背景
用户发现书签批量抓取中，Article 长文章走了 Jina Reader（每篇 ~10-15 秒，2 次 HTTP + hollow 修补），而非预期的 GraphQL 优先策略。经排查发现 v0.6.2 新增 `_render_article_body()` 时只更新了单篇路径（`twitter.py`），5 个批量 fetcher 的 article 分支从未同步更新，仍然直接调 Jina。实际上 GraphQL 层已在 `extract_tweet_data()` → `_extract_article_ref()` 中渲染好了 `article["body"]`，但批量分支不看这个字段。

### 方案决策
- 在所有批量 fetcher 的 article 分支中，先检查 `article.get("body")` 是否存在且 >200 字
- 有：直接使用 GraphQL content_state 渲染结果，零额外网络请求
- 无：fallback 到 `_fetch_article_body()` 走 Jina（与单篇路径 `_try_fetch_article_body()` 的 Priority 1/2 策略一致）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | article 分支新增 content_state 优先检查 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | 同上 |
| `feedgrab/fetchers/twitter_list_tweets.py` | 修改 | 同上 |
| `feedgrab/fetchers/twitter_search_tweets.py` | 修改 | 同上 |
| `feedgrab/fetchers/twitter_api_user_tweets.py` | 修改 | 同上 |

### 验证结果
- 书签文件夹 `手机卡esim`（19 条，8 篇 Article）：全部 8 篇 Article 走 GraphQL content_state ✅
- 修复前：~3 分钟（每篇 Article ~10-15s Jina）→ 修复后：**~30 秒**（零 Jina 调用）
- 日志确认：`Article — GraphQL content_state: @author` 而非 `Jina fetch`

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.12 · `feedgrab doctor` 诊断命令

### 背景
feedgrab 的 Twitter 集成依赖多个组件（Cookie、queryId、x-client-transaction-id、可选依赖、网络连通性），任一环节出问题都会导致抓取失败。用户排障困难，需要逐一检查。参考 twitter-cli 的 `twitter doctor` 命令实现一键诊断。

### 方案决策
- **按平台分区**：`feedgrab doctor [x|xhs|mpweixin]`，不带参数则全平台检查
- **Twitter/X 检查**：可选依赖 → Cookie 状态 → queryId 解析 → x-client-transaction-id 生成 → x.com + 社区源连通性
- **小红书检查**：浏览器引擎 → session 存在性 → xiaohongshu.com 连通性
- **微信公众号检查**：浏览器引擎 → wechat.json session 存在性 + 过期检测（>96h）→ mp.weixin.qq.com 连通性
- **三级状态**：✅ passed / ⚠️ warning / ❌ error，汇总输出，每个失败项附带修复指令

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/cli.py` | 修改 | 新增 `cmd_doctor()` 函数（~120 行）+ `main()` 路由 + help 信息 |

### 验证结果
- `feedgrab doctor x` — 13/13 全过 ✅
- `feedgrab doctor xhs` — 正确提示 session 未登录 ⚠️
- `feedgrab doctor mpweixin` — 正确检测 session 过期（153h > 96h 阈值）⚠️
- `feedgrab doctor` — 全平台检查正常 ✅

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.11 · Feature Flags 动态更新

### 背景
feedgrab 的 GraphQL features 字典是硬编码的，Twitter 前端迭代后可能新增或修改 feature flag 的默认值，导致请求参数过时。参考 [jackwener/twitter-cli](https://github.com/jackwener/twitter-cli) 从 x.com 主页 HTML 提取当前 feature 开关值的做法，实现动态同步。

### 方案决策
- **正则提取**：`_update_features_from_html(html)` 用正则 `"key": { "value": true/false }` 从 x.com 主页内联脚本中提取 feature flag 值
- **只更新已有 key**：绝不新增 key（避免 URL 膨胀），仅更新 7 个 features 字典中已存在的 key
- **零额外 HTTP 请求**：复用 `_get_transaction_id()` 已获取/缓存的 `home_html`，在 transaction 初始化后立即调用
- **实测效果**：检测到 33 个 flag 变化（如 `tweet_awards_web_tipping_enabled: True→False`、`responsive_web_grok_image_annotation_enabled: False→True`）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `_ALL_FEATURES_DICTS` 注册表 + `_update_features_from_html()` 提取函数；在 `_get_transaction_id()` 中调用 |

### 验证结果
- `feedgrab x-so "Claude Code" --days 1 --limit 3` — 33 flags 动态更新 + SearchTimeline 正常 ✅
- `feedgrab https://x.com/0xMilkRabbit/status/...` — TweetDetail Tier 0 命中 ✅

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.10 · Feature Flags 紧凑编码

### 背景
Twitter GraphQL 请求的 URL 中包含 `features` 参数，包含约 30 个 feature flag（True/False 布尔值）。当前实现将所有 flag 都发送（包括 False 值），导致 URL 过长，增加被 HTTP 414 URI Too Long 拒绝的风险。参考 [jackwener/twitter-cli](https://github.com/jackwener/twitter-cli) 只发送 True 值的做法进行优化。

### 方案决策
- **紧凑编码**：在 `_execute_graphql()` 中，将 `features` dict 过滤为只含 True 值的子集后再 JSON 序列化。Twitter 服务端将缺失的 key 视为 false，行为不变
- **效果**：SearchTimeline URL 减少约 689 字节（~30%），其他端点减少约 485 字节

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | `_execute_graphql()` 中新增 `compact_features` 过滤，仅发送 True 值的 features |

### 验证结果
- `feedgrab x-so "Claude Code" --days 1 --limit 3` — SearchTimeline 正常 ✅
- `feedgrab https://x.com/0xMilkRabbit/status/2032018202134212868` — TweetDetail Tier 0 命中 ✅

### 状态：已完成 ✅

---

## 2026-03-12 · v0.9.9 · GraphQL 冷启动加速（磁盘缓存 + 社区 queryId 源）

### 背景
每次 feedgrab 进程启动时，`_get_transaction_id()` 需要请求 x.com 首页 + ondemand.s JS 文件（2 次 HTTP，~3-5 秒）来初始化签名生成器；`resolve_query_ids()` 需要请求首页 + 多个 JS chunk 来解析 queryId（3-8 次 HTTP）。对 `feedgrab x-so` 等频繁使用的命令，冷启动延迟体感明显。参考 [jackwener/twitter-cli](https://github.com/jackwener/twitter-cli) 的磁盘缓存和社区 queryId 源方案进行优化。

### 方案决策
- **x-client-transaction-id 磁盘缓存**：将 x.com 首页 HTML + ondemand.s JS 缓存到 `{data_dir}/cache/twitter_transaction_cache.json`（1 小时 TTL）。进程重启时从磁盘加载，避免 2 次 HTTP 请求。同时将 `home_html` 填充到 `_cached_home_html`，使 queryId JS 扫描也受益
- **queryId 社区源**：新增 `fa0311/twitter-openapi` 社区维护的 queryId 源作为 Tier 1（单次 HTTP 请求获取 87 个 queryId）。解析优先级变为：Tier 0 磁盘缓存 → Tier 1 社区源 → Tier 2 JS bundle 扫描 → Tier 3 硬编码回退。queryId 也缓存到磁盘（`twitter_queryid_cache.json`，1 小时 TTL）
- **Fallback queryIds 更新**：7 个硬编码 fallback queryId 更新为社区源最新值（`SearchTimeline`、`TweetDetail`、`Bookmarks`、`UserTweets` 等）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增磁盘缓存辅助函数（`_load_transaction_cache`/`_save_transaction_cache`/`_load_queryid_cache`/`_save_queryid_cache`）、社区源函数（`_resolve_community_query_ids`）；改造 `_get_transaction_id()` 支持磁盘缓存；改造 `resolve_query_ids()` 支持四级优先级；更新 7 个 fallback queryId |

### 验证结果
- `feedgrab x-so "Claude Code" --days 1 --limit 3` — 首次运行：社区源获取 87 个 queryId，搜索正常 ✅
- 二次运行：queryId + transaction-id 均命中磁盘缓存，零 HTTP 请求 ✅
- `feedgrab https://x.com/0xMilkRabbit/status/...` — Tier 0 GraphQL 一次命中，社区 queryId 正常 ✅
- `feedgrab https://x.com/hualun/status/...` — Tier 0 GraphQL 一次命中 ✅
- 冷启动性能：~5s → ~1s（社区源）；热启动：~3s → **0s**（全磁盘缓存）

### 状态：已完成 ✅

---

## 2026-03-07 · v0.9.8 · x-so 纯 GraphQL 升级 + x-client-transaction-id 反检测

### 背景
v0.9.7 的 `x-so` 命令使用 headed 浏览器（Playwright）打开 Twitter 搜索页面，通过滚动加载 + GraphQL 响应拦截收集推文数据。问题：需要弹出浏览器窗口、占用桌面、启动慢（~10 秒）、滚动等待慢。`twitter_graphql.py` 中已有 `fetch_search_timeline_page()` 纯 GraphQL 函数，应该直接复用。

### 方案决策
- **纯 GraphQL 替代浏览器**：`search_twitter_keyword()` 改为同步函数，直接调用 `fetch_search_timeline_page()` 分页获取搜索结果，无需 Playwright 浏览器
- **`x-client-transaction-id` 反检测**：Twitter 对 SearchTimeline 端点强制要求此签名头（缺失返回 404）。集成 `XClientTransaction` 库在 `_execute_graphql()` 中自动为所有 GraphQL 请求生成此头。算法基于 x.com 主页 SVG 动画 + `ondemand.s` JS 索引 + SHA-256 签名
- **优雅降级**：未安装 `XClientTransaction` 时警告提示，不影响不需要此头的端点（如 TweetDetail）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `_get_transaction_id()` 生成 x-client-transaction-id，注入 `_execute_graphql()` |
| `feedgrab/fetchers/twitter_keyword_search.py` | 修改 | 替换浏览器搜索为纯 GraphQL 分页调用，`async def` → `def` |
| `feedgrab/cli.py` | 修改 | `asyncio.run()` → 直接调用（不再需要 async） |
| `pyproject.toml` | 修改 | 新增 `twitter` 可选依赖组（XClientTransaction + beautifulsoup4） |

### 验证结果
- `feedgrab x-so "AI Agent" --days 1 --limit 5` — 秒级完成，无浏览器弹出 ✅
- `feedgrab x-so openclaw --days 3 --sort top --limit 10` — 热门排序正常 ✅
- 单篇推文抓取 `feedgrab https://x.com/xxx/status/xxx` — TweetDetail 正常工作 ✅
- x-client-transaction-id 30 分钟缓存复用 ✅

### 追加优化（同日）
- **输出格式优化**：`cssclasses: wide` front matter + emoji 表头 + 日期列前移 + 居中对齐
- **排序改为按查看数**：默认按 `views` 降序排列（替代原互动加权公式）
- **内容摘要超链接**：MD 中去掉独立链接列，摘要文本直接作为超链接
- **CSV 同步输出**：同目录生成 `.csv` 文件（UTF-8 BOM，Excel 友好），保留明文链接列
- **蓝 V 标记 + 显示名**：作者列优先使用 `author_name`（显示名）替代 `@handle`，蓝 V 认证作者前加 ✅ emoji
- **微信 URL 参数清理**：自动剥离 `scene`/`click_id`/`sessionid` 等追踪参数，仅保留 `__biz`/`mid`/`idx`/`sn` 四个文章标识参数，解决 PowerShell `&` 解析冲突和去重索引不一致问题

### 状态：已完成 ✅

---

## 2026-03-07 · v0.9.7 · Twitter 关键词搜索（x-so 命令）

### 背景
feedgrab 已有 Twitter 单篇/书签/用户推文/列表等抓取方式，但缺少按关键词搜索 Twitter 的能力。用户需要快速了解某个关键词（如 "openclaw"）在 Twitter 上的讨论热度和观点分布，输出按互动量排序的汇总表格即可，不需要逐篇保存。

### 方案决策
- **浏览器搜索 + GraphQL 拦截**：复用 `twitter_search_tweets.py` 的 `SearchResponseCollector` 和 `_scroll_and_collect_search()`，通过 `page.on("response")` 拦截 SearchTimeline GraphQL 响应获取结构化数据
- **汇总表格为主**：默认只输出一个按互动量排序的 Markdown 表格（YAML front matter + 表格），不保存单篇推文 .md
- **可选单篇保存**：`X_SEARCH_SAVE_TWEETS=true` 或 `--save` 开关，保存完整推文到子目录
- **自动引号包装**：`feedgrab x-so openclaw` 自动在搜索时添加引号精确匹配，用户无需手动加引号
- **Raw 模式**：`--raw` 标志让用户完全控制搜索查询语法（lang/since/filter 等操作符）
- **互动排序公式**：`likes*3 + retweets*2 + bookmarks*2 + replies`
- **配置默认值**：11 个 `X_SEARCH_*` 环境变量提供默认语言(zh)、天数(1)、排序(live)等

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_keyword_search.py` | 新建 | 核心搜索逻辑（查询拼接 + 浏览器搜索 + 互动排序 + 表格生成） |
| `feedgrab/cli.py` | 修改 | 新增 `x-so` 命令路由 + `cmd_twitter_search()` |
| `feedgrab/config.py` | 修改 | 新增 `x_search_*` 系列 11 个配置函数 |
| `.env.example` | 修改 | 新增 Twitter/X 关键词搜索配置段 |

### 验证结果
- `feedgrab x-so openclaw` — 40 条推文，按互动排序输出汇总表 ✅
- 查询自动构建：`"openclaw" lang:zh since:2026-03-06 -is:retweet` ✅
- YAML front matter 包含 query/total/search_tab/created ✅
- 表格含 作者/内容摘要/👍/🔄/💬/👁/📌/日期/链接 九列 ✅

### 状态：已完成 ✅

---

## 2026-03-07 · v0.9.6 · GitHub 仓库 README 抓取（中文优先）

### 背景
feedgrab 在平台覆盖上缺少 GitHub 支持。用户需要丢一个 GitHub 仓库 URL，就能自动抓取 README（中文优先）并保存为 Obsidian Markdown。支持仓库首页、README 文件页、其他内页三种 URL 格式，统一回退到仓库级别。

### 方案决策
- **GitHub REST API**：3 次 API 调用完成抓取（仓库元数据 + 根目录列表 + README 内容），无需浏览器
- **中文 README 优先**：列出根目录所有文件，按优先级匹配 8 种中文 README 变体（`README_CN.md`、`README.zh-CN.md` 等），匹配后直接获取中文版本
- **README 摘要提取**：从 README 内容中提取第一行有意义的描述文本作为标题（跳过 heading、badge、HTML、blockquote、短文本），替代 GitHub API 的英文 description
- **仓库级去重**：`item_id = MD5("{owner}/{repo}")[:12]`，同一仓库无论从哪个 URL 进入都产生相同 ID
- **无 Token 可用**：未配置 `GITHUB_TOKEN` 时 60 次/小时（按 IP），配置后 5000 次/小时
- **URL 解析**：`parse_github_url()` 统一处理仓库首页/blob 文件页/tree 目录页/issues 等内页，取前两段 path 作为 owner/repo

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/github.py` | 新建 | GitHub REST API 抓取核心（URL 解析 + 元数据 + 中文 README 优先 + 摘要提取） |
| `feedgrab/schema.py` | 修改 | 新增 `SourceType.GITHUB` 枚举值 + `from_github()` 工厂方法 |
| `feedgrab/reader.py` | 修改 | 新增 `github.com` 域名检测 + 路由分发 + 多平台去重映射 |
| `feedgrab/utils/storage.py` | 修改 | 新增 GitHub 文件夹映射 + 文件名格式（`{owner}_{repo}：{摘要}`）+ front matter |
| `feedgrab/config.py` | 修改 | 新增 `github_token()` 配置函数 |
| `.env.example` | 修改 | 新增 `GITHUB_TOKEN` 配置说明 |

### 验证结果
- `feedgrab https://github.com/iBigQiang/feedgrab` — 仓库首页抓取 ✅，文件名 `iBigQiang_feedgrab：万能内容抓取器 — 从任意平台抓取、转录和消化内容。.md`
- `feedgrab https://github.com/iBigQiang/feedgrab/blob/main/README.md` — README 文件页 ✅，正确回退到仓库级别
- `feedgrab https://github.com/iBigQiang/feedgrab/tree/main/feedgrab/fetchers` — 内页 URL ✅，正确回退到仓库级别
- `feedgrab https://github.com/nicepkg/aide` — 中文 README 优先 ✅，检测到 `README_CN.md` 并使用
- front matter 包含 stars/forks/language/license/topics 等完整元数据 ✅
- 去重索引生成在 `GitHub/index/item_id_url.json` ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.5 · YouTube Data API v3 搜索 + 单视频下载命令

### 背景
feedgrab 原有的 YouTube 抓取仅依赖 Jina Reader 获取元数据，缺少搜索能力和视频/音频/字幕文件下载能力。对比分析了 yt-search-download 和 union-search-skill 两个第三方仓库后，决定融合 YouTube Data API v3 实现搜索模块，同时升级单视频抓取为 API 优先策略。

### 方案决策
- **YouTube Data API v3 搜索**：免费 10,000 quota/天，search.list=100 单位，videos.list=1 单位。两阶段查询：search → videoId list → videos.list 批量详情
- **API 优先单视频**：替代 Jina-first 元数据获取，1 quota 单位获取完整元数据（标题/作者/时长/播放量/标签/缩略图/字幕标记）
- **多语言字幕回退**：`[sub_lang, "zh-CN", "zh-Hans", "zh-Hant", "zh", "en", "en-US"]`，覆盖手动字幕和自动字幕
- **yt-dlp JS 运行时修复**：yt-dlp 默认只启用 deno，`_js_runtime_args()` 自动检测 deno/node/bun 并加 `--remote-components ejs:github`
- **三个下载命令**：`ytb-dlv`(视频MP4)、`ytb-dla`(音频MP3)、`ytb-dlz`(字幕SRT)，输出目录和文件名与 MD 保持一致
- **频道搜索修复**：channel 限定搜索时跳过 `regionCode`/`relevanceLanguage` 参数（会导致空结果）
- **Cookie 检测简化**：移除不可靠的自动检测（Windows 上 Chrome DB 锁定），改为 `YT_COOKIES_BROWSER` 环境变量控制

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/youtube_search.py` | 新建 | YouTube Data API v3 搜索引擎 + yt-dlp 下载（视频/音频/字幕） |
| `feedgrab/fetchers/youtube.py` | 重写 | API 优先元数据 + 多语言字幕回退 + JS 运行时修复 |
| `feedgrab/cli.py` | 修改 | 新增 `ytb-so`/`ytb-dlv`/`ytb-dla`/`ytb-dlz` 四个命令 |
| `feedgrab/schema.py` | 修改 | `from_youtube()` 扩展支持完整 API 元数据（时长/播放量/标签等） |
| `feedgrab/utils/storage.py` | 修改 | YouTube 文件名前缀 + front matter + 封面图 + 字幕分段 |
| `.env.example` | 修改 | 新增 YouTube API 配置项模板 |

### 验证结果
- `feedgrab ytb-so "AI Agent"` — 搜索成功，10 条结果保存到 `YouTube/search/AI Agent/` ✅
- `feedgrab ytb-so "教程" --channel @Fireship --limit 3` — 频道限定搜索 3 条结果 ✅
- `feedgrab https://www.youtube.com/watch?v=g56TThyELm0` — API 元数据 + zh-Hant 字幕成功 ✅
- `feedgrab https://www.youtube.com/watch?v=bBG25aoIS0s` — zh-CN 手动字幕成功（修复前失败） ✅
- `feedgrab ytb-dlv <url>` — 视频下载到 `{OUTPUT_DIR}/YouTube/` 目录 ✅
- `feedgrab ytb-dla <url>` — 音频下载，长链接和 youtu.be 短链接都兼容 ✅
- `feedgrab ytb-dlz <url>` — 字幕 SRT 下载成功 ✅
- 文件名格式统一：`author_date：title.{mp4,mp3,srt,md}` ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.4 · 微信单篇抓取策略反转：Browser 优先

### 背景
微信单篇抓取原先采用 Jina 优先策略（Tier 1 Jina → Tier 2 Browser → Tier 3 Browser retry），但实际运行中 Jina 几乎每次都因微信 CDN 超时而白等 30 秒，且返回数据不完整（缺少 author/date/cover/tags）。而 Browser 使用 WeChat JS evaluate 提取的数据最全（9 类元数据 + 富文本 Markdown），成功率高。参考 X/Twitter 的 GraphQL 优先策略，将 Browser 提升为 Tier 1。

### 方案决策
- 反转抓取层级：Browser → Jina → Browser retry（与 X/Twitter 的 GraphQL-first 策略对齐）
- 提取 `_browser_fetch()` 内部函数，Tier 1 和 Tier 3 复用同一段浏览器抓取逻辑
- Jina 降级为 Tier 2 轻量兜底，仅在浏览器环境不可用时触发

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/wechat.py` | 重写 | 抓取策略从 Jina→Browser 反转为 Browser→Jina→Browser retry |

### 验证结果
- 普通长文（`mp.weixin.qq.com/s/pQioMCCW9sCOZ1BW8fRD9A`）：Browser Tier 1 直接成功，约 4 秒完成（原方案需 34+ 秒等待 Jina 超时）✅
- 小绿书图片帖（`mp.weixin.qq.com/s/lk60C8tBWknMzFTQRUIFTQ`）：Browser Tier 1 成功提取标题+作者+内容 ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.3 · 微信代码块修复 + 小绿书元数据回退

### 背景
微信公众号文章中使用 plain `<pre><code>` 格式的代码块在抓取后所有行被压缩为一行，原因是 `BeautifulSoup.get_text()` 丢弃了 `<br>` 标签的换行语义。同时，当文章包含 10+ 个代码块时，占位符还原出现前缀碰撞（`WECHAT-CODEBLOCK-1` 匹配到 `WECHAT-CODEBLOCK-10` 的前缀），导致部分代码块被错误替换并残留数字尾巴。此外，markdownify 在处理占位符时吃掉了两侧的换行，导致代码围栏（` ``` `）与相邻图片/文本粘连。

另一个问题：微信"小绿书"图片帖（`itemShowType=16`）的 DOM 结构与普通长文不同 — `#activity-name` 和 `#js_name` 元素不存在，导致标题和作者提取全部为空，文件名缺少 `作者名_日期：` 前缀。

### 方案决策

**代码块修复（3 个子问题）：**
1. `<br>` → `\n`：在 `_preprocess_wechat_html()` 的两个代码块处理器中（`.code-snippet__fix` 和 plain `<pre>`），调用 `get_text()` 前先将所有 `<br>` 标签替换为 `\n` 文本节点
2. 占位符前缀碰撞：还原时反向遍历（从最大索引到 0），避免 `CODEBLOCK-1` 匹配 `CODEBLOCK-10`
3. 围栏间距：还原时在 fence 前后加 `\n\n`，确保代码块与相邻内容有空行分隔

**小绿书元数据回退（`WECHAT_ARTICLE_JS_EVALUATE` 增强）：**
- 标题回退链：`#activity-name` → `og:title` → `.rich_media_title`
- 作者回退链：`#js_name` → JS 脚本 `nick_name` 正则 → `window.cgiDataNew.nick_name`

通过 Playwright 实测确认：小绿书页面的 `cgiDataNew` 对象包含完整的 `nick_name`（如 "饼干哥哥AGI"）和 `title`，是最可靠的回退数据源。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/wechat_search.py` | 修改 | `_preprocess_wechat_html()` 两处 `<br>→\n` + `_html_to_markdown()` 反向还原 + fence 间距 |
| `feedgrab/fetchers/browser.py` | 修改 | `WECHAT_ARTICLE_JS_EVALUATE` 新增标题/作者三级回退 |

### 验证结果
- 代码块测试（`mp.weixin.qq.com/s/pQioMCCW9sCOZ1BW8fRD9A`，12 个 plain `<pre>` 块）：
  - 12 个代码块全部正确识别和还原 ✅
  - Python/JSON/Prompt 内容有正确的多行格式（86 行、55 行、31 行等）✅
  - 代码围栏与相邻图片有空行分隔 ✅
  - 无占位符残留数字 ✅
- 小绿书测试（`mp.weixin.qq.com/s/lk60C8tBWknMzFTQRUIFTQ`）：
  - 标题 "X上疯传 从2050个n8n 工作流中总结出的🔟个要点"（`og:title`）✅
  - 作者 "饼干哥哥AGI"（`cgiDataNew.nick_name`）✅
  - 发布日期 "2025-08-03 23:44"（`create_time`）✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.2 · 微信公众号按账号批量抓取 + cgiDataNew 元数据管线

### 背景
feedgrab 已支持微信公众号单篇抓取和搜狗搜索批量抓取，但缺少按公众号账号批量枚举全部历史文章的能力。通过分析 [wechat-article-exporter](https://github.com/nichenke/wechat-article-exporter) 的 MP 后台 API 逆向方案，发现可以利用 `feedgrab login wechat` 保存的 MP 后台 session，调用 `searchbiz`（搜索公众号→fakeid）和 `appmsgpublish`（分页文章列表）API 实现全量枚举。

同时调研了 `window.cgiDataNew.user_info.appmsg_bar_data` 的阅读量/点赞/评论提取可行性。测试结果：匿名访问时 `appmsg_bar_data` 为空对象，互动数据需要微信认证会话才会填充。代码已预埋管线，未来认证会话可用时自动启用。

### 方案决策

**MP 后台 API 按账号批量抓取**
1. `mpweixin_account.py` 新建：核心 fetcher，使用 Playwright `page.evaluate()` + `fetch(url, {credentials: 'include'})` 调用 MP API（自动携带 session cookie）。
2. `searchbiz` API：按名称搜索公众号，精确匹配优先，返回 fakeid。
3. `appmsgpublish` API：按 fakeid 分页枚举文章列表（每页 5 条），`publish_page.publish_list` 内含 `publish_info.appmsgex[]` 文章数组。
4. 日期过滤：`MPWEIXIN_ID_SINCE` 配置项控制截止日期，到达后停止分页。
5. 断点续传：`_progress_*.json` 缓存文件记录 `next_begin/fetched/skipped/failed`，中断后自动恢复。完成后自动清理。
6. 去重：复用 `utils/dedup.py` 的 `mpweixin` 平台索引，与搜狗搜索、单篇抓取共享。
7. 逐篇抓取：每篇文章在新标签页打开，复用 `evaluate_wechat_article()` + `_html_to_markdown()` 提取全文。
8. 输出目录：`{OUTPUT_DIR}/mpweixin/account/{公众号名}/`。
9. API title fallback：当浏览器页面提取 title 为空时，使用 API 返回的 title 作为回退。

**cgiDataNew 元数据管线**
1. `browser.py` 的 JS evaluate 新增第 8 段：提取 `window.cgiDataNew.user_info.appmsg_bar_data` 的 `read_num/old_like_count/like_count/share_count/comment_count`。
2. `_build_wechat_result()` 透传 cgiMetrics → `schema.py` → `storage.py` 条件输出（仅当 reads > 0 时展示）。

**storage.py 优化**
1. 文件名日期截断为仅日期（去掉时间部分 `[:10]`）。
2. WeChat 正文不再重复输出标题 heading。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/mpweixin_account.py` | 新建 | MP 后台 API 按账号批量抓取（searchbiz + appmsgpublish + 断点续传 + 去重） |
| `feedgrab/cli.py` | 修改 | 新增 `cmd_mpweixin_account()` + `mpweixin-id` 命令路由 |
| `feedgrab/config.py` | 修改 | 新增 `mpweixin_id_since()` + `mpweixin_id_delay()` |
| `feedgrab/fetchers/browser.py` | 修改 | 新增 cgiDataNew 元数据提取（JS evaluate 第 8 段） |
| `feedgrab/schema.py` | 修改 | `from_wechat()` 新增 reads/likes/wow/shares/comments 字段 |
| `feedgrab/utils/storage.py` | 修改 | WeChat 文件名日期截断 + 正文去标题 + 条件性互动指标输出 |
| `.env.example` | 修改 | 新增 `MPWEIXIN_ID_SINCE` + `MPWEIXIN_ID_DELAY` 配置 |

### 验证结果
- `MPWEIXIN_ID_SINCE=2025-08-01 feedgrab mpweixin-id "饼干哥哥AGI"` 实测：
  - Session 加载 + 账号搜索 + fakeid 获取 ✅
  - 文章分页枚举（每页 5 篇） ✅
  - 逐篇打开 + 全文提取 + Markdown 保存 ✅
  - 去重索引更新 ✅
  - 日期过滤停止 ✅
  - 已成功抓取 48+ 篇文章到 `mpweixin/account/饼干哥哥AGI/` ✅
  - 发现并修复 title fallback bug（部分文章 title 为空导致文件名异常） ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.1 · 微信公众号抓取增强（元数据 + markdownify + 图片防盗链）

### 背景
feedgrab 的微信公众号单篇抓取（`wechat.py`）浏览器回退路径使用通用 `innerText` 提取，丢失了标题层级、图片、链接等富文本结构，也无法提取封面图、发布日期、摘要等元数据。与 `wechat_search.py` 的深度提取能力存在差距。同时 `_html_to_markdown()` 使用手写正则转换 HTML，不支持表格、有序列表、代码块、h5-h6 等复杂结构。微信图片（mmbiz.qpic.cn）有 Referer 校验，在 Obsidian 中查看会 403。

通过对比分析 [wechat-article-to-markdown](https://github.com/jackwener/wechat-article-to-markdown) 和 [wechat-article-exporter](https://github.com/nichenke/wechat-article-exporter) 两个 GitHub 项目，提取了可融合的技术方案。

### 方案决策（三阶段）

**P0 — 元数据提取 + 路径统一**
1. `browser.py` 新增 `WECHAT_ARTICLE_JS_EVALUATE`：在 JS 层面一次性提取 `#activity-name`（标题）、`#js_name`（作者）、`#publish_time`（发布时间）、`og:image`（封面）、`og:description`（摘要）、`#js_tags`（标签）、`#js_view_source`（原文链接）、`create_time`（三层正则从 JS 脚本提取精确时间戳）、`msg_cdn_url`（高质量封面图）、`#js_content innerHTML`（富文本 HTML）。
2. `browser.py` 新增 `_build_wechat_result()` + `evaluate_wechat_article()` 统一处理函数。
3. `wechat.py` Tier 2 从通用 `fetch_via_browser()` 改为 `evaluate_wechat_article()` + `_html_to_markdown()`，与 `wechat_search.py` 共享同一套提取逻辑。
4. `schema.py` `from_wechat()` 更新：cover_image 优先级（文章页 > 搜狗缩略图）、tags 支持、新增 extra 字段。
5. `storage.py` 修复 WeChat `cover_image` 重复输出。

**P1 — markdownify 替换正则转换器**
1. `wechat_search.py` 的 `_html_to_markdown()` 重写：markdownify + BeautifulSoup 预处理。
2. `_preprocess_wechat_html()` 处理：lazy image（data-src→src）、SVG/tracking pixel 过滤、WeChat `.code-snippet__fix` 代码块（占位符策略）、噪音元素移除。
3. 移除旧的 `_WECHAT_EXTRACT_JS` 和 `_strip_tags()` 正则转换器。

**P2 — 图片防盗链修复**
1. `storage.py` 为 WeChat 文章在 front matter 后插入 `<meta name="referrer" content="no-referrer">`，让 Obsidian/浏览器不发送 Referer，避免 mmbiz.qpic.cn 图片 403。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/browser.py` | 修改 | 新增 `WECHAT_ARTICLE_JS_EVALUATE` + `_build_wechat_result()` + `evaluate_wechat_article()` |
| `feedgrab/fetchers/wechat.py` | 修改 | Tier 2 改为 WeChat 专用提取（evaluate_wechat_article + _html_to_markdown） |
| `feedgrab/fetchers/wechat_search.py` | 修改 | `_html_to_markdown()` 重写（markdownify + BS4 预处理 + 代码块占位符） |
| `feedgrab/schema.py` | 修改 | `from_wechat()` 更新 cover_image 优先级 + tags + 新 extra 字段 |
| `feedgrab/utils/storage.py` | 修改 | WeChat cover_image 去重 + no-referrer meta 标签 |
| `pyproject.toml` | 修改 | 新增 `wechat` 依赖组（markdownify + beautifulsoup4） |

### 验证结果
- 单篇抓取 `mp.weixin.qq.com/s/ng_0-madiZ2eiXBU2dTNgQ`：
  - 标题 "给OpenClaw开天眼！解决了10个跨境电商网站爬虫难题" ✅
  - 作者 "饼干哥哥AGI" ✅
  - 发布日期 "2026-03-03 19:02"（create_time JS 提取） ✅
  - 封面图 msg_cdn_url 高质量 ✅
  - 摘要 "解决90%跨境数据抓取问题。"（og:description） ✅
  - 富文本保留：##/### 标题层级、超链接、图片、有序/无序列表 ✅
  - cover_image 不再重复 ✅
  - no-referrer meta 标签已插入 ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.9.0 · curl_cffi TLS 指纹 + 搜狗浏览器统一

### 背景
feedgrab 的 HTTP 请求使用标准 `requests` 库，Python 默认 TLS 指纹（JA3/JA4）与真实浏览器差异明显，服务端可在 TLS 握手阶段直接识别为机器流量。此外，搜狗微信搜索存在 HTTP 搜索→浏览器抓取的"指纹分裂"——搜索用 urllib（Python TLS），抓取用 Playwright（Chrome TLS），两阶段指纹不一致。

### 方案决策
1. **统一 HTTP 客户端**（`utils/http_client.py`）：curl_cffi `Session(impersonate="chrome")` 模拟 Chrome TLS 指纹（JA3/JA4 完全匹配），fallback 到标准 requests。连接复用（persistent session）。异常兼容层将 curl_cffi 异常重新包装为 `requests.Timeout`/`requests.ConnectionError`/`requests.RequestException`。`raise_for_status()` 辅助函数确保 curl_cffi Response 的状态码异常也被包装为 `requests.HTTPError`。
2. **全量迁移**：9 个文件的 `requests.get()`/`requests.post()`/`urllib.request.urlopen()` 全部迁移到 `http_client.get()`/`http_client.post()`，异常处理代码无需改动。
3. **搜狗搜索浏览器统一**：`fetch_content=True` 时搜索也走浏览器（获取 Cookie + 提取结果一步完成），消除 HTTP↔浏览器指纹分裂。HTTP 模式仅在浏览器不可用时兜底。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/utils/http_client.py` | 新建 | 统一 HTTP 客户端：curl_cffi TLS 指纹 → requests fallback + 异常兼容 + raise_for_status |
| `feedgrab/fetchers/jina.py` | 修改 | 2 个 `requests.get` → `http_client.get` |
| `feedgrab/fetchers/bilibili.py` | 修改 | 1 个 `requests.get` → `http_client.get` |
| `feedgrab/fetchers/twitter.py` | 修改 | 2 个 `requests.get`（Syndication + oEmbed）→ `http_client.get` |
| `feedgrab/fetchers/twitter_fxtwitter.py` | 修改 | `urllib.request.urlopen` → `http_client.get` + 异常处理重写 |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 3 个 `requests.get`（GraphQL + JS bundle）→ `http_client.get` |
| `feedgrab/fetchers/twitter_api.py` | 修改 | 1 个 `requests.get`（付费 API）→ `http_client.get` |
| `feedgrab/fetchers/wechat_search.py` | 修改 | `urllib.request.urlopen` → `http_client.get` + 浏览器搜索统一 |
| `feedgrab/fetchers/youtube.py` | 修改 | 1 个 `requests.post`（Whisper）→ `http_client.post` |
| `pyproject.toml` | 修改 | `curl_cffi>=0.7` 加入 stealth/all 依赖组 |

### 验证结果
- curl_cffi 引擎正确启用：UA 显示 Chrome/142.0.0.0
- Jina Reader 端到端测试：200 OK，内容正确
- `raise_for_status` 兼容性：404 响应正确抛出 `requests.HTTPError`
- 所有 9 个模块导入无错误
- 本地 CDP 连接（twitter_cookies.py）保持原样不迁移

### 状态：已完成 ✅

## 2026-03-06 · v0.8.4 · Referer 伪装 + 资源拦截

### 背景
浏览器导航无 referer（从 about:blank 直接访问目标站），服务端可轻易识别为机器流量。批量抓取时加载了所有字体、媒体、tracking 脚本，浪费带宽且拖慢速度。

### 方案决策
1. **Referer 伪装**（adapted from Scrapling `fingerprints.py`）：根据目标 URL 域名自动生成搜索引擎 referer — 中国平台→百度、其他→Google。短子域名（en/mp/m/api）自动跳过取主域名。仅首次导航设置，后续页面间导航由浏览器自动携带前一页 URL。
2. **资源拦截**（adapted from Scrapling `navigation.py`）：在 context 级别通过 `route("**/*")` 拦截 7 类非必要资源（font/media/beacon/websocket/manifest/texttrack/eventsource）+ 11 个 tracking 域名（Google Analytics/GTM/Facebook/Hotjar/Sentry 等）。保留 image/stylesheet/xhr 确保 SPA 渲染和内容提取不受影响。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/browser.py` | 修改 | 新增 `generate_referer()` + `setup_resource_blocking()` + `fetch_via_browser()` 应用两者 |
| `feedgrab/fetchers/xhs_user_notes.py` | 修改 | context 级资源拦截 + 首次导航 referer |
| `feedgrab/fetchers/xhs_search_notes.py` | 修改 | context 级资源拦截 + 首次导航 referer |
| `feedgrab/fetchers/wechat_search.py` | 修改 | context 级资源拦截 + 首次导航 referer |

### 验证结果
- Referer 生成正确：XHS/微信→百度，通用→Google，子域名（en/mp/m）正确跳过
- 端到端测试（sspai.com）：81 请求通过 + 7 请求拦截（6 字体 + 1 tracking 脚本），页面正常提取
- 所有 4 个模块导入无错误

### 状态：已完成 ✅

## 2026-03-06 · v0.8.3 · browserforge 浏览器指纹一致性

### 背景
feedgrab 各 HTTP 模块的 User-Agent 和请求头严重不一致：jina.py 使用 `feedgrab/0.1`（直接暴露工具身份），twitter_fxtwitter.py 和 twitter.py 使用极简的 `Mozilla/5.0`，wechat_search.py 使用另一个独立的完整 UA 但缺少 Sec-Ch-Ua 配套。这些不一致容易被服务器识别为非真实浏览器流量。

### 方案决策
引入 browserforge 库生成完整且内部一致的浏览器请求头集合（UA + sec-ch-ua + Accept + Sec-Fetch 等 11 项），缓存到会话级别。

关键设计：
- **版本号精确匹配**：从 `BROWSER_USER_AGENT` 环境变量提取 Chrome 版本号，browserforge 按该版本 pin 生成匹配的 sec-ch-ua，确保 `Chrome/132` 对应 `"Google Chrome";v="132"`
- **OS 自动检测**：`platform.system()` → browserforge OS 参数，header 与实际运行平台一致
- **分层使用**：API 调用（Jina/FxTwitter/Syndication）仅统一 UA，HTML 页面请求（搜狗）用全套 header
- **优雅降级 + 提示**：browserforge 未安装时 loguru WARNING 输出安装指导，降级为基础 header

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/config.py` | 修改 | 新增 `get_stealth_headers()` — browserforge 全套一致 header 生成 + 会话缓存 + 降级提示 |
| `feedgrab/fetchers/jina.py` | 修改 | UA: `feedgrab/0.1` → `get_user_agent()` |
| `feedgrab/fetchers/twitter_fxtwitter.py` | 修改 | UA: `Mozilla/5.0` → `get_user_agent()` + 新增 import |
| `feedgrab/fetchers/twitter.py` | 修改 | Syndication UA: `Mozilla/5.0` → `get_user_agent()` |
| `feedgrab/fetchers/wechat_search.py` | 修改 | 3 个硬编码 header → `get_stealth_headers()` 全套 11 个 |
| `pyproject.toml` | 修改 | `browserforge>=1.1` 加入 stealth/all 依赖组 |

### 验证结果
- browserforge 生成 11 项一致 header，UA Chrome/132 与 sec-ch-ua "Google Chrome";v="132" 精确匹配
- BROWSER_USER_AGENT 环境变量覆盖（Chrome/133）→ sec-ch-ua 自动匹配 v="133"
- 浏览器 context UA、HTTP header UA、config UA 三处完全一致
- 所有 6 个修改模块导入无错误
- browserforge 未安装时正确输出 WARNING 提示及安装命令

### 状态：已完成 ✅

---

## 2026-03-06 · v0.8.2 · 隐身浏览器引擎升级（patchright + stealth flags）

### 背景
feedgrab 的 Playwright 浏览器抓取方案反检测能力极弱——仅有一条 `--disable-blink-features=AutomationControlled` 启动参数，几乎等于"裸奔"。小红书（反爬最严格）和搜狗微信搜索容易被识别为自动化流量。

通过深度分析 [Scrapling](https://github.com/D4Vinci/Scrapling) 项目的反检测技术方案，发现其 patchright + stealth flags + 环境伪装的组合方案投入产出比极高，可以精准移植到 feedgrab。

### 方案决策
- **不直接替换 playwright**，而是 patchright 前置为 Tier 1、playwright 兜底为 Tier 3（间隔编号预留扩展空间）
- **集中管理隐身配置**：在 `browser.py` 新增统一的 stealth 工具函数，所有 fetcher 共享
- 从 Scrapling 适配 52 条 Chrome 隐身启动参数 + 5 条有害默认参数屏蔽
- 浏览器 context 补全环境伪装（viewport/screen/locale/color_scheme/device_scale_factor 等）
- `pyproject.toml` 新增 `stealth` 可选依赖组

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/browser.py` | 重写 | 新增 stealth 引擎模块（双引擎选择 + 52 条启动参数 + context 反指纹配置 + stealth_launch/get_stealth_context_options 工具函数）；重写 fetch_via_browser 使用新引擎 |
| `feedgrab/fetchers/xhs_user_notes.py` | 修改 | 替换为 stealth 引擎，移除硬编码 playwright import 和旧参数 |
| `feedgrab/fetchers/xhs_search_notes.py` | 修改 | 同上 |
| `feedgrab/fetchers/wechat_search.py` | 修改 | 同上 |
| `pyproject.toml` | 修改 | 新增 `stealth = ["patchright>=1.0"]` 可选依赖 |

### 验证结果
- patchright 引擎自动检测：`get_stealth_engine_name()` → `"patchright"` ✅
- 未安装 patchright 时自动降级：→ `"playwright"` ✅
- 通用网页（少数派）：headless 模式，3,043 字符 ✅
- 通用网页（Wikipedia）：headless 模式，84,341 字符 ✅
- XHS 小红书：自动切换 headed 模式 + session 加载 ✅
- 所有文件语法检查通过 ✅

### 状态：已完成 ✅

---

## 2026-03-06 · v0.8.1 · 搜狗微信搜索增强（mpweixin 目录 + 配置开关 + 多页 + 富文本）

### 背景
v0.8.0 搜狗微信搜索功能上线后的实测反馈：
1. 输出目录 `WeChat/search/` 不够明确（WeChat 易与个人微信混淆），需改为 `mpweixin/search_sogou/{keyword}/`
2. 默认 10 篇太少，需要多页抓取支持和配置开关
3. 正文通过 Jina/browser.py 通用链抓取时丢失所有格式（只有 `innerText` 纯文本），需要富文本 Markdown
4. 搜索元数据（公众号名、日期、缩略图、摘要）未保存到 md 文件
5. Sogou antispider 拦截 headless 浏览器和直接 HTTP 跳转

### 方案决策
- **目录重命名**：`WeChat/` → `mpweixin/`，搜索子目录 `search_sogou/{keyword}/`
- **配置开关**：`MPWEIXIN_SOGOU_ENABLED`（默认 false）、`MPWEIXIN_SOGOU_MAX_RESULTS`（默认 10，上限 100）、`MPWEIXIN_SOGOU_DELAY`
- **多页搜索**：`_sogou_search_multi()` 按需翻页（每页 10 条，搜狗最多约 10 页）
- **反爬绕过**：headed 浏览器 + 先访问搜索页获取 Cookie → 从同 context 新标签页访问跳转链接
- **富文本**：直接用已有浏览器实例提取 `#js_content` HTML，自定义 `_html_to_markdown()` 转换（h1-h4/bold/italic/img data-src/link/list/blockquote）
- **元数据完整**：`from_wechat()` 新增 `extra` 传递 publish_date/thumbnail/summary/search_keyword → front matter + 正文开头封面图

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/wechat_search.py` | 重写 | 多页搜索 + 浏览器直提 HTML→Markdown + 反爬 Cookie 策略 |
| `feedgrab/config.py` | 修改 | 新增 `mpweixin_sogou_*` 配置函数 |
| `feedgrab/cli.py` | 修改 | 配置开关检查 + `--limit` 覆盖 |
| `feedgrab/schema.py` | 修改 | `from_wechat()` 传递搜索元数据 + 封面图前置 |
| `feedgrab/utils/storage.py` | 修改 | WeChat→mpweixin 目录 + front matter 元数据 + 文件名带公众号+日期 |
| `.env.example` | 修改 | 新增 `MPWEIXIN_SOGOU_*` 配置项文档 |

### 验证结果
- `MPWEIXIN_SOGOU_ENABLED=true feedgrab mpweixin-so openclaw --limit 2` → 2/2 成功
- 输出路径：`mpweixin/search_sogou/openclaw/人人都是产品经理_2026-02-17：OpenClaw 被 OpenAI 收购了。.md`
- 富文本：**加粗**、*斜体*、`![image](mmbiz.qpic.cn/...)` 图片、段落分隔均正确
- front matter：title/source/author/published/thumbnail/summary/search_keyword 完整
- 未启用时：`feedgrab mpweixin-so xxx` 提示 "Set MPWEIXIN_SOGOU_ENABLED=true"

### 状态：已完成 ✅

---

## 2026-03-06 · v0.8.0 · FxTwitter Tier 0.3 兜底 + 搜狗微信搜索

### 背景
1. 分析了 [x-tweet-fetcher](https://github.com/ythx-101/x-tweet-fetcher) 项目，发现其核心数据源为 FxTwitter 公共 API（`api.fxtwitter.com`），无需认证即可获取丰富的推文数据，完整度显著高于 Syndication。
2. 搜狗微信搜索（`weixin.sogou.com`）可按关键词发现微信公众号文章，补充现有的单篇微信抓取能力。

### 方案决策
- **FxTwitter Tier 0.3**：插入 GraphQL（Tier 0）和 Syndication（Tier 0.5）之间，数据完整度接近 GraphQL（有 views/bookmarks/Article Draft.js），缺少 blue_verified/listed_count/线程展开。单篇失败直接降级；批量模式连续 3 次失败触发 circuit breaker，当前任务后续跳过 FxTwitter。
- **搜狗微信搜索**：新增 `feedgrab mpweixin-so <keyword>` 命令，通过搜狗搜索发现文章 → Playwright 解析加密跳转 → 复用现有 wechat.py 抓取全文 → 去重保存。
- **六级兜底链**：GraphQL → FxTwitter → Syndication → oEmbed → Jina → Playwright

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_fxtwitter.py` | 新建 | FxTwitter API 客户端 + circuit breaker + Article Draft.js 渲染 |
| `feedgrab/fetchers/wechat_search.py` | 新建 | 搜狗微信搜索（HTML 解析 + Playwright 跳转解析 + 批量抓取） |
| `feedgrab/fetchers/twitter.py` | 修改 | 插入 Tier 0.3 FxTwitter 兜底层 |
| `feedgrab/cli.py` | 修改 | 新增 `mpweixin-so` 命令 + 帮助文本 |
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 任务启动时 reset circuit breaker |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | 任务启动时 reset circuit breaker |
| `feedgrab/fetchers/twitter_list_tweets.py` | 修改 | 任务启动时 reset circuit breaker |
| `feedgrab/fetchers/twitter_api_user_tweets.py` | 修改 | 任务启动时 reset circuit breaker |
| `强子笔记/x-tweet-fetcher技术方案分析.md` | 新建 | x-tweet-fetcher 架构分析报告 |
| `强子笔记/FxTwitter与搜狗微信搜索评估报告.md` | 新建 | FxTwitter + 搜狗微信搜索数据完整度评估 |

### 验证结果
- FxTwitter API 实测：普通推文、Article 长文数据完整返回（views/bookmarks/Article Draft.js blocks）
- 搜狗微信搜索实测："openclaw" 返回 10 条结果（标题/摘要/公众号名/时间戳/缩略图）
- 搜狗跳转链接 HTTP 直请求触发反爬 → 改用 Playwright 浏览器解析
- Circuit breaker 逻辑验证通过（3 次连续失败后停用 FxTwitter）

### 状态：已完成 ✅

---

## 2026-03-05 · v0.7.1 · tweet_type 分类 + 日期解析修复

### 背景
1. 需要在 Obsidian 中通过元数据字段筛选不同类型的推文（普通/线程/长文），新增 `tweet_type` 字段。
2. berryxia 的长文缺少 `published` 发布时间，而同类型的长文正常。排查发现 `parse_twitter_date_local()` 的 ISO 8601 格式检测使用 `"T" in created_at`，会误匹配星期名称中的 `T`（如 `Tue`、`Thu`），导致走错分支解析失败。

### 方案决策
- **tweet_type 分类**：在 `from_twitter()` 中根据 `is_article`/线程长度判定 `status`/`thread`/`article`，输出到 front matter
- **日期解析修复**：将 `"T" in created_at` 改为 `re.search(r"\d{4}-\d{2}-\d{2}T", created_at)` 精确匹配 ISO 8601 的 `YYYY-MM-DDT` 模式

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/config.py` | 修改 | 修复 ISO 8601 日期检测误匹配 `Tue`/`Thu` 中的 `T` |
| `feedgrab/schema.py` | 修改 | `from_twitter()` 新增 `tweet_type` 分类逻辑 |
| `feedgrab/utils/storage.py` | 修改 | front matter 输出 `tweet_type` 字段 |

### 验证结果
- berryxia 长文 `published: 2026-03-03` 正确输出（修复前为空）
- 所有日期格式（`Tue`/`Thu`/`Wed`/`Fri`/ISO 8601）均正确解析
- 三种类型的推文 front matter 字段完整一致

### 状态：已完成 ✅

---

## 2026-03-05 · v0.7.0 · GraphQL 数据完整提取 + 引用推文增强 + 富文本标记

### 背景
系统分析 GraphQL 返回的完整数据后，发现大量有价值数据未被提取：1）引用推文只拿到截断的 280 字 `full_text`，丢失完整长文、图片、视频；2）note_tweet 的 `richtext_tags`（粗体/斜体标记）完全忽略；3）作者信息（粉丝数、蓝标认证、发推数等）和推文元数据（被引用次数、语言、发布客户端等）未保存到 front matter。

### 方案决策
- **引用推文完整提取**：从 `quoted_status_result` 中提取 `note_tweet.text`（完整长文不截断）、展开 t.co 链接、提取图片/视频/互动指标，渲染为完整 blockquote
- **richtext_tags 转 Markdown**：`_apply_richtext_tags()` 将 Draft.js 索引式标记转换为 `**bold**`/`*italic*`，从末尾向前插入避免索引偏移
- **新增 8 个 front matter 字段**：`quotes`、`is_blue_verified`、`followers_count`、`statuses_count`、`listed_count`、`lang`、`source_app`、`possibly_sensitive`
- **title 净化**：`_clean_title()` 剥离 Markdown 格式标记，确保 title 是纯文本

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `_apply_richtext_tags()`、`_parse_source_app()`；`extract_tweet_data()` 增加 8 个新字段 + 引用推文完整提取（长文+媒体+指标+t.co展开+richtext） |
| `feedgrab/fetchers/twitter.py` | 修改 | `_fetch_via_graphql()` 两个分支透传新字段；`_clean_title()` 剥离 `**` 标记 |
| `feedgrab/schema.py` | 修改 | 新增 `_render_quoted_tweet()` 完整引用渲染（含图片/视频/URL）；`from_twitter()` extra 透传新字段 |
| `feedgrab/utils/storage.py` | 修改 | front matter 输出 8 个新元数据字段 |

### 验证结果
- `@binghe/status/2003639692542247190`（21条线程）：`AI**漫剧创业**` 粗体正确渲染；title 纯文本无 `**`；front matter 含 `is_blue_verified: true`、`followers_count: 40173`、`quotes: 2` 等完整元数据
- `@iBigQiang/status/2015088004109615266`（带引用推文）：引用推文完整长文+2张图片+t.co展开+作者URL全部到位；旧版仅一行截断文本

### 状态：已完成 ✅

---

## 2026-03-05 · v0.6.2 · Twitter Article GraphQL 原生渲染

### 背景
抓取 Twitter Article（长文）时，正文通过 Jina Reader 抓取 `/article/` 页面获得。但 Jina 的 Markdown 渲染器会丢掉 cashtag 链接（`$MODEL`、`$BASE_URL`）和 mention 链接（`@username`），导致保存的 Markdown 文件正文内容不完整。

### 方案决策
- **根因分析**：GraphQL API 的 `article.article_results.result.content_state` 已经包含完整的 Article 正文（Draft.js 富文本格式），之前未解析利用，错误地走了 Jina 抓取
- **GraphQL 原生渲染**：新增 `_render_article_body()` 将 Draft.js `content_state.blocks` 直接渲染为 Markdown，支持段落、标题、有序/无序列表、代码块、图片、引用块
- **零额外请求**：Article 正文数据随 TweetDetail GraphQL 请求一起返回，本地解析即可，不需要任何额外网络请求
- **Jina 降级为 fallback**：仅在 Syndication tier（无 content_state）时才走 Jina 抓取
- **Jina 空洞修补**：为 Jina fallback 路径新增 `_patch_jina_hollows()` — 检测 Markdown 中被丢掉的 cashtag/mention 空洞，用 Jina text 模式（`X-Return-Format: text`）修补

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `_render_article_body()` Draft.js → Markdown 渲染器；`_extract_article_ref()` 新增 `body` 字段 |
| `feedgrab/fetchers/twitter.py` | 修改 | `_try_fetch_article_body()` 优先用 GraphQL body，Jina 降为 fallback |
| `feedgrab/fetchers/jina.py` | 修改 | 新增 `fetch_via_jina_text()` 纯文本模式获取 |
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 新增 `_detect_hollows()` 和 `_patch_jina_hollows()` 空洞检测修补 |

### 验证结果
- 测试推文：`xiangxiang103/status/2029137537621737817`（含 PowerShell 代码块、`$MODEL` cashtag、`@username` mention 的 Article）
- `$MODEL`、`$BASE_URL`、`$API_KEY`：全部完整保留
- `@LawrenceW_Zen`、`@innomad_io`：全部完整保留
- 代码块（146 行 PowerShell）：格式正确
- 5 张内嵌图片 + cover image：全部输出
- 3 个 H2 标题 + 有序列表：格式正确
- 零 Jina 网络请求，耗时显著减少

### 状态：已完成 ✅

---

### 背景
保存的 Markdown 文件中，当 likes/bookmarks/replies 等指标值为 0 时会被省略，导致元数据缺失和"值为 0"无法区分，影响 Obsidian Dataview 查询准确性。

### 方案决策
- **全量输出指标**：Twitter（likes/retweets/replies/bookmarks/views）和小红书（likes/collects/comments）的指标无条件输出，包括值为 0 的字段
- **保持纯英文 key**：评估了中英双语 key 方案（如 `喜欢_likes`），因 Dataview 兼容性问题决定不采用，改为待实现的 Obsidian CSS/Types 用户侧方案

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/utils/storage.py` | 修改 | Twitter/XHS 指标去掉 `if val` 判断，全量输出 |
| `DEVLOG.md` | 修改 | 新增"待实现计划"区块（Obsidian 中文别名方案） |

### 状态：已完成 ✅

---

## 待实现计划

### Obsidian 元数据中文别名方案

**背景**：front matter key 保持纯英文（`likes`、`bookmarks`）以确保 Dataview 等插件兼容性，但中文用户阅读时希望能直观看到中文含义。

**方案**：通过 Obsidian 用户侧配置实现，不修改代码：
1. **CSS snippet** — 给 Properties 面板的 key 加中文 tooltip 或替换显示文字
2. **Obsidian Types** — 利用属性类型系统给 key 设置中文别名

**状态**：待实现。确定方案后编写用户教程，写入 README 文档。

---

## 2026-03-04 · v0.6.0 · Twitter List 列表批量抓取 + 目录结构优化

### 背景
用户订阅了 Twitter List（如 AI KOL 列表），希望定期批量抓取列表中最近 N 天的推文。同时优化所有批量模式的输出目录结构，使其更清晰易管理。

### 方案决策
- **GraphQL API**：复用 `ListByRestId`（列表元数据）+ `ListLatestTweetsTimeline`（列表推文分页），动态 queryId 解析 + 硬编码 fallback
- **日期过滤**：`X_LIST_TWEETS_DAYS`（默认1天），代码层按 `parse_twitter_date_local()` 过滤
- **会话去重**：预扫描 `conversation_id` 计数，多条目会话只处理根推文（`conv_id == tweet_id`），根推文自动升级为 thread 类型走 GraphQL 深度抓取
- **输出目录三层结构**：`lists_{N}day/{YYYYMMDD}/{列表名}/`，同一天的多个列表聚合在日期目录下
- **全模式目录优化**：用户推文 `status_author/{昵称}/`、书签 `bookmarks/{名称}/`、全部书签 `bookmarks/all/`
- **clean-index 命令**：清理索引目录中的批量记录和断点缓存，保留全局去重索引
- **Article 误判修复**：收紧 stub 判定（去掉 t.co 后剩余 < 30字符），防止正常推文误走 Jina
- **emoji SVG 过滤**：`_format_markdown()` 统一过滤 `abs-0.twimg.com/emoji/` 图片标签

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/config.py` | 修改 | 新增 List 相关配置函数 |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 List GraphQL API 支持 |
| `feedgrab/fetchers/twitter_list_tweets.py` | **新建** | List 批量抓取主逻辑 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | 输出目录改为 `status_author/{昵称}` |
| `feedgrab/fetchers/twitter_api_user_tweets.py` | 修改 | 输出目录改为 `status_author/{昵称}` |
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 输出目录改为 `bookmarks/{名称}` |
| `feedgrab/fetchers/twitter.py` | 修改 | 收紧 article stub 判定逻辑 |
| `feedgrab/utils/storage.py` | 修改 | emoji SVG 图片过滤 |
| `feedgrab/reader.py` | 修改 | URL 路由识别 `/i/lists/` |
| `feedgrab/cli.py` | 修改 | 新增 `clean-index` 命令 + List 批量模式 |
| `.env.example` | 修改 | 新增 List 配置项文档 |

### 验证结果
- "中推圈AI KOL" 列表：190 条推文成功抓取
- "虚拟资源" 列表：31 条条目 → 28 条保存 + 3 条会话去重跳过，0 重复文件
- 目录结构：`lists_1day/20260304/软件工具/`、`bookmarks/OpenClaw/`、`status_author/Geek/` 验证通过
- `feedgrab clean-index --yes`：42 个文件 28.7MB 清理成功
- Article 误判修复：含链接的正常推文不再误走 Jina

### 状态：已完成 ✅

---

## 2026-03-04 · v0.5.2 · Syndication API 作为 Tier 0.5 兜底

### 背景
Twitter 有一个免费、无需认证的 Syndication API（`cdn.syndication.twimg.com`），数据比 oEmbed 丰富得多（含媒体 URL、互动指标、用户信息）。作为 GraphQL 和 oEmbed 之间的降级兜底层，在 Cookie 过期/限流时仍能获取 80% 的数据。

### 方案决策
- **端点**：`https://cdn.syndication.twimg.com/tweet-result?id={tweetId}&token={token}`
- **Token 计算**：`((id / 1e15) * Math.PI).toString(36).replace(/(0+|\.)/g, '')`（参考 yt-dlp 和 Vercel react-tweet 逆向实现）
- **五级兜底**：Tier 0 GraphQL → **Tier 0.5 Syndication** → Tier 1 oEmbed → Tier 2 Jina → Tier 3 Playwright
- **数据能力**：文本、图片、视频、hashtags、likes、replies、article 检测（缺 retweets/bookmarks/views）
- **Article 检测**：Syndication 返回 article 字段时，复用 `_try_fetch_article_body()` 走 Jina 获取正文
- **cover_image 增强**：article cover > 显式 cover_image > 首张图片（三级回退）
- **日期解析**：`parse_twitter_date_local()` 新增 ISO 8601 支持（Syndication 返回 `2022-10-28T03:49:11.000Z` 格式）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter.py` | 修改 | 新增 `_fetch_via_syndication()`、`_syndication_token()`；提取 `_try_fetch_article_body()` 公共函数；调度器插入 Tier 0.5 |
| `feedgrab/config.py` | 修改 | `parse_twitter_date_local()` 新增 ISO 8601 格式支持 |
| `feedgrab/schema.py` | 修改 | `from_twitter()` cover_image 三级回退逻辑 |

### 验证结果
- Syndication API 成功获取推文文本、图片、视频 URL、互动数据
- Article 推文正确检测并通过 Jina 获取完整正文
- Token 计算与 yt-dlp/react-tweet 实现一致
- 有 Cookie 时正常走 GraphQL，Syndication 作为 GraphQL 失败后的第一降级层

### 参考
- [Vercel react-tweet](https://github.com/vercel/react-tweet) — Token 计算源码
- [yt-dlp PR #12107](https://github.com/yt-dlp/yt-dlp/pull/12107) — Python 端 Token 计算实现

### 状态：已完成 ✅

---

## 2026-03-04 · v0.5.1 · 修复 API 补充搜索操作符不可靠问题

### 背景
v0.5.0 的 API 补充抓取在 dontbesilent 等账号测试中返回 0 条推文。经三轮诊断发现 TwitterAPI.io 的搜索操作符全部不可靠：
- `until:` 超过 1 天前的日期 → 返回 0 条
- `since:` 截断结果（1514 条只返回 353 条）
- `max_id` 直接跳转到历史 ID → 返回 0 条
- 只有增量 `max_id`（从上一页最小 ID 递减）能正常工作

### 方案决策
**移除所有搜索操作符，改为纯代码层过滤**：
- 查询只用 `from:{screen_name}` + 增量 `max_id`（从最新向最旧翻页）
- `since_date` 过滤在代码中完成（解析每条推文的 `created_at`）
- 连续 3 页全部早于 `since_date` → 检测为搜索索引空洞，自动停止
- `initial_max_id` 参数标记为忽略（直接跳转不可行）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_api_user_tweets.py` | 修改 | 重写 `_discover_tweets_via_search()` 分页循环：移除 `since:`/`until:` 操作符，增加代码层日期过滤和索引空洞检测 |

### 验证结果
- **vista8 (向阳乔木)**：GraphQL 855 条 + API 补充 4211 条（217 页），`since_date=2025-01-01` 代码层过滤正确，在连续 3 页早于目标日期后自动停止
- **dontbesilent**：发现 345 条（搜索索引在近期推文和 2019 年之间有空洞，属 API 端限制）
- 搜索索引完整的账号补充抓取完全正常

### 状态：已完成 ✅

---

## 2026-03-03 · v0.5.0 · TwitterAPI.io 付费 API 接入 + Cookie 轮换 + 断点续传

### 背景
feedgrab 按账号批量抓取 X/Twitter 的两阶段方案（GraphQL UserTweets ~800 条 + Playwright 浏览器搜索补充）存在三个瓶颈：
1. **浏览器搜索不适合服务器部署**：Playwright 依赖有头浏览器，无法在无 GUI 服务器运行
2. **GraphQL 429 限流**：大量推文需要逐条 GraphQL 调用，单账号容易被限流
3. **中断丢失**：发现阶段全在内存，中途崩溃（如 API 401/网络断开）所有数据丢失

### 方案决策

#### 1. TwitterAPI.io 付费 API（替代浏览器搜索补充）
- **Advanced Search API**：`$0.15/千条`，支持 `from:user since:date` 等高级搜索语法
- **两种接入模式**：
  - `X_API_PROVIDER=graphql`（默认）：GraphQL 主流程 + API 补充（替代浏览器搜索）
  - `X_API_PROVIDER=api`：全量走付费 API（服务器部署，无需 Cookie）

#### 2. max_id 分页（而非 cursor 分页）
实测 TwitterAPI.io 的 cursor 分页对大账号不完整（op7418 2.3 万推文只返回 130 条），而 `max_id:{last_id - 1}` 写在搜索查询中的 ID 分页方案返回完整结果：

| 分页方式 | dontbesilent (1497条) | op7418 (23000条) |
|---------|----------------------|------------------|
| cursor | 178 条 (12%) | 130 条 (0.6%) |
| **max_id** | **1497 条 (100%)** | **8889 条** |

#### 3. Smart Direct Save（智能直保）
`X_API_SAVE_DIRECTLY=true` 时，普通推文直接用 API 数据保存（跳过 GraphQL），仅长文(article)和线程(thread)强制走 GraphQL 获取完整媒体/正文。大幅减少 GraphQL 调用次数和 429 风险。

#### 4. Cookie 多账号轮换
- `sessions/` 目录支持多个 Cookie 文件：`twitter.json`（主）+ `x_2.json` + `x_3.json`...
- GraphQL 429 时自动标记当前账号，下次请求切换到未限流账号
- 15 分钟冷却期后自动恢复

#### 5. 断点续传
- **Phase 1 (发现)**：每页推文实时写入 `.api_discovery_{username}.jsonl` 缓存，中断后从最小 ID 处续传
- **Phase 2 (处理)**：dedup 索引每 50 条自动持久化，重跑时自动跳过已保存推文

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_api.py` | 新建 | TwitterAPI.io HTTP 客户端（重试/退避/认证错误处理） |
| `feedgrab/fetchers/twitter_api_user_tweets.py` | 新建 | API 批量抓取（发现+过滤+处理+断点续传+缓存） |
| `feedgrab/fetchers/twitter_cookies.py` | 修改 | 多账号加载 + 429 轮换（15 分钟冷却自动恢复） |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 429 时触发 Cookie 轮换标记 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | 补充触发点加 API 分支（有 API Key → API 补充，否则浏览器搜索） |
| `feedgrab/reader.py` | 修改 | `X_API_PROVIDER=api` 全量 API 路径路由 |
| `feedgrab/config.py` | 修改 | 新增 6 个配置函数（API Key/Provider/Save Mode/互动过滤） |
| `.env.example` | 修改 | TwitterAPI.io 配置段 + Cookie 轮换教程 + F12 获取方法 |
| `sessions/x_2.json` | 新建 | 第二个 Cookie 账号模板文件 |

### 验证结果
- **API 发现**：op7418 测试 449 页 / 8889 条推文，max_id 分页稳定、零间隙
- **Smart Direct Save**：8889 条推文中 ~14% 需要 GraphQL（线程/长文），其余直接 API 保存
- **Cookie 轮换**：2 个账号环境测试，429 后自动切换，轮换逻辑正确
- **断点续传**：缓存 JSONL 实时写入，`is_complete` 标记正常

### 状态：已完成 ✅

---

## 2026-03-02 · v0.4.0 · 浏览器搜索补充抓取 — 突破 UserTweets 800 条限制

### 背景
`feedgrab https://x.com/dontbesilent` 按账号全量抓取受 Twitter UserTweets API 服务端限制，每次最多返回 ~800 条推文。该博主 2025 年全年活跃，但只能抓到 2025-12-08 之后的内容。需要一种补充方案获取更早的历史推文。

### 方案决策

#### 方案演进（3 次迭代）
1. **SearchTimeline GraphQL API 直接调用**（最初方案）— queryId 频繁变化，即使从浏览器 DevTools 获取正确 queryId，请求仍返回 404（URL 编码差异或 headers 校验）
2. **页面 JS 注入拦截 XHR**（第二次尝试）— `page.goto()` 导航后 JS 环境重置，注入的拦截器丢失，无法捕获首批 GraphQL 响应
3. **Playwright `page.on("response")` 事件**（最终方案）— 在 Python 层面注册响应拦截器，跨导航持久有效，捕获所有 SearchTimeline GraphQL 响应

#### 最终架构
```
阶段1: UserTweets GraphQL API（现有，~800条，纯 API 高速）
         ↓ 检测到历史缺口（earliest_tweet_date > X_USER_TWEETS_SINCE）
阶段2: Playwright 浏览器搜索补充（新增）
         → 启动 Chrome + 加载 sessions/twitter.json
         → 预热访问 x.com/home 激活 session
         → 按月分片导航到 x.com/search?q=from:user since:X until:Y
         → page.on("response") 拦截 SearchTimeline GraphQL 响应
         → 自动滚动加载更多 → 解析推文 → 去重 → 保存 Markdown
```

#### 关键设计
- **SearchResponseCollector 类**：Python 层面的响应拦截器，通过 `page.on("response")` 注册，解析 `data.search_by_raw_query.search_timeline.timeline.instructions` 路径
- **Session 预热**：先访问 x.com/home 激活登录态，再导航到搜索页
- **URL 格式**：`urllib.parse.quote()` 编码，不带 `&f=live` 参数（匹配浏览器手动搜索行为）
- **月度分片**：从 UserTweets 最早日期往回按月分片，连续 3 个空月度提前终止
- **去重共享**：两阶段共用同一个 `item_id_url.json` 索引
- **API 格式兼容**：修复 `extract_tweet_data()` 兼容新版 Twitter API（`screen_name`/`name` 从 `user_legacy` 移到 `user_core`）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_search_tweets.py` | 新建 | 浏览器搜索补充模块（SearchResponseCollector + 月度分片 + 滚动采集） |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | SearchTimeline API 常量/函数 + `extract_tweet_data()` 兼容新版 API 格式 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | 集成搜索补充调用 + earliest_tweet_date 检测 |
| `feedgrab/config.py` | 修改 | 新增 `x_search_supplementary_enabled()` + `x_search_max_pages_per_chunk()` |
| `.env.example` | 修改 | 新增搜索补充配置说明 |

### 验证结果
- 测试用户 `@dontbesilent`（X_USER_TWEETS_SINCE=2025-01-01）
- 阶段1 UserTweets API：~800 条推文（2025-12-08 ~ 2026-03-01），索引 1003 条
- 阶段2 浏览器搜索补充：处理 774 条，新增 284 条，跳过 490 条（去重），失败 0 条
- 最终索引：1003 → 1290 条，总增 287 条历史推文
- 注意：后期月度分片可能因平台风控返回空结果（非数据缺失）

### 状态：已完成 ✅

---

## 2026-03-01 · v0.3.2 · Article 正文抓取修复 + GraphQL 单篇重试

### 背景
批量抓取 `@dontbesilent` 全量推文时发现两个问题：
1. **Article 正文为垃圾内容**：长文推文（如 `dontbesilent/status/2023370066734338381`）保存的 Markdown 正文是 Twitter 登录页 chrome（"New to X?", "Sign up now"...），而非文章正文。根因是 Jina 通过 `/status/` URL 抓取时返回登录页，垃圾内容 >200 字符通过了长度校验
2. **GraphQL 单篇无重试**：单篇推文的 GraphQL 调用失败（连接重置或 RuntimeError）时直接降级到 oEmbed，丢失元数据（likes/views/bookmarks 等）

### 方案决策

#### Article 正文抓取：垃圾检测 + article URL 优先
- 新增 `_is_jina_garbage()` — 匹配 9 个 Twitter 页面 chrome 特征词，命中 ≥2 个判定为垃圾
- 新增 `_fetch_article_body()` 共享函数 — 优先用 `/article/{id}` URL（从 GraphQL 元数据中的 `article.rest_id` 构建），失败后回退 `/status/` URL，每个 URL 重试 2 次，全程带垃圾检测
- 3 处 article 分支（`twitter.py`、`twitter_bookmarks.py`、`twitter_user_tweets.py`）统一调用共享函数，消除重复代码

#### GraphQL 单篇重试：统一重试循环
- 将 `_fetch_via_graphql` 调用包裹在 try/except 重试循环中（1 次初始 + 3 次重试，间隔 5 秒）
- 同时覆盖"返回空数据"和"抛出 RuntimeError"两种失败模式
- Auth 错误（401/403）不重试，直接抛出到外层降级处理

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 新增 `_is_jina_garbage()` + `_fetch_article_body()` 共享函数；article 分支简化为调用共享函数 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | article 分支简化为调用 `_fetch_article_body()`；新增 import |
| `feedgrab/fetchers/twitter.py` | 修改 | GraphQL 单篇重试逻辑（try/except 循环）；article 分支简化为调用 `_fetch_article_body()` |

### 验证结果
- `_is_jina_garbage()` 单元验证：垃圾内容（"New to X?", "Sign up now"...）→ True，正常文章内容 → False
- 3 个模块 import 测试通过

### 状态：已完成 ✅

---

## 2026-03-01 · v0.3.1 · 日期时区修复 + 视频嵌入 + 分页增强

### 背景
真实抓取 `@dontbesilent` 全量推文时发现三个问题：
1. **日期差一天**：推文网页显示"2025年12月26日"，但抓取结果为 `published: 2025-12-25`。根因是 Twitter API 返回 UTC 时间，代码直接 `strftime` 未转本地时区
2. **视频丢失**：含视频的推文只保存了封面截图，没有视频 MP4 链接。`extract_tweet_data()` 正确提取了 `videos`，但 `from_twitter()` 只渲染 `images` 忽略了 `videos`
3. **分页不全**：默认 `X_USER_TWEET_MAX_PAGES=50`（≈1000 条），高产博主不够。且分页请求失败（连接重置）时无重试直接中断

### 方案决策

#### 日期时区：集中化工具函数
- 在 `config.py` 新增 `parse_twitter_date_local(created_at, fmt)` 工具函数
- 核心逻辑：`parsedate_to_datetime()` → `dt.astimezone()`（UTC→系统本地时区）→ `strftime()`
- 替换 4 处分散的日期解析代码，统一走此函数
- `astimezone()` 无参数使用系统时区（Python 3.9+ 内置），无需额外依赖

#### 视频嵌入：双渲染（封面图+视频链接）
- 在 `from_twitter()` 的 Article 模式和普通线程模式两处，images 循环后追加 videos 循环
- 格式 `[▶ video](mp4_url)`，与 `twitter_markdown.py` 一致
- 封面图保留作为 Obsidian 内视觉预览

#### 分页增强：扩容+重试
- 默认最大页数 50→200（≈4000 条推文）
- 分页请求失败后重试 3 次，每次间隔 5 秒

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/config.py` | 修改 | 新增 `parse_twitter_date_local()` 工具函数；`x_user_tweet_max_pages()` 默认值 50→200 |
| `feedgrab/utils/storage.py` | 修改 | 3 处日期解析替换为 `parse_twitter_date_local()` 调用（`_format_twitter_datetime` / `_generate_filename` / `_format_markdown`） |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | `_parse_tweet_date()` 替换为 `parse_twitter_date_local()`；分页失败后重试 3 次（5 秒间隔） |
| `feedgrab/schema.py` | 修改 | `from_twitter()` Article 模式和线程模式两处添加 videos 渲染 `[▶ video](mp4_url)` |
| `.env.example` | 修改 | 更新 `X_USER_TWEET_MAX_PAGES` 默认值注释 50→200 |

### 验证结果
**日期修复**：推文 `dontbesilent/status/2004233380997796009`（UTC 16:50 Dec 25）
- 修复前：文件名 `dontbesilent_2025-12-25：...`，front matter `published: 2025-12-25`
- 修复后：文件名 `dontbesilent_2025-12-26：...`，front matter `published: 2025-12-26`（与 Twitter 网页一致）

**视频嵌入**：同一推文含视频
- 修复前：只有 `![image](...amplify_video_thumb...jpg)` 封面截图
- 修复后：封面图 + `[▶ video](...mp4?tag=21)` 视频链接并存

### 状态：已完成 ✅

---

## 2026-02-28 · v0.3.0 · feedgrab setup 一键部署引导

### 背景
当前首次部署需要用户手动执行多个命令（`detect-ua`、`login xhs`、`login twitter`、配置 `.env` 等），且存在隐式依赖（必须先 `detect-ua` 再 `login`，否则 UA 不一致导致 session 失效）。对普通用户门槛过高。

### 方案
新增 `feedgrab setup` 命令，一键按顺序引导完成所有部署步骤：

```
$ feedgrab setup

[1/4] 检查依赖环境...
  ✅ Python 3.10+
  ✅ Playwright 已安装
  ✅ Chrome 浏览器已检测到

[2/4] 检测浏览器指纹...
  🔍 读取本机 Chrome User-Agent...
  ✅ Chrome/145.0.0.0 已写入 .env

[3/4] 平台登录（可按需跳过）
  🔑 登录小红书？(Y/n) y
  🌐 请在弹出的浏览器窗口中扫码登录...
  ✅ 小红书 session 已保存

  🔑 登录 Twitter/X？(Y/n) n
  ⏭ 已跳过（后续可用 feedgrab login twitter 单独登录）

[4/4] 创建配置文件...
  ✅ .env 已生成（基于 .env.example）

🎉 部署完成！试试：
  feedgrab "https://www.xiaohongshu.com/explore/xxx"
```

### 设计原则
- **命令名 `feedgrab setup`**：语义明确，不与"启动服务"混淆
- **顺序强绑定**：`detect-ua` 必须在所有 `login` 之前执行，确保 UA 一致
- **每步可跳过**：用户按需选择要登录的平台
- **幂等可重入**：重复运行时检测到已完成的步骤自动跳过（如 UA 已检测、session 未过期）
- **Cookie 过期提示**：抓取时检测到 session 失效，提示 `feedgrab setup` 或 `feedgrab login <platform>` 重新登录
- **依赖自动安装**：检测 Playwright 未安装时提示一键安装命令

### 状态：已完成 ✅

---

## 2026-02-28 · v0.2.9 · 小红书搜索结果批量抓取 + UA 一致性修复

### 背景
v0.2.8 完成了按作者主页批量抓取。用户希望新增按搜索关键词批量抓取：在小红书搜索关键词后，给定搜索结果页 URL，批量抓取搜索到的笔记。同时发现 `feedgrab login xhs` 创建的 session 频繁过期，根因是 User-Agent 不一致。

### 方案决策

#### 搜索批量抓取
- **复用三层策略**：搜索结果页和作者主页技术架构完全一致（Vue 3 SSR + 瀑布流），复用同一套 Tier 0/1/2 策略
- **Tier 0**：`__INITIAL_STATE__.search.feeds`（~40 篇，零 API 调用）— 与作者页的 `user.notes` 路径不同
- **Tier 1**：XHR 拦截 `/api/sns/web/v1/search/notes`（与作者页的 `user_posted` 端点不同）
- **Tier 2**：逐篇导航 + `evaluate_xhs_note()` 深度提取（与作者页完全复用）
- **目录命名**：`search_{关键词}`（如 `search_开学第一课`）
- **URL 双重解码**：搜索 URL 中 keyword 可能被双重编码（`%25E5%25BC%2580`），循环 unquote 直到稳定
- **无日期过滤**：搜索结果按相关性排序（非时间顺序），日期过滤无意义

#### User-Agent 集中管理
- **根因**：`login.py` 硬编码 macOS + Chrome 120 UA，而批量抓取使用 Windows + Chrome 132 UA，8 处独立硬编码
- **影响**：同一 session 的 UA 从 Mac 切换到 Windows，触发 XHS 风控导致 session 失效
- **修复方案**：
  - `config.py` 新增 `DEFAULT_USER_AGENT` 常量 + `get_user_agent()` 函数
  - 优先读取 `BROWSER_USER_AGENT` 环境变量，缺省使用内置默认值
  - **8 处硬编码**全部替换为 `get_user_agent()` 调用：`login.py`(2处)、`browser.py`、`twitter.py`、`bilibili.py`、`twitter_cookies.py`、`xhs_search_notes.py`、`xhs_user_notes.py`
  - 新增 `feedgrab detect-ua` CLI 命令：启动本机真实 Chrome → 读取 `navigator.userAgent` → 自动写入 `.env`
  - 首次部署时运行 `feedgrab detect-ua` 即可获取真实环境 UA，确保登录和抓取完全一致

### 数据流

```
feedgrab "https://www.xiaohongshu.com/search_result?keyword=开学第一课&source=..."
  → reader._detect_platform() → "xhs_search"
  → reader._read_search_notes(url)
    → xhs_search_notes.fetch_search_notes(url)
      ├─ _parse_search_url() → keyword = "开学第一课"（双重 URL decode）
      ├─ 启动 Playwright 有头 Chrome（复用 xhs.json session）
      ├─ 检测验证码 → _handle_captcha_or_login()（从 xhs_user_notes 复用）
      ├─ Tier 0: state.search.feeds → 40 篇
      ├─ Tier 1: XHR 拦截 /api/sns/web/v1/search/notes + 滚动加载
      ├─ Tier 2: 逐篇 evaluate_xhs_note() + save_to_markdown()
      ├─ 去重索引更新（platform="XHS"，与作者批量共享索引）
      └─ 批量记录 → XHS/index/search_{keyword}_all_{ts}.json
```

### 搜索页面结构（实测结果）

**`__INITIAL_STATE__`**:
- 路径：`state.search.feeds`（Array，~40 项）
- 每项：`{id, modelType, xsecToken, noteCard: {displayTitle, type, user, interactInfo}}`
- 注意：`noteCard.noteId` 为空，笔记 ID 在 `item.id`（与作者页 `user.notes` 不同）
- 字段命名：camelCase（Vue 响应式对象）

**XHR 分页 API**:
- 端点：`edith.xiaohongshu.com/api/sns/web/v1/search/notes`（POST）
- 响应：`{code: 0, data: {has_more, items}}`，每页 ~22 条
- items 字段命名：snake_case（`note_card`, `xsec_token`, `display_title`）

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/xhs_search_notes.py` | **新建** ~280行 | 搜索批量抓取核心：Tier 0 `search.feeds` + Tier 1 `search/notes` XHR 拦截 + Tier 2 逐篇深度 |
| `feedgrab/fetchers/xhs_user_notes.py` | 修改 ~15行 | `_handle_captcha_or_login()` 通用化：参数从 `profile_url` 改为 `target_url`，URL 检查兼容 `/search_result` |
| `feedgrab/reader.py` | 修改 ~25行 | URL 检测 `/search_result` → `xhs_search` + 路由 + `_read_search_notes()` |
| `feedgrab/config.py` | 新增 ~20行 | `xhs_search_enabled()` / `xhs_search_max_scrolls()` / `xhs_search_delay()` |
| `feedgrab/cli.py` | 修改 ~5行 | 帮助文本 + 搜索 URL 批量输出检测 |
| `feedgrab/login.py` | 修改 ~4行 | UA 统一为 Windows + Chrome 132（修复 session 频繁过期） |
| `.env.example` | 新增 ~4行 | `XHS_SEARCH_ENABLED` / `XHS_SEARCH_MAX_SCROLLS` / `XHS_SEARCH_DELAY` |

### 目录结构

```
{OUTPUT_DIR}/XHS/
├── index/
│   ├── item_id_url.json                         ← XHS 全局去重索引（搜索+作者共享）
│   ├── notes_墨客老师资料库_all_*.json            ← 作者批量记录
│   └── search_开学第一课_all_*.json              ← 搜索批量记录
├── notes_墨客老师资料库/                          ← 作者批量笔记
└── search_开学第一课/                             ← 搜索批量笔记（多作者混合）
    ├── 安安老师_2026-02-25：新学期开学第一课这样上🔥被校长夸爆了.md
    ├── 沐然老师_2026-02-26：开学第一课，三年级这样上超轻松！.md
    └── ...
```

### 验证结果
- **Tier 0**：40 篇搜索结果提取成功
- **Tier 2 深度抓取**：38 成功，2 去重跳过（与作者批量重叠），0 失败
- **去重回归**：第二次运行 37 跳过 + 3 新增（搜索结果动态变化属正常）
- **文件名**：全部包含正确日期格式 `作者_YYYY-MM-DD：标题.md`
- **Front matter**：完整（likes/collects/comments/tags/images/location/author_url/cover_image）
- **source URL**：含 xsec_token，链接可直接访问
- **跨模式去重**：搜索结果中出现的笔记如果已被作者批量抓取过，正确跳过

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.8 · 小红书按作者批量抓取

### 背景
v0.2.7 完成了 XHS 单篇深度抓取（图片、互动数据、标签、日期、作者主页）。用户希望新增按作者主页批量抓取：给定主页 URL（如 `https://www.xiaohongshu.com/user/profile/5eb416f...`），批量抓取该博主所有笔记。参照已有的 Twitter 用户推文批量抓取 (`twitter_user_tweets.py`) 模式。

### 核心挑战

XHS 没有公开 API，且反爬机制严格：
1. **无公开 API**：必须用 Playwright 浏览器打开主页 → 滚动加载瀑布流 → 收集笔记 URL → 逐一提取完整数据
2. **461 反机器人检测**：XHS 对 Playwright 控制的浏览器返回 461 状态码，重定向到 captcha 验证页面。经测试发现这是**服务端 Session 级别**的检测——即使用纯 HTTP 请求（无浏览器）携带被标记的 Session Cookie，也会被 302 重定向到验证码页面
3. **Session 标记**：通过 `feedgrab login xhs`（Playwright 启动 Chrome）创建的 Session 会被 XHS 在登录阶段标记为自动化 Session，后续所有请求都会触发 461

### 反爬对抗历程

尝试了 8+ 种方案均被检测：

| 尝试 | 方案 | 结果 |
|------|------|------|
| 1 | `channel="chrome"` + `--disable-blink-features=AutomationControlled` | 被检测 |
| 2 | Stealth JS 注入（`navigator.webdriver` 覆盖等） | 被检测 |
| 3 | 先访问 explore 页面预热，再访问 profile | 被检测 |
| 4 | `headless=False` 有头模式 | 被检测 |
| 5 | `launch_persistent_context` 使用真实 Chrome 用户数据 | 被检测 |
| 6 | 子进程启动 Chrome + CDP 连接 | 被检测 |
| 7 | `undetected-chromedriver` headless | 被检测 |
| 8 | `undetected-chromedriver` headed | 被检测 |
| 9 | 纯 HTTP 请求（无浏览器） | 302 重定向 → 证实是 Session 级标记 |

**关键发现**：问题不在浏览器指纹，而在 Session 本身。通过 Playwright 登录创建的 Session 已被服务端标记。

### 最终方案：有头浏览器 + 验证码手动解决

放弃绕过反爬，改为**拥抱验证码**：

1. 使用真实 Chrome（`channel="chrome"`）+ 有头模式（`headless=False`）
2. 加载已有 Session 文件打开主页
3. **自动检测**验证码/登录重定向
4. **CLI 提示用户**在弹出的浏览器窗口中手动完成验证码
5. 验证通过后**自动保存更新的 Session**
6. 继续批量抓取操作

### 三层抓取策略

取代原计划的单一 DOM scraping，实际实现了三层策略：

| 层级 | 方式 | 说明 |
|------|------|------|
| Tier 0 | `__INITIAL_STATE__` 提取 | 从 Vue SSR 渲染的页面数据中直接解析笔记列表（约 30 篇），无需滚动 |
| Tier 1 | XHR 拦截器 + 自动滚动 | `page.on("response")` 拦截 `user_posted` API 分页响应，配合自动滚动加载更多笔记 |
| Tier 2 | 逐篇深度抓取 | 带 `xsec_token` 导航到每篇笔记详情页，复用 `evaluate_xhs_note()` 提取完整内容和元数据 |

### 数据流

```
feedgrab https://www.xiaohongshu.com/user/profile/5eb416f...
  → reader._detect_platform() → "xhs_user_notes"
  → reader._read_user_notes(url)
    → xhs_user_notes.fetch_user_notes(url)
      ├─ 解析主页 URL → user_id
      ├─ 启动 Playwright 有头 Chrome（复用 xhs.json session）
      ├─ 检测验证码/登录 → _handle_captcha_or_login()
      ├─ Tier 0: __INITIAL_STATE__ 提取首批笔记 (~30篇)
      ├─ Tier 1: XHR 拦截 + 自动滚动加载更多
      ├─ 加载 XHS 去重索引
      ├─ Tier 2: 逐篇深度抓取：
      │    去重检查 → 跳过已抓取
      │    同浏览器导航到笔记页（带 xsec_token）
      │    evaluate_xhs_note() → 提取完整数据
      │    from_xiaohongshu() → save_to_markdown()
      │    日期检查：< since_date → 连续 3 篇旧笔记则停止
      │    更新去重索引 + 延迟
      ├─ 保存去重索引
      └─ 保存批量记录 JSON
```

### 方案决策

- **有头浏览器而非 headless**：XHS 服务端检测 Session 来源，但对有头模式 + 手动验证码后的 Session 放行
- **单浏览器复用**：整个批量过程只创建一个 browser context，避免每篇笔记 3-5s 启动开销
- **`__INITIAL_STATE__` 优先**：Vue SSR 数据无需额外请求，直接获取约 30 篇笔记
- **source URL 保留 `xsec_token`**：确保保存的链接可直接点击访问（无 token 会 403）
- **连续旧笔记阈值 = 3**：主页可能有置顶笔记（日期较旧），阈值 3 跳过置顶后仍能正确停止
- **平台独立去重索引**：XHS 和 Twitter 各自维护索引，互不干扰，reset 命令也能正确定位

### 日期解析增强（第 4 种格式）

v0.2.7 支持三种日期格式。批量测试中发现第 4 种格式导致 8/32 篇笔记文件名缺少日期：

| 格式 | 示例 | v0.2.7 | v0.2.8 |
|------|------|--------|--------|
| MM-DD + 属地 | `02-18 福建` | ✅ | ✅ |
| 全日期 | `编辑于 2025-08-16` | ✅ | ✅ |
| 相对时间 | `3天前 江苏` | ✅ | ✅ |
| **编辑于 + 相对时间** | `编辑于 昨天 10:17 福建` | ❌ | ✅ |
| **编辑于 + 相对天数** | `编辑于 3天前 福建` | ❌ | ✅ |

修复：在 `_parse_xhs_date()` 起始处增加 `text = re.sub(r"^编辑于\s*", "", text)` 统一剥离 "编辑于" 前缀，使后续解析逻辑能正确匹配。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/xhs_user_notes.py` | **新建** ~250行 | 核心批量抓取：有头 Chrome + 验证码处理 + 三层抓取（`__INITIAL_STATE__` / XHR 拦截 / 逐篇深度）+ 去重 + 日期过滤 |
| `feedgrab/fetchers/browser.py` | 重构 ~20行 | 提取 `XHS_NOTE_JS_EVALUATE` 模块级常量 + `evaluate_xhs_note()` 辅助函数供批量复用；XHS 单篇改为有头模式 |
| `feedgrab/utils/dedup.py` | 修改 ~10行 | 所有函数新增 `platform` 参数（默认 `"X"` 保持向后兼容） |
| `feedgrab/utils/storage.py` | 修改 ~10行 | `_parse_xhs_date()` 新增 "编辑于" 前缀剥离，支持第 4-5 种日期格式 |
| `feedgrab/config.py` | 新增 ~25行 | 4 个 XHS 批量配置函数：`xhs_user_notes_enabled()` / `xhs_user_note_max_scrolls()` / `xhs_user_note_delay()` / `xhs_user_notes_since()` |
| `feedgrab/reader.py` | 修改 ~30行 | URL 检测（`/user/profile/` → `xhs_user_notes`）+ `_read_user_notes()` + 单篇去重平台感知 |
| `feedgrab/cli.py` | 修改 ~15行 | 帮助文本 + 批量输出 + reset 平台感知 |
| `.env.example` | 新增 ~5行 | `XHS_USER_NOTES_ENABLED` / `XHS_USER_NOTE_MAX_SCROLLS` / `XHS_USER_NOTE_DELAY` / `XHS_USER_NOTES_SINCE` |

### 目录结构

```
{OUTPUT_DIR}/XHS/
├── index/
│   ├── item_id_url.json                    ← XHS 去重索引
│   └── notes_墨客老师资料库_all_*.json       ← 批量记录
└── notes_墨客老师资料库/                     ← 批量笔记
    ├── 墨客老师资料库_2026-02-22：熊出没年年有熊主题初中小学开学第一课绝了.md
    ├── 墨客老师资料库_2026-02-18：开学第一课还没思路的班主任看过来👀.md
    └── ...
```

### 验证结果
- 32/32 篇笔记成功抓取（Tier 0 `__INITIAL_STATE__`，无需滚动）
- 所有 32 个文件名均包含正确日期格式（修复第 4 种格式后）
- source URL 包含 `xsec_token`，链接可直接点击访问
- 去重索引正常工作（重复运行全部 skip）
- 批量记录 JSON 正确保存到 `XHS/index/` 目录
- front matter 完整：likes、collects、comments、images、date、tags、author_url、cover_image

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.7 · 小红书笔记深度抓取

### 背景
小红书抓取仅提取标题、正文、作者三个基本字段，缺少图片、互动数据、标签、发布日期等关键信息。对标 Twitter 的完整抓取能力，XHS 输出质量明显不足。

### 方案决策
- **Playwright JS 扩展**：在 headless Chromium 中执行 JS 提取完整页面数据
- **图片提取**：从 Swiper 轮播容器提取，过滤 `swiper-slide-duplicate`，按 `data-swiper-slide-index` 排序保证翻页顺序
- **互动数据**：点赞、收藏、评论三个计数从 `.engage-bar .count` 提取
- **日期解析**：支持三种格式 — `"02-18 福建"`（MM-DD+属地，补当前年份）、`"编辑于 2025-08-16"`（最后编辑日期）、`"3天前 江苏"`（相对时间+属地，抓取时转为绝对日期）
- **作者主页**：从 `.author-wrapper a[href*="/user/profile/"]` 提取干净 URL（去掉追踪参数）
- **标签策略**：元数据取前 3 个（Obsidian 搜索用），正文保留全部 `#标签`（还原原帖风格）
- **文件名格式**：与 Twitter 统一为 `作者名_YYYY-MM-DD：标题.md`
- **Jina 登录页检测**：Jina 返回登录页时自动降级到 Playwright

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/fetchers/browser.py` | XHS JS evaluate 扩展（图片、互动、日期、标签、作者主页 URL），result dict 新增 6 字段 |
| `feedgrab/fetchers/xhs.py` | Tier 2 透传新字段 + Jina 登录页检测降级 |
| `feedgrab/schema.py` | `from_xiaohongshu()` 填充完整 extra（author_url, cover_image, likes, collects, comments, images, date） |
| `feedgrab/utils/storage.py` | `_parse_xhs_date()` 支持三种日期格式（MM-DD/编辑于/相对时间）；`_parse_xhs_location()` 兼容"编辑于"和相对时间格式；文件名 XHS 分支；front matter 新增 author_url/metrics/location/cover_image；正文：文字→标签→图片；元数据 tags 限前 3 个；`_resolve_filepath` head 读取 512→2048 字节 |

### XHS 输出格式
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

# 开学第一课还没思路的班主任看过来👀

正文内容...

#开学第一课ppt #开学第一课 #教师开学第一课 #教师必备 #班主任 ...

![1](https://...)
![2](https://...)
```

文件名：`墨客老师资料库_2026-02-18：开学第一课还没思路的班主任看过来👀.md`

### 验证结果
- 帖子 1（有正文+16张图）：标题、正文、10个标签、16张图片按翻页顺序、互动数据、发布日期+属地 全部正确
- 帖子 2（纯图文+12张图，"编辑于"格式）：日期正确解析、9个标签、12张图片、无正文（原帖无文字）
- 帖子 3（纯图文+18张图，"3天前 江苏"相对时间）：日期正确转为绝对日期 2026-02-24、属地"江苏"正确提取、10个标签、18张图片

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.6b · 移除 unified_inbox.json + feedgrab list 重写

### 背景
`unified_inbox.json` 是 x-reader 原始设计的遗留产物，所有平台、所有采集方式混存到一个 JSON 文件（500 条上限），与 `.md` 文件 100% 数据冗余。每次抓取都要全量读写该文件，唯一消费方 `feedgrab list` 也几乎没人用。

### 方案决策
- **彻底移除** `unified_inbox.json` 及相关写入逻辑（`save_to_json`、`save_content`、`UnifiedInbox` 引用）
- **重写 `feedgrab list`** 为目录扫描统计摘要，零状态文件
- **移除** `INBOX_FILE` 环境变量和 `cmd_clear` 命令

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/cli.py` | 删除 inbox 依赖，重写 `cmd_list()` 为目录统计，删除 `cmd_clear()`，帮助文档更新 |
| `feedgrab/reader.py` | 移除 `UnifiedInbox` import 和 `self.inbox` 逻辑 |
| `feedgrab/utils/storage.py` | 删除 `save_to_json()` 和 `save_content()` |
| `feedgrab/config.py` | 删除 `get_inbox_path()` |
| `feedgrab/schema.py` | `UnifiedInbox.__init__` 恢复简单默认值（类保留但不再被调用） |
| `.env.example` | 移除 `INBOX_FILE` 配置项 |

### feedgrab list 新输出
```
📦 feedgrab 内容统计 (E:\Obsidian\Qiang_Obsidian\inbox)

  🐦 X: 609 篇
     bookmarks_OpenClaw/  34 篇
     bookmarks_Polymarket/  11 篇
     status/  450 篇
     status_强子手记/  114 篇

  ───────────────
  总计: 609 篇
```

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.6c · feedgrab reset 命令

### 背景
批量抓取后如需重新抓取某个子目录（如文件名格式更新后），需要同时清理 .md 文件和去重索引中对应的 item_id。手动操作容易遗漏，新增 `feedgrab reset <folder>` 命令自动化此流程。

### 功能
```bash
feedgrab reset bookmarks_OpenClaw    # 重置书签文件夹
feedgrab reset status_强子手记        # 重置账号推文
```

执行流程：
1. 在 `{OUTPUT_DIR}/` 下各平台目录中查找匹配的子目录
2. 扫描所有 .md 文件的 YAML front matter，提取 `item_id`
3. 显示待删除文件数和 item_id 数，等待用户确认
4. 从去重索引 `item_id_url.json` 中移除对应条目
5. 删除 .md 文件

找不到目录时自动列出所有可用子目录。

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/cli.py` | 新增 `cmd_reset()` + main 路由 + 帮助文档 |

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.6 · 按推特账号批量抓取 + 文件名优化

### 背景
v0.2.5b 完成了书签批量抓取（全量 + 文件夹）、统一去重索引、扁平目录结构。用户希望新增按推特账号批量抓取功能：给定作者主页 URL（如 `https://x.com/iBigQiang`），批量抓取该账号的所有原创推文（或指定日期之后的推文）。

### 方案决策
- **新增 API**：`UserByScreenName`（screen_name → userId + display_name）、`UserTweets`（用户推文时间线分页）
- **目录命名**：`status_{display_name}`（如 `status_强子手记`），获取不到时降级为 `status_{screen_name}`
- **日期过滤**：环境变量 `X_USER_TWEETS_SINCE=2025-10-01`，不设置则抓全部（API 无原生过滤，客户端逐页检查 `created_at`）
- **功能开关**：`X_USER_TWEETS_ENABLED=false`（默认关闭，与书签批量一致）
- **跳过转推**：仅抓原创推文，检测 `retweeted_status_result` 跳过 RT
- **会话去重**：预扫描全部条目，识别多条目会话（自回复线程），跳过非根条目，升级根推文为线程处理，避免重复保存
- **文件名优化**：格式从 `author_name：标题.md` 改为 `author_name_YYYY-MM-DD：标题.md`，便于按日期排序
- **批量记录增强**：JSON 记录新增 `published`（推文发布日期）和 `item_id` 字段

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `UserByScreenName` + `UserTweets` API：2 个 fallback queryId 常量、2 个 features 字典、3 个函数（`fetch_user_by_screen_name()`、`fetch_user_tweets_page()`、`parse_user_tweets_entries()`）；扩展 `resolve_query_ids()` + `_fallback_query_ids()` |
| `feedgrab/fetchers/twitter_user_tweets.py` | 新建 | 账号批量抓取核心：URL 解析、分页获取、日期过滤、RT 跳过、会话去重（预扫描）、分类处理（复用书签的 `_classify_tweet` / `_build_single_tweet_data`）、批量记录保存 |
| `feedgrab/config.py` | 修改 | 新增 4 个配置函数：`x_user_tweets_enabled()`、`x_user_tweet_max_pages()`、`x_user_tweet_delay()`、`x_user_tweets_since()` |
| `feedgrab/reader.py` | 修改 | `_detect_platform()` 新增 profile URL 检测（排除 `/i/`、`/home` 等系统路径）；新增 `_read_user_tweets()` 方法 |
| `feedgrab/utils/storage.py` | 修改 | `_generate_filename()` Twitter 文件名格式增加发布日期：`author_name_YYYY-MM-DD：标题` |
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 批量记录新增 `published` 和 `item_id` 字段（5 处 `bookmark_list.append`） |
| `.env.example` | 修改 | 新增 4 个配置项 |

### 数据流
```
feedgrab https://x.com/iBigQiang
  → reader._detect_platform() → "twitter_user_tweets"
  → reader._read_user_tweets(url)
    → twitter_user_tweets.fetch_user_tweets(url, cookies)
      → _parse_profile_url() → screen_name = "iBigQiang"
      → fetch_user_by_screen_name() → (user_id, display_name="强子手记")
      → 分页: fetch_user_tweets_page() → parse_user_tweets_entries()
        → 逐条 extract_tweet_data()
        → 日期过滤: created_at < X_USER_TWEETS_SINCE → 停止
        → 跳过 RT
      → 预扫描: 构建 conversation_id → count 映射
      → 逐条处理:
          跳过非根自回复 | 升级根推文为线程
          single → _build_single_tweet_data() → save
          thread → _fetch_via_graphql() → save
          article → _build_single_tweet_data() + Jina → save
      → 去重: dedup.add_item() + save_index()
      → 记录: index/status_{screen_name}_all_{ts}.json
```

### 目录结构（改动后）
```
{OUTPUT_DIR}/X/
├── index/
│   ├── item_id_url.json                         ← 全局去重索引
│   ├── bookmarks_all_*.json                     ← 书签批量记录
│   ├── bookmarks_OpenClaw_*.json                ← 书签文件夹记录
│   └── status_iBigQiang_all_*.json              ← 账号抓取记录
├── status/                                      ← 单篇抓取
├── status_强子手记/                              ← iBigQiang 账号推文
├── bookmarks/                                   ← 全部书签
└── bookmarks_OpenClaw/                          ← 书签文件夹
```

### 会话去重算法
UserTweets API 同时返回根推文和自回复，不做处理会导致重复文件：
1. **预扫描**：遍历全部条目，构建 `conversation_id → count` 映射
2. **识别多条目会话**：`count > 1` 的 conversation_id
3. **跳过非根条目**：`conversation_id != tweet_id` 的自回复
4. **升级根推文**：`single` → `thread`（触发完整线程抓取，包含所有自回复）
5. **追踪已处理会话**：`processed_conv_ids` 集合防止重复处理

### 验证结果
- 平台检测：10/10 用例通过（profile URL / 系统路径排除 / 书签 / 单篇）
- 用户解析：iBigQiang → user_id=1001044583273418752, display_name=强子手记
- 分页抓取：2 页 39 条，RT 跳过正常
- 会话去重：修复前 35 文件（7 重复），修复后 28 文件（0 重复）
- 日期过滤：`X_USER_TWEETS_SINCE=2026-02-25` 正确过滤并停止分页
- 去重回归：第二次运行全部 skip
- 文件名格式：`强子手记_2026-02-24：最近看到好多新蓝V都成功✅认证了创作者身份。.md`
- 批量记录：JSON 包含 `published` 和 `item_id` 字段

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.5b · 书签文件夹 + 统一去重 + 目录扁平化

### 背景
v0.2.5 书签批量抓取只支持全部书签，文件夹 URL（`x.com/i/bookmarks/{folderId}`）降级为全量。此外去重索引仅在书签模块内部使用，单篇抓取不写入索引。目录结构嵌套过深（`X/bookmarks/OpenClaw/`）。

### 方案决策
- **书签文件夹**：新增 `BookmarkFoldersSlice` API 获取文件夹名称，`BookmarkFolderTimeline` API 获取指定文件夹推文
- **统一去重**：抽离全局去重模块 `feedgrab/utils/dedup.py`，索引文件迁移到 `{OUTPUT_DIR}/X/index/item_id_url.json`
- **索引格式**：`{"item_id": ["日期", "URL"]}`，每条一行，紧凑可读
- **目录扁平化**：单篇→`status/`，全部书签→`bookmarks/`，文件夹书签→`bookmarks_{name}/`，消除嵌套

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/utils/dedup.py` | 新建 | 全局去重索引模块：load/save/add/has_item + 旧格式自动迁移 |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `fetch_bookmark_folders()`、`fetch_bookmark_folder_page()`；扩展 `parse_bookmark_entries()` 多路径；扩展 `resolve_query_ids()` + `_fallback_query_ids()` |
| `feedgrab/fetchers/twitter_bookmarks.py` | 修改 | 移除旧索引函数改用 dedup 模块；新增 `_resolve_folder_name()`；分页路由文件夹/全量；目录扁平化 |
| `feedgrab/utils/storage.py` | 修改 | `save_to_markdown()` 支持 `category` 子目录 |
| `feedgrab/reader.py` | 修改 | 单篇 Twitter 设置 `category="status"`；保存后写入去重索引 |

### 目录结构（改动后）
```
{OUTPUT_DIR}/X/
├── index/                        ← 运维数据
│   ├── item_id_url.json          ← 全局去重索引
│   └── bookmarks_*.json          ← 批量抓取记录
├── status/                       ← 单篇抓取
├── bookmarks/                    ← 全部书签（无文件夹）
├── bookmarks_OpenClaw/           ← 书签文件夹
└── bookmarks_撸毛课/             ← 另一个书签文件夹
```

### 去重策略
| 模式 | 读索引 | 写索引 | 跳过重复 |
|------|--------|--------|----------|
| 单篇抓取 | 否 | 是 | 否（用户主动请求） |
| 书签批量 | 是 | 是 | 是 |
| 未来作者批量 | 是 | 是 | 是 |

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.5 · Twitter 书签批量抓取

### 背景
用户需要批量抓取 Twitter 书签中收藏的推文，支持 `feedgrab https://x.com/i/bookmarks` 命令。

### 方案决策
- **方案选择**：Approach B（混合模式）—— 从书签 API 响应直接提取推文数据，仅对线程和长文章做二次 API 调用
- **GraphQL 端点**：复用 `_execute_graphql()`，新增 `Bookmarks` 操作（queryId 从 JS bundle 动态解析，fallback `-LGfdImKeQz0xS_jjUwzlA`）
- **响应路径**：`data.bookmark_timeline_v2.timeline.instructions`（不同于 TweetDetail 的 `threaded_conversation_with_injections_v2`）
- **去重策略**：本地 `.item_id_index.json` 索引文件（用户建议，比扫描目录高效）
- **URL 列表**：每次抓取保存 `output/X/bookmarks/bookmarks_all_{timestamp}.json`
- **安全措施**：默认关闭（`X_BOOKMARKS_ENABLED=false`），分页间隔 1.5s，推文处理间隔 2.0s

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `feedgrab/fetchers/twitter_bookmarks.py` | 新建 | 书签批量抓取核心：分页获取、分类处理（单条/线程/文章）、去重索引、URL 列表保存 |
| `feedgrab/fetchers/twitter_graphql.py` | 修改 | 新增 `BOOKMARK_FEATURES`/`BOOKMARK_FIELD_TOGGLES`、`fetch_bookmarks_page()`、`parse_bookmark_entries()`；扩展 `resolve_query_ids()` 和 `_fallback_query_ids()` |
| `feedgrab/config.py` | 修改 | 新增 `x_bookmarks_enabled()`、`x_bookmark_max_pages()`、`x_bookmark_delay()` |
| `feedgrab/reader.py` | 修改 | `_detect_platform()` 识别 `/i/bookmarks` URL；新增 `_read_bookmarks()` 批量流程 |
| `feedgrab/cli.py` | 修改 | 书签 URL 输出汇总信息 |
| `.env.example` | 修改 | 新增 `X_BOOKMARKS_ENABLED`、`X_BOOKMARK_MAX_PAGES`、`X_BOOKMARK_DELAY` |

### 数据流
```
feedgrab https://x.com/i/bookmarks
  → reader._detect_platform() → "twitter_bookmarks"
  → reader._read_bookmarks()
    → twitter_bookmarks.fetch_bookmarks()
      → twitter_graphql.fetch_bookmarks_page() (分页获取全部)
      → 逐条 extract_tweet_data() → 分类:
          单条 → 直出 → from_twitter() → save_to_markdown()
          线程 → fetch_tweet_thread() → 完整线程 → save
          文章 → Jina body → save
      → 保存 .item_id_index.json + bookmarks URL 列表
```

### 状态：已完成 ✅


---

## 2026-02-27 · v0.2.4d · t.co 短链接展开为原始 URL

### 背景
推文正文中的外部链接（如微信公众号）显示为 `https://t.co/xxx` 短链接，而非用户实际可见的完整 URL。GraphQL 返回的 `entities.urls` 中已包含 `expanded_url`（原始链接），但 `extract_tweet_data()` 未做替换。

### 方案决策
在 `extract_tweet_data()` 提取 `full_text` 后，遍历 URL 实体（note_tweet `entity_set.urls` 优先，回退 `legacy.entities.urls`），将正文中的 `url`（t.co）替换为 `expanded_url`（原始完整链接）。

### 改动范围
| 文件 | 改动 |
|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | `extract_tweet_data()` 中 `full_text` 提取后增加 t.co → expanded_url 替换 |

### 验证结果
**binghe 推文**：`https://t.co/WngCfV5mTC` → `https://mp.weixin.qq.com/s/t6xjY07Yf7VIflDWvXjk4A`，输出文件中无残留 t.co 链接。

### 状态：全部完成 ✅


---

## 2026-02-27 · v0.2.4c · 修复作者回帖漏抓 + Article 检测增强 + 排序 bug

### 背景
测试 binghe 推文发现两个问题：
1. 作者嵌套回复 2 条只抓到 1 条 — `created_at` 字符串排序导致条目被错误 slice 掉
2. 长文章偶尔正文只输出 t.co 短链接 — `is_article_stub` 检测仅看合并文本长度，多推文线程合并后超 200 字符就检测失败

### 根因分析
- **排序 bug**：Twitter `created_at` 格式为 `"Fri Dec 26 04:50:10 +0000 2025"`，字符串排序按星期几字母序（Fri < Wed），导致 12月26日的条目排在 12月24日之前，被 `root_idx` slice 切掉
- **作者回帖过滤**：条件 `in_reply_to_user_id != root_user_id` 排除了作者回复自己（对评论者回复的继续回复）
- **Article 检测**：`is_article_stub` 仅检查合并文本 `len(text) < 200 and "https://t.co/"` — 多推文线程合并后轻松超 200 字符

### 方案决策
- **排序修复**：`all_entries.sort()` 改用 Tweet ID（Snowflake ID 单调递增）代替 `created_at` 字符串
- **作者回帖**：移除 `in_reply_to_user_id != root_user_id` 条件，所有不在线程链中的作者推文均视为回帖
- **Article 检测增强**：主信号用 `article_data.has_content`，次信号检查首条推文文本（非合并文本）
- **Jina 重试**：Article 正文获取失败时自动重试 1 次（间隔 2 秒）
- **线程编号**：主贴不加 `[1/21]` 前缀，续帖从 `[1/20]` 编号，主贴与续帖层次更清晰

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/fetchers/twitter_thread.py` | Phase 7 排序改用 `int(id)`；作者回帖/评论排序统一改用 ID；移除 `in_reply_to_user_id` 过滤条件 |
| `feedgrab/fetchers/twitter.py` | `is_article_stub` 改为 `article_data.has_content` + 首条推文文本检测；Jina 获取增加重试机制；线程主贴不加编号前缀 |
| `feedgrab/schema.py` | 线程主贴不加编号前缀，续帖从 `[1/N]` 编号 |

### 验证结果
**binghe 推文**（binghe/status/2003639692542247190）：
- 修复前：1 条作者回帖、6 条评论
- 修复后：2 条作者回帖（时间正序）、10 条评论
- 线程 21 条不变

**鱼总长文章**（AI_Jasonyu/status/2026455606970954087）：
- Article 正确检测，cover_image 正常，正文完整内容

### 状态：全部完成 ✅


---

## 2026-02-27 · v0.2.4 · 修复标题过长 + 图片丢失 + 标签硬编码 + cover_image 逻辑 + 图片格式

### 背景
实测抓取普通推文和长文章发现多个问题：标题使用推文前100字符太长且含换行符，单条推文正文缺少图片，YAML tags 硬编码 `clippings`/`twitter` 未提取推文 `#hashtag`，cover_image 对普通推文和长文章处理不合理，Jina 返回的长文章正文图片使用非标准嵌套 Markdown 格式。

### 方案决策
- **标题智能截断**：`_clean_title()` 函数 — 过滤换行/制表/控制字符，50字符内优先在句号（。！？.!?）处断开
- **图片嵌入**：单条推文去掉多余的 `[1/1]` 前缀，保留图片嵌入逻辑
- **标签提取**：四层穿透提取推文 `#hashtag`，无 hashtag 时不输出 tags 字段，不插入硬编码值
- **Hashtag 源**：优先从 `note_tweet.entity_set.hashtags` 提取（长推文），回退到 `legacy.entities.hashtags`
- **cover_image 区分**：仅长文章（Article）输出 cover_image（从 `cover_media.media_info.original_img_url` 提取），普通推文不输出
- **长文章封面**：正文开头插入 `![cover](url)` 显示封面图
- **Jina 图片格式**：`[![alt](img)](link)` 嵌套格式统一转为标准 `![image](img)`
- **额外修复**：`article` 为 `None` 时 `.get()` 崩溃防护

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/fetchers/twitter_graphql.py` | `extract_tweet_data()` 提取 hashtags（note_tweet 优先）；`_extract_article_ref()` 提取 cover_image |
| `feedgrab/fetchers/twitter.py` | `_clean_title()` 智能截断；透传 hashtags + article_data；Jina 图片格式正规化；`article` None 防护 |
| `feedgrab/schema.py` | 单条推文去 `[1/1]`；Article 正文开头插入封面图；cover_image 仅长文章；tags 只含 hashtag |
| `feedgrab/utils/storage.py` | tags 从 `item.tags` 读取，无 tag 不输出；文件名截断 150→50 |

### 验证结果
**普通推文**（iBigQiang/status/2026279968171606479）：
- 标题智能截断在句号处：`最近看到好多新蓝V都成功✅认证了创作者身份。`
- 无 cover_image 字段，图片内联在正文
- Tags 只有 `互关`、`蓝v关注必回`，无硬编码值

**长文章**（AI_Jasonyu/status/2026455606970954087）：
- cover_image 从 article cover_media 提取：`https://pbs.twimg.com/media/HB7xEvcaAAAmexY.jpg`
- 正文开头显示 `![cover](...)`
- 正文图片全部为标准 `![image](url)` 格式，无嵌套链接

### 状态：全部完成 ✅


---

## 2026-02-27 · v0.2.4b · 评论开关组合逻辑优化

### 背景
四种开关组合中，`X_FETCH_AUTHOR_REPLIES=false` + `X_FETCH_ALL_COMMENTS=true` 时应按时间线输出所有人评论（含作者嵌套回复），而非仅输出他人评论。

### 方案决策

| 组合 | 作者回帖 | 评论区 |
|------|---------|--------|
| 都开 | 独立章节（时间序） | 仅他人（按赞数） |
| 仅 ALL_COMMENTS | 无 | 所有非线程条目（时间序） |
| 仅 AUTHOR_REPLIES | 独立章节 | 无 |
| 都关 | 无 | 无 |

### 关键分析
作者回复分两种类型，当前设计已正确区分：
- **连续自回复（内容分段）**：`_is_same_thread()` 捕获为 `thread_tweets`（始终作为正文）
- **嵌套回复他人评论**：归入 `author_replies`（C 类，可选开关控制）

### 改动范围
| 文件 | 改动 |
|------|------|
| `feedgrab/fetchers/twitter_thread.py` | B 类评论收集逻辑根据 AUTHOR_REPLIES 开关分支：都开时仅他人按赞数排序，仅 ALL_COMMENTS 时所有非线程条目按时间排序 |

### 状态：全部完成 ✅


---

## 2026-02-26 · v0.2.3 · Cookie 集中管理 + 评论回复采集开关

### 背景
当前 cookie/session 分散在 `~/.feedgrab/cookies/` 和 `~/.feedgrab/sessions/` 两处，路径硬编码在各个 fetcher 中，用户难以管理。Cookie 缺失时虽然有 warning，但没有阻断执行，用户容易忽略导致数据不完整。此外用户需要可选采集推文作者回帖和全部评论。

### 方案决策
- **路径统一**：所有 cookie/session 收归到项目根目录 `sessions/`（通过 `FEEDGRAB_DATA_DIR` 配置，默认 `sessions`）
- **扁平结构**：cookie 文件和 Playwright session 在同一目录，不再分 `cookies/` 和 `sessions/` 子目录
- **集中配置**：新建 `feedgrab/config.py` 管理路径常量和 feature flag
- **向后兼容**：自动检测 `.feedgrab/cookies/`、`.feedgrab/sessions/`、`~/.feedgrab/` 老路径，找到后迁移到新位置
- **Cookie 检查**：Tier 0 前强制检查 cookie，缺失时显示醒目引导框
- **评论开关**：`.env` 新增 `X_FETCH_AUTHOR_REPLIES`、`X_FETCH_ALL_COMMENTS` 开关

### 改动范围

| 文件 | 改动 |
|------|------|
| `feedgrab/config.py`（新建） | 集中管理路径常量和配置读取 |
| `feedgrab/fetchers/twitter_cookies.py` | cookie 路径改用 config.py，cookie 文件改名 `x.json`，老路径自动迁移 |
| `feedgrab/fetchers/browser.py` | session 路径改用 config.py |
| `feedgrab/login.py` | session 路径改用 config.py |
| `feedgrab/fetchers/twitter.py` | Cookie 缺失醒目提示框 + Cookie 过期(401/403)提示 |
| `.env.example` | 新增 `FEEDGRAB_DATA_DIR`、评论采集开关 |
| `.gitignore` | 确保 `.feedgrab/` 被忽略 |

### 目录结构
```
项目根目录/
├── sessions/                    # 所有平台认证数据（FEEDGRAB_DATA_DIR，默认 sessions）
│   ├── x.json                   # Twitter cookies: {"auth_token": "...", "ct0": "..."}
│   ├── twitter.json             # Twitter Playwright storage_state
│   ├── xhs.json                 # 小红书 Playwright storage_state
│   └── wechat.json              # 微信 Playwright storage_state
├── output/                      # 抓取内容输出
├── .env                         # 配置文件
└── feedgrab/                    # 源码
```

### 实施步骤

| 阶段 | 步骤 | 文件 | 状态 |
|------|------|------|------|
| A | 新建 config.py，集中路径和开关 | `feedgrab/config.py` | ✅ |
| A | 迁移 cookie/session 路径引用 | `twitter_cookies.py`, `browser.py`, `login.py` | ✅ |
| A | 更新 .env.example + .gitignore | `.env.example`, `.gitignore` | ✅ |
| A | 老路径向后兼容（自动复制） | `twitter_cookies.py` | ✅ |
| B | Cookie 强制前置检查 + 醒目提示 | `twitter.py` | ✅ |
| C | 作者回帖采集 | `twitter_thread.py`, `twitter.py`, `schema.py`, `storage.py` | ✅ |
| D | 全部评论采集 | `twitter_thread.py`, `twitter.py`, `schema.py`, `storage.py` | ✅ |

### C+D 实施细节

**核心设计**：零额外 API 调用，复用 `fetch_tweet_thread()` 已有分页数据，将 `all_entries` 按 `user_id` 分三类：
- A 类（已有）：作者自回复链 → `thread_tweets`
- B 类：其他用户评论 → `comments`（按点赞降序，上限 `X_MAX_COMMENTS`）
- C 类：作者回复评论者 → `author_replies`（按时间升序）

**数据流**：`twitter_thread.py` 分类 → `twitter.py` 透传 → `schema.py` 存入 extra → `storage.py` 渲染 Markdown 章节

**验证结果**（2026-02-26 测试 AI_Jasonyu/status/2026455606970954087）：
- 采集到 21 条作者回帖 + 30 条评论
- Markdown 末尾正确渲染 `## 作者回帖` 和 `## 评论区 (30条)` 章节
- 默认关闭（不设 env）时输出与之前完全一致

### 状态：全部完成 ✅


---

## 2026-02-26 · v0.2.2 修复 Twitter 数据断层 + 丰富元数据 + Cookie 引导

### 背景
真实抓取测试发现：GraphQL 已获取 20+ 字段（likes/views/bookmarks 等），但在 `_fetch_via_graphql()` → `from_twitter()` → `_format_markdown()` 三层传递中全部丢失。Cookie 缺失时 Tier 0 被静默跳过，Jina 返回的冗余前缀混入正文，front matter 不兼容 Obsidian 格式。参考 `x_tracker` 项目的字段标准。

### 方案决策
- **数据断层修复**：在 `_fetch_via_graphql()` 两个 return 路径中，从 root tweet 提升全部指标到顶层 dict
- **Schema 补全**：`from_twitter()` extra 新增 replies/bookmarks/views/created_at/author_name/cover_image
- **Jina 清洗**：过滤 `URL Source:`/`Published Time:`/`Markdown Content:` 前缀行
- **Obsidian 兼容**：front matter 对齐 Obsidian Properties 格式，零值指标不输出
- **Cookie 引导**：缺失时输出 warning + 操作指引，过期(401/403)时提示刷新

### 实施步骤
| 步骤 | 文件 | 说明 |
|------|------|------|
| 1 | `feedgrab/fetchers/twitter.py` | `_fetch_via_graphql()` 提升 likes/retweets/replies/bookmarks/views/created_at/author_name/images/videos 到顶层；`fetch_twitter()` 添加 cookie 缺失/过期提示 |
| 2 | `feedgrab/schema.py` | `from_twitter()` extra 补充完整字段，首张图片作为 cover_image |
| 3 | `feedgrab/fetchers/jina.py` | 新增 `_JINA_META_PREFIXES` 常量，过滤 Jina 元数据前缀行 |
| 4 | `feedgrab/utils/storage.py` | `_format_markdown()` 输出 Obsidian 兼容 YAML front matter（title/source/author/author_name/published/created/cover_image/指标/tags） |

### Front Matter 目标格式（有 Cookie 完整模式）
```yaml
---
title: "OpenClaw新手完整学习路径"
source: "https://x.com/AI_Jasonyu/status/123"
author:
  - "@AI_Jasonyu"
author_name: "鱼总聊AI"
published: 2026-02-26
created: 2026-02-26
cover_image: "https://pbs.twimg.com/media/xxx.jpg"
tweet_count: 3
has_thread: true
likes: 1234
retweets: 567
replies: 89
bookmarks: 234
views: 45678
tags:
  - "clippings"
  - "twitter"
---
```

### 状态：已完成 ✅

---
## 2026-02-26 · v0.2.1 按平台分目录保存内容

背景                                                                                                                              │
│                                                                                                                                   │
│ 当前所有平台的抓取内容都追加到同一个 output/content_hub.md 文件，随着使用量增加会变得混乱且难以管理。内容还被截断到 2000          │
│ 字符。需要改为按平台分目录、每条内容独立一个文件。                                                                                │
│                                                                                                                                   │
│ 改动范围                                                                                                                          │
│                                                                                                                                   │
│ 只改 1 个文件：feedgrab/utils/storage.py（reader.py 调用签名不变，无需修改）                                                      │
│                                                                                                                                   │
│ 目录结构                                                                                                                          │
│                                                                                                                                   │
│ output/                  (由 OUTPUT_DIR 环境变量控制)                                                                             │
│ ├── X/                   # Twitter/X                                                                                              │
│ │   ├── OpenClaw新手完整学习路径.md                                                                                               │
│ │   └── When people ask me about AI agents.md                                                                                     │
│ ├── XHS/                 # 小红书                                                                                                 │
│ ├── Bilibili/            # B站                                                                                                    │
│ ├── WeChat/              # 微信                                                                                                   │
│ ├── YouTube/             # YouTube                                                                                                │
│ ├── Telegram/            # Telegram                                                                                               │
│ ├── RSS/                 # RSS                                                                                                    │
│ └── Manual/              # 手动输入                                                                                               │
│                                                                                                                                   │
│ SourceType → 目录名映射：                                                                                                         │
│ - TWITTER → X                                                                                                                     │
│ - XIAOHONGSHU → XHS                                                                                                               │
│ - BILIBILI → Bilibili                                                                                                             │
│ - WECHAT → WeChat                                                                                                                 │
│ - YOUTUBE → YouTube                                                                                                               │
│ - TELEGRAM → Telegram                                                                                                             │
│ - RSS → RSS                                                                                                                       │
│ - MANUAL → Manual                                                                                                                 │
│                                                                                                                                   │
│ 文件命名规则                                                                                                                      │
│                                                                                                                                   │
│ 1. 优先用 item.title，无标题则取 item.content 前 150 字符，都没有则用 item.id                                                     │
│ 2. 清理非法字符（\ / : * ? " < > |）、控制字符、Windows 保留名                                                                    │
│ 3. 最长 100 字符，截断时不切断单词                                                                                                │
│ 4. 同名冲突：追加 _itemid 后缀（如 My Article_a3f2b9c1d4e5.md）                                                                   │
│ 5. 相同 URL 重复抓取：同一 item.id 产生相同文件名，直接覆盖（更新内容）                                                           │
│                                                                                                                                   │
│ 单文件 Markdown 格式                                                                                                              │
│                                                                                                                                   │
│ ---                                                                                                                               │
│ source: twitter                                                                                                                   │
│ author: "@username"                                                                                                               │
│ url: https://x.com/username/status/123                                                                                            │
│ fetched_at: 2026-02-26T19:32                                                                                                      │
│ tweet_count: 5                                                                                                                    │
│ has_thread: true                                                                                                                  │
│ ---                                                                                                                               │
│                                                                                                                                   │
│ （完整内容，不再截断）                                                                                                            │
│                                                                                                                                   │
│ - Twitter 线程：from_twitter() 已将主贴+作者回帖拼合为 [1/N] 格式，直接保存完整内容                                               │
│ - 非 Twitter 平台：加 # {title} 一级标题 + 完整内容                                                                               │
│ - B站额外字段：bvid、duration                                                                                                     │
│ - 移除 2000 字符截断限制                                                                                                          │
│                                                                                                                                   │
│ storage.py 具体改动                                                                                                               │
│                                                                                                                                   │
│ 1. 新增 PLATFORM_FOLDER_MAP 常量                                                                                                  │
│ 2. 新增 _sanitize_filename() — 文件名清理                                                                                         │
│ 3. 新增 _generate_filename() — 文件名生成                                                                                         │
│ 4. 新增 _resolve_filepath() — 冲突处理                                                                                            │
│ 5. 新增 _format_markdown() — 生成完整 Markdown 内容（YAML front matter + body）                                                   │
│ 6. 重写 save_to_markdown() — 改为写单独文件到平台子目录                                                                           │
│ 7. save_to_json 完全不动                                                                                                          │
│                                                                                                                                   │
│ 验证方式                                                                                                                          │
│                                                                                                                                   │
│ # 测试 Twitter                                                                                                                    │
│ feedgrab https://x.com/AI_Jasonyu/status/2026455606970954087                                                                      │
│ # 预期：output/X/鱼总聊AI on X OpenClaw新手完整学习路径....md 生成                                                                │
│                                                                                                                                   │
│ # 测试列表                                                                                                                        │
│ ls output/X/  


## 2026-02-26 · v0.2.0 · X/Twitter GraphQL 融合升级

### 背景
feedgrab（原 x-reader）的 Twitter 模块只有三级兜底（oEmbed → Jina → Playwright），只能获取单条推文的粗糙文本，无法抓取线程、图片、视频和引用推文。[baoyu-danger-x-to-markdown](https://github.com/anthropics/claude-code) 技能通过逆向工程 X 的私有 GraphQL API 实现了深度抓取，但它是 TypeScript/Bun 运行时的独立工具。

### 方案决策
- **方案选择**：Python 完整重写（而非 TypeScript 子进程调用），保持技术栈统一
- **架构设计**：新增 GraphQL 作为 Tier 0，保留原有三级作为兜底
- **安全措施**：请求间隔 1.5 秒（原版无限制）、最大分页 20 次（原版 1000）、Cookie 日志脱敏、`X_GRAPHQL_ENABLED` 开关

### 实施步骤
| 步骤 | PR | 文件 | 说明 |
|------|-----|------|------|
| 1 | #1 | `twitter_cookies.py` | Cookie 四源合并管理 |
| 2 | #2 | `twitter_graphql.py` | GraphQL API 客户端 + 动态 queryId |
| 3 | #3 | `twitter_thread.py` | 线程重建（6 阶段算法） |
| 4 | #4 | `twitter_markdown.py` | Markdown 渲染 |
| 5 | #5 | `twitter.py` | 四级兜底调度器 |
| 6 | #6 | `schema.py` | Schema 扩展支持线程数据 |

### 参考文档
- 详细技术对比分析：`融合升级方案.md`
- 原始 baoyu 源码：`skills/baoyu-danger-x-to-markdown/`

### 状态：已完成 ✅

---

## 初始版本 · v0.1.0 · 来自 x-reader 的基础功能

- 7+ 平台统一抓取（YouTube、B站、X/Twitter、微信、小红书、Telegram、RSS）
- oEmbed → Jina → Playwright 三级兜底
- CLI / Python 库 / MCP 服务器三层架构
- UnifiedContent 统一数据结构
- Claude Code Skills（视频转录 + AI 分析）

### 状态：已完成 ✅
