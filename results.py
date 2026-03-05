"""
SearXNG-powered search backend for Sodeom.

Queries a SearXNG instance's JSON API to get web results, images, videos,
spell corrections, suggestions, infoboxes (wiki panels), and instant answers.
Falls back across multiple public SearXNG instances if one is down.
"""

import concurrent.futures
import json
import logging
import os
import random
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

_PUBLIC_INSTANCES = [
    "https://search.bus-hit.me",
    "https://searx.be",
    "https://search.ononoki.org",
    "https://searx.tiekoetter.com",
    "https://search.sapti.me",
    "https://searx.oxf.app",
    "https://paulgo.io",
    "https://opnxng.com",
    "https://priv.au",
    "https://searx.work",
]

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
    """Return an ordered list of SearXNG base URLs to try.


    1. SEARXNG_URL env var (self-hosted override)
    2. Local instance at localhost:8888 (started by app.py)
    3. Public instances (shuffled for load spreading)
    """
    instances = list(_PUBLIC_INSTANCES)
    random.shuffle(instances)  # spread load
    # Always try local instance first (fastest, most reliable)
    instances.insert(0, _LOCAL_INSTANCE)
    # Env-var override takes top priority
    if _PRIMARY_INSTANCE:
        instances.insert(0, _PRIMARY_INSTANCE)
    return instances


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


def _query_searxng(params: dict, timeout: int = 8) -> "dict | None":
    """
    Query SearXNG with a two-stage strategy:
    1. Try the local instance first (3 s timeout — it's localhost).
    2. Race the top 3 public instances concurrently; return first success.
    Results are cached for _CACHE_TTL seconds.
    """
    params = {**params, "format": "json"}
    params.setdefault("safesearch", "1")

    # --- Cache check ---
    cache_key = json.dumps(params, sort_keys=True)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # --- Stage 1: local instance (fast, 3 s) ---
    data = _fetch_instance(_LOCAL_INSTANCE, params, timeout=3)
    if data is not None:
        _cache_set(cache_key, data)
        return data

    # --- Stage 2: race top-3 public instances concurrently ---
    candidates = [i for i in _get_instances() if i != _LOCAL_INSTANCE][:3]
    result = None
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(candidates))
    futures = {
        executor.submit(_fetch_instance, base, params, timeout): base
        for base in candidates
    }
    try:
        for future in concurrent.futures.as_completed(futures, timeout=timeout + 1):
            try:
                data = future.result()
                if data is not None:
                    result = data
                    break
            except Exception:
                continue
    except concurrent.futures.TimeoutError:
        pass
    finally:
        executor.shutdown(wait=False)

    if result is not None:
        _cache_set(cache_key, result)
    return result


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
    """
    Perform a general web search via SearXNG.

    Returns a dict with keys:
        results      – list of {title, link, description, engine, ...}
        suggestions  – list of suggested queries
        corrections  – list of spelling corrections
        infoboxes    – list of infobox dicts (wiki panels, QA, etc.)
        answers      – list of instant-answer strings
        query        – the original query
        page         – current page number
    """
    params = {
        "q": query,
        "categories": "general",
        "pageno": page,
        "language": language,
        "engines": "google,duckduckgo,bing,brave,mojeek,qwant",
    }

    data = _query_searxng(params)

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
    """
    Image search via SearXNG.

    Each result contains: title, url (page), img_src (full image),
    thumbnail_src, source/engine, resolution, etc.
    """
    params = {
        "q": query,
        "categories": "images",
        "pageno": page,
        "language": language,
    }

    data = _query_searxng(params)

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
# Public API – Video search
# ---------------------------------------------------------------------------


def search_videos(query: str, page: int = 1, language: str = "en") -> dict:
    """
    Video search via SearXNG.

    Each result contains: title, url, thumbnail, length, author/source, etc.
    """
    params = {
        "q": query,
        "categories": "videos",
        "pageno": page,
        "language": language,
    }

    data = _query_searxng(params)

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

    data = _query_searxng(params)

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
