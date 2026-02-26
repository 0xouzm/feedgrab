# feedgrab 升级计划

本文档记录每次升级迭代的确定方案，作为项目演进的记忆文件。

---

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
