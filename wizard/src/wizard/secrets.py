"""Shared-volume IO helpers for setup state and MCP-bot credentials."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


SECRETS_SUBDIR = "secrets"
SETUP_SENTINEL = ".setup-complete"
ONION_FILE = "onion_hostname"
MCP_CREDS_FILE = "mcp_bot_credentials.json"
MCP_TOKEN_FILE = "mcp_bearer_token"
MCP_TOKEN_PREV_FILE = "mcp_bearer_token.prev"

# Grace window during which a rotated MCP token is still accepted.  Same
# value is honored by mcp-server's BearerAuthMiddleware (env var passed
# through docker-compose so the two sides agree).
MCP_TOKEN_GRACE_SECONDS = int(os.environ.get("MCP_TOKEN_GRACE_SECONDS", "600"))


@dataclass(slots=True)
class SetupState:
    onion: Optional[str]
    registration_secret: Optional[str]
    mcp_token: Optional[str]
    complete: bool
    admin_user: Optional[str]
    admin_password: Optional[str]
    mcp_user: Optional[str]
    recovery_passphrase: Optional[str] = None
    mcp_grace_remaining_s: int = 0

    def phone_payload(self) -> str:
        """Plain-text block we put in the QR for transcription."""
        if not (self.onion and self.admin_user and self.admin_password):
            return ""
        return (
            "PUREPRIVACY\n"
            f"server: http://{self.onion}\n"
            f"user: {self.admin_user}\n"
            f"password: {self.admin_password}\n"
        )


def _read(path: Path) -> Optional[str]:
    if path.is_file() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8").strip()
    return None


def previous_mcp_token_grace_remaining_s(shared: Path) -> int:
    """Seconds remaining for the previous MCP token, 0 if expired/absent."""
    prev = shared / SECRETS_SUBDIR / MCP_TOKEN_PREV_FILE
    if not prev.is_file():
        return 0
    age = time.time() - prev.stat().st_mtime
    remaining = MCP_TOKEN_GRACE_SECONDS - age
    return max(0, int(remaining))


def load_setup_state(shared: Path) -> SetupState:
    secrets_dir = shared / SECRETS_SUBDIR
    sentinel = shared / SETUP_SENTINEL
    summary: dict = {}
    if sentinel.is_file():
        try:
            summary = json.loads(sentinel.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            summary = {}
    return SetupState(
        onion=_read(shared / ONION_FILE),
        registration_secret=_read(secrets_dir / "registration_shared_secret"),
        mcp_token=_read(secrets_dir / MCP_TOKEN_FILE),
        complete=sentinel.is_file(),
        admin_user=summary.get("admin_user"),
        admin_password=summary.get("admin_password"),
        mcp_user=summary.get("mcp_user"),
        recovery_passphrase=summary.get("recovery_passphrase"),
        mcp_grace_remaining_s=previous_mcp_token_grace_remaining_s(shared),
    )


def mark_setup_complete(
    shared: Path,
    *,
    admin_user: str,
    admin_password: str,
    mcp_user: str,
    recovery_passphrase: Optional[str] = None,
) -> None:
    sentinel = shared / SETUP_SENTINEL
    payload = {
        "admin_user": admin_user,
        "admin_password": admin_password,
        "mcp_user": mcp_user,
    }
    if recovery_passphrase is not None:
        payload["recovery_passphrase"] = recovery_passphrase
    sentinel.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    sentinel.chmod(0o600)


def update_admin_password(shared: Path, *, new_password: str) -> None:
    """Rewrite .setup-complete with a new admin_password, keeping other fields."""
    sentinel = shared / SETUP_SENTINEL
    if not sentinel.is_file():
        raise RuntimeError(f"{sentinel} does not exist")
    data = json.loads(sentinel.read_text(encoding="utf-8"))
    data["admin_password"] = new_password
    sentinel.write_text(json.dumps(data, indent=2), encoding="utf-8")
    sentinel.chmod(0o600)


# Reveal counters ----------------------------------------------------------
#
# Every authenticated render of the home page that embeds a sensitive
# value (admin password, recovery key) bumps the matching counter.  The
# home page surfaces the count so the operator can compare it to their
# own knowledge of how many sessions they've opened — a number bigger
# than expected is a signal that another browser session has viewed the
# setup page.  See server.py:root() for the increment sites.
ADMIN_PASSWORD_VIEW_FILE = "admin_password_views"
RECOVERY_KEY_VIEW_FILE = "recovery_key_views"


def _increment_counter(shared: Path, name: str) -> int:
    counter = shared / SECRETS_SUBDIR / name
    counter.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = int(counter.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        current = 0
    new_count = current + 1
    tmp = counter.with_suffix(".tmp")
    tmp.write_text(str(new_count), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(counter)
    return new_count


def _read_counter(shared: Path, name: str) -> int:
    counter = shared / SECRETS_SUBDIR / name
    try:
        return int(counter.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def _reset_counter(shared: Path, name: str) -> None:
    counter = shared / SECRETS_SUBDIR / name
    counter.parent.mkdir(parents=True, exist_ok=True)
    tmp = counter.with_suffix(".tmp")
    tmp.write_text("0", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(counter)


def increment_admin_password_views(shared: Path) -> int:
    return _increment_counter(shared, ADMIN_PASSWORD_VIEW_FILE)


def read_admin_password_views(shared: Path) -> int:
    return _read_counter(shared, ADMIN_PASSWORD_VIEW_FILE)


def reset_admin_password_views(shared: Path) -> None:
    _reset_counter(shared, ADMIN_PASSWORD_VIEW_FILE)


def increment_recovery_key_views(shared: Path) -> int:
    return _increment_counter(shared, RECOVERY_KEY_VIEW_FILE)


def read_recovery_key_views(shared: Path) -> int:
    return _read_counter(shared, RECOVERY_KEY_VIEW_FILE)


def reset_recovery_key_views(shared: Path) -> None:
    _reset_counter(shared, RECOVERY_KEY_VIEW_FILE)


def write_mcp_bot_credentials(
    shared: Path,
    *,
    homeserver_url: str,
    user_id: str,
    password: str,
) -> None:
    secrets_dir = shared / SECRETS_SUBDIR
    secrets_dir.mkdir(parents=True, exist_ok=True)
    creds_path = secrets_dir / MCP_CREDS_FILE
    creds_path.write_text(
        json.dumps(
            {
                "homeserver_url": homeserver_url,
                "user_id": user_id,
                "password": password,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    creds_path.chmod(0o600)
