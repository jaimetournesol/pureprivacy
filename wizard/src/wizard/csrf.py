"""CSRF protection for state-changing wizard routes.

The wizard binds to 127.0.0.1 only, but a malicious local page (browser
extension, drive-by tab, another desktop app) can still issue cross-origin
POSTs to it. The session cookie is ``SameSite=Strict`` to defeat
top-level navigation CSRF, but we add an additional defense-in-depth
layer: every state-changing form embeds a hidden HMAC-signed token, and
the request must arrive with an ``Origin`` (or ``Referer``) that matches
the wizard's own host.

Tokens are stateless — HMAC-SHA256 over ``nonce|issued_at`` using a key
in ``/shared/secrets/wizard_csrf_key`` — so they survive wizard
restarts. The CLI-token bypass header is honoured: requests carrying a
valid CLI token (used by ``scripts/pureprivacy`` and tests) skip CSRF
because they cannot be ridden by a browser.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as stdlib_secrets
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

CSRF_KEY_FILE = "wizard_csrf_key"
CSRF_TOKEN_LIFETIME_SECONDS = 60 * 60 * 12
NONCE_LEN = 16
TS_LEN = 8
SIG_LEN = 32


def _key_path(shared: Path) -> Path:
    return shared / "secrets" / CSRF_KEY_FILE


def _load_or_create_key(shared: Path) -> bytes:
    p = _key_path(shared)
    if p.is_file():
        b = p.read_bytes()
        if len(b) >= 32:
            return b
    p.parent.mkdir(parents=True, exist_ok=True)
    key = stdlib_secrets.token_bytes(32)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(key)
    tmp.chmod(0o600)
    tmp.replace(p)
    return key


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(shared: Path) -> str:
    key = _load_or_create_key(shared)
    nonce = stdlib_secrets.token_bytes(NONCE_LEN)
    ts = int(time.time()).to_bytes(TS_LEN, "big")
    payload = nonce + ts
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return _b64e(payload + sig)


def verify_token(shared: Path, token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        raw = _b64d(token)
    except Exception:
        return False
    if len(raw) != NONCE_LEN + TS_LEN + SIG_LEN:
        return False
    payload, sig = raw[: NONCE_LEN + TS_LEN], raw[NONCE_LEN + TS_LEN :]
    key = _load_or_create_key(shared)
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return False
    issued_at = int.from_bytes(payload[NONCE_LEN:], "big")
    if time.time() - issued_at > CSRF_TOKEN_LIFETIME_SECONDS:
        return False
    return True


def _request_host(request: Request) -> Optional[str]:
    host = request.headers.get("host")
    return host.lower() if host else None


def _origin_host(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if not parsed.netloc:
        return None
    return parsed.netloc.lower()


def origin_matches(request: Any) -> bool:
    """Return True if Origin (or Referer) host matches the wizard's host.

    Browsers always send Origin on cross-origin POSTs and on most
    same-origin POSTs. We accept Referer as a fallback for old clients;
    if neither header is present we refuse the request.

    The argument is duck-typed (anything with a ``headers.get`` mapping)
    so this module stays free of FastAPI imports — keeps tests fast.
    """
    own = _request_host(request)
    if not own:
        return False
    origin = _origin_host(request.headers.get("origin"))
    if origin is not None:
        return origin == own
    referer = _origin_host(request.headers.get("referer"))
    if referer is not None:
        return referer == own
    return False


def make_csrf_protect(shared_dir: Path):
    """Build a FastAPI Depends() callable bound to a shared dir.

    Imports FastAPI lazily so the rest of this module can be unit-tested
    without the FastAPI dependency.
    """
    from fastapi import Form, HTTPException, Request

    from . import auth

    def csrf_protect(
        request: Request,
        csrf_token: str = Form(""),
    ) -> None:
        cli_header = request.headers.get(auth.CLI_TOKEN_HEADER)
        if cli_header and auth.cli_token_matches(shared_dir, cli_header):
            return
        if not origin_matches(request):
            raise HTTPException(403, "Origin/Referer mismatch")
        if not verify_token(shared_dir, csrf_token):
            raise HTTPException(403, "CSRF token invalid or expired")

    return csrf_protect
