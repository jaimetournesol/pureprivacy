"""Talk to the host's Docker daemon over its Unix socket.

The wizard needs to restart Synapse after a federation pairing change so the
new `federation_domain_whitelist` actually takes effect.  We use httpx's UDS
transport instead of installing the docker CLI inside the wizard image —
that's one fewer moving part and avoids the security blanket of "docker is
present, please feel free to use it for unrelated things."
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx


log = logging.getLogger("pureprivacy.wizard.docker")

DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")


class DockerUnavailable(RuntimeError):
    """Raised when the docker socket is not mounted/readable."""


class DockerClient:
    """Minimal Docker daemon client over the local UDS.

    Surface area is intentionally tiny: restart a container by name, then
    poll until it reports healthy.  Anything more is YAGNI for v0.1.x.
    """

    def __init__(self, sock_path: str = DOCKER_SOCK) -> None:
        self.sock_path = sock_path

    def available(self) -> bool:
        return os.path.exists(self.sock_path)

    def _client(self, *, timeout: float) -> httpx.AsyncClient:
        if not self.available():
            raise DockerUnavailable(
                f"docker socket not present at {self.sock_path}; "
                "the wizard container needs /var/run/docker.sock mounted in"
            )
        transport = httpx.AsyncHTTPTransport(uds=self.sock_path)
        return httpx.AsyncClient(
            transport=transport, base_url="http://docker", timeout=timeout
        )

    async def restart(self, name: str, *, timeout_s: int = 30) -> None:
        """POST /containers/<name>/restart.

        ``timeout_s`` is the SIGTERM grace period docker gives the container
        before SIGKILL.  Synapse handles SIGTERM gracefully so 30s is fine.
        """
        async with self._client(timeout=60.0) as client:
            resp = await client.post(
                f"/containers/{name}/restart", params={"t": str(timeout_s)}
            )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"docker restart {name} failed "
                f"({resp.status_code}): {resp.text.strip()[:200]}"
            )

    async def inspect(self, name: str) -> dict:
        async with self._client(timeout=10.0) as client:
            resp = await client.get(f"/containers/{name}/json")
        if resp.status_code == 404:
            raise RuntimeError(f"container {name} not found")
        resp.raise_for_status()
        return resp.json()

    async def wait_healthy(
        self,
        name: str,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 1.5,
    ) -> None:
        """Block until the container reports healthy.

        We watch ``State.Health.Status`` if a healthcheck is defined; for
        containers without a healthcheck we accept ``State.Running == true``.
        Times out with a diagnostic message.
        """
        deadline = time.monotonic() + timeout_s
        last_status = "unknown"
        # Synapse's restart cycle has it transient-down for ~1-3s before the
        # daemon flips Running back on; eat that window before we start
        # checking, otherwise we can race and immediately return on "still up
        # because the docker stop hasn't landed yet."
        await asyncio.sleep(0.5)
        async with self._client(timeout=10.0) as client:
            while time.monotonic() < deadline:
                try:
                    r = await client.get(f"/containers/{name}/json")
                    if r.status_code == 200:
                        state = r.json().get("State", {})
                        health = (state.get("Health") or {}).get("Status", "")
                        running = state.get("Running", False)
                        if health == "healthy":
                            return
                        if not health and running:
                            return
                        if health == "unhealthy":
                            raise RuntimeError(
                                f"container {name} reported unhealthy"
                            )
                        last_status = health or (
                            "running" if running else "stopped"
                        )
                except httpx.HTTPError as exc:
                    last_status = f"error contacting docker: {exc}"
                await asyncio.sleep(poll_interval_s)
        raise RuntimeError(
            f"container {name} did not become healthy within "
            f"{timeout_s:.0f}s (last status: {last_status})"
        )


_default_client: Optional[DockerClient] = None


def default_client() -> DockerClient:
    global _default_client
    if _default_client is None:
        _default_client = DockerClient()
    return _default_client
