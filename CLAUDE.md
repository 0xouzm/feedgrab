# feedgrab 项目指令

## 项目概述

feedgrab 是一个万能内容抓取器，从任意平台（X/Twitter、小红书、YouTube、B站、微信公众号等）抓取内容并输出为结构化 Markdown。

## 语言规范

- 所有对话、提交信息、文档内容一律使用**中文**
- 代码注释可以用英文
- Git commit message 使用英文前缀（feat/fix/docs/chore）+ 英文描述

## 开发工作流

完成功能开发并测试通过后，执行以下收尾流程：

1. **更新 DEVLOG.md** — 在文件顶部（`---` 分隔线之前）新增版本条目，包含：背景、方案决策、改动范围、验证结果、状态
2. **更新 README.md** — 同步新功能的使用说明、配置项、架构图等
3. **提交代码** — 使用 conventional commit 格式
4. **推送到 GitHub** — `git push origin main`

> 提示：可以使用 `/ship` 命令一键完成上述收尾流程。

## 文件说明

| 文件 | 用途 |
|------|------|
| `DEVLOG.md` | 开发日志 — 每次迭代的方案、细节、状态追踪 |
| `README.md` | 用户文档 — 安装、使用、配置说明 |
| `.env.example` | 配置模板 — 新增配置项时同步更新 |
| `feedgrab/config.py` | 集中配置 — 所有环境变量读取和默认值 |
| `feedgrab/cli.py` | CLI 入口 — 命令路由和帮助文本 |

## 版本号规范

- 主要新功能：递增次版本号（如 v0.2.9 → v0.3.0）
- 小功能/修复：递增补丁号（如 v0.3.0 → v0.3.1）
- 版本号记录在 DEVLOG.md 的条目标题中

## 目录结构

```
feedgrab/
├── feedgrab/          # Python 包源码
├── skills/            # Claude Code 技能（video/analyzer）
├── sessions/          # Cookie/Session 存储（git 忽略）
├── output/            # 抓取输出（git 忽略）
├── DEVLOG.md          # 开发日志
├── README.md          # 用户文档（中文）
├── README_en.md       # 用户文档（英文）
└── .env.example       # 配置模板
```
