# -*- coding: utf-8 -*-
"""
Bilibili WBI (Web Bot Interface) signature utility.

Bilibili's newer player/info endpoints (``/x/player/wbi/v2``, etc.) require
a signed request: ``?params&wts={ts}&w_rid={md5}``. This module implements
the community-documented signing algorithm:

1. GET ``/x/web-interface/nav`` → extract ``img_key`` + ``sub_key`` from
   ``data.wbi_img.img_url`` / ``.sub_url`` (filename without extension).
2. Concatenate ``img_key + sub_key`` (64 chars) and reorder by the fixed
   ``MIXIN_KEY_ENC_TAB`` → take first 32 chars = ``mixin_key``.
3. Sort params by key, drop forbidden chars ``!()*'``, URL-encode, append
   ``&wts={ts}``, then ``w_rid = md5(query + mixin_key)``.

The mixin keys are cached on disk for 5 minutes to avoid hitting ``nav``
on every request.

Algorithm source: https://github.com/SocialSisterYi/bilibili-API-collect
"""

import hashlib
import json
import time
import urllib.parse
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from loguru import logger

from feedgrab.config import get_data_dir, get_stealth_headers
from feedgrab.utils import http_client


# Fixed 64-element permutation (community-reverse-engineered, stable since 2023)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
_CACHE_TTL = 300  # 5 min


def _cache_path() -> Path:
    d = get_data_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "bilibili_wbi_key.json"


def _load_cache() -> Optional[Tuple[str, str]]:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if time.time() - data.get("ts", 0) > _CACHE_TTL:
            return None
        return data["img_key"], data["sub_key"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _save_cache(img_key: str, sub_key: str) -> None:
    try:
        _cache_path().write_text(
            json.dumps({"img_key": img_key, "sub_key": sub_key, "ts": time.time()}),
            encoding="utf-8",
        )
    except OSError as e:
        logger.debug(f"[WBI] cache write failed: {e}")


def _extract_key_from_url(url: str) -> str:
    """URL → filename without extension.

    E.g. ``https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png``
    → ``7cd084941338484aae1ad9425b84077c``
    """
    if not url:
        return ""
    tail = url.rsplit("/", 1)[-1]
    return tail.rsplit(".", 1)[0]


def fetch_wbi_keys(force_refresh: bool = False) -> Tuple[str, str]:
    """Return ``(img_key, sub_key)`` pair, cached for 5 minutes.

    Raises on network/API failure — caller should catch and fall back to
    unsigned endpoints.
    """
    if not force_refresh:
        cached = _load_cache()
        if cached:
            return cached

    logger.info("[WBI] fetching nav for img_key/sub_key")
    resp = http_client.get(
        _NAV_URL,
        headers=get_stealth_headers(),
        timeout=10,
    )
    http_client.raise_for_status(resp)
    data = resp.json()
    if not isinstance(data, dict) or "data" not in data:
        raise ValueError(f"[WBI] unexpected nav response: {str(data)[:200]}")

    wbi = data["data"].get("wbi_img", {}) or {}
    img_key = _extract_key_from_url(wbi.get("img_url", ""))
    sub_key = _extract_key_from_url(wbi.get("sub_url", ""))
    if not img_key or not sub_key:
        raise ValueError(f"[WBI] nav missing wbi_img.img_url/sub_url: {wbi}")

    _save_cache(img_key, sub_key)
    return img_key, sub_key


def get_mixin_key(img_key: str, sub_key: str) -> str:
    """Permute ``img_key + sub_key`` (64 chars) by MIXIN_KEY_ENC_TAB → first 32."""
    combined = img_key + sub_key
    if len(combined) < 64:
        # Defensive: pad if Bilibili ever shortens keys
        combined = combined.ljust(64, "0")
    return "".join(combined[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi_params(params: Dict, img_key: str = "", sub_key: str = "") -> Dict:
    """Return a new dict with ``wts`` + ``w_rid`` signature appended.

    Parameters
    ----------
    params : dict
        Original request params (caller-owned, not mutated).
    img_key, sub_key : str
        Optional overrides. If empty, fetched via ``fetch_wbi_keys()``.

    Notes
    -----
    Chars ``!()*'`` are stripped from stringified values per Bilibili's
    JS implementation (see community docs). Values are URL-encoded.
    """
    if not img_key or not sub_key:
        img_key, sub_key = fetch_wbi_keys()

    mixin_key = get_mixin_key(img_key, sub_key)
    wts = int(time.time())

    # Copy + add wts, sort keys, strip forbidden chars
    signed = dict(params)
    signed["wts"] = wts
    signed = {
        k: "".join(c for c in str(v) if c not in "!()*'")
        for k, v in sorted(signed.items())
    }
    query = urllib.parse.urlencode(signed)
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    signed["w_rid"] = w_rid
    return signed
