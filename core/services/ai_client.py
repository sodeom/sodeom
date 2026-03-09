"""OpenAI client, model constants, and error helper."""

import os
import time

from flask import jsonify
from openai import OpenAI

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_ENDPOINT = "https://models.github.ai/inference"
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")

client = OpenAI(base_url=GITHUB_ENDPOINT, api_key=GITHUB_TOKEN)

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
