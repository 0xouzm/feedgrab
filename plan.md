# feedgrab 升级计划

本文档记录每次升级迭代的确定方案，作为项目演进的记忆文件。
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
