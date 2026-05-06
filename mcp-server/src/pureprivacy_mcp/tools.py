"""MCP tool surface — thin wrappers over the matrix-nio client.

The bot must be invited to a room before these tools can act on it.  Tools
that mutate (send_message, mark_read, upload_file) are kept conservative:
they assume the human operator has explicitly added the bot to the room.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from fastmcp import FastMCP
from nio import UploadResponse

from .matrix_bot import MatrixBot

log = logging.getLogger("pureprivacy.tools")


def register_tools(mcp: FastMCP, get_bot: Callable[[], Optional[MatrixBot]]) -> None:
    """Bind every tool to a function that resolves to the current bot.

    The bot is initialized lazily — at boot, before the wizard has run, it
    is None.  Once the wizard creates the MCP bot user and writes its
    credentials, a background task initializes the bot and `get_bot()`
    returns a live instance.
    """

    def _require_ready() -> MatrixBot:
        bot = get_bot()
        if bot is None:
            raise RuntimeError(
                "PurePrivacy MCP is not yet configured.  Open the wizard at "
                "http://127.0.0.1:8088 and complete the setup."
            )
        if not bot.ready:
            raise RuntimeError(
                "PurePrivacy MCP bot is still syncing with Synapse. "
                "Try again in a few seconds."
            )
        return bot

    @mcp.tool()
    async def list_rooms() -> dict[str, Any]:
        """List every room the PurePrivacy bot is a member of.

        Returns a list of `{room_id, name, canonical_alias, encrypted,
        member_count, topic, unread}`.  The bot only sees rooms you have
        explicitly invited it to.
        """
        bot = _require_ready()
        return {
            "rooms": [bot.serialize_room(r) for r in bot.rooms().values()]
        }

    @mcp.tool()
    async def list_unread() -> dict[str, Any]:
        """Subset of `list_rooms` filtered to rooms with unread messages."""
        bot = _require_ready()
        unread = [
            bot.serialize_room(r)
            for r in bot.rooms().values()
            if r.unread_notifications + r.unread_highlights > 0
        ]
        return {"rooms": unread}

    @mcp.tool()
    async def get_room_history(
        room_id: str, limit: int = 50
    ) -> dict[str, Any]:
        """Fetch recent messages in a room.

        `room_id` is either the canonical room ID (`!abc:server`) or the
        canonical alias (`#name:server`).  `limit` caps the number of events
        returned (max 200).
        """
        bot = _require_ready()
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        room = bot.room(room_id)
        resp = await bot.client.room_messages(
            room.room_id, start=bot.client.next_batch or "", limit=limit
        )
        events = []
        if hasattr(resp, "chunk"):
            for ev in resp.chunk:
                events.append(bot.serialize_event(ev))
        return {
            "room_id": room.room_id,
            "events": events,
        }

    @mcp.tool()
    async def search_messages(
        query: str, limit: int = 25
    ) -> dict[str, Any]:
        """Full-text search across rooms the bot is in.

        Uses Synapse's server-side `/search` endpoint, which only indexes
        messages the bot was able to decrypt.  Encrypted rooms whose keys
        the bot never received will return no hits.
        """
        bot = _require_ready()
        if limit < 1 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        resp = await bot.client.room_search(
            search_term=query, limit=limit
        )
        hits: list[dict] = []
        results = getattr(resp, "results", None)
        if results:
            for r in results:
                hits.append(
                    {
                        "rank": getattr(r, "rank", None),
                        "event": bot.serialize_event(r.result),
                        "room_id": getattr(r.result, "room_id", None),
                    }
                )
        return {"query": query, "hits": hits}

    @mcp.tool()
    async def send_message(
        room_id: str, body: str, formatted: Optional[str] = None
    ) -> dict[str, Any]:
        """Post a plain-text message to a room.

        If the room is end-to-end encrypted, matrix-nio handles encryption
        provided the bot has received the relevant Megolm keys.  See the
        device-verification note in the README.
        """
        bot = _require_ready()
        room = bot.room(room_id)
        content = {
            "msgtype": "m.text",
            "body": body,
        }
        if formatted is not None:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted
        resp = await bot.client.room_send(
            room.room_id,
            message_type="m.room.message",
            content=content,
            ignore_unverified_devices=True,
        )
        return {
            "event_id": getattr(resp, "event_id", None),
            "room_id": room.room_id,
        }

    @mcp.tool()
    async def get_room_members(room_id: str) -> dict[str, Any]:
        """List the user IDs and display names in a room."""
        bot = _require_ready()
        room = bot.room(room_id)
        members = []
        for user_id, user in room.users.items():
            members.append(
                {
                    "user_id": user_id,
                    "display_name": user.display_name,
                    "power_level": room.power_levels.users.get(user_id, 0),
                }
            )
        return {"room_id": room.room_id, "members": members}

    @mcp.tool()
    async def mark_read(room_id: str, event_id: str) -> dict[str, Any]:
        """Move the read marker for a room up to the given event."""
        bot = _require_ready()
        room = bot.room(room_id)
        await bot.client.room_read_markers(
            room.room_id,
            fully_read_event=event_id,
            read_event=event_id,
        )
        return {"room_id": room.room_id, "marked_through": event_id}

    @mcp.tool()
    async def upload_file(
        room_id: str,
        path: str,
        body: Optional[str] = None,
    ) -> dict[str, Any]:
        """Upload a local file to the room as an `m.file` event.

        `path` must be an absolute path inside the MCP container.  The
        easiest way to share files is to mount your host directory into
        `/data/uploads` in `docker-compose.override.yml` and reference paths
        below that mount.
        """
        bot = _require_ready()
        room = bot.room(room_id)
        upload_path = Path(path)
        if not upload_path.is_absolute() or not upload_path.is_file():
            raise ValueError(f"upload_file requires an absolute file path, got {path!r}")

        with open(upload_path, "rb") as fh:
            resp, _ = await bot.client.upload(
                fh, content_type="application/octet-stream", filename=upload_path.name
            )
        if not isinstance(resp, UploadResponse):
            raise RuntimeError(f"matrix upload failed: {resp}")
        content = {
            "msgtype": "m.file",
            "body": body or upload_path.name,
            "url": resp.content_uri,
            "info": {"size": upload_path.stat().st_size},
        }
        send = await bot.client.room_send(
            room.room_id,
            message_type="m.room.message",
            content=content,
            ignore_unverified_devices=True,
        )
        return {
            "event_id": getattr(send, "event_id", None),
            "room_id": room.room_id,
            "mxc": resp.content_uri,
        }

    @mcp.tool()
    async def download_file(mxc: str, target_path: str) -> dict[str, Any]:
        """Download an `mxc://` URI to an absolute path inside the MCP container."""
        bot = _require_ready()
        if not mxc.startswith("mxc://"):
            raise ValueError("mxc must start with mxc://")
        target = Path(target_path)
        if not target.is_absolute():
            raise ValueError("target_path must be absolute")
        target.parent.mkdir(parents=True, exist_ok=True)
        rest = mxc[len("mxc://") :]
        server, media_id = rest.split("/", 1)
        resp = await bot.client.download(server_name=server, media_id=media_id)
        body = getattr(resp, "body", None)
        if body is None:
            raise RuntimeError(f"download failed: {resp}")
        target.write_bytes(body)
        return {"path": str(target), "bytes": len(body)}
