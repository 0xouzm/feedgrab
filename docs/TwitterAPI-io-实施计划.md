# 实施计划：TwitterAPI.io 付费 API 接入

## Context

feedgrab 现有的 X/Twitter 按账号批量抓取分两阶段：GraphQL UserTweets（免费，~800条）+ Playwright 浏览器搜索补充（突破 800 限制）。浏览器搜索容易被限流，不适合服务器部署。

**核心改动思路**：只替换最后的浏览器搜索补充环节，现有 GraphQL 主流程完全不动。
- 大部分账号推文不超过 800 条，GraphQL 主流程足够
- 超过 800 条时，原来走 Playwright 浏览器搜索，**现在改为优先走付费 API**
- 同时提供独立的全 API 路径（可选），供服务器部署场景使用

## 文件改动清单

| 文件 | 操作 | 改动量 | 说明 |
|------|------|--------|------|
| `feedgrab/config.py` | 修改 | +30行 | 新增 6 个配置函数 |
| `feedgrab/fetchers/twitter_api.py` | **新建** | ~200行 | API 客户端 + 数据解析 |
| `feedgrab/fetchers/twitter_api_user_tweets.py` | **新建** | ~350行 | API 补充抓取 + 独立全量抓取 |
| `feedgrab/fetchers/twitter_user_tweets.py` | 修改 | **~10行** | 补充触发点加 API 分支 |
| `feedgrab/reader.py` | 修改 | +20行 | 可选：全 API 路径路由 |
| `.env.example` | 修改 | +8行 | 配置模板 |

## Step 1: `feedgrab/config.py` — 新增配置函数

在 `x_search_max_pages_per_chunk()` 之后、`force_refetch()` 之前，新增：

```python
# ---------------------------------------------------------------------------
# TwitterAPI.io paid API (supplementary / standalone)
# ---------------------------------------------------------------------------

def twitterapi_io_key() -> str       # TWITTERAPI_IO_KEY, 默认 ""
def x_api_provider() -> str          # X_API_PROVIDER, 默认 "graphql"（可选 "api" 全量走付费API）
def x_api_save_directly() -> bool    # X_API_SAVE_DIRECTLY, 默认 false
def x_api_min_likes() -> int         # X_API_MIN_LIKES, 默认 0（不过滤）
def x_api_min_retweets() -> int      # X_API_MIN_RETWEETS, 默认 0
def x_api_min_views() -> int         # X_API_MIN_VIEWS, 默认 0
```

`x_api_min_*` 系列返回 int，0 表示不过滤。三项为 OR 关系。

## Step 2: `feedgrab/fetchers/twitter_api.py` — 新建 API 客户端

纯 HTTP 通信层 + 数据解析，不涉及业务逻辑。

**公开函数**:
- `search_tweets(query, query_type="Latest", cursor="") -> Optional[dict]`
- `get_user_last_tweets(user_name, cursor="", include_replies=False) -> Optional[dict]`
- `parse_api_tweet(raw: dict) -> dict` — API 推文 → `extract_tweet_data()` 兼容格式

**内部函数**:
- `_get_headers()` — 构建 `X-API-Key` 请求头
- `_request_with_retry(url, params)` — 重试逻辑（429 指数退避、5xx 重试、401/403 直接报错）

**`parse_api_tweet()` 关键字段映射**:
- `likeCount` → `likes`(int), `viewCount` → `views`(str), `conversationId` → `conversation_id`
- `images: []`, `videos: []` — API 不返回媒体，标记 `_from_api: True`
- `retweeted_tweet` 非空 → `_is_retweet: True`
- 展开 `entities.urls` 中的 t.co 短链

## Step 3: `feedgrab/fetchers/twitter_api_user_tweets.py` — 新建批量抓取

包含两个入口函数：

### 3a. `fetch_api_supplementary()` — 替换浏览器搜索补充

```python
async def fetch_api_supplementary(
    screen_name: str,
    display_name: str,
    since_date: str,
    earliest_tweet_date: str,
    subfolder: str,
    saved_ids: dict,
    is_force: bool,
) -> dict:
    """替换 twitter_search_tweets.fetch_search_supplementary()"""
    # 返回 {"total", "fetched", "skipped", "failed"}
```

**签名对齐现有 `fetch_search_supplementary()`**，去掉 `cookies` 参数（API 不需要）。

流程：
1. 构建查询 `from:{screen_name} since:{since_date} until:{earliest_tweet_date}`
2. 调 `search_tweets()` 分页发现推文
3. 互动过滤（`_passes_engagement_filter()`，OR 关系）
4. 去重（复用传入的 `saved_ids`）
5. 逐条处理：默认调 `_fetch_via_graphql()` 获取完整数据（含媒体），失败 fallback 到 API 数据
6. `from_twitter()` → `save_to_markdown()` → `add_item()`

### 3b. `fetch_api_user_tweets()` — 独立全量路径（可选）

```python
async def fetch_api_user_tweets(profile_url: str) -> dict:
    """独立的全 API 路径，供 X_API_PROVIDER=api 时使用"""
    # 返回 {"total", "fetched", "skipped", "failed", "filtered", "list_path"}
```

完整独立流程（不依赖 GraphQL UserTweets 先跑）：
1. 解析 URL → screen_name
2. API 发现全部推文
3. 互动过滤 + 去重 + 会话去重
4. 逐条处理（`X_API_SAVE_DIRECTLY` 控制是否走 GraphQL 补充媒体）
5. 保存索引 + 批量记录

**两个函数共享的工具**:
- `_discover_tweets_via_search()` — API 分页发现
- `_passes_engagement_filter()` — 互动过滤（OR 关系）
- `_parse_profile_url()` — URL 解析

**复用的现有函数**（不修改）:
- `twitter_bookmarks._classify_tweet()` — 推文分类
- `twitter_bookmarks._build_single_tweet_data()` — 单推文构建
- `twitter_bookmarks._sanitize_folder_name()` — 目录名清理
- `twitter_bookmarks._fetch_article_body()` — 长文正文
- `twitter._fetch_via_graphql()` — 完整线程/媒体获取
- `twitter._clean_title()` — 标题截断
- `dedup.*` — 去重索引
- `storage.save_to_markdown()` — 保存
- `schema.from_twitter()` — 数据转换

## Step 4: `feedgrab/fetchers/twitter_user_tweets.py` — 最小改动

**仅修改第 512-545 行的补充触发点**，改动约 10 行：

```python
# 原代码（第 512-523 行）:
if (since_date
    and earliest_tweet_date
    and earliest_tweet_date > since_date
    and x_search_supplementary_enabled()):
    # ... 直接调 fetch_search_supplementary(浏览器搜索)

# 改为:
if (since_date
    and earliest_tweet_date
    and earliest_tweet_date > since_date
    and x_search_supplementary_enabled()):

    from feedgrab.config import twitterapi_io_key

    if twitterapi_io_key():
        # 优先走付费 API 补充（无需浏览器）
        logger.info("[UserTweets] 使用 TwitterAPI.io 补充抓取")
        from feedgrab.fetchers.twitter_api_user_tweets import fetch_api_supplementary
        search_result = await fetch_api_supplementary(
            screen_name=screen_name,
            display_name=display_name,
            since_date=since_date,
            earliest_tweet_date=earliest_tweet_date,
            subfolder=subfolder,
            saved_ids=saved_ids,
            is_force=is_force,
        )
    else:
        # 兜底：浏览器搜索补充（原有逻辑不变）
        logger.info("[UserTweets] 使用浏览器搜索补充抓取")
        from feedgrab.fetchers.twitter_search_tweets import fetch_search_supplementary
        search_result = await fetch_search_supplementary(
            screen_name=screen_name,
            display_name=display_name,
            cookies=cookies,
            since_date=since_date,
            earliest_tweet_date=earliest_tweet_date,
            subfolder=subfolder,
            saved_ids=saved_ids,
            is_force=is_force,
        )
```

**逻辑**：配置了 `TWITTERAPI_IO_KEY` → 走 API 补充；未配置 → 原有浏览器搜索不变。

## Step 5: `feedgrab/reader.py` — 可选全 API 路由

修改 `_read_user_tweets()` 方法（第 227-260 行），在检查 `x_user_tweets_enabled()` 之后、cookies 检查之前，加入 provider 分支：

```python
# 新增：全 API 路径（服务器部署场景）
from feedgrab.config import x_api_provider
if x_api_provider() == "api":
    from feedgrab.config import twitterapi_io_key
    if not twitterapi_io_key():
        raise ValueError("X_API_PROVIDER=api 但 TWITTERAPI_IO_KEY 未配置")
    from feedgrab.fetchers.twitter_api_user_tweets import fetch_api_user_tweets
    result = await fetch_api_user_tweets(url)
    # ... 返回 summary（含 filtered 统计）

# 原有 GraphQL 路径完全不动
```

## Step 6: `.env.example` — 新增配置段落

在第 51 行（Search API 搜索补充）之后新增：

```env
# === Twitter/X 付费 API（TwitterAPI.io）===
# 替代浏览器搜索补充，无推文数量限制，服务器友好，$0.15/千条
# 配置 API Key 后，超过 800 条时自动用 API 替代浏览器搜索
# TWITTERAPI_IO_KEY=                    # API Key，从 https://twitterapi.io 获取
# X_API_PROVIDER=graphql                # graphql(默认,现有流程) | api(全量走付费API,服务器场景)
# X_API_SAVE_DIRECTLY=false             # true=直接保存API数据(快,无图片) / false=API发现+GraphQL下载(推荐)
# X_API_MIN_LIKES=                      # 最低点赞数（留空=不过滤，三项为 OR 关系）
# X_API_MIN_RETWEETS=                   # 最低转发数（留空=不过滤）
# X_API_MIN_VIEWS=                      # 最低阅读量（留空=不过滤）
```

## 实施顺序

| 步骤 | 文件 | 依赖 |
|------|------|------|
| 1 | `config.py` | 无 |
| 2 | `twitter_api.py` | config.py |
| 3 | `twitter_api_user_tweets.py` | twitter_api.py + 现有模块 |
| 4 | `twitter_user_tweets.py` (最小改动) | twitter_api_user_tweets.py |
| 5 | `reader.py` | twitter_api_user_tweets.py |
| 6 | `.env.example` | 无 |

## 验证方案

1. **API 通信**：`python -c "from feedgrab.fetchers.twitter_api import search_tweets; ..."` 验证 API 调用
2. **补充抓取**：设置 `TWITTERAPI_IO_KEY` + `X_USER_TWEETS_SINCE=2025-01-01`，对推文多的账号测试，确认超 800 条后走 API 而非浏览器
3. **全 API 路径**：`X_API_PROVIDER=api` 测试独立路径
4. **互动过滤**：`X_API_MIN_LIKES=100` 测试 OR 过滤逻辑
5. **去重兼容**：两种模式共享 `item_id_url.json`，切换后不重复下载
6. **未配置 API Key**：确认退回浏览器搜索（原有行为不变）
