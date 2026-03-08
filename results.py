"""
SearXNG-powered search backend for Sodeom.

Queries a SearXNG instance's JSON API to get web results, images, videos,
spell corrections, suggestions, infoboxes (wiki panels), and instant answers.
Falls back across multiple public SearXNG instances if one is down.
"""

import json
import logging
import os
import re
import threading
import time

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SearXNG instance configuration
# ---------------------------------------------------------------------------
# Local SearXNG instance (started as subprocess by app.py)
_LOCAL_INSTANCE = "http://localhost:8888"

# Prefer a self-hosted instance via env var; fall back to local, then public.
_PRIMARY_INSTANCE = os.getenv("SEARXNG_URL", "").rstrip("/")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html",
}

# Adult-content keyword blocklist — pre-compiled regex for fast matching
_ADULT_RE = re.compile(
    r"\b(?:porn|xxx|adult|sex|nude|nsfw|mature)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Persistent HTTP session with connection pooling
# ---------------------------------------------------------------------------
_session = requests.Session()
_http_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
_session.mount("http://", _http_adapter)
_session.mount("https://", _http_adapter)

# ---------------------------------------------------------------------------
# In-memory TTL result cache (thread-safe, 60-second TTL, max 300 entries)
# ---------------------------------------------------------------------------
_CACHE_TTL = 60  # seconds
_cache: dict = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> "dict | None":
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    data, ts = entry
    if time.monotonic() - ts < _CACHE_TTL:
        return data
    with _cache_lock:
        _cache.pop(key, None)
    return None


def _cache_set(key: str, data: dict) -> None:
    with _cache_lock:
        if len(_cache) > 300:
            now = time.monotonic()
            stale = [k for k, (_, ts) in _cache.items() if now - ts >= _CACHE_TTL]
            for k in stale:
                _cache.pop(k, None)
        _cache[key] = (data, time.monotonic())


def _get_instances():
    """Return the SearXNG base URL to use.
    Prefers SEARXNG_URL env var, falls back to local instance.
    """
    return [_PRIMARY_INSTANCE or _LOCAL_INSTANCE]


# ---------------------------------------------------------------------------
# Low-level query helpers
# ---------------------------------------------------------------------------


def _fetch_instance(base_url: str, params: dict, timeout: int) -> "dict | None":
    """Fetch one SearXNG instance. Returns parsed dict or None on failure."""
    try:
        resp = _session.get(
            f"{base_url}/search",
            params=params,
            headers=HEADERS,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            return data
    except Exception as e:
        logger.debug("[SearXNG] %s failed: %s", base_url, e)
    return None


# How long to wait before retrying when SearXNG returns no results
_RETRY_DELAY = 1  # seconds
_MAX_RETRIES = 2  # one retry after a short pause


def _query_searxng(params: dict, timeout: int = 12) -> "dict | None":
    """
    Query the local SearXNG instance with automatic retry.
    Retries up to _MAX_RETRIES times if the instance is still starting up
    or returned an empty result set. No public instance fallback — the
    production machine has no outbound access to external instances.
    Only responses with actual results are cached.
    """
    params = {**params, "format": "json"}
    params.setdefault("safesearch", "1")

    # --- Cache check ---
    cache_key = json.dumps(params, sort_keys=True)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    instance = _PRIMARY_INSTANCE or _LOCAL_INSTANCE

    last: "dict | None" = None
    for attempt in range(_MAX_RETRIES):
        data = _fetch_instance(instance, params, timeout=timeout)
        if data is not None and data.get("results"):
            _cache_set(cache_key, data)
            return data
        if data is not None:
            last = data  # keep as fallback (has structure, just empty results)
        if attempt < _MAX_RETRIES - 1:
            # Small pause — SearXNG may still be initialising or the engine
            # hit a transient upstream timeout; a short wait often resolves it
            time.sleep(_RETRY_DELAY)

    # Return empty-but-structured response rather than None so callers can
    # distinguish "SearXNG reachable but no results" from "SearXNG down".
    return last


# ---------------------------------------------------------------------------
# Content filter
# ---------------------------------------------------------------------------


def _is_safe(text: str) -> bool:
    """Return False if text contains adult keywords."""
    return not _ADULT_RE.search(text)


def _filter_results(results: list[dict]) -> list[dict]:
    """Remove results whose title, URL or description contain adult keywords."""
    safe = []
    for r in results:
        combined = " ".join(str(r.get(k, "")) for k in ("title", "url", "content"))
        if _is_safe(combined):
            safe.append(r)
    return safe


# ---------------------------------------------------------------------------
# Public API – Web search
# ---------------------------------------------------------------------------


def search_web(query: str, page: int = 1, language: str = "en") -> dict:
    params = {
        "q": query,
        "categories": "general",
        "pageno": page,
        "language": language,
        # No engine restriction — let SearXNG use whatever is enabled in
        # settings_local.yml so the query works on any deployment
    }
    data = _query_searxng(params, timeout=12)

    if data is None:
        return _empty_response(query, page)

    # Normalise result keys to what the templates expect
    results = []
    for r in data.get("results", []):
        results.append(
            {
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "description": r.get("content", ""),
                "engine": r.get("engine", ""),
                "engines": r.get("engines", []),
                "score": r.get("score", 0),
                "category": r.get("category", "general"),
                "pretty_url": r.get("pretty_url", ""),
                "parsed_url": r.get("parsed_url", []),
                "thumbnail": r.get("thumbnail", ""),
                "img_src": r.get("img_src", ""),
            }
        )

    results = _filter_results_normalised(results)

    return {
        "results": results,
        "suggestions": list(data.get("suggestions", [])),
        "corrections": list(data.get("corrections", [])),
        "infoboxes": list(data.get("infoboxes", [])),
        "answers": list(data.get("answers", [])),
        "query": query,
        "page": page,
        "number_of_results": data.get("number_of_results", len(results)),
    }


# ---------------------------------------------------------------------------
# Public API – Image search
# ---------------------------------------------------------------------------


def search_images(query: str, page: int = 1, language: str = "en") -> dict:
    params = {
        "q": query,
        "categories": "images",
        "pageno": page,
        "language": language,
    }
    data = _query_searxng(params, timeout=12)

    if data is None:
        return _empty_response(query, page)

    images = []
    for r in data.get("results", []):
        img_url = r.get("img_src", "") or r.get("url", "")
        thumb = r.get("thumbnail_src", "") or r.get("thumbnail", "") or img_url
        combined = f"{r.get('title', '')} {img_url}"
        if not _is_safe(combined):
            continue
        images.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),  # page URL
                "img_src": img_url,  # full-size image
                "thumbnail": thumb,  # thumbnail
                "source": r.get("source", r.get("engine", "")),
                "resolution": r.get("resolution", ""),
                "engine": r.get("engine", ""),
            }
        )

    return {
        "results": images,
        "suggestions": list(data.get("suggestions", [])),
        "corrections": list(data.get("corrections", [])),
        "query": query,
        "page": page,
        "number_of_results": data.get("number_of_results", len(images)),
    }


# ---------------------------------------------------------------------------
# Public API – Single image URL (for /placeholder)
# ---------------------------------------------------------------------------


def search_first_image_url(query: str, count: int = 3) -> list[str]:
    """
    Fetch the first `count` image URLs for a query.
    Returns a list of img_src strings.
    """
    params = {
        "q": query,
        "categories": "images",
        "pageno": 1,
    }
    data = _query_searxng(params, timeout=12)
    if data is None:
        return []
    urls = []
    for r in data.get("results", []):
        img = r.get("img_src", "") or r.get("url", "")
        if img and _is_safe(f"{r.get('title', '')} {img}"):
            urls.append(img)
            if len(urls) >= count:
                break
    return urls


# ---------------------------------------------------------------------------
# Public API – Video search
# ---------------------------------------------------------------------------


def search_videos(query: str, page: int = 1, language: str = "en") -> dict:
    params = {
        "q": query,
        "categories": "videos",
        "pageno": page,
        "language": language,
    }
    data = _query_searxng(params, timeout=12)

    if data is None:
        return _empty_response(query, page)

    videos = []
    for r in data.get("results", []):
        combined = f"{r.get('title', '')} {r.get('url', '')}"
        if not _is_safe(combined):
            continue
        videos.append(
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "thumbnail": (
                    r.get("thumbnail", "")
                    or r.get("img_src", "")
                    or r.get("thumbnail_src", "")
                ),
                "length": r.get("length", ""),
                "author": r.get("author", ""),
                "source": r.get("source", r.get("engine", "")),
                "engine": r.get("engine", ""),
                "publishedDate": r.get("publishedDate", ""),
                "content": r.get("content", ""),
                "iframe_src": r.get("iframe_src", ""),
            }
        )

    return {
        "results": videos,
        "suggestions": list(data.get("suggestions", [])),
        "corrections": list(data.get("corrections", [])),
        "query": query,
        "page": page,
        "number_of_results": data.get("number_of_results", len(videos)),
    }


# ---------------------------------------------------------------------------
# Public API – News search
# ---------------------------------------------------------------------------


def search_news(query: str, page: int = 1, language: str = "en") -> dict:
    """News search via SearXNG."""
    params = {
        "q": query,
        "categories": "news",
        "pageno": page,
        "language": language,
    }
    data = _query_searxng(params, timeout=12)

    if data is None:
        return _empty_response(query, page)

    news = []
    for r in data.get("results", []):
        combined = f"{r.get('title', '')} {r.get('url', '')}"
        if not _is_safe(combined):
            continue
        news.append(
            {
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "description": r.get("content", ""),
                "source": r.get("source", r.get("engine", "")),
                "engine": r.get("engine", ""),
                "publishedDate": r.get("publishedDate", ""),
                "thumbnail": r.get("thumbnail", "") or r.get("img_src", ""),
            }
        )

    return {
        "results": news,
        "suggestions": list(data.get("suggestions", [])),
        "corrections": list(data.get("corrections", [])),
        "query": query,
        "page": page,
        "number_of_results": data.get("number_of_results", len(news)),
    }


# ---------------------------------------------------------------------------
# Public API – Wiki / Infobox lookup
# ---------------------------------------------------------------------------


def search_wiki(query: str, language: str = "en") -> dict:
    """
    Fetch infoboxes and answers for a query (used by the /wiki route).
    Queries the 'general' category and extracts infoboxes + answers.
    Also queries Wikipedia engine specifically.
    """
    params = {
        "q": query,
        "categories": "general",
        "pageno": 1,
        "language": language,
        "engines": "wikipedia,wikidata,duckduckgo",
    }

    data = _query_searxng(params)

    if data is None:
        return {
            "infoboxes": [],
            "answers": [],
            "results": [],
            "suggestions": [],
            "query": query,
        }

    return {
        "infoboxes": list(data.get("infoboxes", [])),
        "answers": list(data.get("answers", [])),
        "results": [
            {
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "description": r.get("content", ""),
                "engine": r.get("engine", ""),
            }
            for r in data.get("results", [])[:5]
        ],
        "suggestions": list(data.get("suggestions", [])),
        "query": query,
    }


# ---------------------------------------------------------------------------
# Backward-compatible main() for existing code
# ---------------------------------------------------------------------------


def main(query: str, page: int = 1) -> list[dict]:
    """
    Backward-compatible entry point.
    Returns a flat list of result dicts with {title, link, description}.
    """
    data = search_web(query, page)
    return data.get("results", [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_response(query: str, page: int) -> dict:
    return {
        "results": [],
        "suggestions": [],
        "corrections": [],
        "infoboxes": [],
        "answers": [],
        "query": query,
        "page": page,
        "number_of_results": 0,
    }


def _filter_results_normalised(results: list[dict]) -> list[dict]:
    """Filter normalised results (with 'link' key instead of 'url')."""
    safe = []
    for r in results:
        combined = " ".join(str(r.get(k, "")) for k in ("title", "link", "description"))
        if _is_safe(combined):
            safe.append(r)
    return safe
