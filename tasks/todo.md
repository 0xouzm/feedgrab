# v0.23.0 实施 TODO（已完成）

> 方案文档：`开发及迭代方案调研报告/20260518-v0.23.0-P1-P2实施方案.md`
> 用户决策（2026-05-18）：6 项全做 / P2-2 opt-in / P1-1 一次性替换
> 实际执行：5 项完成 ship v0.23.0；P1-1 与用户协商拆分到 v0.23.1

---

## ✅ P2-1 — profile 头像原图（已完成）

- [x] `utils/media.py:_optimize_url` Twitter 分支前追加 `_normal|_bigger|_mini|_400x400` → 原图替换
- [x] 单元测试 7 case（4 种前缀 + query 保留 + 媒体 URL 不受影响 + 非头像 URL）

## ✅ P2-3 — Retweeters + Favoriters（已完成）

- [x] `twitter_graphql.py` 加 2 个 queryId + features + `fetch_retweeters_page` / `fetch_favoriters_page`
- [x] `main_ops_missing` + `_fallback_query_ids` 加 `Retweeters` / `Favoriters`
- [x] 新增 `fetchers/twitter_retweeters.py`（MD 表 + CSV，按 followers_count 倒序）
- [x] `reader.py` 路由：`/status/<id>/retweets` → retweeters；`/status/<id>/likes` → favoriters（在单推 `/status/` 检测之前）
- [x] `cli.py` 新增 `x-retweeters` / `x-favoriters` 命令
- [x] `.env.example` 新增 4 个 env vars
- [x] 单元测试 10 case
- [x] 实测：176 个转推者抓取成功 / favoriters 优雅降级

## ✅ P2-4 — People-tab 搜索（已完成）

- [x] `twitter_graphql.py:parse_search_people_entries` 解析 TimelineUser
- [x] 新增 `fetchers/twitter_search_people.py`
- [x] `cli.py:cmd_twitter_search` 检测 `--people` 选项 → 分支
- [x] `.env.example` 新增 3 个 env vars
- [x] 单元测试 4 case
- [x] 实测：3 个匹配用户 / 20 个广义关键词

## ✅ P1-3 — ModeratedTimeline 接入 thread 主路径（已完成）

- [x] `config.py` 新增 `x_fetch_moderated_replies()` + `x_moderated_replies_max_pages()`
- [x] `twitter_thread.py` Phase 8（opt-in）→ `_fetch_moderated_replies` + 标记 `_is_moderated=True`
- [x] `schema.py:from_twitter()` 透传 `moderated_replies` / `has_moderated_replies` 到 extra
- [x] `fetchers/twitter.py` 透传两个字段
- [x] `utils/storage.py` Twitter front matter 加 `moderated_replies_count` + body 加「⚠️ 被作者隐藏的回复」区段
- [x] `.env.example` 新增 2 个 env vars
- [x] 单元测试 8 case（开关 / 空响应 / 单页 / 分页 / 异常吞噬）
- [x] 实测：404 优雅降级 + 主路径无回归

## ✅ P2-2 — 媒体文件名 pattern 系统（X-only，已完成）

- [x] `utils/media.py:download_media` 新增 `context: dict = None` 参数
- [x] `_apply_filename_pattern` 9 token 白名单替换 + path traversal 安全化 + 长度截断
- [x] `{tweet_id}` 智能：优先从 `ctx["url"]` regex 提取真实 Snowflake（避免 feedgrab 内部 hash）
- [x] 7 处调用方（reader.py + 6 个 X 批量 fetcher）传 context dict
- [x] `.env.example` 新增 `X_MEDIA_FILENAME_PATTERN` 注释段
- [x] 单元测试 11 case
- [x] 实测：`20260518_ai_xiaomu_2056173124073525356_1.jpg`

## ⏸ P1-1 — 通用 `_iter_timeline_instructions` helper 重构（推迟 v0.23.1）

- [ ] 抽出 `_iter_timeline_instructions(response, *, paths, item_filter, handle_pin_entry, handle_add_to_module, handle_replace_entry, cursor_types, skip_promoted, drop_components, sort_by_sortindex, fallback_path_scan, return_cursors)`
- [ ] 重构 7 处 parser（`parse_user_tweets_entries` / `_parse_user_list_response` / `parse_moderated_timeline_entries` / `parse_list_tweets_entries` / `parse_bookmark_entries` / `parse_search_entries` / `parse_tweet_entries`）
- [ ] sortIndex 默认启用对 #4/#5/#6/#7 输出顺序的影响：每处单独回归测试
- [ ] helper 单元测试 ≥4 case

> helper 设计草案见 `开发及迭代方案调研报告/20260518-v0.23.0-P1-P2实施方案.md`。
> 因涉及 7 处独立 parser 的微妙差异（pin / addToModule / cursor 类型 / fallback path / sortIndex 默认启用），与用户协商**拆分独立版本**便于回归测试。

---

## ✅ 收尾（已完成）

- [x] 全套 `pytest tests/`（**193/193 通过**，v0.22.0 是 153 → +40 新增）
- [x] 更新 `DEVLOG.md`（顶部 v0.23.0 条目，覆盖 5 项实施 + 实测 + 经验 + P1-1 推迟说明）
- [x] 更新 `README.md` / `README_en.md`（同步 4 个新命令 + 3 个新功能段落）
- [x] 更新 `CLAUDE.md`（版本号 + 迭代历史摘要新增 v0.23.0 行）
- [x] 更新 `pyproject.toml` 版本号 0.22.0 → 0.23.0
- [ ] `/ship` 提交（待执行）

## 复盘

**亮点**：
- 5 项功能按风险从低到高有序推进，每项独立单元测试 + ai_xiaomu 实测，无回归
- 测试覆盖从 153 → 193（+40），稳健的回归基线
- P2-2 媒体 pattern 的 `{tweet_id}` 智能从 URL 提取真实 Snowflake — 解决 feedgrab 内部 hash 与外部期待不符
- P1-3 ModeratedTimeline 404 优雅降级（端点对非作者 Cookie 返回 404 是 Twitter 默认行为而非 bug）
- P1-1 与用户协商拆分到 v0.23.1，避免了 7 处大重构在功能版本中引入回归风险

**经验**：
- Retweeters/Favoriters / People-tab 与 Followers 同 schema，复用 `_parse_user_list_response` + `extract_user_data` 几乎零额外代码
- 模板系统的 path traversal 安全化必须**二次清洗**（单独 token 值 + 最终拼接结果）
- 对端点 404 / 403 这种"预期行为"，应该用 INFO 级别日志解释含义而非让底层 ERROR 困扰用户

**留待 v0.23.1**：
- P1-1 通用 instruction helper 重构（净减 ~120 行重复代码 + sortIndex 默认启用 4 处行为变更）
