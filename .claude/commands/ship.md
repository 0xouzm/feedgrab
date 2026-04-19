完成当前功能的收尾工作：优先使用 Git Bash 执行 `D:\Git\bin\bash.exe ./scripts/ship.sh` 做收尾检查；若 Git Bash 不可用，再回退执行 `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ship.ps1`。然后更新文档、提交代码、推送到 GitHub。

请按以下步骤执行：

## 1. 确认当前状态

运行 `git status` 和 `git diff --stat` 查看所有变更，确认功能已完成。

## 2. 更新 DEVLOG.md

在 DEVLOG.md 顶部（第一个 `---` 分隔线之前）新增本次版本条目，格式：

```markdown
## YYYY-MM-DD · vX.Y.Z · 功能标题

### 背景
为什么要做这个功能，解决什么问题。

### 方案决策
选择了什么技术方案，关键设计决策。

### 改动范围

| 文件 | 类型 | 改动 |
|------|------|------|
| `路径` | 新建/修改 | 说明 |

### 验证结果
测试了什么，结果如何。

### 状态：已完成 ✅
```

## 3. 更新 CLAUDE.md / AGENTS.md

同步更新 CLAUDE.md 中的项目信息，确保与最新代码一致：
- **当前版本号** — 更新"迭代历史摘要"表格，新增本次版本条目
- **核心架构** — 如有新增/删除文件，更新目录树
- **支持的平台** — 如有新平台或抓取方式变更，更新平台表格
- **关键设计决策** — 如有重要的新设计决策，补充说明

同步更新 AGENTS.md（Codex CLI 使用的项目指令副本）：
- AGENTS.md 与 CLAUDE.md 内容对齐，面向 Codex CLI / 其他非 Claude Code 的 AI 代理
- 更新策略：CLAUDE.md 改什么，AGENTS.md 跟着改什么（版本号、架构图、平台表、关键设计决策保持一致）
- 若 CLAUDE.md 有精简（删掉 DEVLOG 已覆盖的细节），AGENTS.md 同步精简

## 4. 更新 README.md

将新功能的使用说明同步到 README.md 的对应位置：
- 新命令 → CLI 示例区
- 新配置项 → 配置表格
- 新平台/功能 → 平台支持表格
- 新文件 → 架构图

同时更新 README_EN.md（如果存在且内容对应）。

## 5. 更新 skills/ 技能包

本项目自身 skill 化的 5 个技能包位于 `skills/` 目录，需要与最新 CLI 能力保持一致：

| 技能包 | 关注点 | 更新条件 |
|--------|--------|---------|
| `skills/feedgrab/SKILL.md` | 单条 URL 抓取 | 新增平台 / 新命令 / description 里平台清单过期 |
| `skills/feedgrab-batch/SKILL.md` | 批量抓取 | 新增批量命令（`x-so` / `xhs-so` / `mpweixin-zhuanji` 等） |
| `skills/feedgrab-setup/SKILL.md` | 安装配置 | 新增依赖 / 配置项 / 诊断命令 |
| `skills/analyzer/SKILL.md` | 内容分析 | 分析输出模板或 LLM 参数变化时 |
| `skills/video/SKILL.md` | 视频/播客摘要 | 新增播客平台（如 v0.17.0 的小宇宙/喜马拉雅）/ 字幕源 / Whisper 管线 |

同步要点：
- **description 字段里的平台/能力清单**必须反映实际支持（会被 skill 路由使用）
- **Supported Platforms / Commands 表格**要加上新平台和新命令
- **Examples 章节**补充新功能用法
- 本次迭代如果没有新增平台/命令，仍需快速扫一遍确认 description 不过期

## 6. 提交代码

将所有变更（包括文档更新）一起提交：
- 使用 conventional commit 格式（feat/fix/docs/chore）
- 提交信息用英文前缀 + 英文描述

## 7. 推送到 GitHub

```bash
git push origin main
```

推送完成后告知用户结果。
