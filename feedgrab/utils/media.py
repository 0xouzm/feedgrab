# -*- coding: utf-8 -*-
"""
Media download — download images/videos to local attachments directory.

Follows the Feishu image download pattern (feishu.py download_feishu_images):
    1. save_to_markdown() returns the saved .md path
    2. download_media() downloads files to {md_dir}/attachments/{item_id}/
    3. Replaces remote URLs in .md with relative paths

Configuration:
    X_DOWNLOAD_MEDIA=true       (default false)
    XHS_DOWNLOAD_MEDIA=true     (default false)
"""

import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from loguru import logger


def download_media(
    md_path: str,
    images: list,
    videos: list,
    item_id: str,
    platform: str = "twitter",
) -> None:
    """Download images/videos to {md_dir}/attachments/{item_id}/ and rewrite .md URLs.

    Args:
        md_path: Path to the saved .md file (from save_to_markdown).
        images: List of image URLs.
        videos: List of video URLs.
        item_id: Unique ID for subdirectory (matches front matter item_id).
        platform: "twitter" or "xhs" — determines URL optimization and headers.
    """
    all_urls = [u for u in (images or []) if u] + [u for u in (videos or []) if u]
    if not all_urls:
        return

    md_file = Path(md_path)
    if not md_file.exists():
        return

    att_dir = md_file.parent / "attachments" / item_id
    att_dir.mkdir(parents=True, exist_ok=True)

    url_map = {}  # {remote_url: relative_path}
    downloaded = 0

    for url in all_urls:
        filename = _extract_filename(url, platform)
        if not filename:
            continue

        dest = att_dir / filename

        # Skip if already downloaded
        if dest.exists() and dest.stat().st_size > 0:
            rel = f"attachments/{item_id}/{filename}"
            url_map[url] = rel
            downloaded += 1
            continue

        # Optimize URL for best quality
        dl_url = _optimize_url(url, platform)
        headers = _download_headers(platform)

        ok = _download_file(dl_url, dest, headers)
        if ok:
            rel = f"attachments/{item_id}/{filename}"
            url_map[url] = rel
            downloaded += 1
        else:
            # Clean up empty file
            if dest.exists() and dest.stat().st_size == 0:
                dest.unlink(missing_ok=True)

    # Replace URLs in .md
    if url_map:
        _replace_urls_in_md(md_file, url_map)

    total = len(all_urls)
    if downloaded > 0:
        logger.info(f"[media] Downloaded {downloaded}/{total} files → attachments/{item_id}/")
    if downloaded < total:
        logger.warning(f"[media] {total - downloaded} files failed, kept remote URLs")


def _download_file(url: str, dest: Path, headers: dict = None) -> bool:
    """Download a single file. Returns True on success."""
    from feedgrab.utils.http_client import get as http_get

    try:
        is_video = any(ext in dest.suffix.lower() for ext in [".mp4", ".m4v", ".webm"])
        timeout = 120 if is_video else 30

        resp = http_get(url, headers=headers or {}, timeout=timeout)
        resp.raise_for_status()

        data = resp.content
        if not data or len(data) < 100:
            logger.debug(f"[media] Empty response for {url}")
            return False

        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception as e:
        logger.debug(f"[media] Download failed: {url} — {e}")
        return False


def _extract_filename(url: str, platform: str) -> str:
    """Extract a clean filename from a media URL.

    Twitter images:  pbs.twimg.com/media/GmNx7jHXcAA5EYi?format=jpg → GmNx7jHXcAA5EYi.jpg
    Twitter videos:  video.twimg.com/.../xxx.mp4?tag=12 → xxx.mp4
    XHS images:      sns-webpic-qc.xhscdn.com/.../xxx.jpg!nd_xxx → xxx.jpg
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    if platform == "twitter":
        # Image: /media/GmNx7jHXcAA5EYi (format in query) or /media/xxx.jpg
        if "/media/" in path:
            stem = path.split("/")[-1]
            # If stem already has an extension (e.g. xxx.jpg), use as-is
            if "." in stem:
                return _sanitize(stem)
            qs = parse_qs(parsed.query)
            fmt = qs.get("format", ["jpg"])[0]
            return f"{stem}.{fmt}"

        # Video/other: extract filename from path
        basename = path.split("/")[-1]
        # Remove query params from extension
        if "." in basename:
            name = basename.split("?")[0]
            return _sanitize(name)

    elif platform == "xhs":
        basename = path.split("/")[-1]
        # Strip XHS CDN suffixes like !nd_dft_wgth_webp_3
        basename = re.sub(r"![a-z_0-9]+$", "", basename)
        if basename:
            return _sanitize(basename)

    elif platform == "wechat":
        # mpvideo.qpic.cn/.../xxx.f10002.mp4?dis_k=...
        basename = path.split("/")[-1]
        # Strip query params already handled by urlparse, just sanitize
        if "." in basename:
            return _sanitize(basename)
        # Fallback: use last two segments (some URLs have no extension in last part)
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and "." in parts[-1]:
            return _sanitize(parts[-1])
        # Last resort: hash-based name
        if basename:
            return _sanitize(f"{basename}.mp4")

    elif platform == "weibo":
        # Image: wx1.sinaimg.cn/large/abc123.jpg → abc123.jpg
        # Video: f.video.weibocdn.com/.../abc123.mp4?label=mp4_hd&Expires=...
        basename = path.split("/")[-1]
        if basename and "." in basename:
            return _sanitize(basename)
        if basename:
            return _sanitize(f"{basename}.mp4")

    # Generic fallback
    basename = path.split("/")[-1]
    if "." in basename:
        return _sanitize(basename.split("?")[0])

    return ""


def _optimize_url(url: str, platform: str) -> str:
    """Optimize URL for highest quality download.

    Twitter: append name=orig for original resolution.
    XHS: strip CDN resize suffix.
    WeChat: upgrade http to https.
    """
    if platform == "twitter" and "pbs.twimg.com/media/" in url:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        qs["name"] = ["orig"]
        new_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    if platform == "xhs":
        # Remove CDN resize/format suffixes
        return re.sub(r"![a-z_0-9]+$", "", url)

    if platform == "wechat":
        # mpvideo.qpic.cn requires HTTPS
        if url.startswith("http://"):
            url = "https://" + url[7:]
        return url

    return url


def _download_headers(platform: str) -> dict:
    """Platform-specific download headers."""
    if platform == "xhs":
        return {"Referer": "https://www.xiaohongshu.com/"}
    if platform == "wechat":
        return {"Referer": "https://mp.weixin.qq.com/"}
    if platform == "weibo":
        # weibocdn requires Referer + UA from m.weibo.cn for the signed URL
        # to actually return 200; otherwise it 403s even with a fresh URL.
        from feedgrab.config import get_user_agent
        return {
            "Referer": "https://m.weibo.cn/",
            "User-Agent": get_user_agent(),
        }
    return {}


def _replace_urls_in_md(md_path: Path, url_map: dict) -> None:
    """Replace remote URLs with local relative paths in a .md file."""
    content = md_path.read_text(encoding="utf-8")
    changed = False

    for remote_url, local_path in url_map.items():
        if remote_url in content:
            content = content.replace(remote_url, local_path)
            changed = True

    if changed:
        md_path.write_text(content, encoding="utf-8")


def _sanitize(name: str) -> str:
    """Sanitize filename for filesystem safety."""
    # Remove problematic chars
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Collapse multiple underscores/hyphens
    name = re.sub(r'[_-]{2,}', '-', name)
    return name[:200]  # cap length
