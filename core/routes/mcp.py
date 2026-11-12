"""Public, keyless MCP (Model Context Protocol) server for Sodeom.

Implements the Streamable HTTP transport at ``/mcp`` so any MCP-capable agent
(Claude Desktop / Claude Code, OpenCode, LangChain MCP adapters, custom bots)
can search the web through Sodeom without an API key.

Design notes
------------
* No authentication: the endpoint is intentionally public and read-only.
* JSON-RPC 2.0 only. ``POST`` carries one message or a batch; the response is
  plain JSON (``text/event-stream`` is not needed because we never push
  server-initiated messages). ``GET`` therefore answers 405, which the spec
  explicitly allows for servers without a server-push channel.
* ``Mcp-Session-Id`` is issued on ``initialize`` and echoed back when the
  client sends it, but it is not enforced — stateless clients work too.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import uuid

import requests
from flask import Blueprint, Response, jsonify, request

from search.results import (
    search_images,
    search_news,
    search_videos,
    search_web,
    search_wiki,
)

mcp_bp = Blueprint("mcp", __name__)

SERVER_NAME = "sodeom"
SERVER_TITLE = "Sodeom Search"
SERVER_VERSION = "1.0.0"

# Newest first. The client's requested version wins when we know it,
# otherwise we answer with the newest one we speak.
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL = SUPPORTED_PROTOCOLS[0]

MAX_FETCH_BYTES = 500_000
MAX_TOOL_CHARS = 12_000
MAX_PAGE_CHARS = 8_000

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SodeomMCP/1.0"
)

INSTRUCTIONS = (
    "Sodeom is a privacy-first meta search engine. Use the `search` tool for "
    "web results, `search_news` / `search_videos` / `search_images` for other "
    "verticals, `wiki` for quick facts, and `fetch_url` to read a page you "
    "found. Results are plain text lists of title / URL / snippet. No API key "
    "is required."
)


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------


def _result(msg_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _clip(text, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clip_block(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[output truncated]"


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_QUERY_PROP = {
    "type": "string",
    "description": "The search query.",
}
_PAGE_PROP = {
    "type": "integer",
    "description": "Results page, 1-based (default 1).",
    "minimum": 1,
    "maximum": 50,
}
_LANG_PROP = {
    "type": "string",
    "description": "Language code, e.g. 'en', 'fr', 'de' (default 'en').",
}

TOOLS = [
    {
        "name": "search",
        "title": "Web search",
        "description": (
            "Search the web with Sodeom (SearXNG meta search + Bing/Brave "
            "fallbacks). Returns up to 10 results as numbered title / URL / "
            "snippet lines, plus answers and spelling suggestions when "
            "available. Use `fetch_url` afterwards to read a page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _QUERY_PROP,
                "page": _PAGE_PROP,
                "language": _LANG_PROP,
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "search_news",
        "title": "News search",
        "description": "Search recent news articles. Same text output shape as `search`.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _QUERY_PROP,
                "page": _PAGE_PROP,
                "language": _LANG_PROP,
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "search_videos",
        "title": "Video search",
        "description": "Search for videos (mostly YouTube). Returns title / URL / snippet lines.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _QUERY_PROP,
                "page": _PAGE_PROP,
                "language": _LANG_PROP,
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "search_images",
        "title": "Image search",
        "description": (
            "Search for images. Each result includes the direct image URL "
            "(`img_src`) plus the page URL, useful when the user asks for a "
            "picture of something."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": _QUERY_PROP,
                "page": _PAGE_PROP,
                "language": _LANG_PROP,
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "wiki",
        "title": "Wikipedia / knowledge lookup",
        "description": (
            "Quick factual lookup from Wikipedia and Wikidata: infobox, "
            "one-line answer and a few reference links."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": _QUERY_PROP, "language": _LANG_PROP},
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "fetch_url",
        "title": "Read a web page",
        "description": (
            "Download a public http(s) page and return its readable text "
            "(scripts and styles stripped), truncated to 8000 characters. "
            "Use it to read search results in depth. Private / internal "
            "addresses are refused."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Absolute http:// or https:// URL to read.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters of text to return (default 8000).",
                    "minimum": 500,
                    "maximum": 20000,
                },
            },
            "required": ["url"],
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
]


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------


def _format_results(data: dict) -> str:
    lines: list[str] = []

    for ans in (data.get("answers") or [])[:3]:
        lines.append(f"Answer: {_clip(ans, 500)}")

    for ib in (data.get("infoboxes") or [])[:2]:
        title = _clip(ib.get("title", ""), 120)
        content = _clip(ib.get("content", "") or ib.get("answer", ""), 500)
        if title or content:
            lines.append(f"{title}: {content}".strip(": "))

    results = data.get("results") or []
    if not results:
        lines.append("No results found.")
    for i, r in enumerate(results[:10], 1):
        title = _clip(r.get("title", ""), 200)
        link = str(r.get("link", "") or "")
        snippet = _clip(r.get("description", ""), 300)
        lines.append(f"{i}. {title}\n   URL: {link}")
        if snippet:
            lines.append(f"   {snippet}")

    corrections = data.get("corrections") or []
    if corrections:
        lines.append("Spelling corrections: " + ", ".join(str(c) for c in corrections[:3]))
    suggestions = data.get("suggestions") or []
    if suggestions:
        lines.append("Related searches: " + ", ".join(str(s) for s in suggestions[:5]))

    return "\n".join(lines)


def _format_images(data: dict) -> str:
    results = data.get("results") or []
    if not results:
        return "No images found."
    lines = []
    for i, r in enumerate(results[:10], 1):
        title = _clip(r.get("title", ""), 160)
        img = str(r.get("img_src", "") or r.get("thumbnail", "") or "")
        page = str(r.get("link", "") or "")
        lines.append(f"{i}. {title}\n   Image: {img}\n   Page: {page}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _require_query(args: dict) -> str:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("'query' must be a non-empty string")
    return query.strip()


def _page(args: dict) -> int:
    try:
        page = int(args.get("page", 1) or 1)
    except (TypeError, ValueError):
        page = 1
    return max(1, min(page, 50))


def _language(args: dict) -> str:
    lang = args.get("language")
    if not isinstance(lang, str) or not lang.strip():
        return "en"
    return lang.strip()[:12]


def _tool_search(args: dict) -> str:
    return _format_results(search_web(_require_query(args), _page(args), _language(args)))


def _tool_news(args: dict) -> str:
    return _format_results(search_news(_require_query(args), _page(args), _language(args)))


def _tool_videos(args: dict) -> str:
    return _format_results(search_videos(_require_query(args), _page(args), _language(args)))


def _tool_images(args: dict) -> str:
    return _format_images(search_images(_require_query(args), _page(args), _language(args)))


def _tool_wiki(args: dict) -> str:
    return _format_results(search_wiki(_require_query(args), _language(args)))


def _host_is_public(host: str) -> bool:
    """SSRF guard: resolve the host and reject anything non-global."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def _check_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("'url' must be a non-empty string")
    url = url.strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ValueError("'url' must start with http:// or https://")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError("'url' has no host")
    if not _host_is_public(parsed.hostname):
        raise ValueError("Refusing to fetch a private or internal address")
    return url


def _html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "form"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    except Exception:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _tool_fetch(args: dict) -> str:
    url = _check_url(args.get("url"))
    try:
        max_chars = int(args.get("max_chars", MAX_PAGE_CHARS) or MAX_PAGE_CHARS)
    except (TypeError, ValueError):
        max_chars = MAX_PAGE_CHARS
    max_chars = max(500, min(max_chars, 20_000))

    resp = requests.get(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/html,text/plain,*/*"},
        timeout=12,
        allow_redirects=True,
    )
    # Redirects can bounce us somewhere internal — re-check the final URL.
    _check_url(resp.url)
    resp.raise_for_status()

    raw = resp.content[:MAX_FETCH_BYTES]
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "html" in ctype or raw[:512].lstrip().lower().startswith((b"<!doctype", b"<html")):
        text = _html_to_text(raw.decode(resp.encoding or "utf-8", errors="replace"))
    else:
        text = raw.decode(resp.encoding or "utf-8", errors="replace").strip()

    if not text:
        raise ValueError("The page had no readable text")

    header = f"URL: {resp.url}\nTitle: {_clip(resp.headers.get('X-Title', ''), 200)}\n\n"
    body = text[:max_chars]
    if len(text) > max_chars:
        body += "\n\n[truncated]"
    return header + body


TOOL_EXECUTORS = {
    "search": _tool_search,
    "search_news": _tool_news,
    "search_videos": _tool_videos,
    "search_images": _tool_images,
    "wiki": _tool_wiki,
    "fetch_url": _tool_fetch,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------


def _handle_initialize(params: dict) -> dict:
    requested = params.get("protocolVersion")
    protocol = requested if requested in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
    return {
        "protocolVersion": protocol,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": SERVER_VERSION},
        "instructions": INSTRUCTIONS,
    }


def _handle_tools_call(params: dict) -> "tuple[str, dict]":
    """Return ("result", result) or ("error", error_payload) for tools/call."""
    name = params.get("name")
    if not isinstance(name, str) or name not in TOOL_EXECUTORS:
        return "error", {"code": -32602, "message": f"Unknown tool: {name}"}
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return "error", {"code": -32602, "message": "'arguments' must be an object"}
    try:
        text = TOOL_EXECUTORS[name](args)
    except ValueError as exc:
        # Bad arguments are a protocol-level problem, not a tool failure.
        return "error", {"code": -32602, "message": str(exc)}
    except Exception as exc:  # network / upstream trouble
        return "result", {
            "content": [
                {"type": "text", "text": f"{name} failed: {type(exc).__name__}: {exc}"}
            ],
            "isError": True,
        }
    return "result", {
        "content": [{"type": "text", "text": _clip_block(text)}],
        "isError": False,
    }


def _handle_message(msg) -> "dict | None":
    """Handle one JSON-RPC message. Returns None for notifications."""
    if not isinstance(msg, dict):
        return _error(None, -32600, "Invalid Request")

    method = msg.get("method")
    msg_id = msg.get("id")
    is_notification = "id" not in msg

    if not isinstance(method, str):
        return _error(msg_id, -32600, "Invalid Request")

    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _error(msg_id, -32602, "'params' must be an object")

    if method == "initialize":
        return _result(msg_id, _handle_initialize(params))

    if method.startswith("notifications/"):
        return None

    if method == "ping":
        return _result(msg_id, {})

    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})

    if method == "tools/call":
        kind, payload = _handle_tools_call(params)
        if kind == "error":
            return _error(msg_id, payload["code"], payload["message"])
        return _result(msg_id, payload)

    if is_notification:
        return None
    return _error(msg_id, -32601, f"Method not found: {method}")


def _json_response(payload, status: int = 200, headers: dict | None = None) -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Expose-Headers"] = "Mcp-Session-Id"
    if headers:
        for key, value in headers.items():
            resp.headers[key] = value
    return resp


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@mcp_bp.route("/mcp", methods=["POST", "GET", "DELETE", "OPTIONS"])
@mcp_bp.route("/mcp/", methods=["POST", "GET", "DELETE", "OPTIONS"])
def mcp_endpoint():
    if request.method == "OPTIONS":
        resp = Response(status=204)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "POST, GET, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = (
            "Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version, Last-Event-ID"
        )
        resp.headers["Access-Control-Max-Age"] = "86400"
        return resp

    if request.method == "GET":
        # No server-push channel: the spec allows 405 here.
        return _json_response(
            {"error": "This MCP server has no server-initiated stream; use POST."},
            405,
            {"Allow": "POST, DELETE, OPTIONS"},
        )

    if request.method == "DELETE":
        if request.headers.get("Mcp-Session-Id"):
            return Response(status=200)
        return _json_response({"error": "No Mcp-Session-Id header"}, 400)

    body = request.get_data(as_text=True) or ""
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return _json_response(_error(None, -32700, "Parse error"), 400)

    is_batch = isinstance(payload, list)
    if is_batch:
        if not payload:
            return _json_response(_error(None, -32600, "Invalid Request"), 400)
        messages = payload
    else:
        messages = [payload]

    responses = [r for r in (_handle_message(m) for m in messages) if r is not None]

    # Issue (and accept) a session id, but never require it.
    session_headers = {}
    if any(isinstance(m, dict) and m.get("method") == "initialize" for m in messages):
        session_headers["Mcp-Session-Id"] = str(uuid.uuid4())

    if not responses:
        return Response(status=202, headers={"Access-Control-Allow-Origin": "*"})

    if is_batch:
        return _json_response(responses, 200, session_headers)
    return _json_response(responses[0], 200, session_headers)


@mcp_bp.route("/.well-known/mcp.json", methods=["GET"])
@mcp_bp.route("/.well-known/mcp", methods=["GET"])
def mcp_discovery():
    """Open Discovery-style descriptor so agents can find the endpoint."""
    root = request.host_url.rstrip("/")
    return _json_response(
        {
            "name": SERVER_TITLE,
            "description": "Privacy-first web search for AI agents. No API key.",
            "version": SERVER_VERSION,
            "protocolVersion": LATEST_PROTOCOL,
            "endpoints": {"mcp": f"{root}/mcp"},
            "website": f"{root}/apis/mcp",
        }
    )
