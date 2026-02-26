#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
feedgrab 发布自动化脚本

功能：
    1. 版本号管理（自动递增或指定版本）
    2. 更新日志生成（从 git log 提取，写入 更新日志.md）
    3. README 同步检查（验证版本号、安装链接一致性）
    4. pip 安装包构建验证
    5. Git tag 创建 + 推送

用法：
    python scripts/release.py                    # 交互式（提示输入版本号和变更说明）
    python scripts/release.py --version 0.3.0    # 指定版本号
    python scripts/release.py --check            # 仅检查，不发布
    python scripts/release.py --build            # 检查 + 构建验证
"""

import os
import re
import sys
import json
import subprocess
from datetime import datetime
from pathlib import Path

# === 项目路径 ===
ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "更新日志.md"
PLAN = ROOT / "plan.md"
README_EN = ROOT / "README.md"
README_ZH = ROOT / "README_zh.md"
REPO_URL = "https://github.com/iBigQiang/feedgrab"


def get_current_version() -> str:
    """从 pyproject.toml 读取当前版本号。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', text)
    if not match:
        print("❌ 无法从 pyproject.toml 读取版本号")
        sys.exit(1)
    return match.group(1)


def set_version(new_version: str):
    """更新 pyproject.toml 中的版本号。"""
    text = PYPROJECT.read_text(encoding="utf-8")
    text = re.sub(
        r'version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        text,
    )
    PYPROJECT.write_text(text, encoding="utf-8")
    print(f"✅ pyproject.toml 版本号更新为 {new_version}")


def bump_version(current: str, bump_type: str = "patch") -> str:
    """递增版本号。bump_type: major / minor / patch"""
    parts = current.split(".")
    if len(parts) != 3:
        print(f"❌ 版本号格式不正确: {current}")
        sys.exit(1)
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:
        return f"{major}.{minor}.{patch + 1}"


def get_git_log_since_tag() -> list:
    """获取自上一个 tag 以来的 git commit 列表。"""
    try:
        last_tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=ROOT, stderr=subprocess.DEVNULL
        ).decode().strip()
        range_spec = f"{last_tag}..HEAD"
    except subprocess.CalledProcessError:
        range_spec = "HEAD~20..HEAD"

    try:
        log = subprocess.check_output(
            ["git", "log", range_spec, "--pretty=format:%s"],
            cwd=ROOT
        ).decode().strip()
        return [line for line in log.split("\n") if line.strip()]
    except subprocess.CalledProcessError:
        return []


def categorize_commits(commits: list) -> dict:
    """将 commit 按 conventional commit 类型分类。"""
    categories = {
        "新增": [],
        "变更": [],
        "修复": [],
        "文档": [],
        "其他": [],
    }
    for msg in commits:
        lower = msg.lower()
        if lower.startswith("feat"):
            categories["新增"].append(msg)
        elif lower.startswith("fix"):
            categories["修复"].append(msg)
        elif lower.startswith("docs"):
            categories["文档"].append(msg)
        elif lower.startswith(("refactor", "chore", "ci", "build")):
            categories["变更"].append(msg)
        else:
            categories["其他"].append(msg)
    return {k: v for k, v in categories.items() if v}


def update_changelog(version: str, categories: dict, summary: str = ""):
    """在更新日志.md 顶部插入新版本条目。"""
    today = datetime.now().strftime("%Y-%m-%d")

    entry_lines = [f"## [{version}] - {today}", ""]
    if summary:
        entry_lines.append(summary)
        entry_lines.append("")

    for category, commits in categories.items():
        entry_lines.append(f"#### {category}")
        for msg in commits:
            # 清理 conventional commit 前缀
            clean = re.sub(r'^(feat|fix|docs|refactor|chore|ci|build)(\([^)]*\))?:\s*', '', msg)
            entry_lines.append(f"- {clean}")
        entry_lines.append("")

    entry_lines.append("---")
    entry_lines.append("")
    new_entry = "\n".join(entry_lines)

    if CHANGELOG.exists():
        content = CHANGELOG.read_text(encoding="utf-8")
        # 在第一个 ## 之前插入
        marker = "\n## ["
        idx = content.find(marker)
        if idx >= 0:
            content = content[:idx] + "\n" + new_entry + content[idx:]
        else:
            content += "\n" + new_entry
    else:
        content = (
            "# 更新日志\n\n"
            "所有重要的项目变更都记录在此文件中。\n\n"
            "格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，"
            "版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。\n\n"
            "---\n\n" + new_entry
        )

    CHANGELOG.write_text(content, encoding="utf-8")
    print(f"✅ 更新日志.md 已添加 v{version} 条目")


def check_readme_consistency(version: str) -> list:
    """检查 README 中的链接和信息一致性。"""
    issues = []
    for readme_path in [README_EN, README_ZH]:
        if not readme_path.exists():
            continue
        content = readme_path.read_text(encoding="utf-8")
        name = readme_path.name

        # 检查仓库链接
        if "runesleo/x-reader" in content:
            issues.append(f"{name}: 仍有旧链接 runesleo/x-reader（安装命令中）")
        if "x_reader" in content:
            issues.append(f"{name}: 仍有旧模块名 x_reader")

        # 检查项目名一致性
        if content.startswith("# x-reader"):
            issues.append(f"{name}: 标题仍为 x-reader，应为 feedgrab")

        # 检查安装链接可达性
        if REPO_URL not in content:
            issues.append(f"{name}: 缺少仓库链接 {REPO_URL}")

    return issues


def verify_build() -> bool:
    """验证 pip 包能否正常构建。"""
    print("🔨 验证 pip 包构建...")
    try:
        # 清理旧构建
        dist_dir = ROOT / "dist"
        if dist_dir.exists():
            for f in dist_dir.iterdir():
                f.unlink()

        result = subprocess.run(
            [sys.executable, "-m", "build", "--sdist"],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            # 找到构建产物
            artifacts = list(dist_dir.glob("feedgrab-*.tar.gz"))
            if artifacts:
                size = artifacts[0].stat().st_size
                print(f"✅ 构建成功: {artifacts[0].name} ({size:,} bytes)")
                return True
        print(f"❌ 构建失败:\n{result.stderr[-500:]}")
        return False
    except Exception as e:
        print(f"❌ 构建异常: {e}")
        return False


def create_git_tag(version: str):
    """创建并推送 git tag。"""
    tag = f"v{version}"
    subprocess.run(["git", "tag", tag], cwd=ROOT, check=True)
    print(f"✅ 已创建 tag: {tag}")
    subprocess.run(["git", "push", "origin", tag], cwd=ROOT, check=True)
    print(f"✅ 已推送 tag: {tag}")


def run_check():
    """仅检查模式：验证一致性但不修改任何文件。"""
    version = get_current_version()
    print(f"📋 当前版本: {version}")
    print()

    # 检查 README
    issues = check_readme_consistency(version)
    if issues:
        print("⚠️  README 一致性问题:")
        for issue in issues:
            print(f"   - {issue}")
    else:
        print("✅ README 一致性检查通过")

    # 检查未提交更改
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.stdout.strip():
        print(f"\n⚠️  有未提交的更改:")
        for line in result.stdout.strip().split("\n")[:10]:
            print(f"   {line}")
    else:
        print("✅ 工作区干净")

    # 检查远程同步
    subprocess.run(["git", "fetch", "origin"], cwd=ROOT, capture_output=True)
    result = subprocess.run(
        ["git", "log", "HEAD..origin/main", "--oneline"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.stdout.strip():
        print(f"\n⚠️  本地落后于远程:")
        print(f"   {result.stdout.strip()}")
    else:
        print("✅ 与远程同步")

    print()
    return len(issues) == 0


def run_release(target_version: str = ""):
    """完整发布流程。"""
    current = get_current_version()
    print(f"📋 当前版本: {current}")

    # 确定新版本号
    if target_version:
        new_version = target_version
    else:
        print()
        print("选择版本类型:")
        print(f"  1. patch  → {bump_version(current, 'patch')}")
        print(f"  2. minor  → {bump_version(current, 'minor')}")
        print(f"  3. major  → {bump_version(current, 'major')}")
        print(f"  4. 自定义")
        choice = input("\n请选择 (1/2/3/4): ").strip()
        if choice == "1":
            new_version = bump_version(current, "patch")
        elif choice == "2":
            new_version = bump_version(current, "minor")
        elif choice == "3":
            new_version = bump_version(current, "major")
        elif choice == "4":
            new_version = input("输入版本号: ").strip()
        else:
            print("❌ 无效选择")
            sys.exit(1)

    print(f"\n🚀 准备发布 v{new_version}")

    # 获取变更说明
    summary = ""
    if not target_version:
        summary = input("输入版本摘要（可选，直接回车跳过）: ").strip()

    # 获取 git log
    commits = get_git_log_since_tag()
    categories = categorize_commits(commits)

    if not commits:
        print("⚠️  没有找到新的 commit")
        if input("继续？(y/n): ").strip().lower() != "y":
            sys.exit(0)

    # 1. 更新版本号
    set_version(new_version)

    # 2. 更新 更新日志.md
    update_changelog(new_version, categories, summary)

    # 3. 检查 README
    issues = check_readme_consistency(new_version)
    if issues:
        print("\n⚠️  README 一致性问题（请手动检查）:")
        for issue in issues:
            print(f"   - {issue}")

    # 4. 验证构建
    if not verify_build():
        print("\n❌ 构建验证失败，中止发布")
        sys.exit(1)

    # 5. 提交 + tag + 推送
    print(f"\n📦 准备提交 v{new_version}...")
    subprocess.run(
        ["git", "add", "pyproject.toml", "更新日志.md"],
        cwd=ROOT, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"release: v{new_version}"],
        cwd=ROOT, check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    create_git_tag(new_version)

    print(f"\n🎉 v{new_version} 发布完成！")
    print(f"   GitHub: {REPO_URL}/releases/tag/v{new_version}")
    print(f"   安装:   pip install git+{REPO_URL}.git@v{new_version}")


def main():
    os.chdir(ROOT)
    args = sys.argv[1:]

    if "--check" in args:
        run_check()
    elif "--build" in args:
        if run_check():
            verify_build()
    elif "--version" in args:
        idx = args.index("--version")
        if idx + 1 < len(args):
            run_release(args[idx + 1])
        else:
            print("❌ 请指定版本号: --version X.Y.Z")
            sys.exit(1)
    else:
        run_release()


if __name__ == "__main__":
    main()
