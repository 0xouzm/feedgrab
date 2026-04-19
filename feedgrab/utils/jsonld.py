# -*- coding: utf-8 -*-
"""
JSON-LD articleBody extractor.

Many news / blog sites embed full Schema.org article data in
<script type="application/ld+json"> blocks for SEO.  This module extracts
that structured data (headline, author, publish date, articleBody) as a
lightweight alternative to full HTML parsing or Jina Reader.

Much faster than Jina (<200ms vs 5-15s) and preserves metadata.

Supported Schema.org types:
    NewsArticle, Article, BlogPosting, Report, LiveBlogPosting,
    ReportageNewsArticle, AnalysisNewsArticle, OpinionNewsArticle
"""

import json
import re
from html import unescape
from typing import Optional

from loguru import logger


# Schema.org article-like types we treat as "has body"
ARTICLE_TYPES = {
    "NewsArticle",
    "Article",
    "BlogPosting",
    "Report",
    "LiveBlogPosting",
    "ReportageNewsArticle",
    "AnalysisNewsArticle",
    "OpinionNewsArticle",
    "TechArticle",
    "ScholarlyArticle",
}

# Match <script type="application/ld+json">...</script>, case-insensitive, DOTALL
_JSONLD_RE = re.compile(
    r'<script[^>]*\btype\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _iter_candidates(data):
    """Flatten JSON-LD payload into individual article candidate dicts."""
    if isinstance(data, list):
        for item in data:
            yield from _iter_candidates(item)
        return
    if not isinstance(data, dict):
        return
    # @graph array — common in Yoast SEO, news publishers
    if "@graph" in data and isinstance(data["@graph"], list):
        for item in data["@graph"]:
            yield from _iter_candidates(item)
        return
    yield data


def _matches_article_type(obj: dict) -> bool:
    """True if obj's @type matches any known article type."""
    t = obj.get("@type")
    if not t:
        return False
    if isinstance(t, str):
        return t in ARTICLE_TYPES
    if isinstance(t, list):
        return any(x in ARTICLE_TYPES for x in t if isinstance(x, str))
    return False


def _extract_author(author) -> str:
    """Author can be str, dict with 'name', or list of either."""
    if not author:
        return ""
    if isinstance(author, str):
        return author.strip()
    if isinstance(author, dict):
        return str(author.get("name", "")).strip()
    if isinstance(author, list):
        names = []
        for a in author:
            if isinstance(a, str):
                names.append(a.strip())
            elif isinstance(a, dict):
                name = a.get("name")
                if name:
                    names.append(str(name).strip())
        return ", ".join(n for n in names if n)
    return ""


def _extract_image(image) -> str:
    """Image can be str URL, dict with 'url', or list."""
    if not image:
        return ""
    if isinstance(image, str):
        return image.strip()
    if isinstance(image, dict):
        return str(image.get("url", "")).strip()
    if isinstance(image, list) and image:
        return _extract_image(image[0])
    return ""


def _clean_body(body: str) -> str:
    """Unescape and normalize whitespace in articleBody."""
    if not body:
        return ""
    text = unescape(body)
    # Collapse excessive blank lines (3+ → 2)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_jsonld_article(html: str) -> Optional[dict]:
    """Extract article from JSON-LD Schema.org markup in HTML.

    Returns
    -------
    dict or None
        {
          "headline": str,
          "author": str,
          "datePublished": str,
          "articleBody": str,
          "image": str (URL, possibly empty),
        }
        Returns None if no JSON-LD article with articleBody found.
    """
    if not html or "ld+json" not in html.lower():
        return None

    best: Optional[dict] = None
    best_len = 0

    for match in _JSONLD_RE.finditer(html):
        raw = match.group(1).strip()
        # Some sites leave HTML comments inside; strip them
        raw = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try unescaping HTML entities (some CMS escape inside <script>)
            try:
                data = json.loads(unescape(raw))
            except Exception:
                continue

        for candidate in _iter_candidates(data):
            if not _matches_article_type(candidate):
                continue
            body = candidate.get("articleBody") or ""
            if not isinstance(body, str):
                continue
            body = _clean_body(body)
            # Keep the longest articleBody across all matches (some pages
            # embed both summary and full-body JSON-LD blocks)
            if len(body) > best_len:
                best = {
                    "headline": str(candidate.get("headline", "")).strip(),
                    "author": _extract_author(candidate.get("author")),
                    "datePublished": str(candidate.get("datePublished", "")).strip(),
                    "articleBody": body,
                    "image": _extract_image(candidate.get("image")),
                }
                best_len = len(body)

    if best and best["articleBody"]:
        logger.debug(
            f"[JSON-LD] Extracted article: "
            f"headline={best['headline'][:40]!r}, body={best_len} chars"
        )
        return best
    return None


def extract_title_from_html(html: str) -> str:
    """Extract <title> text from HTML as a quick fallback."""
    if not html:
        return ""
    m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    if not m:
        return ""
    return unescape(m.group(1).strip())
