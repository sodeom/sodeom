"""OpenAI-compatible client, model constants, and error helper."""

import os
import time

from flask import jsonify
from openai import OpenAI

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_ENDPOINT = "https://api.mistral.ai/v1"

OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_ENDPOINT = "https://opencode.ai/zen/v1"

if MISTRAL_API_KEY:
    _DEFAULT_MODEL = "mistral-small-latest"
elif GITHUB_TOKEN:
    _DEFAULT_MODEL = "gpt-4o-mini"
else:
    _DEFAULT_MODEL = "mistral-small-latest"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", _DEFAULT_MODEL)

if MISTRAL_API_KEY:
    client = OpenAI(base_url=MISTRAL_ENDPOINT, api_key=MISTRAL_API_KEY)
elif GITHUB_TOKEN:
    client = OpenAI(base_url=GITHUB_ENDPOINT, api_key=GITHUB_TOKEN)
else:
    client = None

# Allowed parameters for the legacy /ai endpoint
_ALLOWED_AI_PARAMS = {"model", "messages", "temperature", "max_tokens", "top_p"}

# Models exposed through /v1/models
_AVAILABLE_MODELS = [
    "gpt-4o-mini",
    "gpt-4o",
    "o1-mini",
    "Meta-Llama-3.1-8B-Instruct",
    "Meta-Llama-3.1-70B-Instruct",
    "Mistral-small",
    "Phi-3.5-mini-instruct",
    "mistral-small-latest",
    "mistral-medium-latest",
    "mistral-large-latest",
    "mistral-tiny-latest",
    "open-mistral-7b",
    "open-mixtral-8x7b",
    "open-mixtral-8x22b",
    "codestral-latest",
    "mistral-saba-latest",
    # OpenCode free models
    "deepseek-v4-flash-free",
    "big-pickle",
    "ling-3.0-flash-free",
    "nemotron-3-ultra-free",
    "laguna-s-2.1-free",
]

# Models that route through OpenCode instead of Mistral
_OPENCODE_MODELS = {
    "deepseek-v4-flash-free", "big-pickle", "ling-3.0-flash-free",
    "nemotron-3-ultra-free", "laguna-s-2.1-free",
}


def _get_client_and_model(model: str):
    """Return the right client and resolved model name for the given model."""
    if model in _OPENCODE_MODELS:
        if not OPENCODE_API_KEY:
            return None, model
        return OpenAI(base_url=OPENCODE_ENDPOINT, api_key=OPENCODE_API_KEY), model
    return client, model

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
    "tools",
    "tool_choice",
    "parallel_tool_calls",
}


def openai_error(
    message: str,
    err_type: str = "invalid_request_error",
    status: int = 400,
    param: str = None,
):
    """Return a JSON error response in the OpenAI error format."""
    return (
        jsonify(
            {
                "error": {
                    "message": message,
                    "type": err_type,
                    "param": param,
                    "code": None,
                }
            }
        ),
        status,
    )
