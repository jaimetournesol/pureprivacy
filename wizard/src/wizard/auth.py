"""Session-cookie auth for the post-setup wizard.

First-boot setup is unauthenticated — there is no admin password yet.
After /setup writes ``.setup-complete``, the operator-facing routes
(/people, /pair, /rotate-token, /show-recovery-key) sit behind a cookie
issued by /login when the operator re-enters the admin password.

Cookie format is ``payload.signature`` where payload is
``"<admin_user>|<issued_at_unix>"`` and signature is HMAC-SHA256 over
the payload using ``/shared/secrets/wizard_session_key``.  Sessions are
stateless — no server-side table — and expire after
``SESSION_LIFETIME_SECONDS``.

Why a separate cookie key (not the admin password directly): we need to
expire/rotate sessions independently of the admin password.  Why not
PBKDF2 the admin password and compare hashes: the admin password is
already at rest plaintext in ``.setup-complete`` (mode 0600), so PBKDF2
here would be cargo-culting.  See docs/v0.1.x-plan.md and SECURITY.md
for the v0.2 plan to encrypt that file under the recovery key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets as stdlib_secrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Request, Response


WIZARD_SESSION_COOKIE = "pureprivacy_wizard"
SESSION_LIFETIME_SECONDS = 60 * 60 * 12  # 12h — short enough to cap lost-laptop blast radius
SESSION_KEY_FILE = "wizard_session_key"


def _key_path(shared: Path) -> Path:
    return shared / "secrets" / SESSION_KEY_FILE


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


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_cookie(shared: Path, *, admin_user: str) -> str:
    key = _load_or_create_key(shared)
    payload = f"{admin_user}|{int(time.time())}".encode("utf-8")
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(sig)}"


def verify_cookie(shared: Path, cookie: Optional[str]) -> Optional[str]:
    """Return the admin user_id if the cookie is valid and unexpired."""
    if not cookie or "." not in cookie:
        return None
    try:
        payload_b64, sig_b64 = cookie.split(".", 1)
        payload = _b64decode(payload_b64)
        sig = _b64decode(sig_b64)
    except Exception:
        return None
    key = _load_or_create_key(shared)
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        admin_user, ts_str = payload.decode("utf-8").split("|", 1)
        ts = int(ts_str)
    except Exception:
        return None
    if time.time() - ts > SESSION_LIFETIME_SECONDS:
        return None
    return admin_user


def password_matches(admin_password: Optional[str], submitted: str) -> bool:
    if not admin_password or not submitted:
        return False
    return hmac.compare_digest(
        admin_password.encode("utf-8"),
        submitted.encode("utf-8"),
    )


def set_session_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        WIZARD_SESSION_COOKIE,
        value,
        max_age=SESSION_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=False,  # loopback HTTP; HMAC-signed and short-lived
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(WIZARD_SESSION_COOKIE, path="/")


def current_session(request: Request, shared: Path) -> Optional[str]:
    return verify_cookie(shared, request.cookies.get(WIZARD_SESSION_COOKIE))


# ---- CLI-token bypass ------------------------------------------------------
#
# The pureprivacy bash CLI and test scripts both POST to state-changing
# wizard routes (rotate-token, pair/accept, …) and can't carry a cookie.
# They authenticate instead with a long-lived shared secret stored at
# /shared/secrets/cli_token, readable from inside the wizard container via
# `docker exec`.  Anyone who can `docker exec` the wizard already has root
# on the host, so this token doesn't widen the trust boundary — it just
# lets the CLI bypass the operator-facing cookie auth.

CLI_TOKEN_FILE = "cli_token"
CLI_TOKEN_HEADER = "X-PurePrivacy-CLI-Token"


def _cli_token_path(shared: Path) -> Path:
    return shared / "secrets" / CLI_TOKEN_FILE


def load_or_create_cli_token(shared: Path) -> str:
    p = _cli_token_path(shared)
    if p.is_file():
        token = p.read_text(encoding="utf-8").strip()
        if token:
            return token
    p.parent.mkdir(parents=True, exist_ok=True)
    token = stdlib_secrets.token_hex(32)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(token + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)
    return token


def cli_token_matches(shared: Path, presented: Optional[str]) -> bool:
    if not presented:
        return False
    expected = load_or_create_cli_token(shared)
    return hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8"))


def authenticated_principal(request: Request, shared: Path) -> Optional[str]:
    """Return the auth principal: admin user_id, "cli", or None."""
    user = current_session(request, shared)
    if user:
        return user
    if cli_token_matches(shared, request.headers.get(CLI_TOKEN_HEADER)):
        return "cli"
    return None
