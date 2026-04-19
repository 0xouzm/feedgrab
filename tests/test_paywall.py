# -*- coding: utf-8 -*-
"""Unit tests for paywall bypass + JSON-LD extraction."""

import pytest

from feedgrab.utils.jsonld import (
    extract_jsonld_article,
    extract_title_from_html,
)
from feedgrab.fetchers.paywall import (
    _has_content,
    _is_paywall_content,
    _is_captcha_page,
    _match_domain,
    is_paywall_domain,
    _get_domain,
    GOOGLEBOT_DOMAINS,
    BINGBOT_DOMAINS,
    AMP_DOMAINS,
    PAYWALL_DOMAINS,
)


# ---------------------------------------------------------------------------
# JSON-LD extraction
# ---------------------------------------------------------------------------

SIMPLE_JSONLD = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "NewsArticle",
  "headline": "Breaking Story",
  "author": {"@type": "Person", "name": "Jane Doe"},
  "datePublished": "2026-04-19T09:00:00Z",
  "articleBody": "Paragraph one. Paragraph two. Paragraph three."
}
</script>
</head><body>page body</body></html>
"""

GRAPH_JSONLD = """
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebPage","@id":"https://x.com/"},
  {"@type":"BlogPosting","headline":"A Post","articleBody":"Body text here."}
]}
</script>
"""

MULTI_TYPE_JSONLD = """
<script type="application/ld+json">
{"@type":["Article","NewsArticle"],"headline":"Multi","articleBody":"multi body"}
</script>
"""

MULTI_AUTHOR_JSONLD = """
<script type="application/ld+json">
{
  "@type":"NewsArticle",
  "headline":"Duo",
  "author":[
    {"@type":"Person","name":"Alice"},
    {"@type":"Person","name":"Bob"}
  ],
  "articleBody":"dual authored"
}
</script>
"""

TWO_BLOCKS_PICK_LONGEST = """
<script type="application/ld+json">
{"@type":"NewsArticle","headline":"Short","articleBody":"short"}
</script>
<script type="application/ld+json">
{"@type":"NewsArticle","headline":"Long","articleBody":"a much longer piece of body text here"}
</script>
"""


def test_jsonld_basic_extraction():
    got = extract_jsonld_article(SIMPLE_JSONLD)
    assert got is not None
    assert got["headline"] == "Breaking Story"
    assert got["author"] == "Jane Doe"
    assert got["datePublished"] == "2026-04-19T09:00:00Z"
    assert "Paragraph one" in got["articleBody"]


def test_jsonld_graph_nested():
    got = extract_jsonld_article(GRAPH_JSONLD)
    assert got is not None
    assert got["headline"] == "A Post"
    assert got["articleBody"] == "Body text here."


def test_jsonld_multi_type_array():
    got = extract_jsonld_article(MULTI_TYPE_JSONLD)
    assert got is not None
    assert got["headline"] == "Multi"


def test_jsonld_multi_author():
    got = extract_jsonld_article(MULTI_AUTHOR_JSONLD)
    assert got is not None
    assert got["author"] == "Alice, Bob"


def test_jsonld_picks_longest_body():
    got = extract_jsonld_article(TWO_BLOCKS_PICK_LONGEST)
    assert got is not None
    assert got["headline"] == "Long"
    assert "longer piece" in got["articleBody"]


def test_jsonld_missing_returns_none():
    assert extract_jsonld_article("<html><body>no structured data</body></html>") is None


def test_jsonld_malformed_returns_none():
    bad = '<script type="application/ld+json">{not: json}</script>'
    assert extract_jsonld_article(bad) is None


def test_jsonld_non_article_type_ignored():
    # WebPage is not in ARTICLE_TYPES → even with articleBody, should skip
    html = (
        '<script type="application/ld+json">'
        '{"@type":"WebPage","articleBody":"should not match"}'
        "</script>"
    )
    assert extract_jsonld_article(html) is None


def test_extract_title_from_html():
    html = "<html><head><title>Hello &amp; World</title></head></html>"
    assert extract_title_from_html(html) == "Hello & World"


def test_extract_title_missing():
    assert extract_title_from_html("<html><body>no title</body></html>") == ""


# ---------------------------------------------------------------------------
# Content validators
# ---------------------------------------------------------------------------

def _make_content(line_count: int, line_len: int = 80) -> str:
    return "\n".join("x" * line_len for _ in range(line_count))


def test_has_content_happy_path():
    assert _has_content(_make_content(20)) is True


def test_has_content_too_short():
    assert _has_content("short text") is False


def test_has_content_too_few_lines():
    # 600 chars on a single line
    assert _has_content("x" * 600) is False


def test_has_content_error_snippet():
    text = _make_content(20) + "\n404 Not Found"
    assert _has_content(text) is False


def test_paywall_phrase_detected():
    assert _is_paywall_content("Subscribe to continue reading this article") is True
    assert _is_paywall_content("Only 3 remaining free articles this month") is True
    assert _is_paywall_content("Sign in to continue reading") is True


def test_paywall_phrase_clean_article():
    assert _is_paywall_content("The analysts concluded that the market...") is False


def test_captcha_detected():
    assert _is_captcha_page("Please complete the CAPTCHA challenge") is True
    assert _is_captcha_page("Cloudflare challenge verification in progress") is True


def test_captcha_clean_page():
    assert _is_captcha_page("normal article text") is False


# ---------------------------------------------------------------------------
# Domain matching
# ---------------------------------------------------------------------------

def test_get_domain_strips_www():
    assert _get_domain("https://www.wsj.com/articles/xxx") == "wsj.com"
    assert _get_domain("https://ft.com/content/yyy") == "ft.com"


def test_match_domain_exact():
    assert _match_domain("https://wsj.com/x", "wsj.com|ft.com") is True


def test_match_domain_www_prefix():
    assert _match_domain("https://www.wsj.com/x", GOOGLEBOT_DOMAINS) is True


def test_match_domain_subdomain():
    assert _match_domain("https://news.wsj.com/x", GOOGLEBOT_DOMAINS) is True


def test_match_domain_miss():
    assert _match_domain("https://example.com/x", GOOGLEBOT_DOMAINS) is False


def test_match_domain_empty_list():
    assert _match_domain("https://wsj.com/x", "") is False


def test_is_paywall_domain_union():
    # Across all 3 lists
    assert is_paywall_domain("https://www.nytimes.com/2026/x") is True
    assert is_paywall_domain("https://www.haaretz.com/x") is True  # Bingbot only
    assert is_paywall_domain("https://www.ft.com/x") is True  # Googlebot only
    assert is_paywall_domain("https://www.example.org/x") is False


def test_domain_list_format_valid():
    """Domain lists should contain valid hostname chars only."""
    import re
    pattern = re.compile(r"^[a-z0-9.\-]+(\|[a-z0-9.\-]+)*$")
    assert pattern.match(GOOGLEBOT_DOMAINS)
    assert pattern.match(BINGBOT_DOMAINS)
    assert pattern.match(AMP_DOMAINS)
    assert pattern.match(PAYWALL_DOMAINS)
