"""Long-running matrix-nio client that backs the MCP tool surface.

The bot logs in once with username/password (the wizard creates the user),
persists its device + Olm keys in `data_dir/store`, and syncs continuously
in a background task.  Tools call `bot.client.<method>` to read or write.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from nio import (
    AsyncClient,
    AsyncClientConfig,
    InviteMemberEvent,
    JoinError,
    LoginResponse,
    MatrixRoom,
    RoomMessageText,
    SyncResponse,
)

from .config import BotCredentials

log = logging.getLogger("pureprivacy.bot")


class MatrixBot:
    """Wraps an `nio.AsyncClient` with login/persistence helpers."""

    def __init__(self, credentials: BotCredentials, data_dir: Path) -> None:
        self.credentials = credentials
        self.data_dir = data_dir
        self.store_dir = data_dir / "store"
        self.session_path = data_dir / "session.json"
        self.store_dir.mkdir(parents=True, exist_ok=True)

        config = AsyncClientConfig(
            store_sync_tokens=True,
            encryption_enabled=True,
        )
        self.client = AsyncClient(
            homeserver=credentials.homeserver_url,
            user=credentials.user_id,
            store_path=str(self.store_dir),
            config=config,
        )
        self._sync_task: Optional[asyncio.Task[None]] = None
        self._ready = asyncio.Event()

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def wait_ready(self, timeout: float = 60.0) -> None:
        await asyncio.wait_for(self._ready.wait(), timeout=timeout)

    async def start(self) -> None:
        """Log in (or restore session) and begin syncing in the background."""
        if self.session_path.is_file():
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
            self.client.access_token = data["access_token"]
            self.client.user_id = data["user_id"]
            self.client.device_id = data["device_id"]
            log.info(
                "restored session for %s device=%s",
                self.client.user_id,
                self.client.device_id,
            )
        else:
            log.info("logging in as %s", self.credentials.user_id)
            resp = await self.client.login(
                password=self.credentials.password,
                device_name="pureprivacy-mcp",
            )
            if not isinstance(resp, LoginResponse):
                raise RuntimeError(f"matrix login failed: {resp}")
            self.session_path.write_text(
                json.dumps(
                    {
                        "access_token": resp.access_token,
                        "user_id": resp.user_id,
                        "device_id": resp.device_id,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.session_path.chmod(0o600)

        # matrix-nio needs the store loaded before it can decrypt anything.
        if self.client.should_upload_keys:
            await self.client.keys_upload()

        # Auto-accept any room invitation addressed to the bot.  The human
        # operator is expected to invite the bot themselves; an attacker on
        # the same homeserver could spam invites, but they'd also need to
        # be on the homeserver in the first place (registration is closed).
        self.client.add_event_callback(self._on_invite, InviteMemberEvent)

        self._sync_task = asyncio.create_task(self._sync_forever())

    async def _on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        if event.state_key != self.client.user_id:
            return
        log.info("auto-joining %s (invited by %s)", room.room_id, event.sender)
        for attempt in range(3):
            resp = await self.client.join(room.room_id)
            if not isinstance(resp, JoinError):
                return
            log.warning(
                "join %s failed (attempt %d): %s", room.room_id, attempt + 1, resp
            )
            await asyncio.sleep(2)

    async def stop(self) -> None:
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        await self.client.close()

    async def _sync_forever(self) -> None:
        """Continuously sync; mark ready after first sync completes."""
        try:
            while True:
                resp = await self.client.sync(timeout=30000, full_state=False)
                if isinstance(resp, SyncResponse):
                    if not self._ready.is_set():
                        log.info("first sync complete; bot is ready")
                        self._ready.set()
                else:
                    log.warning("sync error: %s; sleeping 5s", resp)
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("sync loop died; restarting in 10s")
            await asyncio.sleep(10)
            self._sync_task = asyncio.create_task(self._sync_forever())

    # ---- helpers used by the tool layer ------------------------------------

    def rooms(self) -> dict[str, MatrixRoom]:
        return self.client.rooms

    def room(self, room_id_or_alias: str) -> MatrixRoom:
        rooms = self.client.rooms
        if room_id_or_alias in rooms:
            return rooms[room_id_or_alias]
        # Allow lookup by canonical alias too.
        for room in rooms.values():
            if room.canonical_alias == room_id_or_alias:
                return room
        raise KeyError(
            f"room {room_id_or_alias!r} not found.  The bot only sees rooms "
            "it has been invited to and joined."
        )

    @staticmethod
    def serialize_room(room: MatrixRoom) -> dict:
        return {
            "room_id": room.room_id,
            "name": room.display_name,
            "canonical_alias": room.canonical_alias,
            "encrypted": room.encrypted,
            "member_count": room.member_count,
            "topic": room.topic,
            "unread": room.unread_notifications + room.unread_highlights,
        }

    @staticmethod
    def serialize_event(event) -> dict:
        body = getattr(event, "body", None)
        return {
            "event_id": getattr(event, "event_id", None),
            "sender": getattr(event, "sender", None),
            "ts": getattr(event, "server_timestamp", None),
            "type": event.__class__.__name__,
            "body": body,
            "decrypted": isinstance(event, RoomMessageText),
        }
