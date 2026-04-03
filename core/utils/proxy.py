"""
Proxy helper for making HTTP requests through Cloudflare Worker.

This module provides a simple wrapper to route requests through a Cloudflare Worker
proxy to bypass PythonAnywhere whitelist restrictions.

Usage:
    from core.utils.proxy import ProxyClient

    # Initialize with your worker URL
    proxy = ProxyClient("https://your-proxy.workers.dev")

    # Make requests as usual
    response = proxy.get("https://search.brave.com/search?q=python")
    response = proxy.post("https://api.example.com", json={"key": "value"})
"""

from typing import Optional, Dict, Any
from urllib.parse import quote
import requests

_DEFAULT_WORKER_URL = "https://myproxy.abdulhadijunaidahmedkhan.workers.dev"


class ProxyClient:
    """HTTP client that routes requests through Cloudflare Worker proxy."""

    def __init__(self, worker_url: Optional[str] = None):
        """
        Initialize proxy client.

        Args:
            worker_url: Cloudflare Worker URL. If None, uses the project default URL.
        """
        self.worker_url = (worker_url or _DEFAULT_WORKER_URL).strip()
        self.enabled = bool(self.worker_url)

    def _proxy_url(self, target_url: str) -> str:
        """Convert target URL to proxied URL."""
        if not self.enabled:
            return target_url
        return f"{self.worker_url}?url={quote(target_url, safe='')}"

    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Make a GET request through the proxy.

        Args:
            url: Target URL to fetch
            **kwargs: Additional arguments passed to requests.get()

        Returns:
            requests.Response object
        """
        proxied_url = self._proxy_url(url)
        return requests.get(proxied_url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """
        Make a POST request through the proxy.

        Args:
            url: Target URL to post to
            **kwargs: Additional arguments passed to requests.post()

        Returns:
            requests.Response object
        """
        proxied_url = self._proxy_url(url)
        return requests.post(proxied_url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        Make an HTTP request through the proxy.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            url: Target URL
            **kwargs: Additional arguments passed to requests.request()

        Returns:
            requests.Response object
        """
        proxied_url = self._proxy_url(url)
        return requests.request(method, proxied_url, **kwargs)


# Global proxy instance (auto-configured from environment)
proxy = ProxyClient()


# Convenience functions
def get(url: str, **kwargs) -> requests.Response:
    """Make a GET request through the proxy (if configured)."""
    return proxy.get(url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    """Make a POST request through the proxy (if configured)."""
    return proxy.post(url, **kwargs)


def request(method: str, url: str, **kwargs) -> requests.Response:
    """Make an HTTP request through the proxy (if configured)."""
    return proxy.request(method, url, **kwargs)
