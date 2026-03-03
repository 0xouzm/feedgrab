# TwitterAPI.io 接入方案综合分析

2026-3-3迭代需求记录：

> 经过我们前面的迭代，对x 推文抓取功能已经非常全面了，但是我想尽可能的完美万无一失。后期可能会把feedgrab部署到服务器openclaw系统中让ai自动主导运行，那么我们推文抓取的最后一个启动真实浏览器的方案可能会有问题，还是这个我自己测试的时候，时不时还是会遇到搜索翻页不久一会就会被限制的情况，我综合考虑和调研了下有一个付费api成本很低，我现在要你帮我 对批量抓取推文（主要要按推特账号主页批量抓取的情况）新增一个走付费api的方案。
>
> 
>
> 我这里保存了一个该付费api平台姐好啊的基本文档，和我用的对比文档，我发给你也看看"C:\Users\Qiang\Documents\Twitter-X-API服务商对比报告.md"和"C:\Users\Qiang\Documents\TwitterAPI-io获取用户全部推文分析.md"，我基本确定了采用 twitterapi.io 这家api服务商，你根据官方文档地址去读取分析下，他的推文获取接口，我们要实现的功能：
>
> 
>
> 1、给推特账号主页地址，批量获取该账号下截止目前位置的所有推文（同时看看这个接口是否可以设置参数 比如 返回的推文id和元数据如果有元数据是否可以默认采集所有推文id或链接，还是根据条件如阅读量 点赞 评论 超多过少的获取信息）；
>
> 2、分析api返回的数据结构，如果一次性都包含了元数据和正文信息，那就直接保存下载，如果只有元数据正文需要再次查询获取，那就付费api只那推文id（或推文url地址），拿到推文id或url换我们现有的单篇获取方案0成本下载。
>
> 
>
> 总之就是新增这个付费api核心解决的问题就是高效完整的拿到推特账号下所有推文的id或url，然后能一次下载内容更好，如果数据不全就走我们现有的单篇抓取方案拿到完整元数据和内容。你先综合分析下，链接到官方文档速度分析下后我们再敲定方案。

> 分析日期：2026-03-03
> 状态：已确认，进入实施阶段

---

## 一、背景

feedgrab 现有的 X/Twitter 批量抓取方案（按账号主页抓取全部推文）存在两个痛点：

1. **UserTweets GraphQL API 受服务端限制**，每次最多返回 ~800 条推文
2. **浏览器搜索补充方案**（Playwright）在翻页不久后容易被 Twitter 限流，且不适合服务器（OpenClaw）无头部署

经调研 10 家 Twitter API 服务商后，选定 **TwitterAPI.io** 作为付费 API 方案：
- 按量付费，无月费，$0.15/千条推文
- 59 个端点，功能最全
- 7年+ 历史数据，无推文数量限制
- 1000+ QPS，99.99% SLA
- 只需 API Key，无需 Twitter Cookie/浏览器

---

## 二、API 数据完整性对比

| 字段 | TwitterAPI.io 返回 | 我们现有 GraphQL 返回 | 差异 |
|------|:------------------:|:--------------------:|------|
| 正文 `text` | ✅ | ✅ | 一致 |
| 点赞/转发/阅读/书签 | ✅ 全部 | ✅ 全部 | 一致 |
| 作者信息 | ✅ 非常详细 | ✅ | 一致 |
| **图片 URL** | **❌ 未提供** | ✅ `media_url_https` | **关键缺失** |
| **视频 URL** | **❌ 未提供** | ✅ 最高码率 mp4 | **关键缺失** |
| **长文 Article** | ❌ 需单独接口 | ✅ `_extract_article_ref` | **缺失** |
| 引用推文 | ✅ `quoted_tweet` | ✅ | 一致 |
| 转推原文 | ✅ `retweeted_tweet` | ✅ | 一致 |
| Hashtags | ✅ `entities.hashtags` | ✅ | 一致 |
| URLs | ✅ `entities.urls` | ✅（t.co 已展开） | API 的 t.co 可能未展开 |
| 线程重建 | ❌ 仅有 `conversationId` | ✅ 完整线程重建 | **缺失** |
| 日期 | ✅ `createdAt` | ✅ `created_at` | 格式不同 |

### 关键发现

1. **媒体缺失是最大问题**：API 的 `entities` 只有 `hashtags`、`urls`、`user_mentions`，没有 `media` 字段
2. **API 优势在于发现能力**：无需 Cookie/浏览器，7年+ 历史，无数量限制，支持高级搜索语法
3. **两个可用接口**：
   - `GET /twitter/user/last_tweets`：按用户名分页，每页20条
   - `GET /twitter/tweet/advanced_search`：支持 `from:user since:date until:date min_faves:N`

---

## 三、确定方案：API 发现 + GraphQL 下载（智能混合）

```
阶段 1：API 发现（付费，极低成本）
  TwitterAPI.io Advanced Search: from:username since:date
  → 快速拿到全部推文 ID + URL + 基础元数据（含互动数据）
  → 无浏览器、无 Cookie 依赖，服务器友好
  → $0.15/千条
  → 支持互动数据过滤（点赞/转发/阅读量门槛）

阶段 2：智能下载（免费，现有能力）
  对每个 tweet_id：
  ├─ 去重检查（全局索引）→ 已有则跳过
  ├─ 简单文本推文（无图片/视频）→ 可选：直接用 API 数据保存
  └─ 含媒体/线程/长文 → 走现有 GraphQL 单篇抓取（完整数据，0 成本）
```

---

## 四、配置项设计

```env
# === TwitterAPI.io 付费 API ===
TWITTERAPI_IO_KEY=xxx                  # API Key（从 twitterapi.io 获取）
X_API_PROVIDER=graphql                 # 批量抓取引擎：graphql（默认）| api（付费API）
X_API_SAVE_DIRECTLY=false              # 直接保存 API 数据，不走 GraphQL 二次抓取（默认 false）

# === 互动数据过滤（付费 API 专用） ===
# 仅在 X_API_PROVIDER=api 时生效
# 三项为"或"关系：满足任一条件即获取
# 不设置或留空 = 不启用该项过滤
X_API_MIN_LIKES=                       # 最低点赞数（如 100）
X_API_MIN_RETWEETS=                    # 最低转发数（如 50）
X_API_MIN_VIEWS=                       # 最低阅读量（如 10000）
```

### 过滤逻辑说明

- **三项为"或"(OR)关系**：满足任一条件即获取该推文
- 例如设置 `X_API_MIN_LIKES=100` + `X_API_MIN_VIEWS=10000`：点赞≥100 **或** 阅读≥10000 的推文都会被获取
- 选择"或"关系的原因：一条推文可能阅读量很高但点赞不多（信息型），也可能点赞很多但阅读量一般（小圈子热帖），"或"关系更宽容不会遗漏有价值内容
- **全部留空** = 不启用过滤，获取全部推文
- **部分留空** = 只按已设置的项过滤

---

## 五、文件架构

```
新增文件：
  feedgrab/fetchers/twitter_api.py              ← TwitterAPI.io HTTP 客户端
  feedgrab/fetchers/twitter_api_user_tweets.py  ← 付费 API 批量抓取主流程

修改文件：
  feedgrab/config.py              ← 新增配置项
  feedgrab/fetchers/twitter.py    ← 路由分支（X_API_PROVIDER=api 时走新路径）
  feedgrab/reader.py              ← 路由层适配
  .env.example                    ← 新增配置模板
```

---

## 六、成本估算

| 场景 | API 发现成本 | GraphQL 下载成本 | 总计 |
|------|:-----------:|:----------------:|:----:|
| 1万条推文全量 | **$1.50** | 免费 | **$1.50** |
| 5万条推文全量 | **$7.50** | 免费 | **$7.50** |
| 1万条（直接保存） | **$1.50** | 免费 | **$1.50** |
| 启用过滤（仅高互动） | 更低（获取少） | 免费 | < $1.50 |

---

## 七、对比现有方案

| 维度 | 现有方案（GraphQL + 浏览器搜索） | 新增 API 方案 |
|------|-------------------------------|-------------|
| 需要 Cookie | ✅ 必须 | ❌ 只需 API Key |
| 需要浏览器 | ✅ 超 800 条时 | ❌ 完全不需要 |
| 推文上限 | ~800 + 浏览器补充 | **无限制**（7年+历史） |
| 被限流风险 | 高（浏览器搜索易触发） | 极低（商业 API） |
| 服务器部署 | 困难（需 Playwright） | **友好**（纯 HTTP 请求） |
| 数据完整性 | 完整（媒体+线程+文章） | 需混合策略补媒体 |
| 成本 | 免费（但有风险成本） | ~$0.15/千条 |
| 互动过滤 | ❌ 不支持 | ✅ 支持点赞/转发/阅读量过滤 |

---

## 八、参考文档

- [TwitterAPI.io 官方文档](https://docs.twitterapi.io)
- [Get User Last Tweets 端点](https://docs.twitterapi.io/api-reference/endpoint/get_user_last_tweets)
- [Advanced Search 端点](https://docs.twitterapi.io/api-reference/endpoint/tweet_advanced_search)
- [Twitter 高级搜索语法参考](https://github.com/igorbrigadir/twitter-advanced-search)
- [TwitterAPI.io 定价](https://twitterapi.io/pricing)

---

*文档生成时间：2026-03-03*
