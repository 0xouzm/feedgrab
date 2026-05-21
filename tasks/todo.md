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
