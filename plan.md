# feedgrab 升级计划

本文档记录每次升级迭代的确定方案，作为项目演进的记忆文件。
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

<!-- 模板：复制以下内容用于新的升级计划 -->
<!--
## YYYY-MM-DD · vX.Y.Z · 升级标题

### 背景
（为什么要做这个升级）

### 方案决策
- **方案选择**：
- **架构设计**：
- **注意事项**：

### 实施步骤
| 步骤 | PR | 文件 | 说明 |
|------|-----|------|------|
| 1 | # | | |

### 参考文档
-

### 状态：进行中 / 已完成 ✅
-->
