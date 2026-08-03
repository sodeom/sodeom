import glob
import hashlib
import os

from flask import request


def _css_version(static_folder: str) -> str:
    """Return a short MD5 hash of all CSS files for cache-busting."""
    h = hashlib.md5()
    for f in sorted(glob.glob(os.path.join(static_folder, "*.css"))):
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest()[:8]


def add_privacy_headers(response):
    """Attach security and privacy headers to every outgoing response."""
    response.headers["DNT"] = "1"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "interest-cohort=()"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-src https://www.youtube.com "
        "https://www.youtube-nocookie.com https://player.vimeo.com "
        "https://www.dailymotion.com; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"

    _CACHEABLE_EXTS = (
        ".css",
        ".js",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".svg",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".webmanifest",
    )
    if request.path.startswith("/static/") or request.path.endswith(_CACHEABLE_EXTS):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        response.headers.pop("Pragma", None)

    return response
