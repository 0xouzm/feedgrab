#!/usr/bin/env bash
set -euo pipefail

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONUTF8=1
export PYTHONIOENCODING=UTF-8

json_mode=0
if [[ "${1:-}" == "--json" ]]; then
  json_mode=1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_git() {
  XDG_CONFIG_HOME="$repo_root" git "$@" 2>/dev/null || return $?
}

mapfile -t git_status < <(run_git status --short || true)
status_exit=$?
mapfile -t git_diff_stat < <(run_git diff --stat || true)
diff_exit=$?

# Scan skills/*/SKILL.md (feedgrab project's own skill manifests)
skill_manifests=()
if [[ -d "$repo_root/skills" ]]; then
  while IFS= read -r -d '' manifest; do
    skill_manifests+=("${manifest#$repo_root/}")
  done < <(find "$repo_root/skills" -mindepth 2 -maxdepth 2 -name SKILL.md -print0 2>/dev/null | sort -z)
fi

required_docs=("DEVLOG.md" "CLAUDE.md" "AGENTS.md" "README.md" "README_en.md")
next_actions=(
  "Confirm the feature is finished and tested"
  "Update the top entry in DEVLOG.md"
  "Sync CLAUDE.md and AGENTS.md project notes with the latest code"
  "Sync README.md and README_en.md if needed"
  "Sync skills/*/SKILL.md (description, platforms, commands) with new capabilities"
  "Review git diff before commit and push"
)

if [[ "$json_mode" -eq 1 ]]; then
  export REPO_ROOT="$repo_root"
  export STATUS_EXIT="$status_exit"
  export DIFF_EXIT="$diff_exit"
  export REQUIRED_DOCS="$(printf '%s\n' "${required_docs[@]}")"
  export SKILL_MANIFESTS="$(printf '%s\n' "${skill_manifests[@]}")"
  export GIT_STATUS_LINES="$(printf '%s\n' "${git_status[@]}")"
  export GIT_DIFF_STAT_LINES="$(printf '%s\n' "${git_diff_stat[@]}")"
  export NEXT_ACTIONS="$(printf '%s\n' "${next_actions[@]}")"
  python - <<'PY'
import json
import os
from pathlib import Path

repo_root = os.environ["REPO_ROOT"]
required_docs = [line for line in os.environ.get("REQUIRED_DOCS", "").splitlines() if line]
skill_manifests = [line for line in os.environ.get("SKILL_MANIFESTS", "").splitlines() if line]
git_status = [line for line in os.environ.get("GIT_STATUS_LINES", "").splitlines() if line]
git_diff_stat = [line for line in os.environ.get("GIT_DIFF_STAT_LINES", "").splitlines() if line]
next_actions = [line for line in os.environ.get("NEXT_ACTIONS", "").splitlines() if line]

result = {
    "workspace": repo_root,
    "git_status_ok": os.environ.get("STATUS_EXIT") == "0",
    "git_diff_stat_ok": os.environ.get("DIFF_EXIT") == "0",
    "git_status": git_status,
    "git_diff_stat": git_diff_stat,
    "required_docs": [
        {"path": doc, "exists": Path(repo_root, doc).exists()} for doc in required_docs
    ],
    "skill_manifests": [
        {"path": m, "exists": Path(repo_root, m).exists()} for m in skill_manifests
    ],
    "next_actions": next_actions,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
  exit 0
fi

echo "[ship] release readiness"
echo "workspace: $repo_root"
echo
echo "[required-docs]"
for doc in "${required_docs[@]}"; do
  if [[ -f "$repo_root/$doc" ]]; then
    echo "OK $doc"
  else
    echo "MISSING $doc"
  fi
done

echo
echo "[skill-manifests]"
if [[ ${#skill_manifests[@]} -eq 0 ]]; then
  echo "(no skills/ directory found)"
else
  for manifest in "${skill_manifests[@]}"; do
    echo "OK $manifest"
  done
fi

echo
echo "[git-status --short]"
for line in "${git_status[@]}"; do
  [[ -n "$line" ]] && echo "$line"
done

echo
echo "[git-diff --stat]"
for line in "${git_diff_stat[@]}"; do
  [[ -n "$line" ]] && echo "$line"
done

echo
echo "[next-actions]"
for item in "${next_actions[@]}"; do
  echo "- $item"
done
