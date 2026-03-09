"""AI routes: legacy /ai endpoint and OpenAI SDK-compatible /v1/* endpoints."""

import json
import time
import uuid

from flask import Blueprint, Response, jsonify, request, stream_with_context

from app.services.ai_client import (
    _ALLOWED_AI_PARAMS,
    _ALLOWED_COMPLETIONS_PARAMS,
    _AVAILABLE_MODELS,
    DEFAULT_MODEL,
    client,
    openai_error,
)

ai_bp = Blueprint("ai", __name__)


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
        if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
            return openai_error("Each message must have 'role' and 'content' fields")
        if msg["role"] not in ("system", "user", "assistant", "tool", "function"):
            return openai_error(f"Invalid role: {msg['role']}")

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
        return openai_error("AI service temporarily unavailable", "server_error", 500)
