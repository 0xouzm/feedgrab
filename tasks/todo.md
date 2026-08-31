# v0.26.1 实施 TODO（已完成）

> 用户要求：把 x.com **全部渠道**逐一核验一遍，找出还有哪些属于「必须主账号权限」，做成和书签一样锁定
> `sessions/twitter.json`；不强调权限的公开页面继续走小号轮换。明确要求：**不要猜测，用真实抓取验证**。
> 来源：`feedgrab-desktop` 分支提交 `e66f6465`，本次 cherry-pick 回 main（版本 v0.26.1）。

---

## ✅ 核验（已完成，18 项渠道 × 2 账号）

- [x] 写探针脚本，主号 `@iBigQiang` / 备用号 `x_2.json` 交叉跑同一批 GraphQL operation
- [x] 排除伪信号 1：`TweetResultByRestId` 返回 `data.tweetResult`，**没有 `entryId`** —— 按 entryId 计数会把单贴 / 长文误报为 EMPTY，改用递归找 `full_text`
- [x] 排除伪信号 2：`timeline: {}` 只说明「没内容」，不等于「没权限」—— 先从列表 timeline 按 `favorite_count` / `retweet_count` 挑出高互动第三方推文（@rehan_shei，12817 赞 / 995 转）再测，结论随即翻转
- [x] 得出三级边界：公开（任何登录态）→ 账号本人（书签 / 用户 likes）→ 推文作者本人（favoriters）

## ✅ 实施（已完成）

- [x] main 线首次引入主账号语义三件套：`_PRIMARY_SOURCE_LABELS` / `is_primary_cookie_label()` / `load_primary_twitter_cookies()` + `fetch_with_cookie_rotation(primary_only=True)`
- [x] 书签两条分页路径锁主账号；`_parse_bookmark_url` 兼容 `/i/history` 新拼写；`_graphql_error_summary()` 让 200+errors 的权限失败不再静默成 0 条
- [x] 用户 likes 锁主账号（`primary_only=(mode == "likes")`，tweets / replies 不受影响）
- [x] favoriters 锁主账号（`_MODE_CONFIG` 加 `primary_only` 字段，配实测依据注释）
- [x] reader 层缺主账号前置硬失败，不拿备用号白跑一趟拿空结果
- [x] 修正两处错误归因文案（原文案把平台机制说成对方的隐私设置，会误导用户去调设置）
- [x] 修复书签 URL 路由：X 已把总览迁到 `/i/history`，用精确正则而非前缀匹配

## ✅ 审查三关回头改（code-review / verify / security-review）

第一版能跑，但三关又改出 6 处边界问题：

- [x] CLI `x-favoriters` 完全没有闸门 → 缺主账号时用备用号发请求打印「总数：0」，看起来像没人点赞
- [x] `parse_tweet_user_list_url` 正则写死裸域 → `www.x.com` / `mobile.twitter.com` 解析成 `(None, None)`，闸门落空 + 功能整条 `ValueError`
- [x] `reader.py` 写死 `mode == "favoriters"` → 与 `_MODE_CONFIG` 成两处真相，抽出 `mode_requires_primary()`
- [x] 主账号被限流时 `primary_only` 无可轮换对象 → 429 被报成「登录态已过期」，新增 `cookie_rate_limit_remaining()` 分叉归因
- [x] 路由 `\d` vs 解析 `[0-9]` 口径不一致 → 阿拉伯-印度数字的 folder id 会让「抓某个文件夹」静默变成「抓全部书签」
- [x] （桌面端 GUI 示例文案，留在 `feedgrab-desktop` 分支，不属 main 线）

## ✅ 测试（已完成）

- [x] main 线 264 → **310 passed**（+46）
- [x] `tests/test_twitter_primary_account.py` 20 例 —— 锁「哪些渠道钉主账号」这条策略本身
- [x] `tests/test_twitter_bookmarks_url.py` 14 例 —— 锁书签 URL 三形态 + 路由与解析口径一致
- [x] `tests/test_twitter_primary_gate.py` 12 例 —— 锁闸门入口覆盖面 + 失败归因

## ✅ 真实抓取验证（已完成，不是跑测试是真抓）

- [x] 10 项渠道端到端，产物全部落地（书签总览 / 用户喜欢 / 点赞者 / 转推者 / 单贴 / 长文 / 列表 / 书签文件夹 / 账号批量 / 词组批量搜）
- [x] 三关修复后复验：CLI `x-favoriters` 194 用户（主账号 5 页）、`x-retweeters` 47 用户（`[6/6 可用]` 确认公开渠道仍轮换）、`www.` 子域走 reader 路由 194 用户（修复前必抛 `ValueError`）

## ✅ 安全审查（已完成）

- [x] 结论：无达到报告门槛的安全漏洞
- [x] 驳回两条：`_fetch_home_html` 落盘缓存不含凭据值且 `sessions/` 已 gitignore（增量暴露为零）；主/备账号选错的后果是空结果而非越权（授权由 X 服务端 ACL 执行）

## ✅ cherry-pick 回 main（本次）

- [x] 5 个 twitter fetcher 在两分支基线逐字节一致 → 直接取终态，零冲突
- [x] `cli.py` / `reader.py` / `skills/feedgrab-batch/SKILL.md` / `README_en.md` 三方合并，全部干净应用
- [x] 版本走 main 自己的线：`pyproject.toml` 0.26.0 → **0.26.1**（不是 desktop 的 0.25.1）
- [x] 文档按 main 内容重写：DEVLOG 顶部新增 v0.26.1 条目、CLAUDE.md / AGENTS.md 版本行 + X 约定 + 迭代表逐字对齐、AGENTS.md 补权限边界章节、中英文 README 同步
- [x] 桌面端 `App.tsx` 不带入（main 无此文件）

## 复盘

**亮点**：
- 「不要猜测，用真实抓取验证」这条要求直接改变了结论：第一版探针的两个伪信号都会把「有权限」误判成「无权限」，如果按探针结果动手，retweeters 会被错误地锁成主账号，等于砍掉一个本可轮换的公开渠道
- 三级边界（公开 / 账号本人 / 推文作者本人）是实测出来的，X 官方文档没有这个说法；favoriters 属「作者本人」这一级尤其反直觉
- main 此前**完全没有**主账号基础设施，这次不只补上了 likes / favoriters，连上一批的「书签锁主账号」也一并落到 main 线

**做错的、值得记住的**（已沉淀进 `tasks/lessons.md`）：
- 同一条策略有两个入口（reader / CLI），只在其中一个加闸门 —— 判据必须抽成一个函数，让两个入口共用
- 替换一层抽象（`load_twitter_cookies()` → `primary_only`）前没列清它顺手做了哪些事，把「跳过限流冷却账号」一起抽掉了，导致 15 分钟冷却被报成「登录态已过期」
- 文档里的测试数字凭印象填，实际现场跑一遍才发现口径全错 —— 写进文档的数字一律现场跑一遍再填

---

# v0.24.1 实施 TODO（已完成）

> 用户报告：批量抓 `feedgrab https://x.com/AdrianPunk115` 在第 1 个账号 429 后，3 次重试都用同一账号失败 → 停在 557 条
> 修复版本：v0.24.1（2026-05-21）

---

## ✅ 定位根因（已完成）

- [x] `twitter_user_tweets.py` 重试时不刷 `cookies` 字典，3 次都用同一被限流账号
- [x] 排查发现 7 个批量 fetcher 全有同问题（程度不一）：user_tweets / bookmarks / list_tweets / user_lists / retweeters / search_people / keyword_search

## ✅ 修复：抽出 `fetch_with_cookie_rotation()` helper（已完成）

- [x] `twitter_cookies.py` 新增 3 个 public 函数：`count_total_accounts()` / `count_available_accounts()` / `earliest_rate_limit_recovery_seconds()`
- [x] `twitter_cookies.py` 新增 `fetch_with_cookie_rotation(callable, *args, label, network_retry_delay, **kwargs) -> (response, last_cookies)`
- [x] 核心循环：最多试 N=total 次（每个账号都试一遍）；切换账号时打印"切换账号重试 (N/total) — 新账号 xxx... 剩余可用 M/total"
- [x] 单账号场景死循环防御：连续两次同账号 key 立即终止
- [x] 全失败明确日志：`>>> 所有 N 个账号均已被限流 <<< 最早 Xs 后自动恢复`

## ✅ 调用方迁移（已完成）

- [x] `twitter_user_tweets.py` — 替换 3 次同账号重试为统一 helper
- [x] `twitter_bookmarks.py` — 替换"直接 break"为 helper（folder + 非 folder 两条路径）
- [x] `twitter_list_tweets.py` — 同上
- [x] `twitter_user_lists.py` — 同上
- [x] `twitter_retweeters.py` — 同上
- [x] `twitter_search_people.py` — 同上
- [x] `twitter_keyword_search.py` — 替换"重试 1 次"半成品方案为 helper
- [x] 所有调用方 `cookies = rotated_cookies` 接住返回值，让下一页直接用新账号

## ✅ 测试（已完成）

- [x] `tests/test_twitter_cookie_rotation.py` 新增 8 case：
  - 首次成功 / 第二账号轮换 / 全限流 / 单账号防死循环 / 无 cookie / 异常吞噬 / kwargs 透传 / 实时账号统计
- [x] 全套 `pytest tests/`：193 → **201 全过**

## ✅ 实测验证（已完成）

- [x] `feedgrab https://x.com/AdrianPunk115` 实测：
  - 抓取条数 557 → **632**（+75 / +13.4%）
  - 触发 2 次跨账号轮换（3a43aed6 → ae0669d0 → 467488bb），可用账号数 6 → 5 → 4
  - 服务端 cursor 用尽自然结束（不再因 429 提前停止）

## ✅ 文档更新（已完成）

- [x] DEVLOG.md 新增 v0.24.1 条目（根因 / 实施 / 实测 / 经验）
- [x] CLAUDE.md 版本号更新 + 迭代历史摘要新增 v0.24.1 行
- [x] pyproject.toml 版本号 0.24.0 → 0.24.1
- [ ] `/ship` 提交（等待用户确认）

## 复盘

**亮点**：
- 一次性修复 7 处同源 bug（不止用户报告的 user_tweets，所有批量 fetcher 都享受到统一改造）
- 抽出 helper 让代码净减 ~30 行 + 行为统一化（之前 3 种风格：3 次同账号 / 直接 break / 1 次半成品）
- 新加 8 个 unit test 覆盖死循环 / 异常 / 全限流 / 单账号边界

**经验**：
- `load_twitter_cookies()` 已经实现"跳过限流账号"逻辑，关键是要**在重试循环里重新调用它**——而不是缓存第一次的 cookies 字典反复用
- 多账号重试的最强语义：重试次数 = 账号数，每次天然切到下一个可用账号；全部限流才真正终止
- 关键日志格式 `>>> 关键事件 <<<` + 剩余可用账号数 + 倒计时，让用户一眼看清楚发生了什么 / 还能等多久
