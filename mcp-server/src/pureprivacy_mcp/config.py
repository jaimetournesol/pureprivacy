"""Runtime configuration loaded from env + the wizard's shared volume."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class BotCredentials:
    homeserver_url: str
    user_id: str
    password: str


@dataclass(slots=True)
class Config:
    host: str
    port: int
    shared_dir: Path
    data_dir: Path
    uploads_dir: Path
    bearer_token: Optional[str]
    credentials: Optional[BotCredentials]
    # Extra Matrix user IDs allowed to invite the bot, beyond same-homeserver
    # users (which are always allowed). Comma-separated MCP_INVITE_ALLOWLIST.
    invite_allowlist: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env(cls) -> "Config":
        shared_dir = Path(os.environ.get("SHARED_DIR", "/shared"))
        data_dir = Path(os.environ.get("MCP_DATA_DIR", "/data"))
        data_dir.mkdir(parents=True, exist_ok=True)

        # Files shared via the MCP file tools must live inside this jail. The
        # operator can mount their host directory at /data/uploads in
        # docker-compose.override.yml. We refuse to read or write anywhere
        # else — see tools.py:_jail_path.
        uploads_dir = (data_dir / "uploads").resolve()
        uploads_dir.mkdir(parents=True, exist_ok=True)

        token_path = shared_dir / "secrets" / "mcp_bearer_token"
        bearer_token = (
            token_path.read_text(encoding="utf-8").strip()
            if token_path.is_file() and token_path.stat().st_size > 0
            else None
        )

        creds_path = shared_dir / "secrets" / "mcp_bot_credentials.json"
        credentials: Optional[BotCredentials] = None
        if creds_path.is_file():
            data = json.loads(creds_path.read_text(encoding="utf-8"))
            credentials = BotCredentials(
                homeserver_url=data["homeserver_url"],
                user_id=data["user_id"],
                password=data["password"],
            )

        raw_allow = os.environ.get("MCP_INVITE_ALLOWLIST", "").strip()
        invite_allowlist = frozenset(
            entry.strip()
            for entry in raw_allow.split(",")
            if entry.strip().startswith("@") and ":" in entry.strip()
        )

        return cls(
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8089")),
            shared_dir=shared_dir,
            data_dir=data_dir,
            uploads_dir=uploads_dir,
            bearer_token=bearer_token,
            credentials=credentials,
            invite_allowlist=invite_allowlist,
        )
