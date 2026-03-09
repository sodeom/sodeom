import atexit
import hashlib
import ipaddress
import json
import logging
import mimetypes
import os
import re
import secrets
import socket
import subprocess
import time
import uuid
from urllib.parse import quote_plus, urlparse

import requests
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    stream_with_context,
)
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

from results import (
    main,
    search_first_image_url,
    search_images,
    search_news,
    search_videos,
    search_web,
    search_wiki,
)

app = Flask(__name__)


# ── Cache-busting: hash all CSS files so updates always reach the browser ──
def _css_version() -> str:
    import glob

    h = hashlib.md5()
    for f in sorted(glob.glob(os.path.join(app.static_folder, "*.css"))):
        try:
            with open(f, "rb") as fh:
                h.update(fh.read())
        except OSError:
            pass
    return h.hexdigest()[:8]


app.jinja_env.globals["static_ver"] = _css_version()


# ── Privacy: Add security/privacy headers to every response ──
@app.after_request
def add_privacy_headers(response):
    # Tell browsers not to track
    response.headers["DNT"] = "1"
    # No referrer info leaked to external sites
    response.headers["Referrer-Policy"] = "no-referrer"
    # Block third-party cookies, trackers, etc.
    response.headers["Permissions-Policy"] = "interest-cohort=()"  # Block FLoC
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    # Content Security Policy
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.stripe.com; "
        "frame-src https://js.stripe.com https://www.youtube.com https://www.youtube-nocookie.com https://player.vimeo.com https://www.dailymotion.com; "
        "object-src 'none'; "
        "base-uri 'self';"
    )
    # HTTPS enforcement
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    # Don't cache search queries on the server
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response.headers["Pragma"] = "no-cache"

    cacheable_exts = (
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
    if request.path.startswith("/static/") or request.path.endswith(cacheable_exts):
        response.headers["Cache-Control"] = "public, max-age=604800, immutable"
        response.headers.pop("Pragma", None)
    return response


import dotenv
from openai import OpenAI

dotenv.load_dotenv()

# ---------------------------------------------------------------------------
# Auto-start local SearXNG instance as a subprocess
# ---------------------------------------------------------------------------
_SEARXNG_PROC = None
_SEARXNG_SETTINGS = os.path.join(
    os.path.dirname(__file__), "searxng_src", "settings_local.yml"
)
_SEARXNG_PYTHON = os.path.join(os.path.dirname(__file__), ".venv", "bin", "python")


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if something is listening on host:port."""
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _start_searxng():
    """Start SearXNG as a background subprocess if not already running."""
    global _SEARXNG_PROC

    # Check if already running on port 8888
    if _port_open("127.0.0.1", 8888):
        print("[SearXNG] Already running on port 8888")
        return

    if not os.path.exists(_SEARXNG_PYTHON):
        print(f"[SearXNG] Python not found at {_SEARXNG_PYTHON} — skipping local start")
        return

    if not os.path.exists(_SEARXNG_SETTINGS):
        print(
            f"[SearXNG] Settings not found at {_SEARXNG_SETTINGS} — skipping local start"
        )
        return

    env = os.environ.copy()
    env["SEARXNG_SETTINGS_PATH"] = _SEARXNG_SETTINGS

    try:
        _SEARXNG_PROC = subprocess.Popen(
            [_SEARXNG_PYTHON, "-m", "searx.webapp"],
            cwd=os.path.join(os.path.dirname(__file__), "searxng_src"),
            env=env,
            stdout=open("/tmp/searxng.log", "a"),
            stderr=subprocess.STDOUT,
        )
        print(f"[SearXNG] Started with PID {_SEARXNG_PROC.pid}")

        # Wait up to 60 seconds for SearXNG to start listening on port 8888.
        # Uses a raw socket check so botdetection headers don't interfere.
        for i in range(60):
            time.sleep(1)
            if _port_open("127.0.0.1", 8888):
                print(f"[SearXNG] Ready after {i + 1}s")
                return
        print("[SearXNG] Warning: instance did not open port 8888 within 60s")
    except Exception as e:
        print(f"[SearXNG] Failed to start: {e}")


def _stop_searxng():
    """Terminate the SearXNG subprocess on app shutdown."""
    global _SEARXNG_PROC
    if _SEARXNG_PROC and _SEARXNG_PROC.poll() is None:
        print(f"[SearXNG] Stopping PID {_SEARXNG_PROC.pid}")
        _SEARXNG_PROC.terminate()
        try:
            _SEARXNG_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _SEARXNG_PROC.kill()


# Register shutdown hook
atexit.register(_stop_searxng)

# Start SearXNG (only in main process, not in Flask reloader child)
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    _start_searxng()

# AI features enabled via GitHub Models API
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
client = OpenAI(base_url=GITHUB_ENDPOINT, api_key=GITHUB_TOKEN)


# Maximum image download size: 10 MB
MAX_IMAGE_SIZE = 10 * 1024 * 1024

# Shared session for image downloads (connection pooling)
_img_session = requests.Session()
_img_session.mount("http://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
_img_session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))


def _is_safe_url(url: str) -> bool:
    """Block SSRF: reject private/internal IPs and non-http(s) schemes."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        # Resolve hostname to IP and check if it's private/reserved
        addr = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
                return False
        return True
    except Exception:
        return False


_IMG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def install_image(url: str, base_dir="placeholders") -> str | None:
    # SSRF protection: only allow safe external URLs
    if not _is_safe_url(url):
        return None

    os.makedirs(base_dir, exist_ok=True)

    # Unique filename from URL hash
    filename = hashlib.sha256(url.encode()).hexdigest() + ".jpg"
    filepath = os.path.join(base_dir, filename)

    # Already cached on disk — skip download entirely
    if os.path.exists(filepath):
        return filepath

    try:
        response = _img_session.get(
            url, stream=True, timeout=6, headers=_IMG_HEADERS, allow_redirects=False
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None

        # Enforce size limit to prevent disk exhaustion
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


# Use env var or generate a strong random key (never use a hardcoded default)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)


def utf8_string_to_binary(input_str: str) -> str:
    byte_data = input_str.encode("utf-8")
    binary = "".join(format(byte, "08b") for byte in byte_data)
    # Pad to multiple of 64 bits
    while len(binary) % 64 != 0:
        binary += "0"
    return binary


# Allowed parameters that can be passed to the AI model
_ALLOWED_AI_PARAMS = {"model", "messages", "temperature", "max_tokens", "top_p"}

# Models exposed through the OpenAI-compatible /v1/models endpoint
_AVAILABLE_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o1-mini",
    "Meta-Llama-3.1-8B-Instruct",
    "Meta-Llama-3.1-70B-Instruct",
    "Mistral-small",
    "Phi-3.5-mini-instruct",
]

# Allowed fields for the OpenAI-compatible completions endpoint
_ALLOWED_COMPLETIONS_PARAMS = {
    "model",
    "messages",
    "temperature",
    "max_tokens",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
    "stop",
    "n",
    "seed",
    "logprobs",
    "response_format",
}


@app.route("/ai", methods=["GET", "POST"])
def query_ai():
    # TODO: Add rate limiting (e.g., Flask-Limiter) to prevent API abuse
    query = request.args.get("query", "").strip()
    other_params = request.get_json(silent=True) or {}

    if not query and "messages" not in other_params:
        return jsonify({"error": "No query or messages provided"}), 400

    # Whitelist: only allow safe parameters to be passed to the AI client
    safe_params = {k: v for k, v in other_params.items() if k in _ALLOWED_AI_PARAMS}

    if "model" not in safe_params:
        safe_params["model"] = DEFAULT_MODEL

    if "messages" not in safe_params:
        safe_params["messages"] = [
            {
                "role": "system",
                "content": (
                    "You are a concise search assistant. Answer the user's query "
                    "directly in 2-4 sentences. Be factual and brief."
                ),
            },
            {"role": "user", "content": query},
        ]

    if "max_tokens" not in safe_params:
        safe_params["max_tokens"] = 512

    # Validate messages structure
    if not isinstance(safe_params.get("messages"), list):
        return jsonify({"error": "Invalid messages format"}), 400

    for msg in safe_params["messages"]:
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            return jsonify({"error": "Invalid message structure"}), 400
        if msg["role"] not in ("system", "user", "assistant"):
            return jsonify({"error": "Invalid message role"}), 400

    try:
        response = client.chat.completions.create(**safe_params)
        answer = response.choices[0].message.content
        return jsonify({"answer": answer})
    except Exception:
        # Don't leak internal error details to the client
        return jsonify({"error": "AI service temporarily unavailable"}), 500


# ---------------------------------------------------------------------------
# OpenAI SDK-compatible API  (/v1/...)
# Point the OpenAI SDK at this server:  OpenAI(base_url="https://sodeom.com/v1", api_key="any")
# ---------------------------------------------------------------------------


def _openai_error(
    message: str,
    err_type: str = "invalid_request_error",
    status: int = 400,
    param: str = None,
):
    return jsonify(
        {"error": {"message": message, "type": err_type, "param": param, "code": None}}
    ), status


@app.route("/v1/models", methods=["GET"])
def v1_models():
    now = int(time.time())
    return jsonify(
        {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "created": now, "owned_by": "sodeom"}
                for m in _AVAILABLE_MODELS
            ],
        }
    )


@app.route("/v1/models/<path:model_id>", methods=["GET"])
def v1_model(model_id):
    if model_id not in _AVAILABLE_MODELS:
        return _openai_error(
            f"Model '{model_id}' not found", "invalid_request_error", 404
        )
    return jsonify(
        {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "sodeom",
        }
    )


@app.route("/v1/chat/completions", methods=["POST"])
def v1_chat_completions():
    body = request.get_json(silent=True) or {}

    # Whitelist — never forward unexpected fields to the upstream client
    safe_params = {k: v for k, v in body.items() if k in _ALLOWED_COMPLETIONS_PARAMS}

    if "model" not in safe_params:
        safe_params["model"] = DEFAULT_MODEL

    messages = safe_params.get("messages")
    if not isinstance(messages, list) or not messages:
        return _openai_error("messages must be a non-empty array", param="messages")

    for msg in messages:
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            return _openai_error("Each message must have 'role' and 'content' fields")
        if msg["role"] not in ("system", "user", "assistant", "tool", "function"):
            return _openai_error(f"Invalid role: {msg['role']}")

    if "max_tokens" not in safe_params:
        safe_params["max_tokens"] = 1024

    want_stream = bool(body.get("stream", False))
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = safe_params["model"]

    if want_stream:

        def _generate():
            safe_params["stream"] = True
            try:
                for chunk in client.chat.completions.create(**safe_params):
                    delta = {}
                    finish_reason = None
                    if chunk.choices:
                        c = chunk.choices[0]
                        if c.delta.role:
                            delta["role"] = c.delta.role
                        if c.delta.content:
                            delta["content"] = c.delta.content
                        finish_reason = c.finish_reason
                    payload = {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {"index": 0, "delta": delta, "finish_reason": finish_reason}
                        ],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception:
                err = {
                    "error": {
                        "message": "AI service temporarily unavailable",
                        "type": "server_error",
                    }
                }
                yield f"data: {json.dumps(err)}\n\n"

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming response
    try:
        resp = client.chat.completions.create(**safe_params)
        choice = resp.choices[0]
        usage = resp.usage
        return jsonify(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": choice.message.content,
                        },
                        "finish_reason": choice.finish_reason or "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "total_tokens": usage.total_tokens if usage else 0,
                },
            }
        )
    except Exception:
        return _openai_error("AI service temporarily unavailable", "server_error", 500)


def binary_to_utf8_string(binary_str: str) -> str:
    if len(binary_str) % 8 != 0:
        raise ValueError("Binary string length must be a multiple of 8")
    byte_list = [int(binary_str[i : i + 8], 2) for i in range(0, len(binary_str), 8)]
    # Remove trailing zero bytes (padding)
    while byte_list and byte_list[-1] == 0:
        byte_list.pop()
    return bytes(byte_list).decode("utf-8")


# Common headers to mimic a real browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


### ── Flask Routes ─────────────────────────────────────────────────────────────


@app.route("/")
def index():
    q = request.args.get("q", "")
    b = request.args.get("b", "")
    page = request.args.get("page", 1, type=int)

    query_error = ""
    if isinstance(q, str):
        q = q.strip()
        if q == "" and request.args.get("q") is not None:
            query_error = "Please enter a search query."

    # Ensure page is at least 1
    if page < 1:
        page = 1

    if b == "" and q != "":
        binary = utf8_string_to_binary(q)
        return redirect(f"/?q={q}&b={binary}&page={page}")

    if b != "" and q == "":
        try:
            text = binary_to_utf8_string(b)
            return redirect(f"/?q={text}&b={b}&page={page}")
        except ValueError:
            # Invalid binary, redirect to clean search
            return redirect("/?q=&b=&page=1")

    results = []
    suggestions = []
    corrections = []
    infoboxes = []
    answers = []
    total_results = 0

    if q:
        try:
            data = search_web(q, page)
            results = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            infoboxes = data.get("infoboxes", [])
            answers = data.get("answers", [])
            total_results = data.get("number_of_results", len(results))
        except Exception:
            query_error = "Search temporarily unavailable. Please try again."
            results = []
            total_results = 0

    # Calculate pagination info
    has_next = (
        total_results >= 10 or len(results) >= 10
    )  # Assume there might be more results if we got 10 or more
    has_prev = page > 1

    return render_template(
        "index.html",
        results=results,
        query=q,
        query_error=query_error,
        page=page,
        b=b,
        has_next=has_next,
        has_prev=has_prev,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
        infoboxes=infoboxes,
        answers=answers,
    )


@app.route("/api/search")
def indexapi():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    category = request.args.get("category", "general")

    if not q:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    # Ensure page is at least 1
    if page < 1:
        page = 1

    try:
        if category == "images":
            data = search_images(q, page)
        elif category == "videos":
            data = search_videos(q, page)
        elif category == "news":
            data = search_news(q, page)
        else:
            data = search_web(q, page)

        results = data.get("results", [])
        total_results = data.get("number_of_results", len(results))
    except Exception:
        return jsonify({"error": "Search temporarily unavailable"}), 500

    response_data = {
        "results": results,
        "query": q,
        "page": page,
        "category": category,
        "has_next": len(results) >= 10,
        "has_prev": page > 1,
        "total_results": total_results,
        "suggestions": data.get("suggestions", []),
        "corrections": data.get("corrections", []),
        "infoboxes": data.get("infoboxes", []),
        "answers": data.get("answers", []),
    }

    return jsonify(response_data)


# ── Wiki lookup route ──────────────────────────────────────────────────────────
@app.route("/wiki/<query>", methods=["GET"])
def wiki(query):
    try:
        data = search_wiki(query)
        infoboxes = data.get("infoboxes", [])
        answers = data.get("answers", [])
        results = data.get("results", [])
        suggestions = data.get("suggestions", [])
    except Exception:
        infoboxes = []
        answers = []
        results = []
        suggestions = []

    return render_template(
        "wiki.html",
        query=query,
        infoboxes=infoboxes,
        answers=answers,
        results=results,
        suggestions=suggestions,
    )


@app.route("/images")
def images():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    imgs = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_images(q, page)
            imgs = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(imgs))
        except Exception:
            imgs = []

    return render_template(
        "images.html",
        images=imgs,
        query=q,
        page=page,
        has_next=len(imgs) >= 20,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@app.route("/videos")
def videos():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    vids = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_videos(q, page)
            vids = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(vids))
        except Exception:
            vids = []

    return render_template(
        "videos.html",
        videos=vids,
        query=q,
        page=page,
        has_next=len(vids) >= 10,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@app.route("/news")
def news():
    q = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)

    if page < 1:
        page = 1

    articles = []
    suggestions = []
    corrections = []
    total_results = 0

    if q:
        try:
            data = search_news(q, page)
            articles = data.get("results", [])
            suggestions = data.get("suggestions", [])
            corrections = data.get("corrections", [])
            total_results = data.get("number_of_results", len(articles))
        except Exception:
            articles = []

    return render_template(
        "news.html",
        articles=articles,
        query=q,
        page=page,
        has_next=len(articles) >= 10,
        has_prev=page > 1,
        total_results=total_results,
        suggestions=suggestions,
        corrections=corrections,
    )


@app.route("/placeholder")
def placeholder():
    q = request.args.get("q", "")
    if not q:
        return render_template("placeholder.html")

    fallback = os.path.join("static", "not-found.png")

    try:
        candidates = search_first_image_url(q, count=3)
    except Exception:
        candidates = []

    for url in candidates:
        img_path = install_image(url)
        if img_path and os.path.exists(img_path):
            mime_type, _ = mimetypes.guess_type(img_path)
            return send_file(
                os.path.abspath(img_path),
                mimetype=mime_type or "application/octet-stream",
            )

    return send_file(fallback, mimetype="image/png")


@app.route("/placeholder/url")
def placeholder_url():
    q = request.args.get("q", "")
    if not q:
        return render_template("placeholder.html")

    try:
        urls = search_first_image_url(q, count=1)
        if urls:
            return urls[0]
    except Exception:
        pass

    return os.path.join("static", "not-found.png")


@app.route("/aaaa")
def aaaa():
    return "HELLO, WORLD"


# — Additional routes as requested —
@app.route("/services")
def services():
    return render_template("services.html")


@app.route("/urls")
def list_urls():
    links = []
    for rule in app.url_map.iter_rules():
        # Skip static files if not needed
        if rule.endpoint == "static":
            continue
        url = str(rule)
        methods = ", ".join((rule.methods or set()) - {"HEAD", "OPTIONS"})
        links.append((url, methods))

    # Render with inline HTML (or use a Jinja template instead)
    return render_template("urls.html", links=sorted(links))


@app.route("/faq")
def faq():
    return render_template("faq.html")


@app.route("/blog/<blog>")
def blogs(blog):
    # Prevent path traversal: only allow alphanumeric, hyphens, and underscores
    if not re.match(r"^[a-zA-Z0-9_-]+$", blog):
        abort(404)
    return render_template(f"blogs/{blog}.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/services/ai")
def services_ai():
    return render_template("ai.html")


@app.route("/services/software")
def services_software():
    return render_template("software.html")


@app.route("/services/sodium")
def services_sodium():
    return render_template("sodium.html")


@app.route("/services/webs")
def services_webs():
    return render_template("webs.html")


@app.route("/services/projects")
def services_projects():
    return render_template("projects.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy-policy")
def privacy():
    return render_template("privacy.html")


@app.route("/funprojects")
def funprojects():
    return render_template("funprojects.html")


@app.route("/apis")
def apis():
    return render_template("apis.html")


@app.route("/apis/root")
def apis_root():
    return render_template("apis_root.html")


@app.route("/apis/search")
def apis_search():
    return render_template("apis_search.html")


@app.route("/apis/ai")
def apis_ai():
    return render_template("apis_ai.html")


@app.route("/apis/images")
def apis_images():
    return render_template("apis_images.html")


@app.route("/apis/placeholder")
def apis_placeholder():
    return render_template("apis_placeholder.html")


@app.route("/apis/wiki")
def apis_wiki():
    return render_template("apis_wiki.html")


@app.route("/apis/routes")
def apis_routes():
    return render_template("apis_routes.html")


@app.route("/robots.txt")
def robots():
    return render_template("robots.txt")


@app.route("/sitemap.xml")
def site():
    return render_template("sitemap.xml")


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        ".", "static/favicon.ico", mimetype="image/vnd.microsoft.icon"
    )


@app.route("/upgrade")
def upgrade():
    return render_template("upgrade.html", stripe_payment_link="#", spots_remaining=100)


@app.route("/fake-sha256")
def fakesha256():
    return render_template("fake-sha256.html")


@app.route("/ads.txt")
def ads_txt():
    return render_template("ads.txt"), 200, {"Content-Type": "text/plain"}


@app.route("/cancel")
def cancel():
    return render_template("cancel.html")


@app.route("/success")
def success():
    return render_template("success.html")


@app.route("/metrics")
def metrics():
    return render_template("metrics.html", data=[])


### ── App Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "false").lower() in ("true", "1", "yes")
    app.run(host="0.0.0.0", port=9999, debug=debug_mode, threaded=True)
