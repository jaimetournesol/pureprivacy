"""Box-to-box pairing helpers.

The pair code is a small JSON blob the operator transcribes (or scans as
a QR) between boxes.  Each box generates a code, the other accepts it,
and they're both added to each other's `federation_domain_whitelist`.

v0.1.x is intentionally simple: no Ed25519 signature on the code itself.
The trust root is the operator's eyeballs — they're presumably reading
both QR codes off two devices they control.  Synapse's own server-key
exchange takes over once federation begins.
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAIR_VERSION = 1
PAIR_LIFETIME_SECONDS = 15 * 60  # 15 minutes


@dataclass(slots=True)
class Pairing:
    onion: str
    added_at: int
    nonce: str

    def to_dict(self) -> dict[str, Any]:
        return {"onion": self.onion, "added_at": self.added_at, "nonce": self.nonce}


def generate_code(onion: str) -> dict[str, Any]:
    """Build the JSON blob the peer will paste into their wizard."""
    if not onion.endswith(".onion"):
        raise ValueError("onion hostname required")
    return {
        "version": PAIR_VERSION,
        "onion": onion,
        "expires_at": int(time.time()) + PAIR_LIFETIME_SECONDS,
        "nonce": secrets.token_hex(16),
    }


def _active_code_path(shared: Path) -> Path:
    return shared / "active_pair_code.json"


def load_or_mint_code(shared: Path, onion: str) -> dict[str, Any]:
    """Return the currently-offered pair code, minting a new one if absent
    or expired.  Cached in /shared so that a wizard page reload doesn't
    invalidate the code the operator just sent to their peer.
    """
    p = _active_code_path(shared)
    now = int(time.time())
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = None
        # Re-use only if same onion, version, and not expired.
        if (
            isinstance(data, dict)
            and data.get("version") == PAIR_VERSION
            and data.get("onion") == onion
            and isinstance(data.get("expires_at"), int)
            and data["expires_at"] > now + 30  # 30 s headroom
        ):
            return data
    code = generate_code(onion)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(code), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)
    return code


def discard_active_code(shared: Path) -> None:
    """Drop the cached code so the next view mints a fresh one.

    Call after a successful pair to avoid leaving a still-valid code lying
    around, and from the wizard's "regenerate" action.
    """
    p = _active_code_path(shared)
    if p.is_file():
        p.unlink()


def encode_code(code: dict[str, Any]) -> str:
    """Serialize a pair code to a single base64 string for transport."""
    return base64.urlsafe_b64encode(
        json.dumps(code, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def decode_code(blob: str) -> dict[str, Any]:
    """Inverse of `encode_code`.  Raises ValueError on bad input."""
    blob = blob.strip()
    try:
        decoded = base64.urlsafe_b64decode(blob.encode("ascii") + b"==")
    except Exception as exc:
        raise ValueError(f"could not base64-decode pair code: {exc}") from exc
    try:
        data = json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"pair code is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("pair code must be a JSON object")
    if data.get("version") != PAIR_VERSION:
        raise ValueError(f"unsupported pair-code version: {data.get('version')}")
    onion = data.get("onion", "")
    if not isinstance(onion, str) or not onion.endswith(".onion"):
        raise ValueError("pair code must include an .onion hostname")
    expires_at = data.get("expires_at", 0)
    if not isinstance(expires_at, int) or expires_at < int(time.time()):
        raise ValueError("pair code is expired")
    nonce = data.get("nonce", "")
    if not isinstance(nonce, str) or len(nonce) < 8:
        raise ValueError("pair code is missing a nonce")
    return data


def load_pairings(shared: Path) -> list[Pairing]:
    p = shared / "pairings.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out: list[Pairing] = []
    for entry in data.get("peers", []):
        try:
            out.append(
                Pairing(
                    onion=entry["onion"],
                    added_at=int(entry.get("added_at", 0)),
                    nonce=entry.get("nonce", ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def save_pairing(shared: Path, code: dict[str, Any]) -> Pairing:
    """Append a verified peer to /shared/pairings.json (idempotent on onion)."""
    pairings = load_pairings(shared)
    onion = code["onion"]
    nonce = code["nonce"]

    # Refuse to re-add the same nonce — single-use, prevents replay.
    if any(p.nonce == nonce for p in pairings):
        raise ValueError("this pair code has already been consumed")
    # If we've paired with this onion before with a different nonce, that's
    # fine; just refresh the entry.
    pairings = [p for p in pairings if p.onion != onion]

    new = Pairing(onion=onion, added_at=int(time.time()), nonce=nonce)
    pairings.append(new)

    out_path = shared / "pairings.json"
    payload = {"peers": [p.to_dict() for p in pairings]}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(out_path)
    return new


def remove_pairing(shared: Path, onion: str) -> bool:
    pairings = load_pairings(shared)
    remaining = [p for p in pairings if p.onion != onion]
    if len(remaining) == len(pairings):
        return False
    out_path = shared / "pairings.json"
    payload = {"peers": [p.to_dict() for p in remaining]}
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(out_path)
    return True
