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

get_preferred_doc() {
  local candidate
  for candidate in "$@"; do
    if [[ -f "$repo_root/$candidate" ]]; then
      printf '%s\n' "$repo_root/$candidate"
      return 0
    fi
  done
  return 1
}

get_current_version() {
  local file_path="$1"
  [[ -f "$file_path" ]] || return 0
  python - "$file_path" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
for line in text.splitlines():
    if "当前版本" in line:
        match = re.search(r"v(\d+\.\d+\.\d+)", line)
        if match:
            print(f"v{match.group(1)}")
            break
PY
}

get_version_from_pyproject() {
  local pyproject="$repo_root/pyproject.toml"
  [[ -f "$pyproject" ]] || return 0
  python - "$pyproject" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'version\s*=\s*"(\d+\.\d+\.\d+)"', text)
if match:
    print(f"v{match.group(1)}")
PY
}

get_recent_devlog_title() {
  local file_path="$1"
  [[ -f "$file_path" ]] || return 0
  while IFS= read -r line; do
    if [[ "$line" =~ ^##[[:space:]]+ ]]; then
      printf '%s\n' "$line"
      return 0
    fi
  done < "$file_path"
}

get_first_non_empty_lines() {
  local file_path="$1"
  local count="$2"
  [[ -f "$file_path" ]] || return 0
  python - "$file_path" "$count" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
count = int(sys.argv[2])
lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
for line in lines[:count]:
    print(line)
PY
}

context_doc="$(get_preferred_doc "CLAUDE.md" "AGENTS.md" || true)"
agents_doc="$(get_preferred_doc "AGENTS.md" || true)"
readme_doc="$(get_preferred_doc "README.md" || true)"
devlog_doc="$(get_preferred_doc "DEVLOG.md" || true)"

version=""
if [[ -n "$context_doc" ]]; then
  version="$(get_current_version "$context_doc")"
fi
recent_devlog=""
if [[ -n "$devlog_doc" ]]; then
  recent_devlog="$(get_recent_devlog_title "$devlog_doc")"
fi
if [[ "$recent_devlog" =~ v([0-9]+\.[0-9]+\.[0-9]+) ]]; then
  version="v${BASH_REMATCH[1]}"
fi
if [[ -z "$version" ]]; then
  version="$(get_version_from_pyproject)"
fi

mapfile -t context_preview < <(get_first_non_empty_lines "$context_doc" 14 || true)
mapfile -t agents_preview < <(get_first_non_empty_lines "$agents_doc" 14 || true)
mapfile -t readme_preview < <(get_first_non_empty_lines "$readme_doc" 10 || true)

if [[ "$json_mode" -eq 1 ]]; then
  export REPO_ROOT="$repo_root"
  export CONTEXT_DOC="${context_doc:-}"
  export AGENTS_DOC="${agents_doc:-}"
  export README_DOC="${readme_doc:-}"
  export DEVLOG_DOC="${devlog_doc:-}"
  export VERSION="${version:-}"
  export RECENT_DEVLOG="${recent_devlog:-}"
  export CONTEXT_PREVIEW="$(printf '%s\n' "${context_preview[@]}")"
  export AGENTS_PREVIEW="$(printf '%s\n' "${agents_preview[@]}")"
  export README_PREVIEW="$(printf '%s\n' "${readme_preview[@]}")"
  python - <<'PY'
import json
import os

def lines(name: str):
    return [line for line in os.environ.get(name, "").splitlines() if line]

result = {
    "workspace": os.environ.get("REPO_ROOT", ""),
    "context_doc": os.environ.get("CONTEXT_DOC", ""),
    "agents_doc": os.environ.get("AGENTS_DOC", ""),
    "readme_doc": os.environ.get("README_DOC", ""),
    "devlog_doc": os.environ.get("DEVLOG_DOC", ""),
    "version": os.environ.get("VERSION", ""),
    "recent_devlog": os.environ.get("RECENT_DEVLOG", ""),
    "context_preview": lines("CONTEXT_PREVIEW"),
    "agents_preview": lines("AGENTS_PREVIEW"),
    "readme_preview": lines("README_PREVIEW"),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
  exit 0
fi

echo "[newup] feedgrab project context"
echo "workspace: $repo_root"
[[ -n "$version" ]] && echo "version: $version"
[[ -n "$context_doc" ]] && echo "context-doc: $context_doc"
[[ -n "$agents_doc" ]] && echo "agents-doc: $agents_doc"
[[ -n "$readme_doc" ]] && echo "readme-doc: $readme_doc"
[[ -n "$devlog_doc" ]] && echo "devlog-doc: $devlog_doc"
[[ -n "$recent_devlog" ]] && echo "recent-devlog: $recent_devlog"

echo
echo "[context-preview]"
for line in "${context_preview[@]}"; do
  [[ -n "$line" ]] && echo "$line"
done

echo
echo "[agents-preview]"
for line in "${agents_preview[@]}"; do
  [[ -n "$line" ]] && echo "$line"
done

echo
echo "[readme-preview]"
for line in "${readme_preview[@]}"; do
  [[ -n "$line" ]] && echo "$line"
done
