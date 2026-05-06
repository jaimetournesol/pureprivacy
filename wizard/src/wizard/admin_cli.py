"""Admin CLI for the wizard image.

Lives here (and not in scripts/pureprivacy) because it needs the
registration_shared_secret and admin credentials that are mounted at
/shared inside the wizard container.  Invoked via `docker exec` from
scripts/pureprivacy's user/admin/pair subcommands.

All output is JSON on stdout for the bash wrapper to parse.  Errors go to
stderr and the process exits non-zero.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

from . import pairing as pair
from . import recovery
from .secrets import (
    SetupState,
    load_setup_state,
    update_admin_password,
)
from .synapse import SynapseAdminClient, random_password


SHARED_DIR = Path(os.environ.get("SHARED_DIR", "/shared"))
SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")


# ---- helpers ---------------------------------------------------------------


def _require_setup() -> SetupState:
    state = load_setup_state(SHARED_DIR)
    if not state.complete:
        print("setup is not complete; run `pureprivacy init` first", file=sys.stderr)
        sys.exit(2)
    return state


def _server_name(state: SetupState) -> str:
    if state.admin_user and ":" in state.admin_user:
        return state.admin_user.split(":", 1)[1]
    if state.onion:
        return state.onion
    raise RuntimeError("could not determine server_name from setup state")


def _full_user_id(name: str, state: SetupState) -> str:
    if name.startswith("@") and ":" in name:
        return name
    return f"@{name.lstrip('@')}:{_server_name(state)}"


_ADMIN_TOKEN_FILE = "admin_access_token"


def _admin_token_path() -> Path:
    return SHARED_DIR / "secrets" / _ADMIN_TOKEN_FILE


def _load_cached_admin_token() -> Optional[str]:
    """Read the cached admin access token, if any.  Stripped of whitespace."""
    p = _admin_token_path()
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def _store_cached_admin_token(token: str) -> None:
    p = _admin_token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(token + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(p)


def _invalidate_cached_admin_token() -> None:
    p = _admin_token_path()
    if p.is_file():
        p.unlink()


async def _admin_login(
    client: httpx.AsyncClient,
    *,
    admin_user_id: str,
    admin_password: str,
) -> str:
    """Log in as the admin user and return an access_token."""
    localpart = admin_user_id.lstrip("@").split(":", 1)[0]
    body = {
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": localpart},
        "password": admin_password,
    }
    r = await client.post(f"{SYNAPSE_URL}/_matrix/client/r0/login", json=body)
    r.raise_for_status()
    return r.json()["access_token"]


async def _whoami(client: httpx.AsyncClient, token: str) -> bool:
    """Cheap check that an access token is still valid."""
    try:
        r = await client.get(
            f"{SYNAPSE_URL}/_matrix/client/r0/account/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
        return r.status_code == 200
    except httpx.HTTPError:
        return False


async def admin_session(state: SetupState) -> tuple[httpx.AsyncClient, str]:
    """Return an httpx client + valid admin access_token.

    Caches the token in /shared/secrets/admin_access_token so consecutive
    CLI calls don't re-hit Synapse's `rc_login` rate limit (3 burst, 1
    per 6 s).  If the cached token is stale we transparently re-login.
    """
    if not state.admin_user or not state.admin_password:
        raise RuntimeError("admin credentials missing in /shared/.setup-complete")
    client = httpx.AsyncClient(timeout=60.0)
    try:
        cached = _load_cached_admin_token()
        if cached and await _whoami(client, cached):
            return client, cached
        # Cache miss or stale — log in.
        token = await _admin_login(
            client,
            admin_user_id=state.admin_user,
            admin_password=state.admin_password,
        )
        _store_cached_admin_token(token)
        return client, token
    except Exception:
        await client.aclose()
        raise


# ---- core user operations --------------------------------------------------
#
# These are the building blocks shared by the CLI (`pureprivacy user …`)
# and the wizard's /people web UI.  All return plain dicts and raise
# Python exceptions on error; the caller decides how to render those.


class UserManagementError(Exception):
    """A user-mgmt operation was rejected for a reason worth surfacing
    verbatim to the operator (e.g. "refusing to deactivate the admin")."""


async def add_user(
    state: SetupState,
    *,
    name: str,
    admin: bool = False,
    password: Optional[str] = None,
) -> dict[str, Any]:
    if not state.registration_secret:
        raise UserManagementError("registration_shared_secret missing")
    api = SynapseAdminClient(
        base_url=SYNAPSE_URL,
        registration_shared_secret=state.registration_secret,
    )
    pw = password or random_password(20)
    user_id = await api.register_user(
        username=name.lstrip("@").split(":", 1)[0],
        password=pw,
        admin=admin,
    )
    return {
        "user_id": user_id,
        "password": pw,
        "homeserver_url": (
            f"http://{state.onion}" if state.onion else SYNAPSE_URL
        ),
        "admin": admin,
    }


async def list_users(state: SetupState) -> list[dict[str, Any]]:
    client, token = await admin_session(state)
    try:
        r = await client.get(
            f"{SYNAPSE_URL}/_synapse/admin/v2/users",
            params={"limit": 500, "guests": "false", "deactivated": "true"},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
        users = r.json().get("users", [])
    finally:
        await client.aclose()
    return [
        {
            "user_id": u["name"],
            "admin": bool(u.get("admin")),
            "deactivated": bool(u.get("deactivated")),
            "display_name": u.get("displayname"),
        }
        for u in users
    ]


async def remove_user(state: SetupState, *, name: str) -> dict[str, Any]:
    full_id = _full_user_id(name, state)
    if state.admin_user and full_id == state.admin_user:
        raise UserManagementError(
            "refusing to deactivate the admin user — use `pureprivacy admin "
            "reset-password` to change credentials, or `pureprivacy reset` "
            "to wipe the box"
        )
    if state.mcp_user and full_id == state.mcp_user:
        raise UserManagementError(
            "refusing to deactivate the MCP bot — disable the mcp service "
            "in docker-compose.yml if you want to turn the agent off"
        )
    client, token = await admin_session(state)
    try:
        r = await client.post(
            f"{SYNAPSE_URL}/_synapse/admin/v1/deactivate/{full_id}",
            json={"erase": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
    finally:
        await client.aclose()
    return {"user_id": full_id, "deactivated": True}


async def reset_user_password(
    state: SetupState,
    *,
    name: str,
    password: Optional[str] = None,
) -> dict[str, Any]:
    full_id = _full_user_id(name, state)
    new_pw = password or random_password(20)
    client, token = await admin_session(state)
    try:
        r = await client.post(
            f"{SYNAPSE_URL}/_synapse/admin/v1/reset_password/{full_id}",
            json={"new_password": new_pw, "logout_devices": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        r.raise_for_status()
    finally:
        await client.aclose()
    return {"user_id": full_id, "password": new_pw}


# ---- user subcommands (CLI wrappers) ---------------------------------------


async def cmd_user_add(args: argparse.Namespace) -> int:
    state = _require_setup()
    try:
        result = await add_user(
            state,
            name=args.name,
            admin=bool(args.admin),
            password=args.password,
        )
    except UserManagementError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


async def cmd_user_list(args: argparse.Namespace) -> int:
    state = _require_setup()
    users = await list_users(state)
    print(json.dumps({"users": users}, indent=2))
    return 0


async def cmd_user_remove(args: argparse.Namespace) -> int:
    state = _require_setup()
    try:
        result = await remove_user(state, name=args.name)
    except UserManagementError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


async def cmd_user_reset_password(args: argparse.Namespace) -> int:
    state = _require_setup()
    try:
        result = await reset_user_password(
            state,
            name=args.name,
            password=args.password,
        )
    except UserManagementError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


# ---- admin subcommands -----------------------------------------------------


async def cmd_admin_reset_password(args: argparse.Namespace) -> int:
    """Reset the admin password using the recovery key.

    The recovery key was minted at first setup and its hash is in
    /shared/secrets/recovery_hash.  We don't have admin auth (that's the
    point of "I forgot my password"), so we use Synapse's HMAC-shared-secret
    flow to bootstrap a temporary recovery user with admin privileges, log
    in as it, and reset the original admin's password through the admin
    API.  The recovery user is deactivated immediately afterwards.
    """
    state = _require_setup()
    encoded = recovery.load_recovery_hash(SHARED_DIR)
    if not encoded:
        print(
            "no recovery hash found — this box predates the recovery flow; "
            "use `pureprivacy reset` to wipe and re-init",
            file=sys.stderr,
        )
        return 2
    if not recovery.verify_recovery_key(args.passphrase, encoded):
        print("recovery key did not match", file=sys.stderr)
        return 1
    if not state.registration_secret:
        print("registration_shared_secret missing", file=sys.stderr)
        return 2
    if not state.admin_user:
        print(".setup-complete is missing admin_user", file=sys.stderr)
        return 2

    new_password = args.new_password or random_password(20)
    api = SynapseAdminClient(
        base_url=SYNAPSE_URL,
        registration_shared_secret=state.registration_secret,
    )
    # Random localpart so we don't collide with previously-deactivated
    # recovery users (Synapse keeps deactivated localparts reserved).
    recovery_localpart = "pureprivacy-recovery-" + os.urandom(4).hex()
    recovery_password = random_password(32)
    recovery_full_id = await api.register_user(
        username=recovery_localpart,
        password=recovery_password,
        admin=True,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        token = await _admin_login(
            client,
            admin_user_id=recovery_full_id,
            admin_password=recovery_password,
        )
        try:
            r = await client.post(
                f"{SYNAPSE_URL}/_synapse/admin/v1/reset_password/{state.admin_user}",
                json={"new_password": new_password, "logout_devices": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
            # Tear down the recovery user — done with it.
            r = await client.post(
                f"{SYNAPSE_URL}/_synapse/admin/v1/deactivate/{recovery_full_id}",
                json={"erase": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            r.raise_for_status()
        except httpx.HTTPStatusError:
            # Best-effort cleanup so we don't leave a high-privilege user
            # behind if the password reset itself failed.
            try:
                await client.post(
                    f"{SYNAPSE_URL}/_synapse/admin/v1/deactivate/{recovery_full_id}",
                    json={"erase": True},
                    headers={"Authorization": f"Bearer {token}"},
                )
            except Exception:
                pass
            raise

    update_admin_password(SHARED_DIR, new_password=new_password)

    print(
        json.dumps(
            {"user_id": state.admin_user, "password": new_password},
            indent=2,
        )
    )
    return 0


# ---- pair subcommands ------------------------------------------------------


async def cmd_pair_create(args: argparse.Namespace) -> int:
    state = _require_setup()
    if not state.onion:
        print("onion not yet published", file=sys.stderr)
        return 2
    code = pair.generate_code(state.onion)
    blob = pair.encode_code(code)
    print(
        json.dumps(
            {
                "pair_code": blob,
                "expires_at": code["expires_at"],
                "nonce": code["nonce"],
            },
            indent=2,
        )
    )
    return 0


async def cmd_pair_list(args: argparse.Namespace) -> int:
    _require_setup()
    peers = pair.load_pairings(SHARED_DIR)
    print(
        json.dumps(
            {"peers": [p.to_dict() for p in peers]},
            indent=2,
        )
    )
    return 0


async def cmd_pair_accept(args: argparse.Namespace) -> int:
    """Save a pair code without restarting Synapse.

    The bash wrapper hits the wizard's HTTP endpoint instead — that route
    handles the docker-restart-and-wait dance.  This subcommand is a
    file-only alternative for environments where the wizard cannot reach
    the docker socket (containers-in-containers, minimal CI).
    """
    state = _require_setup()
    code = pair.decode_code(args.code)
    if code["onion"] == state.onion:
        print("refusing to pair this box with itself", file=sys.stderr)
        return 2
    new = pair.save_pairing(SHARED_DIR, code)
    print(json.dumps({"paired": new.to_dict()}, indent=2))
    return 0


async def cmd_pair_remove(args: argparse.Namespace) -> int:
    _require_setup()
    if not pair.remove_pairing(SHARED_DIR, args.onion):
        print(f"no peer matches {args.onion}", file=sys.stderr)
        return 2
    print(json.dumps({"removed": args.onion}, indent=2))
    return 0


# ---- argparse plumbing -----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wizard.admin_cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("user-add")
    a.add_argument("name")
    a.add_argument("--admin", action="store_true")
    a.add_argument("--password", default=None)
    a.set_defaults(handler=cmd_user_add)

    a = sub.add_parser("user-list")
    a.set_defaults(handler=cmd_user_list)

    a = sub.add_parser("user-remove")
    a.add_argument("name")
    a.set_defaults(handler=cmd_user_remove)

    a = sub.add_parser("user-reset-password")
    a.add_argument("name")
    a.add_argument("--password", default=None)
    a.set_defaults(handler=cmd_user_reset_password)

    a = sub.add_parser("admin-reset-password")
    a.add_argument("passphrase")
    a.add_argument("--new-password", default=None)
    a.set_defaults(handler=cmd_admin_reset_password)

    a = sub.add_parser("pair-create")
    a.set_defaults(handler=cmd_pair_create)

    a = sub.add_parser("pair-list")
    a.set_defaults(handler=cmd_pair_list)

    a = sub.add_parser("pair-accept")
    a.add_argument("code")
    a.set_defaults(handler=cmd_pair_accept)

    a = sub.add_parser("pair-remove")
    a.add_argument("onion")
    a.set_defaults(handler=cmd_pair_remove)

    return p


def main() -> None:
    args = build_parser().parse_args()
    try:
        rc = asyncio.run(args.handler(args))
    except httpx.HTTPStatusError as exc:
        # Translate the most common Synapse status codes into operator-
        # readable hints; everything else falls through to a verbatim dump.
        sc = exc.response.status_code
        if sc == 429:
            print(
                "Synapse rate-limited the wizard (HTTP 429).  This usually "
                "happens after several rapid `pureprivacy user …` calls — "
                "Synapse's login rate limit is 3 burst then 1 per 6 s.  "
                "Wait ~10 seconds and retry.",
                file=sys.stderr,
            )
        elif sc in (401, 403):
            print(
                f"Synapse rejected the request (HTTP {sc}).  The cached admin "
                "access token may be stale; re-running often clears it.  If "
                "the problem persists, the admin password in /shared/.setup-complete "
                "may not match the live admin user — see "
                "`pureprivacy admin reset-password`.",
                file=sys.stderr,
            )
        else:
            print(
                f"synapse responded {sc}: {exc.response.text[:300]}",
                file=sys.stderr,
            )
        sys.exit(1)
    sys.exit(rc)


if __name__ == "__main__":
    main()
