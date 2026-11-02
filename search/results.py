"""
SearXNG-powered search backend for Sodeom.

Queries a SearXNG instance's JSON API to get web results, images, videos,
spell corrections, suggestions, infoboxes (wiki panels), and instant answers.
Uses only the local SearXNG instance.
"""

import json
import logging
import re
import threading
import time
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proxy configuration (for PythonAnywhere whitelist bypass)
# ---------------------------------------------------------------------------
import os

_PROXY_WORKER_URL = os.getenv(
    "PROXY_WORKER_URL", "https://myproxy.abdulhadijunaidahmedkhan.workers.dev"
).rstrip("/")
_USE_PROXY = bool(_PROXY_WORKER_URL)

if _USE_PROXY:
    logger.info("[Proxy] Cloudflare Worker proxy enabled: %s", _PROXY_WORKER_URL)
else:
    logger.info("[Proxy] Direct requests (no proxy configured)")

# ---------------------------------------------------------------------------
# SearXNG instance configuration
# ---------------------------------------------------------------------------
# Local SearXNG instance (started as subprocess by app.py)
_LOCAL_INSTANCE = "http://localhost:8888"

# External fallback (used when local fails or for remote access)
_EXTERNAL_INSTANCE = os.getenv("SEARXNG_URL", "").strip()
if _EXTERNAL_INSTANCE:
    _EXTERNAL_INSTANCE = _EXTERNAL_INSTANCE.rstrip("/")

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


def _local_port_open(timeout: float = 0.3) -> bool:
    """Return True if local SearXNG is listening on localhost:8888."""
    try:
        resp = _session.get(f"{_LOCAL_INSTANCE}/healthz", timeout=timeout)
        return resp.status_code in (200, 404)
    except Exception:
        return False


def _ensure_local_searxng_started() -> None:
    if _local_start_disabled():
        return
    """Try to boot local SearXNG when localhost instance is unavailable.

    This keeps searches working in local/dev environments if the subprocess
    has died. In hosted environments that intentionally disable local start,
    start_searxng() will safely no-op.
    """
    if _local_port_open():
        return
    try:
        from core.services.searxng import start_searxng

        start_searxng()
        # Give the subprocess a short window to boot so this same request
        # can still return results instead of requiring a second refresh.
        for _ in range(6):
            if _local_port_open(timeout=0.5):
                return
            time.sleep(0.5)
    except Exception as e:
        logger.debug("[SearXNG] Local auto-start skipped: %s", e)


# ---------------------------------------------------------------------------
# In-memory TTL result cache (thread-safe, 5-minute TTL, max 300 entries)
# ---------------------------------------------------------------------------
_CACHE_TTL = 600  # seconds
_cache: dict = {}
_cache_lock = threading.Lock()


def _cache_get(key: str) -> "dict | None":
    with _cache_lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    data, ts, ttl = entry
    if time.monotonic() - ts < ttl:
        return data
    with _cache_lock:
        _cache.pop(key, None)
    return None


def _cache_set(key: str, data: dict, ttl: int = _CACHE_TTL) -> None:
    with _cache_lock:
        if len(_cache) > 300:
            now = time.monotonic()
            stale = [k for k, (_, ts, item_ttl) in _cache.items() if now - ts >= item_ttl]
            for k in stale:
                _cache.pop(k, None)
        _cache[key] = (data, time.monotonic(), ttl)



def _local_start_disabled() -> bool:
    """True when running in external-only mode (typical on PythonAnywhere free)."""
    return os.getenv("SEARXNG_DISABLE_LOCAL_START", "").strip().lower() in ("1", "true", "yes", "on")


def _get_instances():
    """Return SearXNG instances to try.
    Tries local first (unless disabled), then external.
    """
    instances = []
    if not _local_start_disabled():
        instances.append(_LOCAL_INSTANCE)
    if _EXTERNAL_INSTANCE and _EXTERNAL_INSTANCE != _LOCAL_INSTANCE:
        instances.append(_EXTERNAL_INSTANCE)
    # External-only mode with no configured external instance (common on
    # PythonAnywhere free before SEARXNG_URL is set): return no local instance
    # and let callers fall back to the direct proxy search.
    return instances


def _search_direct_via_proxy(query: str) -> "dict | None":
    """Fallback: search directly via proxy using Brave."""
    if not _USE_PROXY:
        return None
    try:
        import requests

        url = f"https://search.brave.com/search?q={quote(query, safe='')}"
        proxied = f"{_PROXY_WORKER_URL}/?url={quote(url, safe='')}"
        resp = requests.get(
            proxied,
            timeout=15,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0 Safari/537.36"
                )
            },
        )
        if resp.status_code != 200:
            return None

        results = _parse_brave_results(resp.text)
        if results:
            return {
                "results": results,
                "answers": [],
                "suggestions": [],
                "infoboxes": [],
            }
    except Exception as e:
        logger.debug("[Direct] Fallback failed: %s", e)
    return None


def _parse_brave_results(html: str) -> list[dict]:
    """Extract clean title/url/description from Brave SERP HTML (regex, fast)."""
    import html as _html

    def _strip(text: str) -> str:
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = _html.unescape(text)
        return " ".join(text.split())

    results = []
    seen_urls = set()
    marker = "<div class=\"snippet"
    pos = 0
    while len(results) < 10:
        start = html.find(marker, pos)
        if start < 0:
            break
        nxt = html.find(marker, start + 1)
        seg = html[start:nxt] if nxt >= 0 else html[start:]
        # Only web result cards carry data-type="web".
        if 'data-type="web"' not in seg:
            pos = start + 1 if nxt < 0 else nxt
            continue

        link_match = re.search(r'<a href="(https?://[^"]+)"', seg)
        if not link_match:
            pos = start + 1 if nxt < 0 else nxt
            continue

        href = link_match.group(1)
        if href in seen_urls:
            pos = start + 1 if nxt < 0 else nxt
            continue

        title_match = re.search(
            r'class="title search-snippet-title[^"]*"[^>]*>(.*?)</div>', seg, re.S
        )
        title = _strip(title_match.group(1)) if title_match else ""

        pretty_match = re.search(
            r'class="snippet-url[^"]*"[^>]*>(.*?)</cite>', seg, re.S
        )
        pretty = _strip(pretty_match.group(1)) if pretty_match else ""

        content_match = re.search(
            r'class="content[^"]*"[^>]*>(.*?)</div>', seg, re.S
        )
        desc = _strip(content_match.group(1)) if content_match else ""
        desc = " ".join(desc.split())[:220]

        if (title or desc) and len(title) <= 120:
            if not title_match and not content_match:
                # Skip empty/nav cards
                pos = start + 1 if nxt < 0 else nxt
                continue

            domain_fallback = False
            if not title:
                from urllib.parse import urlparse

                domain = urlparse(href).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
                title = domain or href[:60]

            seen_urls.add(href)
            results.append(
                {
                    "title": title[:120],
                    "url": href,
                    "pretty_url": pretty[:120],
                    "content": desc,
                    "engine": "brave",
                }
            )

        pos = start + 1 if nxt < 0 else nxt

    return results


def _search_images_direct(query: str) -> "dict | None":
    """Fallback: search images directly via proxy using Bing Images."""
    if not _USE_PROXY:
        return None
    try:
        import requests
        from urllib.parse import quote
        # Use Bing Images through proxy
        url = f"https://www.bing.com/images/search?q={quote(query, safe='')}"
        proxied = f"{_PROXY_WORKER_URL}/?url={quote(url, safe='')}"
        resp = requests.get(proxied, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return None

        # Parse Bing Images HTML via regex (avoid heavy BeautifulSoup)
        results = []
        seen = set()

        for raw_m in re.findall(r'm="(\{[^"]*\})"', resp.text):
            m_data = raw_m.replace("&quot;", "\"").replace("&#39;", "'")
            try:
                data = json.loads(m_data)
            except Exception:
                continue

            # Get image URLs
            purl = data.get("purl", "")  # page URL
            img_url = data.get("turl", "") or data.get("iurl", "") or data.get("murl", "")
            if not img_url or img_url in seen:
                continue
            seen.add(img_url)

            # Get title from page URL
            title = purl.split("/")[-1] if purl else query
            title = title.replace("-", " ").replace("_", " ").title()[:50]

            results.append({
                "title": title,
                "url": purl,
                "img_src": img_url,
                "thumbnail": img_url,
                "source": "bing_images",
                "resolution": "",
                "engine": "bing_images",
            })
            if len(results) >= 10:
                break

        if results:
            return {"results": results, "answers": [], "suggestions": [], "infoboxes": []}
    except Exception as e:
        logger.debug("[Direct Images] Fallback failed: %s", e)
    return None


# ---------------------------------------------------------------------------
# Low-level query helpers
# ---------------------------------------------------------------------------


def _proxy_url(url: str) -> str:
    """Convert URL to proxied URL if proxy is configured."""
    if not _USE_PROXY:
        return url
    return f"{_PROXY_WORKER_URL}?url={quote(url, safe='')}"


def _fetch_instance(base_url: str, params: dict, timeout: int) -> "dict | None":
    """Fetch one SearXNG instance. Returns parsed dict or None on failure."""
    try:
        # Build the search URL
        search_url = f"{base_url}/search"

        # Use proxy if configured (except for localhost)
        if _USE_PROXY and not base_url.startswith("http://localhost"):
            # Proxy the entire URL with query parameters
            from urllib.parse import urlencode

            full_url = f"{search_url}?{urlencode(params)}"
            proxied_url = _proxy_url(full_url)
            resp = _session.get(
                proxied_url,
                headers=HEADERS,
                timeout=timeout,
            )
        else:
            # Direct request (localhost or no proxy)
            resp = _session.get(
                search_url,
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
_RETRY_DELAY = 0.3  # seconds
_MAX_RETRIES = 1


def _query_searxng(params: dict, timeout: int = 6) -> "dict | None":
    """
    Query SearXNG instances with automatic retry.
    Local-only mode retries the localhost instance up to _MAX_RETRIES times.
    Only responses with actual results are cached.
    """
    params = {**params, "format": "json"}
    params.setdefault("safesearch", "1")

    if _local_start_disabled():
        timeout = min(timeout, 6)

    # If local instance is part of the fallback chain and currently down,
    # attempt to start it in the background before querying.
    _ensure_local_searxng_started()

    # --- Cache check ---
    cache_key = json.dumps(params, sort_keys=True)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    retries = 1 if _local_start_disabled() else _MAX_RETRIES

    last: "dict | None" = None
    last_instance = None
    for instance in _get_instances():
        logger.debug("[SearXNG] Trying instance: %s", instance)
        for attempt in range(retries):
            data = _fetch_instance(instance, params, timeout=timeout)
            # If we got results, cache and return
            if data is not None and data.get("results"):
                _cache_set(cache_key, data)
                return data
            # Track last valid response
            if data is not None:
                last = data
                last_instance = instance
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_DELAY)

        # If local failed/empty and we have external, continue to next
        if instance == _LOCAL_INSTANCE and _EXTERNAL_INSTANCE:
            logger.debug("[SearXNG] Local empty, trying external...")
            continue

    # If no results, try direct search via proxy
    if not last or not last.get("results"):
        query = params.get("q", "")
        logger.debug("[SearXNG] Trying direct search for: %s", query)
        direct = _search_direct_via_proxy(query)
        if direct and direct.get("results"):
            _cache_set(cache_key, direct)
            return direct

    # Cache empty/error responses briefly to reduce repeated slow upstream calls.
    if last is not None and not last.get("results"):
        _cache_set(cache_key, last, ttl=60)

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


def _search_videos_direct(query: str) -> "dict | None":
    """Direct fallback for videos (free-plan): reuse Brave results for video-friendly links."""
    if not _USE_PROXY:
        return None
    try:
        data = _search_direct_via_proxy(f"{query} site:youtube.com")
        if not (data and data.get("results")):
            data = _search_direct_via_proxy(query)
        if not (data and data.get("results")):
            return None
        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "thumbnail": "",
                "length": "",
                "author": "",
                "source": "brave",
                "engine": "brave",
                "publishedDate": "",
                "content": r.get("content", ""),
                "iframe_src": "",
            }
            for r in data["results"]
        ]
        return {"results": results, "answers": [], "suggestions": [], "infoboxes": []}
    except Exception as e:
        logger.debug("[Direct Videos] Fallback failed: %s", e)
    return None


def _search_news_direct(query: str) -> "dict | None":
    """Direct fallback for news via Bing News RSS."""
    if not _USE_PROXY:
        return None
    try:
        import xml.etree.ElementTree as ET
        from urllib.parse import quote, unquote, urlparse, parse_qs

        url = f"https://www.bing.com/news/search?q={quote(query, safe='')}&format=rss"
        proxied = f"{_PROXY_WORKER_URL}/?url={quote(url, safe='')}"
        import requests

        resp = requests.get(
            proxied, timeout=12, headers={"User-Agent": "Mozilla/5.0"}
        )
        if resp.status_code != 200:
            return None

        root = ET.fromstring(resp.text)
        results = []
        for item in root.findall(".//item")[:10]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            source_el = item.find("{https://www.bing.com/news/search?q=}Source")
            source = ""
            if source_el is not None and (source_el.text or "").strip():
                source = source_el.text.strip()
            # Extract real article URL from Bing redirect (optional)
            try:
                parsed = urlparse(link)
                if "apiclick.aspx" in (parsed.path or ""):
                    qs = parse_qs(parsed.query)
                    if "url" in qs:
                        link = unquote(qs["url"][0])
            except Exception:
                pass
            img_el = item.find("{https://www.bing.com/news/search?q=}Image")
            thumb = (img_el.text or "").strip() if img_el is not None else ""
            results.append(
                {
                    "title": title,
                    "url": link,
                    "content": desc,
                    "publishedDate": pub,
                    "source": source or "bing_news",
                    "engine": "bing_news",
                }
            )
        if not results:
            return None
        return {"results": results, "answers": [], "suggestions": [], "infoboxes": []}
    except Exception as e:
        logger.debug("[Direct News] Fallback failed: %s", e)
    return None


def _search_wiki_direct(query: str) -> "dict | None":
    """Direct fallback for wiki via Wikipedia opensearch (fast JSON)."""
    if not _USE_PROXY:
        return None
    try:
        import requests

        url = "https://en.wikipedia.org/w/api.php?" + "action=opensearch&format=json&limit=5&search=" + quote(query, safe="")
        proxied = f"{_PROXY_WORKER_URL}/?url={quote(url, safe='')}"
        resp = requests.get(proxied, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) < 4:
            return None
        titles, descs, urls = data[1], data[2], data[3]
        results = []
        for t, d, u in zip(titles, descs, urls):
            results.append({"title": t, "url": u, "content": d})
        if not results:
            return None
        return {"results": results, "answers": [], "suggestions": [], "infoboxes": []}
    except Exception as e:
        logger.debug("[Direct Wiki] Fallback failed: %s", e)
    return None


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
    data = _query_searxng(params, timeout=6)

    if data is None:
        return _empty_response(query, page)

    # Normalise result keys to what the templates expect
    results = []
    for r in data.get("results", []):
        link = r.get("url", "") or r.get("link", "")
        pretty = r.get("pretty_url", "") or r.get("prettyUrl", "")
        if not pretty and link:
            from urllib.parse import urlparse

            parsed = urlparse(link)
            pretty = parsed.netloc + parsed.path
            if pretty.endswith("/"):
                pretty = pretty[:-1]
            if pretty.startswith("www."):
                pretty = pretty[4:]
        results.append(
            {
                "title": r.get("title", ""),
                "link": link,
                "description": r.get("content", "") or r.get("description", ""),
                "engine": r.get("engine", ""),
                "engines": r.get("engines", []),
                "score": r.get("score", 0),
                "category": r.get("category", "general"),
                "pretty_url": pretty,
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
    if _local_start_disabled() and not _EXTERNAL_INSTANCE:
        data = None
    else:
        data = _query_searxng(params, timeout=6)

    # If no usable results, try direct image search fallback
    if data is None or not data.get("results"):
        data = _search_images_direct(query)

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
    if _local_start_disabled() and not _EXTERNAL_INSTANCE:
        data = None
    else:
        data = _query_searxng(params, timeout=6)
    if data is None or not data.get("results"):
        direct = _search_images_direct(query)
        if direct and direct.get("results"):
            data = direct
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
    if _local_start_disabled() and not _EXTERNAL_INSTANCE:
        data = None
    else:
        data = _query_searxng(params, timeout=6)

    if data is None or not data.get("results"):
        direct = _search_videos_direct(query)
        if direct and direct.get("results"):
            data = direct

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
    if _local_start_disabled() and not _EXTERNAL_INSTANCE:
        data = None
    else:
        data = _query_searxng(params, timeout=6)

    if data is None or not data.get("results"):
        direct = _search_news_direct(query)
        if direct and direct.get("results"):
            data = direct

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

    if _local_start_disabled() and not _EXTERNAL_INSTANCE:
        data = None
    else:
        data = _query_searxng(params, timeout=6)

    if data is None or not data.get("results"):
        direct = _search_wiki_direct(query)
        if direct and direct.get("results"):
            data = direct

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
