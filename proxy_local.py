#!/usr/bin/env python3
"""
Simple HTTP proxy that forwards requests to Cloudflare Worker proxy.
Run on localhost:8081, set SearXNG proxy to http://localhost:8081.
"""
import sys
import os
from urllib.parse import urlparse, quote
from flask import Flask, request, Response, stream_with_context
import requests

WORKER_URL = os.getenv("PROXY_WORKER_URL", "https://myproxy.abdulhadijunaidahmedkhan.workers.dev").rstrip("/")

app = Flask(__name__)
session = requests.Session()

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "HEAD", "PUT", "DELETE", "PATCH"])
@app.route("/<path:path>", methods=["GET", "POST", "HEAD", "PUT", "DELETE", "PATCH"])
def proxy(path):
    # Build target URL from request
    target_url = request.url.replace(request.host_url, "", 1)
    # Ensure scheme present (if missing, add http)
    if not target_url.startswith(("http://", "https://")):
        # Use request scheme and reconstruct
        target_url = f"{request.scheme}://{target_url}"

    # Convert to Cloudflare Worker proxy URL
    proxied_url = f"{WORKER_URL}/?url={quote(target_url, safe='')}"

    # Forward request
    headers = {key: value for key, value in request.headers if key.lower() not in ("host", "connection")}
    try:
        resp = session.request(
            method=request.method,
            url=proxied_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=30,
        )
    except Exception as e:
        return f"Proxy error: {e}", 502

    # Stream response
    def generate():
        for chunk in resp.iter_content(chunk_size=8192):
            yield chunk

    excluded_headers = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    response_headers = [(name, value) for name, value in resp.raw.headers.items()
                        if name.lower() not in excluded_headers]

    return Response(
        stream_with_context(generate()),
        status=resp.status_code,
        headers=response_headers,
    )

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    print(f"Starting Cloudflare Worker proxy adapter on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
