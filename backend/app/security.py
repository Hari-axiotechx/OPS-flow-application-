import base64
import hashlib
import hmac
import json
import time

from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


# ---------------------------------------------------------------------
# Signed, stateless session tokens (HMAC-SHA256), equivalent to the
# signToken_/verifyToken_ pair in the old Apps Script backend.
# ---------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign_token(payload: dict) -> str:
    body = _b64url_encode(json.dumps(payload).encode())
    sig = _b64url_encode(
        hmac.new(settings.TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.split(".", 1)
    expected = _b64url_encode(
        hmac.new(settings.TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64url_decode(body))
    except Exception:
        return None
    if not payload.get("exp") or time.time() * 1000 > payload["exp"]:
        return None
    return payload


def make_session_token(email: str) -> str:
    exp = int((time.time() + settings.TOKEN_TTL_HOURS * 3600) * 1000)
    return sign_token({"email": email, "exp": exp})
