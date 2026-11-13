"""
Fast Claude client for the voice assistant.

Why not urllib.urlopen?  Every urlopen() opens a brand-new TCP + TLS connection
to api.anthropic.com (often 150-400 ms before the model even starts). Here a
small pool keeps keep-alive HTTPS connections open and re-uses them, and
`warmup()` opens one in the background as soon as the user says "Hello Ops", so
the first real question does not pay the handshake either.

Standard library only (no new dependency).
"""
from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time

log = logging.getLogger("opsflow.llm")

HOST = "api.anthropic.com"
PATH = "/v1/messages"
_ssl_ctx = ssl.create_default_context()
_IDLE_LIMIT = 45.0   # seconds; servers drop idle keep-alive connections after about a minute
_POOL_MAX = 4

_pool: list[tuple[http.client.HTTPSConnection, float]] = []
_pool_lock = threading.Lock()


def _settings():
    try:
        from .config import settings
        return settings
    except Exception:  # config needs pydantic-settings; unit tests may run without it
        return None


def api_key() -> str:
    s = _settings()
    return (getattr(s, "ANTHROPIC_API_KEY", "") or "") if s else ""


def model() -> str:
    s = _settings()
    return (getattr(s, "VOICE_LLM_MODEL", "") or "claude-haiku-5-5") if s else "claude-haiku-5-5"


def enabled() -> bool:
    return bool(api_key())


def _close(c):
    try:
        c.close()
    except Exception:
        pass


def _acquire(timeout: float) -> http.client.HTTPSConnection:
    now = time.monotonic()
    with _pool_lock:
        while _pool:
            c, last = _pool.pop()
            if now - last < _IDLE_LIMIT and c.sock is not None:
                try:
                    c.sock.settimeout(timeout)
                except Exception:
                    pass
                c.timeout = timeout
                return c
            _close(c)
    return http.client.HTTPSConnection(HOST, timeout=timeout, context=_ssl_ctx)


def _release(c):
    with _pool_lock:
        if len(_pool) < _POOL_MAX and c.sock is not None:
            _pool.append((c, time.monotonic()))
            return
    _close(c)


def call(body: dict, timeout: float = 7.0) -> dict | None:
    """POST /v1/messages and return the parsed JSON, or None on any failure."""
    key = api_key()
    if not key:
        return None
    payload = json.dumps(body).encode()
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json",
               "connection": "keep-alive"}
    for attempt in (1, 2):           # a stale keep-alive socket fails once: reconnect and retry
        c = _acquire(timeout)
        try:
            c.request("POST", PATH, body=payload, headers=headers)
            r = c.getresponse()
            data = r.read()
            if r.getheader("connection", "").lower() == "close":
                _close(c)
            else:
                _release(c)
            if r.status != 200:
                log.warning("Claude API %s: %s", r.status, data[:300])
                return None
            return json.loads(data)
        except (http.client.RemoteDisconnected, http.client.CannotSendRequest, http.client.BadStatusLine,
                ConnectionError, BrokenPipeError) as e:
            _close(c)
            if attempt == 2:
                log.warning("Claude API connection failed: %s", e)
                return None
        except Exception:
            _close(c)
            log.exception("Claude API call failed")
            return None
    return None


def tool_uses(data: dict | None) -> list[dict]:
    return [b for b in (data or {}).get("content", []) or [] if b.get("type") == "tool_use"]


def first_tool_use(data: dict | None) -> tuple[str, dict] | None:
    for block in tool_uses(data):
        return block.get("name", ""), block.get("input") or {}
    return None


# ----------------------------------------------------------------------
# Warm-up: open a TLS connection before it is needed
# ----------------------------------------------------------------------
_warm_at = 0.0


def _warm():
    try:
        c = http.client.HTTPSConnection(HOST, timeout=5, context=_ssl_ctx)
        c.connect()
        _release(c)
    except Exception:
        pass


def warmup() -> bool:
    """Open a pooled connection in the background (at most every 20 s)."""
    global _warm_at
    if not enabled():
        return False
    with _pool_lock:
        fresh = any(time.monotonic() - last < _IDLE_LIMIT - 5 for _, last in _pool)
        if fresh or time.monotonic() - _warm_at < 20:
            return True
        _warm_at = time.monotonic()
    threading.Thread(target=_warm, daemon=True).start()
    return True
