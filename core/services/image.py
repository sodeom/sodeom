"""Image proxy: safe download with SSRF protection and size limiting."""

import hashlib
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse, quote

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

# Proxy configuration
_PROXY_WORKER_URL = "https://myproxy.abdulhadijunaidahmedkhan.workers.dev".rstrip("/")
_USE_PROXY = bool(_PROXY_WORKER_URL)

_img_session = requests.Session()
_img_session.mount("http://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
_img_session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))

_IMG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def _proxy_url(url: str) -> str:
    """Convert URL to proxied URL if proxy is configured."""
    if not _USE_PROXY:
        return url
    return f"{_PROXY_WORKER_URL}?url={quote(url, safe='')}"


def is_safe_url(url: str) -> bool:
    """Block SSRF: reject private/internal IPs and non-http(s) schemes."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        addr = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _type, _proto, _canon, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return False
        return True
    except Exception:
        return False


def install_image(url: str, base_dir: str = "placeholders") -> str | None:
    """Download *url* to *base_dir* (if not already cached) and return the path.

    Returns None if the URL is unsafe, the response is not an image, or the
    download exceeds MAX_IMAGE_SIZE.
    """
    if not is_safe_url(url):
        return None

    os.makedirs(base_dir, exist_ok=True)

    filename = hashlib.sha256(url.encode()).hexdigest() + ".jpg"
    filepath = os.path.join(base_dir, filename)

    if os.path.exists(filepath):
        return filepath

    try:
        # Use proxy if configured
        fetch_url = _proxy_url(url)

        response = _img_session.get(
            fetch_url, stream=True, timeout=6, headers=_IMG_HEADERS, allow_redirects=False
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None

        downloaded = 0
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(16384):
                downloaded += len(chunk)
                if downloaded > MAX_IMAGE_SIZE:
                    f.close()
                    os.remove(filepath)
                    return None
                f.write(chunk)
        return filepath
    except Exception as e:
        logger.debug("[install_image] Failed: %s", e)
        if os.path.exists(filepath):
            os.remove(filepath)
        return None
