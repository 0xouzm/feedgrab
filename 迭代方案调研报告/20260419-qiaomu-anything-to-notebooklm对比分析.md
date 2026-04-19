# qiaomu-anything-to-notebooklm vs feedgrab 深度对比调研报告

- **日期**：2026-04-19
- **目标仓库**：https://github.com/joeseesun/qiaomu-anything-to-notebooklm
- **提交**：`main` 分支最新（浅克隆）
- **仓库体量**：3549 行（main.py 458 + SKILL.md 735 + README.md 496 + scripts 546 + feishu-read-mcp 1314）
- **我方版本**：feedgrab v0.15.2

## 一、目标项目定位

该项目是 **Claude Code Skill**，本质是 **NotebookLM 的前置采集器 + 后置包装器**：

```
多源内容采集 → 转成 TXT → 上传 NotebookLM → 触发生成（播客/PPT/思维导图/Quiz/闪卡...）
                                            ↓
                                  可选：深度分析（10 问递归）
                                  可选：写入飞书文档
```

与 feedgrab 的**定位差异**：
- **feedgrab**：纯抓取器，把任意 URL → Obsidian 兼容 Markdown（端点就是 `.md` 文件）
- **qiaomu**：抓取只是一环，终点是 NotebookLM 生成播客等

因此两者**采集逻辑可相互借鉴，但后端处理（NotebookLM、飞书文档生成、深度分析问答）不是 feedgrab 定位**。

## 二、文件清单与规模

| 文件 | 行数 | 定位 | 对 feedgrab 参考价值 |
|------|------|------|-----------|
| `main.py` | 458 | CLI 入口 + 平台分派 + 深度分析 | ⭐ 只做分派，参考意义低 |
| `scripts/fetch_url.sh` | 380 | **付费墙绕过核心（6 层级联）** | ⭐⭐⭐⭐⭐ 最高 |
| `scripts/get_podcast_transcript.py` | 166 | Get笔记 API 播客/视频转写 | ⭐⭐⭐⭐ |
| `feishu-read-mcp/src/scraper.py` | 469 | 飞书 Playwright 抓取 | ⭐ 质量远低于 feedgrab |
| `feishu-read-mcp/src/parser.py` | 401 | HTML → Markdown | ⭐ 只识别 p/h1-h6/ul/ol/blockquote/pre/table |
| `feishu-read-mcp/src/image_handler.py` | 300 | aiohttp 图片下载 | ⭐⭐ 图片压缩/去重/白名单 |
| `feishu-read-mcp/src/server.py` | 128 | MCP 服务器 | ⭐ MCP 胶水代码 |
| `SKILL.md` | 735 | Skill 描述 + 工作流文档 | ⭐⭐⭐ 策略说明可参考 |

## 三、支持平台对比

| 平台 | qiaomu 方案 | feedgrab 方案 | 谁更强 |
|------|-------------|---------------|--------|
| 微信公众号 | `wexin-read-mcp`（README 提及但**仓库已删除**） | Browser JS 提取 + Jina + 搜狗/MP后台/专辑批量 + 视频 | **feedgrab** 完胜 |
| X/Twitter | `fetch_url.sh`：r.jina.ai → defuddle.md → agent-fetch | 六级兜底（GraphQL/FxTwitter/Syndication/oEmbed/Jina/Playwright）+ 批量/书签/搜索/List | **feedgrab** 完胜 |
| YouTube | 直接交 NotebookLM，**不自己抓** | InnerTube API + yt-dlp + Groq Whisper + 搜索/下载 | **feedgrab** 完胜 |
| **小宇宙** | **Get笔记 API 转写** ✅ | 域名检测但无 fetcher（落 Jina） | **qiaomu** 胜 |
| **喜马拉雅** | **Get笔记 API 转写** ✅ | 无 | **qiaomu** 胜 |
| **Apple Podcasts** | 无 | 域名检测但无 fetcher | 都没有 |
| B站视频 | **Get笔记 API 字幕转写** ✅ | API（只拿元数据 + 投稿），**没有视频字幕/转录** | **qiaomu** 胜 |
| 飞书 | Playwright `body.innerText` + HTML 解析 | Tier 0 Open API → Tier 1 CDP → Tier 2 PageMain Block → Tier 3 Export → Tier 4 Jina + Block→MD 20+ 类型 + 嵌入表格 Protobuf 解码 + 三阶段图片下载 + 知识库批量 | **feedgrab** 完胜 50 倍 |
| GitHub | 无专门处理 | REST API + 中文 README 优先 + 摘要 + 仓库级去重 | **feedgrab** 完胜 |
| **付费新闻** (NYT/WSJ/FT/...) | **6 层级联绕过，300+ 站点** ✅ | 仅 Jina 兜底（对硬付费墙无效） | **qiaomu** 完胜 |
| 小红书 | 无 | API (xhshow) + Pinia 注入 + Jina + Playwright + xhs-so | **feedgrab** 完胜 |
| 知乎 | 无 | API v4 + Playwright + Jina + zhihu-so | **feedgrab** 完胜 |
| 金山文档/有道 | 无 | ProseMirror DOM / JSON API | **feedgrab** 完胜 |
| Telegram | 无 | Telethon | **feedgrab** 完胜 |
| RSS | 无 | feedparser | **feedgrab** 完胜 |
| **EPUB** | **ebooklib 提取** ✅ | 无 | **qiaomu** 胜 |
| **PDF/DOCX/PPTX/XLSX/音频/图片** | markitdown 统一转换 | 无 | **qiaomu** 胜（但定位不同） |

## 四、qiaomu 核心技术亮点深度解读

### 亮点 A：付费墙绕过（`fetch_url.sh`，380 行） ★★★★★

**这是这个仓库最大的独立贡献。** feedgrab 完全没有相关能力。

#### 域名清单（硬编码）

```bash
# Googlebot UA 生效 (~22 个)
GOOGLEBOT_DOMAINS="wsj.com|barrons.com|ft.com|economist.com|theaustralian.com.au|
    thetimes.co.uk|telegraph.co.uk|zeit.de|handelsblatt.com|leparisien.fr|
    nzz.ch|usatoday.com|quora.com|lefigaro.fr|lemonde.fr|spiegel.de|
    sueddeutsche.de|frankfurter-allgemeine.de|brisbanetimes.com.au|
    smh.com.au|theage.com.au|..."

# Bingbot UA 生效 (4 个)
BINGBOT_DOMAINS="haaretz.com|nzherald.co.nz|stratfor.com|themarker.com"

# AMP 页面可用 (~12 个)
AMP_DOMAINS="wsj.com|bostonglobe.com|latimes.com|chicagotribune.com|
    seattletimes.com|theatlantic.com|wired.com|newyorker.com|
    washingtonpost.com|smh.com.au|theage.com.au|brisbanetimes.com.au"

# 所有已知付费墙 (44 个)
PAYWALL_DOMAINS="nytimes.com|wsj.com|ft.com|economist.com|bloomberg.com|..."
```

#### 绕过层级（`fetch_url.sh` 从上到下）

| Tier | 策略 | 覆盖 | 成功率（按 README 自述） |
|------|------|------|------|
| 1a | `r.jina.ai/<url>` 代理 | 通用 | 软付费墙常用 |
| 1b | `defuddle.md/<url>` 代理 | 通用 | 备选 |
| 2a | **Googlebot UA + `X-Forwarded-For: 66.249.66.1` + Referer `google.com` + JSON-LD 提取** | 22 站 | **最高** |
| 2b | Bingbot UA + Referer `bing.com` | 4 站 | 中 |
| 3a | Googlebot UA（对所有 `PAYWALL_DOMAINS`） | 44 站 | 中 |
| 3b | Bingbot UA（同上） | 44 站 | 中 |
| 3c | Facebook Referer（`law.com`/`ftm.nl`/`law360.com`/`sloanreview.mit.edu`） | 4 站 | 中 |
| 3d | Twitter `t.co` Referer（通用） | 44 站 | 中 |
| 3e | **AMP 页面**（尝试 `/amp`、`?outputType=amp`、`.amp.html`、`?amp`） | 12 站 | 中高 |
| 3f | EU IP（`X-Forwarded-For: 185.X.X.X`）+ Google Referer | 44 站 | 低 |
| 4 | **archive.today 存档**（CAPTCHA 自动检测 → 返回 exit 75 提示用户） | 全部 | 兜底 |
| 5 | Google Cache | 全部 | 降级 |
| 6 | `npx agent-fetch` 本地工具 | 全部 | 最后 |

#### 关键辅助函数（应当原样借鉴）

- `_extract_jsonld_article()`（行 91-95）：从 HTML 里正则抠出 `"articleBody":"..."` —— **这个策略对非付费站点也有效**（各大新闻站 SEO 会内嵌 JSON-LD）
- `_is_paywall_content()`（行 77-82）：识别 `subscribe to continue` 等 20+ 种付费墙文案
- `_is_captcha_page()`（行 84-88）：识别 Cloudflare Challenge / recaptcha / hcaptcha
- `_has_content()`（行 48-68）：行数 >8、字符 >500、过滤 `Access Denied`/`404 Not Found`/`Don't miss what's happening`

#### 不足

- 全是 Bash + sed/grep，**在 Windows 没 Git Bash 的环境不可用**
- HTML → text 仅用 sed 剥离标签（行 98-114），比 feedgrab 的 markdownify 差
- 没有 JS 渲染能力（对 React/Vue 单页应用无效）
- 域名列表硬编码，更新需要改代码

### 亮点 B：Get笔记 API 播客转写（`get_podcast_transcript.py`，166 行） ★★★★

**feedgrab 没有小宇宙/喜马拉雅/B站视频字幕**，这是可增量的新平台。

#### API 流程

```python
# Step 1: POST /open/api/v1/resource/note/save {note_type: "link", link_url: URL}
#         → 返回 task_id
# Step 2: 轮询 /open/api/v1/resource/note/task/progress （每 30s，最多 20 分钟）
#         status: success → 得到 note_id
# Step 3: GET /voicenotes/web/notes/{note_id}/links/detail
#         → 返回 {title, content, web_title}
#         content 就是完整转写文本（带时间戳）
```

#### 认证机制

- **OpenAPI Key** + **Client ID**（`GETNOTE_API_KEY` / `GETNOTE_CLIENT_ID`，用户向 Get笔记 官方申请）
- **Web JWT**（90 天有效，自动 refresh，存在 `~/.claude/skills/getnote/tokens.json`）

#### 限制

- 第三方商业服务 biji.com（罗辑思维系），**需付费 API Key**
- 转写需等待 1-20 分钟（音频服务端处理）
- 不是直接从小宇宙/喜马拉雅 API 抓原始数据，而是**上传 URL 交给 Get笔记 转写**

#### 可选替代方案（feedgrab 自己实现）

- **小宇宙**：可逆向其 Web API（`api.xiaoyuzhoufm.com/episode/{id}`），拿到音频 mp3 URL → Groq Whisper（feedgrab 已有 Whisper 能力）
- **喜马拉雅**：同上（`mobile.ximalaya.com/mobile-playpage/track/v3/baseInfo`）
- **B站视频字幕**：字幕接口 `api.bilibili.com/x/v2/dm/view` 或 `api.bilibili.com/x/player/wbi/v2?aid=...&cid=...` → `subtitle.subtitles[].subtitle_url`
- **B站无字幕时**：`yt-dlp` 下载音频 → Groq Whisper（feedgrab 的 YouTube 管线现成可复用）

**结论**：Get笔记 API 是 **"买算力"捷径**，feedgrab 应做 **"原生逆向 + Whisper 兜底"** 的自研方案。

### 亮点 C：JSON-LD articleBody 提取 ★★★★

```bash
_extract_jsonld_article() {
  echo "$html" | grep -o '"articleBody":"[^"]*"' | head -1 | \
    sed 's/^"articleBody":"//;s/"$//' | \
    sed 's/\\n/\n/g; s/\\"/"/g; s/\\\\/\\/g'
}
```

这个策略对**所有主流新闻站点通用**（不限付费墙）—— Schema.org NewsArticle 是 SEO 标配。  
feedgrab 可以作为 Jina 之前的一层兜底：先尝试 HTML + JSON-LD 提取，失败再走 Jina。

### 亮点 D：EPUB 提取 ★★★

```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

book = epub.read_epub(epub_path)
for item in book.get_items():
    if item.get_type() == ebooklib.ITEM_DOCUMENT:
        soup = BeautifulSoup(item.get_content(), 'html.parser')
        content.append(soup.get_text())
```

10 行代码。feedgrab 没有，如果要扩展「任意文件 → MD」可以加。

## 五、qiaomu 明显更差的点

### 飞书抓取（`feishu-read-mcp/src/scraper.py`）

对比 feedgrab `fetchers/feishu.py` 的差距：

| 维度 | qiaomu | feedgrab | 差距 |
|------|--------|----------|------|
| 认证 | 手动 cookie 字符串 | Open API App Key + CDP Cookie + Playwright storage_state 多源 | 3 倍 |
| 浏览器 | headless Chromium（无隐身） | patchright + 52 条 stealth flags | 反检测更强 |
| 内容提取 | **`document.body.innerText` 取文本** | `window.PageMain` Block 树 JSON（20+ block 类型） | 结构化完胜 |
| Block→MD | 只识别 `<p><h1-6><ul><ol><blockquote><pre><table>` 7 种 HTML 标签 | 20+ 种飞书 Block 类型（text/heading/bullet/ordered/todo/code/callout/isv/sheet/bitable/file/image/embed 等） | 覆盖率 3 倍 |
| 嵌入电子表格 | **完全不支持**（HTML 里没数据） | Protobuf 5 层 wire format 解码 + 懒加载分段预热 + `/sheet/block` 合并 | 独家 |
| 图片下载 | 简单 aiohttp 拉取 `<img src>` | 三阶段：network interceptor → scroll 触发懒加载 → DOM 发现真实 CDN + JS fetch 批量 | 独家 |
| 图片命名 | `md5(url).<ext>` 全局平铺 | `attachments/{item_id}/xxx.<ext>` 每文档独立子目录 | 更整洁 |
| 知识库批量 | 无 | Open API 递归节点树 + 断点续传 | 独家 |
| 零宽字符清理 | 无 | `_clean_feishu_title()` 过滤 U+200B-U+206F + U+FEFF | 独家 |

**结论**：飞书抓取 qiaomu 的实现是**玩具级**，一条也不值得借鉴。

### X/Twitter、YouTube、微信

qiaomu 的方案：
- Twitter：`r.jina.ai → defuddle.md → agent-fetch` 三级代理 — 拿不到完整线程/图片/视频/互动数据
- YouTube：**直接交给 NotebookLM 处理**（等于没实现）
- 微信：README 说走 `wexin-read-mcp`，但仓库已删除此目录

feedgrab 在这三个平台的深度远超 qiaomu，不存在可借鉴点。

### `main.py` 的平台分派

只是简单 `if-elif-else` 匹配域名和文件后缀，不如 feedgrab 的 `reader.py` 支持子路径识别（如小红书的 `/user/profile/` 走作者批量）。

## 六、不推荐融合的部分

| 项 | 为什么不融合 |
|----|------------|
| 飞书 MCP 整个子项目 | 实现质量远不如 feedgrab，混入反而是技术债 |
| NotebookLM 集成 | 不是 feedgrab 定位（feedgrab 是抓取器，不是 AI 前置） |
| 深度分析 10 问递归 | 同上，属于后处理/分析层 |
| 飞书文档生成（`lark-cli docs +create`） | 同上，反向写入不是 feedgrab 定位 |
| markitdown 统一文件转换 | 超出 feedgrab 当前范围（当前只做 URL 抓取，不做本地文件转换）。如要做，建议作为独立 skill 而非主 CLI |

## 七、推荐融合的技术点（按优先级）

### P0（强烈推荐，直接收益最大）

#### F1. 付费墙绕过引擎

**新建** `feedgrab/fetchers/paywall.py`：
- 把 `fetch_url.sh` 的 6 层级联**移植成 Python**（用 feedgrab 现有的 `utils/http_client.py`（curl_cffi）调用）
- 策略：
  1. Googlebot UA + `X-Forwarded-For: 66.249.66.1` + Google Referer（对 `GOOGLEBOT_DOMAINS`）
  2. Bingbot UA（对 `BINGBOT_DOMAINS`）
  3. 通用策略对 `PAYWALL_DOMAINS`：Googlebot / Bingbot / FB Referer / Twitter Referer / AMP / EU IP
  4. archive.today（检测 CAPTCHA，通过日志提示用户）
  5. Google Cache
- **JSON-LD articleBody 提取**作为每层响应的首选解析方式（行 91-95 的 `_extract_jsonld_article`）
- 域名列表放入 `config.py`，允许 `.env` 追加：`PAYWALL_DOMAINS_EXTRA=a.com|b.com`
- 在 `reader.py` 的"generic" 平台中，**Jina 之前**先跑 paywall bypass

#### F2. JSON-LD articleBody 提取（通用增强）

新建 `utils/jsonld.py`：
- `extract_jsonld_article(html) -> Optional[str]`
- 不限付费站点，作为 Jina 之前的一个**轻量前置策略**（HTTP 一次请求 + 正则，比 Jina 快 5-10 倍）

### P1（新增平台，独立增量）

#### F3. 小宇宙（`fetchers/xiaoyuzhou.py`）

**不依赖 Get笔记 API**，自研：
- Web API 逆向：`https://api.xiaoyuzhoufm.com/v1/episode/get?id={id}`（或抓页面 `__NEXT_DATA__`）
- 拿到音频 mp3 URL → 如有字幕直接转 MD；否则 Groq Whisper 转录（复用 `youtube.py` 现有管线）
- Front matter：`title`/`podcast_name`/`duration`/`publish_date`

#### F4. 喜马拉雅（`fetchers/ximalaya.py`）

类似小宇宙：
- Web API `mobile.ximalaya.com/mobile-playpage/track/v3/baseInfo`
- Groq Whisper 转录

#### F5. B站视频字幕（扩展 `fetchers/bilibili.py`）

- 字幕接口 `api.bilibili.com/x/player/wbi/v2?aid=...&cid=...` → `subtitle.subtitles[].subtitle_url`
- 有字幕直接转 MD，无字幕用 yt-dlp + Whisper（复用 YouTube 管线）
- CLI 新命令（如 `feedgrab bili-sub <URL>`）或复用 feedgrab 默认路由

### P2（可选，非核心）

#### F6. EPUB 提取（`fetchers/epub.py`）

- `ebooklib` + `BeautifulSoup`，10 行代码
- 只在 `reader.py` 检测到 `.epub` 本地文件时走该 fetcher
- 与 feedgrab 当前 URL-only 的定位有冲突，**建议作为独立 skill 而非主 CLI**

## 八、实施规划建议

### 方案 A：只做付费墙 + JSON-LD（风险最低）

- 1 周工作量
- 新增 `fetchers/paywall.py` + `utils/jsonld.py` + 域名列表配置
- 改 `reader.py` 的 generic 路由
- 升到 v0.16.0
- 测试：对 NYT/WSJ/FT/Bloomberg/The Information 各抓 3 篇，和 Jina 对比覆盖率

### 方案 B：A + 小宇宙/喜马拉雅/B站字幕（增量最大）

- 2-3 周
- 除 A 外新增 3 个 fetcher
- 升到 v0.16.0（付费墙）→ v0.17.0（播客三平台）

### 方案 C：A + B + EPUB + 本地文件支持（范围扩展）

- 3-4 周
- 触及 feedgrab 定位边界（URL → local file），需要你先确认是否扩展

## 九、结论

**qiaomu-anything-to-notebooklm 的核心贡献是付费墙绕过（`fetch_url.sh`）**。剔除这个脚本之后，它的其他抓取能力**全部弱于** feedgrab（其中飞书子项目差距最大）。

**建议动作**：
1. 优先融合付费墙绕过 → 新 `paywall.py` 模块，v0.16.0 主打"付费新闻网站全覆盖"
2. JSON-LD articleBody 提取 → 作为 Jina 前置兜底
3. 小宇宙 / 喜马拉雅 / B站字幕 → 自研方案（不依赖 Get笔记 付费 API），v0.17.0 主打"播客+视频字幕"
4. EPUB / 飞书 MCP / NotebookLM 集成 → **不融合**

---

## 附：参考仓库原文链接

- `fetch_url.sh` 全文（核心）：`scripts/fetch_url.sh`（已本地 clone，`/tmp/feedgrab-research/qiaomu-anything-to-notebooklm/`）
- `get_podcast_transcript.py` 全文：`scripts/get_podcast_transcript.py`
- [Bypass Paywalls Clean](https://gitflic.ru/project/magnolia1234/bypass-paywalls-chrome-clean)（付费墙策略原始来源，值得深挖）
- [Get笔记 OpenAPI](https://openapi.biji.com)（第三方播客转写服务）
