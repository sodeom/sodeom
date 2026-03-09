"""SearXNG subprocess lifecycle manager."""

import atexit
import os
import socket
import subprocess
import time

# Project root: three levels up from app/services/searxng.py
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SEARXNG_SETTINGS = os.path.join(_ROOT, "searxng_src", "settings_local.yml")
_SEARXNG_PYTHON = os.path.join(_ROOT, ".venv", "bin", "python")

_SEARXNG_PROC = None


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """Return True if something is already listening on host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_searxng() -> None:
    """Start SearXNG as a background subprocess if not already running."""
    global _SEARXNG_PROC

    if _port_open("127.0.0.1", 8888):
        print("[SearXNG] Already running on port 8888")
        return

    if not os.path.exists(_SEARXNG_PYTHON):
        print(f"[SearXNG] Python not found at {_SEARXNG_PYTHON} — skipping local start")
        return

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
            if _port_open("127.0.0.1", 8888):
                print(f"[SearXNG] Ready after {i + 1}s")
                return
        print("[SearXNG] Warning: instance did not open port 8888 within 60s")
    except Exception as e:
        print(f"[SearXNG] Failed to start: {e}")


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
