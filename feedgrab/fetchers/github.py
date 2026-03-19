# -*- coding: utf-8 -*-
"""GitHub repository fetcher — README with Chinese priority via REST API."""

import base64
import re
from urllib.parse import urlparse
from typing import Dict, Any, Optional

from loguru import logger

from feedgrab.config import github_token
from feedgrab.utils import http_client


API_BASE = "https://api.github.com"

# Chinese README variants, ordered by priority
CHINESE_README_VARIANTS = [
    "README_CN.md",
    "README.zh-CN.md",
    "README_zh-CN.md",
    "README.zh.md",
    "README_ZH.md",
    "README.zh-Hans.md",
    "README_zh.md",
    "README.Chinese.md",
]


def _api_headers() -> dict:
    """Build GitHub API request headers."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _raw_headers() -> dict:
    """Build headers for raw content fetching."""
    headers = _api_headers()
    headers["Accept"] = "application/vnd.github.raw+json"
    return headers


def parse_github_url(url: str) -> tuple:
    """Extract (owner, repo) from any GitHub URL.

    Handles:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/blob/main/README.md
      - https://github.com/owner/repo/tree/main/src
      - https://github.com/owner/repo/issues/123
    """
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]

    if len(path_parts) < 2:
        raise ValueError(f"Invalid GitHub URL: need at least owner/repo, got: {url}")

    owner = path_parts[0]
    repo = path_parts[1]

    # Strip .git suffix
    if repo.endswith(".git"):
        repo = repo[:-4]

    return owner, repo


def _fetch_repo_metadata(owner: str, repo: str) -> dict:
    """Fetch repository metadata via GET /repos/{owner}/{repo}."""
    url = f"{API_BASE}/repos/{owner}/{repo}"
    resp = http_client.get(url, headers=_api_headers(), timeout=15)
    http_client.raise_for_status(resp)
    data = resp.json()

    license_name = ""
    lic = data.get("license")
    if lic and lic.get("spdx_id"):
        license_name = lic["spdx_id"]
        if license_name == "NOASSERTION":
            license_name = lic.get("name", "")

    return {
        "full_name": data.get("full_name", ""),
        "description": data.get("description", "") or "",
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0),
        "language": data.get("language", "") or "",
        "license": license_name,
        "topics": data.get("topics", []),
        "html_url": data.get("html_url", ""),
        "created_at": data.get("created_at", ""),
        "updated_at": data.get("updated_at", ""),
        "pushed_at": data.get("pushed_at", ""),
        "default_branch": data.get("default_branch", "main"),
        "open_issues": data.get("open_issues_count", 0),
        "owner_login": data.get("owner", {}).get("login", ""),
        "owner_avatar": data.get("owner", {}).get("avatar_url", ""),
    }


def _find_chinese_readme(owner: str, repo: str) -> Optional[str]:
    """Check if a Chinese README variant exists in the repo root.

    Fetches root directory listing (1 API call), then matches against
    known Chinese README filenames.
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/"
    try:
        resp = http_client.get(url, headers=_api_headers(), timeout=15)
        http_client.raise_for_status(resp)
        files = resp.json()
    except Exception as e:
        logger.warning(f"[GitHub] Failed to list repo contents: {e}")
        return None

    if not isinstance(files, list):
        return None

    root_files = {f["name"] for f in files if f.get("type") == "file"}
    root_files_lower = {name.lower(): name for name in root_files}

    for variant in CHINESE_README_VARIANTS:
        if variant in root_files:
            return variant
        actual = root_files_lower.get(variant.lower())
        if actual:
            return actual

    return None


def _fetch_file_raw(owner: str, repo: str, path: str) -> str:
    """Fetch raw file content via GET /repos/{owner}/{repo}/contents/{path}."""
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
    resp = http_client.get(url, headers=_raw_headers(), timeout=20)
    http_client.raise_for_status(resp)
    return resp.text


def _fetch_default_readme(owner: str, repo: str) -> tuple:
    """Fetch the default README via GET /repos/{owner}/{repo}/readme.

    Returns (content, filename) tuple.
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/readme"
    resp = http_client.get(url, headers=_api_headers(), timeout=15)
    http_client.raise_for_status(resp)
    data = resp.json()

    filename = data.get("name", "README.md")
    encoded = data.get("content", "")
    if encoded:
        content = base64.b64decode(encoded).decode("utf-8", errors="replace")
    else:
        # Fallback: fetch raw
        raw_resp = http_client.get(url, headers=_raw_headers(), timeout=20)
        content = raw_resp.text

    return content, filename


def _find_chinese_readme_from_content(
    owner: str, repo: str, readme_content: str
) -> Optional[tuple]:
    """Search README content for Chinese README links.

    Scans for language navigation patterns like:
      [中文](docs/README.zh-CN.md)
      README in [中文](./docs/README.zh-CN.md) / [日本語](...)

    Returns (path, content) tuple if found, None otherwise.
    """
    # Patterns for Chinese language link text (with optional bold/italic markers)
    cn_link_patterns = [
        r'\[\*{0,2}中文\*{0,2}\]\(([^)]+)\)',
        r'\[\*{0,2}简体中文\*{0,2}\]\(([^)]+)\)',
        r'\[\*{0,2}繁體中文\*{0,2}\]\(([^)]+)\)',
        r'\[\*{0,2}Chinese\*{0,2}\]\(([^)]+)\)',
        r'\[\*{0,2}ZH-CN\*{0,2}\]\(([^)]+)\)',
        r'\[\*{0,2}zh-CN\*{0,2}\]\(([^)]+)\)',
    ]

    for pattern in cn_link_patterns:
        match = re.search(pattern, readme_content, re.IGNORECASE)
        if not match:
            continue

        path = match.group(1).strip()

        # Handle full GitHub URLs pointing to the same repo
        if path.startswith(("http://", "https://")):
            if f"{owner}/{repo}" in path:
                # Extract relative path: .../blob/main/docs/README.zh-CN.md
                parts = path.split(f"{owner}/{repo}/", 1)
                if len(parts) > 1:
                    path = re.sub(r"^(blob|tree)/[^/]+/", "", parts[1])
                else:
                    continue
            else:
                continue

        # Clean leading ./
        if path.startswith("./"):
            path = path[2:]

        # Skip anchors and empty paths
        if not path or path.startswith("#"):
            continue

        try:
            content = _fetch_file_raw(owner, repo, path)
            logger.info(f"[GitHub] Found Chinese README from content link: {path}")
            return path, content
        except Exception as e:
            logger.debug(
                f"[GitHub] Failed to fetch linked Chinese README {path}: {e}"
            )
            continue

    return None


def _resolve_relative_urls(
    content: str, owner: str, repo: str, branch: str, readme_path: str
) -> str:
    """Convert relative image URLs in README to absolute GitHub raw URLs.

    Handles both Markdown images ![alt](path) and HTML <img src="path">.
    """
    # Base directory of the README file
    if "/" in readme_path:
        base_dir = readme_path.rsplit("/", 1)[0] + "/"
    else:
        base_dir = ""

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"

    def _resolve(rel_path: str) -> str:
        """Resolve a single relative path to an absolute raw URL."""
        # Skip absolute URLs, anchors, data URIs
        if rel_path.startswith(("http://", "https://", "//", "data:", "#")):
            return rel_path

        if rel_path.startswith("./"):
            rel_path = rel_path[2:]

        full_path = base_dir + rel_path

        # Normalize ../ segments
        parts = full_path.split("/")
        resolved = []
        for part in parts:
            if part == "..":
                if resolved:
                    resolved.pop()
            elif part and part != ".":
                resolved.append(part)

        return raw_base + "/".join(resolved)

    # Markdown images: ![alt](relative/path)
    def _replace_md_img(m):
        return f"![{m.group(1)}]({_resolve(m.group(2))})"

    content = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace_md_img, content)

    # HTML img src: <img src="relative/path" ...> or <img src='path'>
    def _replace_html_img(m):
        return f"{m.group(1)}{m.group(2)}{_resolve(m.group(3))}{m.group(2)}"

    content = re.sub(
        r'(<img\s[^>]*?src=)(["\'])([^"\']+)\2',
        _replace_html_img,
        content,
        flags=re.IGNORECASE,
    )

    return content


def _extract_readme_summary(content: str) -> str:
    """Extract the first meaningful descriptive line from README content.

    Skips headings (#), badges ([![...]), images (![...]), HTML tags,
    blockquotes (>), empty lines, and pure-link lines.
    """
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip headings
        if line.startswith("#"):
            continue
        # Skip badges and images: [![...] or ![...]
        if line.startswith("[![") or line.startswith("!["):
            continue
        # Skip pure links: [text](url) with no surrounding text
        if re.match(r'^\[.*\]\(.*\)$', line):
            continue
        # Skip badge-only lines (multiple badges separated by spaces)
        if all(part.startswith("[![") or part.startswith("[!") or not part
               for part in line.split()):
            continue
        # Skip HTML tags
        if line.startswith("<"):
            continue
        # Skip blockquotes
        if line.startswith(">"):
            continue
        # Skip horizontal rules
        if re.match(r'^[-*_]{3,}\s*$', line):
            continue
        # Skip lines that are just separators like "---" or "***" or "|"
        if re.match(r'^[\|\-\s:]+$', line):
            continue
        # Found a meaningful line — clean it up
        # Remove inline markdown links: [text](url) → text
        summary = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', line)
        # Remove bold/italic markers
        summary = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', summary)
        summary = summary.strip()
        # Skip short lines (language selectors, nav links, etc.)
        if len(summary) < 15:
            continue
        if summary:
            return summary
    return ""


async def fetch_github(url: str) -> Dict[str, Any]:
    """Fetch GitHub repository README with Chinese priority.

    Flow (3 API calls):
      1. GET /repos/{owner}/{repo}           → metadata
      2. GET /repos/{owner}/{repo}/contents/  → root dir listing → find CN readme
      3. GET /repos/{owner}/{repo}/contents/{readme} or /readme → content
    """
    owner, repo = parse_github_url(url)
    logger.info(f"[GitHub] Fetching {owner}/{repo}")

    # Step 1: Repo metadata
    meta = _fetch_repo_metadata(owner, repo)
    logger.info(
        f"[GitHub] {meta['full_name']} "
        f"★{meta['stars']} Fork:{meta['forks']} "
        f"lang={meta['language']}"
    )

    # Step 2: Find Chinese README
    readme_file = None
    readme_content = ""

    chinese_readme = _find_chinese_readme(owner, repo)
    if chinese_readme:
        logger.info(f"[GitHub] Found Chinese README: {chinese_readme}")
        try:
            readme_content = _fetch_file_raw(owner, repo, chinese_readme)
            readme_file = chinese_readme
        except Exception as e:
            logger.warning(
                f"[GitHub] Failed to fetch {chinese_readme}: {e}, "
                f"falling back to default README"
            )

    # Step 3: Fallback to default README
    if not readme_content:
        try:
            readme_content, default_name = _fetch_default_readme(owner, repo)
            readme_file = readme_file or default_name
            logger.info(f"[GitHub] Using default README: {readme_file}")

            # Step 3b: Search default README for Chinese version link
            cn_result = _find_chinese_readme_from_content(
                owner, repo, readme_content
            )
            if cn_result:
                readme_file, readme_content = cn_result
        except Exception as e:
            logger.warning(f"[GitHub] No README found: {e}")
            readme_content = meta.get("description", "") or "(No README)"
            readme_file = ""

    # Step 4: Resolve relative image URLs to absolute GitHub raw URLs
    if readme_file:
        readme_content = _resolve_relative_urls(
            readme_content, owner, repo,
            meta["default_branch"], readme_file,
        )

    # Build title: prefer README summary, fallback to API description
    summary = _extract_readme_summary(readme_content)
    if summary:
        title = summary
        if len(title) > 100:
            title = title[:97] + "..."
    elif meta.get("description"):
        title = meta["description"]
        if len(title) > 100:
            title = title[:97] + "..."
    else:
        title = f"{owner}/{repo}"

    return {
        "owner": owner,
        "repo": repo,
        "full_name": meta["full_name"],
        "title": title,
        "description": meta.get("description", ""),
        "content": readme_content,
        "url": meta.get("html_url", f"https://github.com/{owner}/{repo}"),
        "stars": meta["stars"],
        "forks": meta["forks"],
        "language": meta["language"],
        "license": meta["license"],
        "topics": meta.get("topics", []),
        "default_branch": meta["default_branch"],
        "open_issues": meta["open_issues"],
        "created_at": meta["created_at"],
        "updated_at": meta["updated_at"],
        "pushed_at": meta["pushed_at"],
        "owner_avatar": meta.get("owner_avatar", ""),
        "readme_file": readme_file or "README.md",
    }
