"""AI routes: legacy /ai endpoint and OpenAI SDK-compatible /v1/* endpoints."""

import json
import subprocess
import sys
import time
import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

from core.services.ai_client import (
    _ALLOWED_AI_PARAMS,
    _ALLOWED_COMPLETIONS_PARAMS,
    _AVAILABLE_MODELS,
    DEFAULT_MODEL,
    _get_client_and_model,
    openai_error,
)

ai_bp = Blueprint("ai", __name__)


# Parameters we are confident every OpenAI-compatible backend accepts.  When a
# framework sends extra params (response_format, tools, seed, ...) that the
# upstream rejects, we retry once with only these so the call still succeeds.
_CORE_COMPLETION_PARAMS = {"model", "messages", "stream", "max_tokens", "temperature", "top_p"}


def _usage_dict(usage) -> dict:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(usage, "total_tokens", 0) or 0,
    }


def _create_with_fallback(client, params: dict):
    """Call chat.completions.create with two safety nets.

    1) If the upstream rejects extra params (response_format, tools, seed, ...),
       retry once with only the core params so framework calls still succeed.
    2) beam is a reasoning model: small max_tokens can be burned on reasoning,
       yielding empty content with finish_reason="length". Retry with a larger
       budget when that happens.
    """
    try:
        try:
            resp = client.chat.completions.create(**params)
        except Exception as first_err:
            slim = {k: v for k, v in params.items() if k in _CORE_COMPLETION_PARAMS}
            if slim == params:
                raise
            try:
                resp = client.chat.completions.create(**slim)
            except Exception:
                raise first_err
    except Exception:
        raise

    try:
        choice = resp.choices[0]
        content = getattr(choice.message, "content", None) or ""
        if not content.strip() and choice.finish_reason == "length":
            cur = int(params.get("max_tokens") or params.get("max_completion_tokens") or 1024)
            bigger = min(max(cur * 4, 512), 4096)
            if bigger > cur:
                p2 = dict(params)
                if "max_tokens" in p2:
                    p2["max_tokens"] = bigger
                if "max_completion_tokens" in p2:
                    p2["max_completion_tokens"] = bigger
                resp2 = client.chat.completions.create(**p2)
                c2 = resp2.choices[0]
                if ((getattr(c2.message, "content", None) or "").strip()):
                    return resp2
    except Exception:
        pass
    return resp


def _chunk_to_payload(chunk, completion_id: str, created: int, model: str) -> dict:
    delta = {}
    finish_reason = None
    if chunk.choices:
        c = chunk.choices[0]
        if c.delta.role:
            delta["role"] = c.delta.role
        if c.delta.content:
            delta["content"] = c.delta.content
        if c.delta.tool_calls:
            delta["tool_calls"] = [
                {
                    "index": tc.index,
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name if tc.function else "",
                        "arguments": tc.function.arguments if tc.function else "",
                    },
                }
                for tc in c.delta.tool_calls
            ]
        finish_reason = c.finish_reason
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }

# ---------------------------------------------------------------------------
# Built-in tools for the agentic endpoint
# ---------------------------------------------------------------------------

_BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current information on a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "page": {
                        "type": "integer",
                        "description": "Page number (default 1)",
                        "default": 1,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wiki_lookup",
            "description": "Look up factual information from Wikipedia.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Topic to look up"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_search",
            "description": "Search for recent news articles on a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "News search query"},
                    "page": {
                        "type": "integer",
                        "description": "Page number (default 1)",
                        "default": 1,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": (
                "Execute Python code and return the output. "
                "Use this whenever the user asks you to run, execute, or test code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to run"},
                },
                "required": ["code"],
            },
        },
    },
]


def _execute_tool(name: str, arguments_json: str) -> str:
    """Execute a built-in tool and return its result as a plain string."""
    from search.results import search_news, search_web, search_wiki

    try:
        args = json.loads(arguments_json)
    except Exception:
        return "Error: invalid tool arguments"

    if name == "web_search":
        data = search_web(args.get("query", ""), args.get("page", 1))
        results = data.get("results", [])[:5]
        if not results:
            return "No results found."
        return "\n\n".join(
            f"{r['title']}\n{r['description']}\n{r['link']}" for r in results
        )

    if name == "wiki_lookup":
        data = search_wiki(args.get("query", ""))
        boxes = data.get("infoboxes", [])
        if boxes:
            b = boxes[0]
            return f"{b.get('infobox', '')}: {b.get('content', '')}"
        results = data.get("results", [])[:3]
        if results:
            return "\n".join(f"{r['title']}: {r['description']}" for r in results)
        return "No information found."

    if name == "news_search":
        data = search_news(args.get("query", ""), args.get("page", 1))
        results = data.get("results", [])[:5]
        if not results:
            return "No news found."
        return "\n\n".join(
            f"{r['title']} ({r.get('publishedDate', '')})\n{r['description']}\n{r['link']}"
            for r in results
        )

    if name == "run_python":
        code = args.get("code", "")
        if not code.strip():
            return "Error: no code provided"
        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=10,
            )
            output = result.stdout + result.stderr
            # Truncate to avoid huge responses
            if len(output) > 4000:
                output = output[:4000] + "\n[output truncated]"
            return output if output.strip() else "(no output)"
        except subprocess.TimeoutExpired:
            return "Error: execution timed out (10s limit)"
        except Exception as e:
            return f"Error: {e}"

    return f"Unknown tool: {name}"


@ai_bp.route("/ai", methods=["GET", "POST"])
def query_ai():
    # TODO: Add rate limiting (e.g., Flask-Limiter) to prevent API abuse
    query = request.args.get("query", "").strip()
    other_params = request.get_json(silent=True) or {}

    if not query and "messages" not in other_params:
        return jsonify({"error": "No query or messages provided"}), 400

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

    if not isinstance(safe_params.get("messages"), list):
        return jsonify({"error": "Invalid messages format"}), 400

    for msg in safe_params["messages"]:
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            return jsonify({"error": "Invalid message structure"}), 400
        if msg["role"] not in ("system", "user", "assistant"):
            return jsonify({"error": "Invalid message role"}), 400

    try:
        use_client, use_model = _get_client_and_model(safe_params.get("model", DEFAULT_MODEL))
        safe_params["model"] = use_model
        response = use_client.chat.completions.create(**safe_params)
        answer = response.choices[0].message.content
        return jsonify({"answer": answer})
    except Exception:
        return jsonify({"error": "AI service temporarily unavailable"}), 500


# ---------------------------------------------------------------------------
# OpenAI SDK-compatible API  (/v1/...)
# Point the OpenAI SDK at this server:  OpenAI(base_url="https://sodeom.com/v1", api_key="any")
# ---------------------------------------------------------------------------


@ai_bp.route("/v1/models", methods=["GET"])
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


@ai_bp.route("/v1/models/<path:model_id>", methods=["GET"])
def v1_model(model_id):
    # Unknown model IDs are aliased to the configured default model instead of
    # returning an error; /v1 only serves the configured model.
    resolved = model_id if model_id in _AVAILABLE_MODELS else DEFAULT_MODEL
    return jsonify(
        {
            "id": resolved,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "sodeom",
        }
    )


@ai_bp.route("/v1/chat/completions", methods=["POST"])
def v1_chat_completions():
    body = request.get_json(silent=True) or {}

    safe_params = {k: v for k, v in body.items() if k in _ALLOWED_COMPLETIONS_PARAMS}

    if "model" not in safe_params:
        safe_params["model"] = DEFAULT_MODEL

    messages = safe_params.get("messages")
    if not isinstance(messages, list) or not messages:
        return openai_error("messages must be a non-empty array", param="messages")

    for msg in messages:
        if not isinstance(msg, dict) or "role" not in msg:
            return openai_error("Each message must have a 'role' field")
        role = msg["role"]
        if role not in ("system", "user", "assistant", "tool", "function"):
            return openai_error(f"Invalid role: {role}")
        # tool-result messages use tool_call_id instead of content
        if role not in ("tool", "function") and "content" not in msg:
            return openai_error(
                f"Message with role '{role}' must have a 'content' field"
            )

    if "max_tokens" not in safe_params and "max_completion_tokens" not in safe_params:
        safe_params["max_tokens"] = 1024
    # beam is a reasoning model: tiny limits are spent on reasoning and can
    # produce empty content, so enforce a small floor for framework calls.
    for _k in ("max_tokens", "max_completion_tokens"):
        if isinstance(safe_params.get(_k), int) and safe_params[_k] < 128:
            safe_params[_k] = 128

    # Frameworks (LangChain, LangGraph, LlamaIndex, ...) send stream_options.
    # Keep it local: never forward it upstream.
    stream_options = body.get("stream_options")
    if not isinstance(stream_options, dict):
        stream_options = {}
    include_usage = bool(stream_options.get("include_usage"))

    want_stream = bool(body.get("stream", False))
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = safe_params["model"]
    use_client, use_model = _get_client_and_model(model)
    model = use_model
    safe_params["model"] = use_model

    if want_stream:

        def _iter_payloads(params: dict):
            params = {**params, "stream": True}
            emitted = False
            last_usage = None
            try:
                stream = use_client.chat.completions.create(**params)
                for chunk in stream:
                    emitted = True
                    if getattr(chunk, "usage", None):
                        last_usage = chunk.usage
                    yield _chunk_to_payload(chunk, completion_id, created, model)
            except Exception:
                if emitted:
                    raise
                slim = {k: v for k, v in params.items() if k in _CORE_COMPLETION_PARAMS}
                if slim == params:
                    raise
                stream = use_client.chat.completions.create(**slim)
                for chunk in stream:
                    emitted = True
                    if getattr(chunk, "usage", None):
                        last_usage = chunk.usage
                    yield _chunk_to_payload(chunk, completion_id, created, model)
            if include_usage:
                yield {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": _usage_dict(last_usage),
                }

        def _generate():
            try:
                for payload in _iter_payloads(safe_params):
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
                yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        resp = _create_with_fallback(use_client, safe_params)
    except Exception:
        return openai_error("AI service temporarily unavailable", "server_error", 500)

    choice = resp.choices[0]
    usage = resp.usage
    msg = choice.message
    message_out = {
        "role": "assistant",
        "content": msg.content,
    }
    # Pass through tool_calls if the model wants to call a function
    if msg.tool_calls:
        message_out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return jsonify(
        {
            "id": completion_id,
            "object": "chat.completions",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message_out,
                    "finish_reason": choice.finish_reason or "stop",
                }
            ],
            "usage": _usage_dict(usage),
        }
    )


# ---------------------------------------------------------------------------
# Legacy /v1/completions (older SDKs & frameworks still call this)
# ---------------------------------------------------------------------------
@ai_bp.route("/v1/completions", methods=["POST"])
def v1_completions():
    body = request.get_json(silent=True) or {}

    prompt = body.get("prompt")
    if isinstance(prompt, list):
        prompt = "\n".join(str(p) for p in prompt)
    if not isinstance(prompt, str) or not prompt.strip():
        return openai_error("prompt must be a non-empty string", param="prompt")

    messages = [{"role": "user", "content": prompt}]
    chat_body = {"model": body.get("model", DEFAULT_MODEL), "messages": messages}
    for k in ("temperature", "top_p", "max_tokens", "stop", "n", "seed", "logit_bias", "user"):
        if k in body:
            chat_body[k] = body[k]
    if "max_tokens" not in chat_body:
        chat_body["max_tokens"] = 1024
    if isinstance(chat_body.get("max_tokens"), int) and chat_body["max_tokens"] < 128:
        chat_body["max_tokens"] = 128

    want_stream = bool(body.get("stream", False))
    completion_id = f"cmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    model = chat_body["model"]
    use_client, use_model = _get_client_and_model(model)
    model = use_model
    chat_body["model"] = use_model

    if want_stream:

        def _generate():
            try:
                stream = use_client.chat.completions.create(**{**chat_body, "stream": True})
                for chunk in stream:
                    text = ""
                    finish = None
                    if chunk.choices:
                        c = chunk.choices[0]
                        if c.delta and c.delta.content:
                            text = c.delta.content
                        finish = c.finish_reason
                    payload = {
                        "id": completion_id,
                        "object": "text_completion",
                        "created": created,
                        "model": model,
                        "choices": [
                            {"text": text, "index": 0, "logprobs": None, "finish_reason": finish}
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
                yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(_generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    try:
        resp = _create_with_fallback(use_client, chat_body)
    except Exception:
        return openai_error("AI service temporarily unavailable", "server_error", 500)

    choice = resp.choices[0]
    return jsonify(
        {
            "id": completion_id,
            "object": "text_completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "text": choice.message.content or "",
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": choice.finish_reason or "stop",
                }
            ],
            "usage": _usage_dict(resp.usage),
        }
    )


@ai_bp.route("/v1/embeddings", methods=["POST"])
def v1_embeddings():
    # This deployment serves a chat model only. Return a proper OpenAI-shaped
    # error so frameworks fail loudly instead of hanging.
    return openai_error(
        "Embeddings are not supported by this deployment",
        "unsupported",
        501,
    )


# ---------------------------------------------------------------------------
# Agentic endpoint — built-in search tools with automatic tool-call loop
# POST /ai/agent
# Body: { "query": "...", "model": "...", "max_steps": 5 }
#    or: { "messages": [...], "model": "...", "max_steps": 5 }
# Response: { "answer": "...", "messages": [...], "steps": N }
# ---------------------------------------------------------------------------


@ai_bp.route("/ai/agent", methods=["POST"])
def ai_agent():
    body = request.get_json(silent=True) or {}
    model = body.get("model", DEFAULT_MODEL)
    max_steps = min(int(body.get("max_steps", 5)), 10)
    use_client, model = _get_client_and_model(model)

    messages = body.get("messages")
    if not messages:
        query = body.get("query", "").strip()
        if not query:
            return jsonify({"error": "Provide 'query' or 'messages'"}), 400
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a helpful search assistant with access to web search, "
                    "Wikipedia, and news tools. Use them to give accurate, up-to-date answers."
                ),
            },
            {"role": "user", "content": query},
        ]
    else:
        if not isinstance(messages, list) or not messages:
            return jsonify({"error": "'messages' must be a non-empty array"}), 400
        messages = list(messages)  # copy so we can append

    for step in range(max_steps):
        try:
            resp = use_client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_BUILTIN_TOOLS,
                tool_choice="auto",
                max_tokens=1024,
            )
        except Exception:
            return jsonify({"error": "AI service temporarily unavailable"}), 500

        choice = resp.choices[0]
        msg = choice.message

        # Add assistant turn (may contain tool_calls)
        assistant_turn = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_turn["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_turn)

        if choice.finish_reason == "stop" or not msg.tool_calls:
            return jsonify(
                {"answer": msg.content or "", "messages": messages, "steps": step + 1}
            )

        # Execute every tool call and add results
        for tc in msg.tool_calls:
            result = _execute_tool(tc.function.name, tc.function.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                }
            )

    # Ran out of steps — return last assistant content
    last = next((m for m in reversed(messages) if m.get("role") == "assistant"), None)
    return jsonify(
        {
            "answer": last.get("content", "") if last else "",
            "messages": messages,
            "steps": max_steps,
        }
    )
