"""
Professional speech-to-text for the voice assistant (Deepgram, streaming).

WHY: the browser's built-in recognizer (Chrome "Web Speech") is slow to finish sentences and often
mishears technical words ("access request", "AWS", application names). Deepgram Nova-3 streams the
audio while you talk (words appear in ~0.3 s) and can be told the words to expect (`keyterm`), such as
your application names.

SECURITY: the browser must never see the real API key. The browser asks this endpoint (login required)
for a SHORT-LIVED token and connects to Deepgram directly with it.

No key configured -> {"enabled": false} and the app keeps using the browser's recognizer.
Standard library only.
"""
from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
from urllib.parse import quote

log = logging.getLogger("opsflow.stt")

HOST = "api.deepgram.com"
_ctx = ssl.create_default_context()
_lock = threading.Lock()
_cache: dict = {"token": "", "exp": 0.0}
TOKEN_TTL = 600  # seconds the browser may open new connections with one token

# Words the recognizer should expect (boosts them). Application names are added per request.
BASE_TERMS = [
    "Hello Ops", "OPSFlow", "deployment", "deployments", "access request", "AWS issue", "rollback",
    "roll back", "approve", "reject", "DevOps", "production", "QA", "UAT", "S3", "EC2", "IAM",
    "GitHub", "branch", "frontend", "backend", "dashboard",
]


def _settings():
    try:
        from .config import settings
        return settings
    except Exception:  # config needs pydantic-settings; unit tests may run without it
        return None


def _get(name: str, default: str = "") -> str:
    s = _settings()
    return (getattr(s, name, "") or default) if s else default


def api_key() -> str:
    return _get("DEEPGRAM_API_KEY")


def enabled() -> bool:
    return bool(api_key())


def _grant() -> tuple[str, int] | None:
    """Ask Deepgram for a temporary access token. -> (token, ttl) or None."""
    key = api_key()
    if not key:
        return None
    try:
        c = http.client.HTTPSConnection(HOST, timeout=5, context=_ctx)
        c.request("POST", "/v1/auth/grant", body=json.dumps({"ttl_seconds": TOKEN_TTL}),
                  headers={"Authorization": f"Token {key}", "Content-Type": "application/json"})
        r = c.getresponse()
        data = r.read()
        c.close()
        if r.status != 200:
            log.warning("Deepgram token request failed (%s): %s", r.status, data[:200])
            return None
        j = json.loads(data)
        return str(j["access_token"]), int(j.get("expires_in") or TOKEN_TTL)
    except Exception:
        log.exception("Deepgram token request failed")
        return None


def temp_token() -> tuple[str, int] | None:
    """Cached for most of its life (the token is not user specific; the endpoint itself needs a login)."""
    with _lock:
        now = time.time()
        if _cache["token"] and _cache["exp"] - now > 60:
            return _cache["token"], int(_cache["exp"] - now)
    got = _grant()
    if not got:
        return None
    with _lock:
        _cache["token"], _cache["exp"] = got[0], time.time() + got[1]
    return got


def build_url(terms: list[str]) -> str:
    model = _get("STT_MODEL", "nova-3")
    lang = _get("STT_LANGUAGE", "en-IN")
    q = [
        f"model={quote(model)}", f"language={quote(lang)}",
        "smart_format=true", "punctuate=true",
        "interim_results=true",   # words appear while you are still speaking
        "endpointing=300",        # ms of silence that ends a phrase
    ]
    seen = set()
    for t in terms:
        t = str(t).strip()
        if t and t.lower() not in seen and len(seen) < 80:
            seen.add(t.lower())
            q.append("keyterm=" + quote(t))
    return f"wss://{HOST}/v1/listen?" + "&".join(q)


def handle_voice_stt_token(db, body: dict, ctx) -> dict:
    from .auth_helpers import require_auth
    require_auth(ctx)
    if not enabled():
        return {"enabled": False}
    got = temp_token()
    if not got:
        return {"enabled": False, "reason": "token"}
    terms = list(BASE_TERMS)
    try:
        from .voice import _apps
        terms += _apps(db)
    except Exception:
        pass
    return {"enabled": True, "token": got[0], "expires_in": got[1], "url": build_url(terms),
            "wake": _get("STT_WAKE", "browser").lower() == "cloud"}
