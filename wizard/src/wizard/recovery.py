"""Recovery key for the admin user.

A recovery key is a 16-character base32 string (80 bits, formatted in
four-char groups) generated once at first setup.  We hash it with
PBKDF2-HMAC-SHA256 (stdlib, no extra deps, available everywhere) and store
the hash in /shared/secrets/recovery_hash; the plaintext is shown to the
operator exactly once at init time.

Forgetting the admin password is recoverable IFF the operator wrote the
recovery key down: `pureprivacy admin reset-password` accepts the key,
verifies it, and rotates the admin password without wiping any data.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path
from typing import Optional


PBKDF2_ITERS = 600_000  # ~0.3-1s per verify on modern hardware
SALT_BYTES = 16
HASH_BYTES = 32

_RECOVERY_KEY_BYTES = 10  # 80 bits — 16 base32 chars
_GROUP_SIZE = 4
_NORMALISER = re.compile(r"[^A-Z2-7]")  # base32 alphabet (RFC 4648, no padding)


def generate_recovery_key() -> str:
    """Return a freshly-minted recovery key, formatted with dashes for legibility."""
    raw = secrets.token_bytes(_RECOVERY_KEY_BYTES)
    b32 = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(b32[i : i + _GROUP_SIZE] for i in range(0, len(b32), _GROUP_SIZE))


def normalise_recovery_key(value: str) -> str:
    """Canonicalise user input so that case + dashes + spaces don't matter."""
    return _NORMALISER.sub("", value.upper())


def hash_recovery_key(value: str) -> str:
    """PBKDF2-hash the (normalised) recovery key.  Self-describing format."""
    norm = normalise_recovery_key(value)
    if not norm:
        raise ValueError("recovery key is empty after normalisation")
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", norm.encode("utf-8"), salt, PBKDF2_ITERS, dklen=HASH_BYTES
    )
    return (
        f"pbkdf2$sha256$iter={PBKDF2_ITERS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_recovery_key(value: str, encoded: str) -> bool:
    """Constant-time check of `value` against the stored hash."""
    norm = normalise_recovery_key(value)
    if not norm:
        return False
    parts = encoded.split("$")
    if len(parts) != 5 or parts[0] != "pbkdf2" or parts[1] != "sha256":
        return False
    try:
        iters = int(parts[2].split("=", 1)[1])
        salt = base64.b64decode(parts[3])
        expected = base64.b64decode(parts[4])
    except (IndexError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", norm.encode("utf-8"), salt, iters, dklen=len(expected)
    )
    return hmac.compare_digest(actual, expected)


# ---- on-disk layout --------------------------------------------------------

_HASH_FILE = "recovery_hash"


def hash_path(shared: Path) -> Path:
    return shared / "secrets" / _HASH_FILE


def write_recovery_hash(shared: Path, encoded: str) -> None:
    p = hash_path(shared)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(encoded + "\n", encoding="utf-8")
    p.chmod(0o600)


def load_recovery_hash(shared: Path) -> Optional[str]:
    p = hash_path(shared)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip() or None
