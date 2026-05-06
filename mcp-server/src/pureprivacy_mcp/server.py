"""HTTP entry point: FastMCP serves /mcp; we add /healthz and bearer auth.

The MCP container can boot before the wizard has run.  In that state, the
matrix bot is not yet configured (no credentials on disk), so /healthz
reports `matrix_bot_ready: false` and tools return a friendly "run the
wizard first" error.  A background task polls for the credentials file and
brings the bot online as soon as it appears.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .config import Config
from .matrix_bot import MatrixBot
from .tools import register_tools

log = logging.getLogger("pureprivacy.server")

# Grace window during which a rotated MCP token is still accepted.  Same
# value is honored by the wizard (env var passed through docker-compose so
# the two sides agree on what "10 min" means).
MCP_TOKEN_GRACE_SECONDS = int(os.environ.get("MCP_TOKEN_GRACE_SECONDS", "600"))


def build_app() -> tuple[Starlette, dict, Config]:
    cfg = Config.from_env()
    token_path = cfg.shared_dir / "secrets" / "mcp_bearer_token"
    prev_token_path = cfg.shared_dir / "secrets" / "mcp_bearer_token.prev"

    # Bot is held in a one-element dict so the closure inside register_tools
    # always sees the current value, including after the background task
    # populates it.
    state: dict = {"bot": None}

    mcp = FastMCP(name="pureprivacy")
    register_tools(mcp, lambda: state["bot"], cfg)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> Response:
        bot = state["bot"]
        return JSONResponse(
            {
                "status": "ok",
                "matrix_bot_ready": bool(bot and bot.ready),
                "wizard_run": (cfg.shared_dir / ".setup-complete").is_file(),
            }
        )

    asgi_app = mcp.http_app(transport="streamable-http")

    def _read_token(path) -> Optional[str]:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8").strip() or None

    def valid_tokens() -> set[str]:
        """Set of currently-accepted bearer tokens.

        Always includes the live token; conditionally includes the previous
        token while its grace window is open.  Both files are re-read on
        every request so rotation is visible immediately.
        """
        accepted: set[str] = set()
        live = _read_token(token_path)
        if live:
            accepted.add(live)
        if prev_token_path.is_file():
            try:
                age = time.time() - prev_token_path.stat().st_mtime
            except OSError:
                age = MCP_TOKEN_GRACE_SECONDS + 1
            if age < MCP_TOKEN_GRACE_SECONDS:
                prev = _read_token(prev_token_path)
                if prev:
                    accepted.add(prev)
        return accepted

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.url.path == "/healthz":
                return await call_next(request)
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                return JSONResponse(
                    {"error": "missing Bearer token"}, status_code=401
                )
            offered = header.removeprefix("Bearer ").strip()
            accepted = valid_tokens()
            if not accepted:
                return JSONResponse(
                    {"error": "no MCP token configured; run the setup wizard"},
                    status_code=503,
                )
            if offered not in accepted:
                return JSONResponse(
                    {"error": "invalid Bearer token"}, status_code=403
                )
            return await call_next(request)

    asgi_app.add_middleware(BearerAuthMiddleware)
    return asgi_app, state, cfg


async def run() -> None:
    app, state, cfg = build_app()

    async def setup_bot() -> None:
        """Wait for the wizard to write credentials, then bring the bot up."""
        attempt = 0
        while True:
            fresh = Config.from_env()  # re-read to pick up wizard-written files
            if fresh.credentials is None:
                if attempt == 0:
                    log.info("matrix bot waiting for wizard to create credentials")
                attempt += 1
                await asyncio.sleep(5)
                continue
            try:
                bot = MatrixBot(
                    fresh.credentials,
                    fresh.data_dir,
                    invite_allowlist=fresh.invite_allowlist,
                )
                await bot.start()
                state["bot"] = bot
                log.info("matrix bot online")
                return
            except Exception as exc:
                log.warning("bot start attempt %d failed: %s", attempt + 1, exc)
                attempt += 1
                await asyncio.sleep(min(60, 5 * (attempt + 1)))

    bot_task = asyncio.create_task(setup_bot())
    config = uvicorn.Config(
        app,
        host=cfg.host,
        port=cfg.port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        bot_task.cancel()
        try:
            await bot_task
        except (asyncio.CancelledError, Exception):
            pass
        bot = state.get("bot")
        if bot is not None:
            try:
                await bot.stop()
            except Exception:
                pass


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
