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
    client,
    openai_error,
)

ai_bp = Blueprint("ai", __name__)

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
        response = client.chat.completions.create(**safe_params)
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
    if model_id not in _AVAILABLE_MODELS:
        return openai_error(
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
                        # Pass through tool_calls deltas
                        if c.delta.tool_calls:
                            delta["tool_calls"] = [
                                {
                                    "index": tc.index,
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name if tc.function else "",
                                        "arguments": tc.function.arguments
                                        if tc.function
                                        else "",
                                    },
                                }
                                for tc in c.delta.tool_calls
                            ]
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

    try:
        resp = client.chat.completions.create(**safe_params)
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
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": message_out,
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
        return openai_error("AI service temporarily unavailable", "server_error", 500)


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
            resp = client.chat.completions.create(
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
