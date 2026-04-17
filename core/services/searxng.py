"""SearXNG subprocess lifecycle manager."""

import atexit
import os
import socket
import subprocess
import threading
import time
import sys

import requests

# Project root: three levels up from app/services/searxng.py
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SEARXNG_SETTINGS = os.path.join(_ROOT, "searxng_src", "settings_local.yml")


def _find_searxng_python():
    """Find a Python interpreter that can launch the vendored SearXNG app."""

    explicit_python = os.getenv("SEARXNG_PYTHON", "").strip()
    if explicit_python:
        return explicit_python

    current = _ROOT
    for _ in range(5):  # Check up to 5 parent directories
        venv_python = os.path.join(current, ".venv", "bin", "python")
        if os.path.exists(venv_python):
            return venv_python
        parent = os.path.dirname(current)
        if parent == current:  # Reached filesystem root
            break
        current = parent
    if sys.executable:
        return sys.executable

    return None


_SEARXNG_PYTHON = _find_searxng_python()

_SEARXNG_PROC = None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _instance_healthy(base_url: str, timeout: float = 1.0) -> bool:
    """Return True when a SearXNG instance responds to a lightweight health check."""
    base_url = base_url.rstrip("/")
    if not base_url:
        return False

    try:
        resp = requests.get(f"{base_url}/healthz", timeout=timeout)
        return resp.status_code in (200, 404)
    except requests.RequestException:
        return False


_PROXY_PROC = None

def _start_proxy_blocking():
    """Start the proxy server that forwards to Cloudflare Worker."""
    global _PROXY_PROC
    import sys
    
    if _port_open("127.0.0.1", 8080, timeout=0.3):
        print("[Proxy] Already running on port 8080")
        return
    
    try:
        _PROXY_PROC = subprocess.Popen(
            [_SEARXNG_PYTHON, "proxy_simple.py", "--port", "8080"],
            cwd=_ROOT,
            stdout=open("/tmp/proxy.log", "a"),
            stderr=subprocess.STDOUT,
        )
        print(f"[Proxy] Started with PID {_PROXY_PROC.pid}")
        
        for i in range(15):
            time.sleep(1)
            if _port_open("127.0.0.1", 8080, timeout=0.3):
                print(f"[Proxy] Ready after {i + 1}s")
                return
        print("[Proxy] Warning: proxy did not start within 15s")
    except Exception as e:
        print(f"[Proxy] Failed to start: {e}")

def _start_searxng_blocking() -> None:
    """Internal: start SearXNG subprocess and wait for it to be ready.
    Runs in a background thread so app startup is never blocked."""
    global _SEARXNG_PROC

    # Start proxy first
    _start_proxy_blocking()
    time.sleep(2)
    
    if _port_open("127.0.0.1", 8888, timeout=0.3):
        print("[SearXNG] Already running on port 8888")
        _start_watchdog()
        return

    if not _SEARXNG_PYTHON or not os.path.exists(_SEARXNG_PYTHON):
        print(
            f"[SearXNG] No usable Python interpreter found (searched from {_ROOT}) — skipping local start"
        )
        return

    print(f"[SearXNG] Using Python at: {_SEARXNG_PYTHON}")

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
            cwd=os.path.join(_ROOT, "searxng_src"),
            env=env,
            stdout=open("/tmp/searxng.log", "a"),
            stderr=subprocess.STDOUT,
        )
        print(f"[SearXNG] Started with PID {_SEARXNG_PROC.pid}")

        for i in range(60):
            time.sleep(1)
            if _port_open("127.0.0.1", 8888, timeout=0.3):
                print(f"[SearXNG] Ready after {i + 1}s")
                _start_watchdog()
                return
        print("[SearXNG] Warning: instance did not open port 8888 within 60s")
    except Exception as e:
        print(f"[SearXNG] Failed to start: {e}")


def start_searxng() -> None:
    """Kick off SearXNG startup in a background thread so it never blocks requests.

    Local SearXNG is preferred by default. Set SEARXNG_DISABLE_LOCAL_START=1
    to skip spawning the local subprocess (for environments that only want
    remote SearXNG instances).
    """
    disable_local = os.getenv("SEARXNG_DISABLE_LOCAL_START", "").strip().lower()
    if disable_local in ("1", "true", "yes", "on"):
        print("[SearXNG] Local subprocess start disabled via SEARXNG_DISABLE_LOCAL_START")
        return

    t = threading.Thread(
        target=_start_searxng_blocking, daemon=True, name="searxng-start"
    )
    t.start()


def _start_watchdog() -> None:
    """Background thread that restarts SearXNG if it dies."""

    def _watch():
        while True:
            time.sleep(15)
            if not _port_open("127.0.0.1", 8888):
                print("[SearXNG] Watchdog: port closed, restarting…")
                start_searxng()

    t = threading.Thread(target=_watch, daemon=True, name="searxng-watchdog")
    t.start()


def stop_searxng() -> None:
    """Terminate the SearXNG subprocess on app shutdown."""
    global _SEARXNG_PROC
    if _SEARXNG_PROC and _SEARXNG_PROC.poll() is None:
        print(f"[SearXNG] Stopping PID {_SEARXNG_PROC.pid}")
        _SEARXNG_PROC.terminate()
        try:
            _SEARXNG_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _SEARXNG_PROC.kill()


atexit.register(stop_searxng)
