#!/usr/bin/env python3
"""
Simple HTTP proxy server that forwards to Cloudflare Worker proxy.
Uses http.server and requests.
"""
import os
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, quote
import requests

WORKER_URL = os.getenv("PROXY_WORKER_URL", "https://myproxy.abdulhadijunaidahmedkhan.workers.dev").rstrip("/")

class ProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._proxy_request()

    def do_POST(self):
        self._proxy_request()

    def do_HEAD(self):
        self._proxy_request()

    def do_PUT(self):
        self._proxy_request()

    def do_DELETE(self):
        self._proxy_request()

    def do_PATCH(self):
        self._proxy_request()

    def _proxy_request(self):
        # Determine target URL
        print(f"[Proxy] Request: {self.command} {self.path}")
        
        # For absolute URL in path (SearXNG uses http://...)
        if self.path.startswith('http://') or self.path.startswith('https://'):
            target = self.path
        else:
            # Assume http with host header
            target = f"http://{self.headers.get('Host', 'localhost')}{self.path}"

        # Convert to Cloudflare Worker URL
        proxied = f"{WORKER_URL}/?url={quote(target, safe='')}"

        # Prepare headers
        headers = {}
        for key, value in self.headers.items():
            if key.lower() not in ('host', 'connection', 'content-length'):
                headers[key] = value

        # Read request body if present
        content_length = self.headers.get('Content-Length')
        data = None
        if content_length:
            data = self.rfile.read(int(content_length))

        try:
            resp = requests.request(
                method=self.command,
                url=proxied,
                headers=headers,
                data=data,
                timeout=30,
                stream=True,
                allow_redirects=False
            )
        except Exception as e:
            self.send_error(502, f"Proxy error: {e}")
            return

        # Send response
        self.send_response(resp.status_code)
        for key, value in resp.headers.items():
            if key.lower() not in ('transfer-encoding', 'connection', 'content-encoding'):
                self.send_header(key, value)
        self.end_headers()

        # Stream body
        for chunk in resp.iter_content(chunk_size=8192):
            self.wfile.write(chunk)

    def log_message(self, format, *args):
        # Quiet logging
        pass

def run_server(host='127.0.0.1', port=8081):
    server = HTTPServer((host, port), ProxyHandler)
    print(f"Proxy server running on http://{host}:{port}")
    server.serve_forever()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8081)
    args = parser.parse_args()
    run_server(args.host, args.port)
