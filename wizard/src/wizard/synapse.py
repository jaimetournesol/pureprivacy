"""Thin wrapper for the Synapse admin API endpoints we need."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass

import httpx


def random_password(length: int = 24) -> str:
    """Cryptographically random password using a URL-safe alphabet."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass(slots=True)
class SynapseAdminClient:
    base_url: str
    registration_shared_secret: str

    async def register_user(
        self,
        *,
        username: str,
        password: str,
        admin: bool,
    ) -> str:
        """Register a user via Synapse's HMAC-shared-secret endpoint.

        Returns the full Matrix ID, e.g. ``@alice:abc.onion``.
        """
        nonce_url = f"{self.base_url}/_synapse/admin/v1/register"
        async with httpx.AsyncClient(timeout=30.0) as http:
            r = await http.get(nonce_url)
            r.raise_for_status()
            nonce = r.json()["nonce"]

            mac_input = (
                f"{nonce}\0{username}\0{password}\0{'admin' if admin else 'notadmin'}"
            ).encode("utf-8")
            mac = hmac.new(
                self.registration_shared_secret.encode("utf-8"),
                mac_input,
                hashlib.sha1,
            ).hexdigest()

            body = {
                "nonce": nonce,
                "username": username,
                "password": password,
                "admin": admin,
                "mac": mac,
            }
            r = await http.post(nonce_url, json=body)
            if r.status_code == 400 and "User ID already taken" in r.text:
                # Wizard re-run scenario.  Treat as success and return the full
                # ID; the caller knows the original password.
                return await self._discover_user_id(http, username)
            r.raise_for_status()
            return r.json()["user_id"]

    async def _discover_user_id(
        self, http: httpx.AsyncClient, username: str
    ) -> str:
        # /_synapse/admin doesn't have a "look up by localpart" endpoint that
        # works without auth; the simplest robust fallback is to construct
        # @username:server_name from the well-known.
        r = await http.get(f"{self.base_url}/_matrix/client/versions")
        r.raise_for_status()
        # Synapse's /_matrix/federation/v1/version exposes server_name under
        # `server.name`, but a much simpler path is to read it from the
        # Synapse instance's homeserver.yaml -- which we don't have access to
        # from here.  For now we trust the operator gave a sensible username
        # and reconstruct using the Host header.
        host = http.headers.get("Host", "")
        # Fallback: ask the discovery endpoint.
        r = await http.get(f"{self.base_url}/.well-known/matrix/server")
        if r.status_code == 200:
            host = r.json().get("m.server", host).split(":", 1)[0]
        return f"@{username}:{host}" if host else f"@{username}:unknown"
