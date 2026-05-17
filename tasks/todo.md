# v0.22.0 + v0.23.0 — twitter-web-exporter 融合方案 执行 TODO

> 调研报告：`开发及迭代方案调研报告/20260517-twitter-web-exporter-vs-feedgrab对比与融合方案.md`
> twe 源码归档：`tasks/twe_research/`（19 个核心 .ts 文件）
> 实施范围（用户已确认）：**阶段一 P0 + 阶段二 P1 全部**
> fetcher 优先级（用户已选）：Followers/Following + ListMembers/Subscribers 最高，其次 Likes、UserTweetsAndReplies

---

## 版本拆分

- **v0.22.0** = P0（5 个新 fetcher + 3 个解析鲁棒性增强）
- **v0.23.0** = P1（通用 helper 重构 + sortIndex + ModeratedTimeline）

每个版本独立 `/ship`，降低回归风险。

---

## v0.22.0 — P0 实施清单

### A. 解析鲁棒性增强（最低风险，独立改动）

- [ ] A1. `twitter_graphql.py` 的 `extract_tweet_data` 增加 `TweetTombstone` / `TweetUnavailable` 显式分支 + `logger.warning` 记录 tombstone 文案，front matter 标记 `is_tombstone=true`
- [ ] A2. `twitter_graphql.py` 的 `parse_user_tweets_entries` 增加 `TimelinePinEntry` 单独提取（避免 UserTweets 漏抓置顶推文）
- [ ] A3. `twitter_graphql.py:1446` 区域：视频 variant 删除 `content_type == "video/mp4"` 过滤，直接按 bitrate 排序取最大（防漏抓 webm）

### B. 新增 GraphQL fetcher（按用户优先级排序）

- [ ] B1. **Followers / Following / BlueVerifiedFollowers**（用户关系，最高优先）
  - `twitter_graphql.py` 加 `FALLBACK_FOLLOWERS_QUERY_ID` / `FALLBACK_FOLLOWING_QUERY_ID` / `FALLBACK_BLUE_VERIFIED_FOLLOWERS_QUERY_ID` + features + `fetch_followers_page()` / `fetch_following_page()` + `parse_users_entries()`（解析 user 而非 tweet）
  - 新建 `twitter_followers.py`：批量抓取 + 流式落盘 + 汇总表
  - `reader.py`：识别 `/followers` / `/following` / `/verified_followers` URL → 新平台 `twitter_followers` / `twitter_following`
  - `schema.py`：新增 `SourceType.X_USER_LIST`（导出 user 列表，与 tweet 区分）+ `from_x_user_list()`
  - `utils/storage.py`：`PLATFORM_FOLDER_MAP` 新增 `X_USER_LIST → X/users/`，user list markdown 渲染
  - `config.py`：新增 `X_FOLLOWERS_ENABLED` env

- [ ] B2. **ListMembers / ListSubscribers**（列表成员，次高优先）
  - `twitter_graphql.py` 加 `FALLBACK_LIST_MEMBERS_QUERY_ID` / `FALLBACK_LIST_SUBSCRIBERS_QUERY_ID` + features + `fetch_list_members_page()` / `fetch_list_subscribers_page()`
  - 新建 `twitter_list_members.py`（复用 B1 的 user list 渲染）
  - `reader.py`：`/i/lists/<id>/members` / `/subscribers` → `twitter_list_members` / `twitter_list_subscribers`
  - `config.py`：`X_LIST_MEMBERS_ENABLED` env

- [ ] B3. **Likes**（用户喜欢的推文）
  - `twitter_graphql.py` 加 `FALLBACK_LIKES_QUERY_ID` + features + `fetch_user_likes_page()`（结构与 UserTweets 类似）
  - 新建 `twitter_user_likes.py`（复用 user_tweets 的 tweet 列表渲染）
  - `reader.py`：`/likes` → `twitter_user_likes`
  - `config.py`：`X_USER_LIKES_ENABLED` env

- [ ] B4. **UserTweetsAndReplies**（用户回复 tab）
  - `twitter_graphql.py` 加 `FALLBACK_USER_TWEETS_AND_REPLIES_QUERY_ID` + features + `fetch_user_tweets_and_replies_page()`
  - 复用 `twitter_user_tweets.py`：增加 `with_replies` 模式开关
  - `reader.py`：`/with_replies` → 走 user_tweets 但传入 `mode="with_replies"`
  - `config.py`：`X_USER_REPLIES_ENABLED` env（或复用 X_USER_TWEETS_ENABLED）

### C. CLI 命令

- [ ] C1. `feedgrab/cli.py` 新增命令（仿 `x-so`）：
  - `feedgrab x-followers <user>` / `feedgrab x-following <user>` / `feedgrab x-blue-followers <user>`
  - `feedgrab x-list-members <list_id>` / `feedgrab x-list-subscribers <list_id>`
  - `feedgrab x-likes <user>`
  - `feedgrab x-replies <user>`（或自动通过 URL 识别，可省略）

### D. 测试

- [ ] D1. `tests/test_twitter_followers.py`（mock GraphQL 响应，解析 user 列表）
- [ ] D2. `tests/test_twitter_list_members.py`
- [ ] D3. `tests/test_twitter_user_likes.py`
- [ ] D4. `tests/test_twitter_pin_entry.py`（A2 单元测试：含置顶推文的 UserTweets 响应能提取出置顶）
- [ ] D5. `tests/test_twitter_tombstone.py`（A1 单元测试：TweetTombstone 响应不写空数据）
- [ ] D6. 全套测试无回归

### E. 实测验证

- [ ] E1. `feedgrab https://x.com/<user>/followers` 实际跑通
- [ ] E2. `feedgrab https://x.com/<user>/likes` 实际跑通
- [ ] E3. `feedgrab https://x.com/i/lists/<id>/members` 实际跑通
- [ ] E4. `feedgrab https://x.com/<user>/with_replies` 实际跑通

### F. 文档同步 + 发版

- [ ] F1. `pyproject.toml` 0.21.0 → 0.22.0
- [ ] F2. `DEVLOG.md` 顶部 v0.22.0 完整条目
- [ ] F3. `README.md` / `README_en.md` 平台清单 + 使用示例
- [ ] F4. `CLAUDE.md` 已用 operationName 清单 + 平台数更新
- [ ] F5. `.env.example` 新增 env vars
- [ ] F6. `/ship` 一键收尾

---

## v0.23.0 — P1 实施清单

### G. 通用 helper 重构

- [ ] G1. `twitter_graphql.py` 新增 `_extract_timeline_entries(response_json, instructions_path_fn, entry_to_data_fn)` 通用 helper（参考 twe `utils/api.ts:38-75`）
- [ ] G2. 改造 6 处现有 instruction 解析逻辑使用新 helper（Bookmarks / UserTweets / SearchTimeline / ListTimeline / TweetDetail / Article）
- [ ] G3. 验证无回归（全套测试 + 实测 4 个核心场景）

### H. sortIndex 字段

- [ ] H1. `schema.py` 新增 `sort_index: str` 字段（保留为字符串，避免大整数溢出）
- [ ] H2. `_extract_timeline_entries` 入库时按 `int(sort_index)` 倒序排列
- [ ] H3. `twitter_markdown.py` / batch 汇总表按 sort_index 输出顺序

### I. ModeratedTimeline 抓被隐藏回复

- [ ] I1. `twitter_graphql.py` 加 `FALLBACK_MODERATED_TIMELINE_QUERY_ID` + features + `fetch_moderated_timeline()`
- [ ] I2. `twitter_thread.py` 单推 thread 路径增加 `ModeratedTimeline` query 兜底，front matter 标记 `has_moderated_replies=true`

### J. 测试 + 文档 + 发版

- [ ] J1. 单元测试覆盖 G/H/I 改动
- [ ] J2. `pyproject.toml` 0.22.0 → 0.23.0
- [ ] J3. DEVLOG/README/CLAUDE 同步
- [ ] J4. `/ship`

---

## 进度摘要

- ⏳ A 解析鲁棒性增强（v0.22.0 第一批，最低风险）
- ⏳ B 5 个新 fetcher（按优先级 B1 → B2 → B3 → B4）
- ⏳ C CLI 命令
- ⏳ D/E 测试 + 实测
- ⏳ F /ship v0.22.0
- ⏳ G/H/I v0.23.0（重构 + sortIndex + ModeratedTimeline）
- ⏳ J /ship v0.23.0

---

## 风险与回归点

| 风险点 | 缓解措施 |
|--------|---------|
| 新 queryId 不稳定 | 复用 4 级 fallback（cache → community fa0311 → JS bundle → hardcoded） |
| Followers 返回 user 不是 tweet，数据结构不同 | 新增 `SourceType.X_USER_LIST` 隔离，独立 markdown 渲染 |
| TimelinePinEntry 改变 UserTweets 输出顺序 | 置顶推文标记后单独放 markdown 头部 |
| _extract_timeline_entries 重构涉及 6 处改动 | 分阶段重构 + 完整单元测试 + 实测验证 |
| ModeratedTimeline 需要 thread 路径改造 | 仅在 thread 模式下追加，不影响单推路径 |
