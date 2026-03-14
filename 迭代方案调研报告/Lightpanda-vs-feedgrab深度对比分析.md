# Lightpanda vs feedgrab 深度对比分析

> 调研日期：2026-03-14
> 结论：**不值得融合，对 feedgrab 零加分**，终止融合计划

---

## Lightpanda 是什么

| 属性 | 值 |
|------|-----|
| 仓库 | [lightpanda-io/browser](https://github.com/lightpanda-io/browser) |
| 语言 | **Zig**（从零构建，非 Chromium fork） |
| JS 引擎 | V8 |
| 版本 | v0.2.5（Beta） |
| Stars | 15,600+ |
| 许可证 | **AGPL-3.0**（传染性开源） |
| 贡献者 | 22 人（核心团队约 3-4 人） |
| 创建时间 | 2023-02-07 |
| 最近推送 | 2026-03-14（非常活跃） |

核心思路：砍掉一切图形渲染（CSS 布局、图片解码、GPU 合成、字体光栅化），只保留 DOM + JS + 网络，所以启动快 30-50x、运行快 11x、内存省 9x。

### 基准测试数据

| 指标 | Chrome Headless | Lightpanda | 倍率 |
|------|---------------|------------|------|
| Puppeteer 请求 100 页 | 25.2s | 2.3s | **11x** |
| 峰值内存 | 207MB | 24MB | **9x** |
| 启动时间 | 3-5s | <100ms | **30-50x** |
| AWS m5.large 并发实例 | ~15 | ~140 | **9x** |

> **重要提醒**：基准测试使用的是本地简单网站（[lightpanda-io/demo](https://github.com/lightpanda-io/demo)）。社区普遍认为，随着网站复杂度增加和 Web API 实现增多，性能差距会缩小。

---

## 关键结论：不值得融合，对 feedgrab 零加分

原因按重要性排序：

### 1. 反爬能力为零 — 致命硬伤

feedgrab 面对的平台**全部有反爬**，而 Lightpanda 官方明确表态不打算解决：

| 检测维度 | feedgrab (patchright) | Lightpanda |
|---------|----------------------|------------|
| UA 自定义 | 完整控制 | **只允许加后缀**，`setUserAgentOverride` 未实现 |
| TLS 指纹 (JA3/JA4) | curl_cffi 完美伪装 Chrome | libcurl，**非浏览器指纹** |
| `navigator.webdriver` | patchright CDP 层移除 | 未知/未处理 |
| Canvas/WebGL 指纹 | 真实 Chrome 引擎 | **无渲染引擎，返回空值** |
| Web API 覆盖 | Chrome 级别完整 | 数百个 API 缺失，FingerprintJS 一查即知 |
| browserscan.net | 通过 | **JS 直接报错崩溃** |

> Lightpanda 官方开发者原话：*"Lightpanda 与其他浏览器有太多差异，通过 Web API 实现或 HTTP/TLS 指纹就很容易被发现。这种情况下我建议使用传统浏览器。"* — issue [#1436](https://github.com/lightpanda-io/browser/issues/1436)

### 2. SPA 页面基本不能工作

feedgrab 抓取的平台大量使用 SPA：
- **飞书**：Vue/React 渲染的 `window.PageMain` block 树 → Lightpanda 无法初始化
- **小红书**：Vue SSR + 客户端 hydration → 大概率 JS 报错
- **微信公众号**：WeChat JS Bridge 环境 → 不可能支持
- **Twitter**：React SPA → 无法加载

官方 issue [#1798](https://github.com/lightpanda-io/browser/issues/1798) 确认 SPA 需要大量尚未实现的 Web API。

### 3. 功能缺失覆盖 feedgrab 的全部需求

| feedgrab 必需功能 | Lightpanda 支持 |
|------------------|----------------|
| 多标签页并行 | **不支持**（每连接 1 page） |
| Storage State（登录态） | **不支持** |
| Cookie 完整管理 | 部分 |
| `page.on("response")` 拦截 | 基础支持，但不稳定 |
| iframe 内交互 | 不工作 |
| 文件上传/下载 | **不支持** |
| headed 模式（人工验证码） | **不存在**（无 GUI） |

### 4. 稳定性不够生产使用

- 多用户报告**段错误崩溃**（WordPress、Amazon、NIST.gov 等普通网站）
- issue [#882](https://github.com/lightpanda-io/browser/issues/882)：*"99% 的网站都被拦截了…这软件目前没法用"*
- 版本号还在 v0.2.x，官方标注 "work in progress, may encounter errors or crashes"

### 5. Python 生态为零

- **无 Python SDK**
- playwright-python 的 `connect_over_cdp()` 存在兼容性 bug（frame ID 不匹配，[#1800](https://github.com/lightpanda-io/browser/issues/1800)）
- feedgrab 全部浏览器代码基于 playwright/patchright Python API，无法复用

### 6. 许可证风险

AGPL-3.0 有**传染性**：如果 feedgrab（MIT 许可）集成 Lightpanda，可能被迫将整个项目改为 AGPL。

---

## feedgrab 现有方案 vs Lightpanda 逐平台对比

| 平台 | feedgrab 现有方案 | Lightpanda 能否替代 |
|------|------------------|-------------------|
| **Twitter** | GraphQL → FxTwitter → Syndication → oEmbed → Jina → Playwright（浏览器几乎不用） | 无意义，前 5 级已覆盖 |
| **小红书** | xhshow API → Jina → Playwright（浏览器是降级路径） | 无法通过反爬 |
| **微信** | Playwright JS evaluate（**浏览器是主力**） | WeChat JS Bridge 不可能支持 |
| **飞书** | Open API → Playwright PageMain → Export API → Jina | SPA 无法渲染，patchright 都被拒更别说 Lightpanda |
| **YouTube** | yt-dlp + API（不用浏览器） | 不相关 |
| **GitHub** | REST API（不用浏览器） | 不相关 |
| **Jina 兜底** | HTTP 调用 Jina 服务（不用浏览器） | 不相关 |

**结论**：feedgrab 真正依赖浏览器的场景（微信、飞书、小红书降级），Lightpanda 一个都做不了。不依赖浏览器的场景（Twitter GraphQL、YouTube API、GitHub API），也不需要它。

---

## CDP 协议支持情况（参考）

| CDP Domain | 状态 | 说明 |
|-----------|------|------|
| `Page` | 已实现 | 导航、生命周期事件 |
| `DOM` | 已实现 | DOM 查询和操作 |
| `Runtime` | 已实现 | JS 执行（`evaluate`/`callFunctionOn`） |
| `Network` | 已实现 | 网络请求监控 |
| `Fetch` | 已实现 | 网络请求拦截 |
| `Input` | 已实现 | 点击、表单输入 |
| `Target` | 已实现 | 目标管理（多连接支持） |
| `Accessibility` | 部分实现 | 语义树提取（专为 AI 优化） |
| `Storage` | 已实现 | Cookie 管理 |
| `Emulation` | **部分** | `setUserAgentOverride` **未实现** |
| `CSS` | 部分实现 | CSSOM 刚开始支持 |
| `LP`（自定义） | 已实现 | `LP.getMarkdown` — 直接输出 Markdown |

---

## 什么时候值得重新评估

| 条件 | 当前状态 |
|------|---------|
| 版本号 ≥ v1.0 | v0.2.5 |
| SPA 完整支持 | 基本不支持 |
| `setUserAgentOverride` 实现 | 官方拒绝 |
| Storage State 支持 | 不支持 |
| 多 page/context | 不支持 |
| Python SDK 出现 | 无 |
| 社区有"过 Cloudflare"案例 | 无 |

**建议**：至少等到 v1.0 + SPA 支持 + Python 生态成型再回来看。以 Lightpanda 当前的开发方向（为 AI agent 提供轻量语义提取，而非做反爬工具），可能永远不会成为 feedgrab 的合适方案。

---

## 附：分析过程中发现的 feedgrab 浏览器层改进机会

> 以下与 Lightpanda 无关，是分析 `browser.py` 时顺便发现的优化点

1. **`_build_wechat_result` 死代码**：`browser.py` 第 592 行 `return result` 后的 `cgiMetrics` 处理永远不执行，微信阅读量/点赞数被丢弃
2. **Twitter Tier 3 未用隐身引擎**：`twitter.py` 和 `twitter_search_tweets.py` 直接用 vanilla playwright，未走 `stealth_launch`
3. **资源拦截不统一**：Twitter 两个浏览器路径未启用资源拦截，加载了不必要的字体/tracking 脚本

---

## 参考链接

- [Lightpanda GitHub 仓库](https://github.com/lightpanda-io/browser)
- [Lightpanda 官网](https://lightpanda.io/)
- [性能基准测试详情](https://github.com/lightpanda-io/demo)
- [CDP 技术博客](https://lightpanda.io/blog/posts/cdp-vs-playwright-vs-puppeteer-is-this-the-wrong-question)
- [Bot 检测问题 #1177](https://github.com/lightpanda-io/browser/issues/1177)
- [Python Playwright 支持 #552](https://github.com/lightpanda-io/browser/issues/552)
- [SPA 支持 #1798](https://github.com/lightpanda-io/browser/issues/1798)
- [UA 自定义 #1436](https://github.com/lightpanda-io/browser/issues/1436)
- [稳定性问题 #1304](https://github.com/lightpanda-io/browser/issues/1304)
- [多 context/page 问题 #882](https://github.com/lightpanda-io/browser/issues/882)
- [Playwright connectOverCDP 问题 #1800](https://github.com/lightpanda-io/browser/issues/1800)
