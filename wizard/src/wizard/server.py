"""FastAPI app: first-boot wizard + ongoing operator management.

Routes split into three lifecycle phases:

1. **Pre-setup** (no ``.setup-complete`` yet): only ``/`` and ``/setup``
   are reachable.  No auth — there is no admin password yet.
2. **Login screen**: ``/login`` (GET form, POST verify) and ``/logout``.
3. **Authenticated** (cookie OR CLI-token in header): everything else
   — ``/people`` user mgmt, ``/pair`` federation, ``/rotate-token``,
   ``/show-recovery-key``.

The CLI-token header path is so ``scripts/pureprivacy`` and the test
scripts can call state-changing routes without a browser session.  See
``auth.py`` for details.
"""
from __future__ import annotations

import logging
import os
import secrets as stdlib_secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, PackageLoader, select_autoescape

from . import admin_cli
from . import auth
from . import csrf
from . import pairing as pair
from . import recovery
from .docker_client import DockerUnavailable, default_client as docker_default_client
from .qr import qr_png_data_url
from .secrets import (
    load_setup_state,
    mark_setup_complete,
    write_mcp_bot_credentials,
)
from .synapse import SynapseAdminClient, random_password

log = logging.getLogger("pureprivacy.wizard")

SHARED_DIR = Path(os.environ.get("SHARED_DIR", "/shared"))
SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
SYNAPSE_CONTAINER = os.environ.get("SYNAPSE_CONTAINER", "pureprivacy-synapse")

env = Environment(
    loader=PackageLoader("wizard", "templates"),
    autoescape=select_autoescape(),
)


SETUP_TOKEN_PATH = SHARED_DIR / "secrets" / "setup_token"


def _mint_setup_token_if_unset() -> None:
    """Plant a one-time setup token before /setup is reachable.

    Without this, anything that can hit ``127.0.0.1:8088`` before the
    operator does (a stray browser tab, a misbehaving local service, a
    container that can reach the host) can race the operator and seize
    admin. With it, ``/setup`` requires a token that only the operator
    can read out-of-band — by running ``pureprivacy info`` on the host or
    by inspecting ``docker logs pureprivacy-wizard``.
    """
    if (SHARED_DIR / ".setup-complete").is_file():
        return
    SETUP_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SETUP_TOKEN_PATH.is_file() and SETUP_TOKEN_PATH.stat().st_size > 0:
        token = SETUP_TOKEN_PATH.read_text(encoding="utf-8").strip()
    else:
        token = stdlib_secrets.token_hex(16)
        tmp = SETUP_TOKEN_PATH.with_suffix(".tmp")
        tmp.write_text(token + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(SETUP_TOKEN_PATH)
    # Print loud and clear: the operator needs to find this in `docker
    # logs pureprivacy-wizard` (or `pureprivacy info`) and paste it into
    # the setup form. This is the trade-off for refusing anonymous setup.
    log.warning("=" * 60)
    log.warning("PUREPRIVACY SETUP TOKEN: %s", token)
    log.warning("Paste it on the first-boot setup page to claim admin.")
    log.warning("=" * 60)


def _verify_setup_token(submitted: str) -> bool:
    """Constant-time check that ``submitted`` matches the on-disk token.

    Pure read; never unlinks.  Use ``_invalidate_setup_token`` to consume
    the token only after the rest of /setup has fully committed.
    """
    if not submitted or not SETUP_TOKEN_PATH.is_file():
        return False
    expected = SETUP_TOKEN_PATH.read_text(encoding="utf-8").strip()
    import hmac as _hmac
    return _hmac.compare_digest(expected, submitted.strip())


def _invalidate_setup_token() -> None:
    """Remove the one-time token from disk after a successful /setup.

    Idempotent — already-missing is fine.  Any error is logged and
    swallowed: setup *did* commit, so we'd rather leak a one-time
    token than 500 the operator after the fact.
    """
    try:
        SETUP_TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        log.exception("could not remove setup token at %s", SETUP_TOKEN_PATH)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Mint the CLI-token file at startup so scripts can read it as soon as
    # the wizard is healthy.  Lazy generation on first request would race
    # the CLI's first call.
    auth.load_or_create_cli_token(SHARED_DIR)
    _mint_setup_token_if_unset()
    yield


app = FastAPI(title="PurePrivacy setup wizard", lifespan=_lifespan)
# Build the CSRF Depends() once, bound to this wizard's SHARED_DIR. The
# module avoids importing FastAPI itself so it stays unit-testable
# without that dependency installed.
_csrf_protect = csrf.make_csrf_protect(SHARED_DIR)


def _render(template: str, **ctx: Any) -> HTMLResponse:
    # Every render carries a fresh CSRF token; templates that submit forms
    # embed it as a hidden field. Tokens are cheap (HMAC over 24 bytes)
    # and stateless, so there is no benefit to reusing them.
    ctx.setdefault("csrf_token", csrf.issue_token(SHARED_DIR))
    body = env.get_template(template).render(**ctx)
    return HTMLResponse(body)


# ---- auth dependency -------------------------------------------------------


def require_session(request: Request) -> str:
    """FastAPI dep: redirect to / pre-setup, /login if unauthed.

    Returns the principal (admin user_id, or "cli" for CLI-token requests).
    """
    state = load_setup_state(SHARED_DIR)
    if not state.complete:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/"},
        )
    principal = auth.authenticated_principal(request, SHARED_DIR)
    if principal:
        return principal
    raise HTTPException(
        status_code=303,
        headers={"Location": "/login"},
    )


# ---- liveness --------------------------------------------------------------


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---- root: pre-setup form, or post-login dashboard ------------------------


@app.get("/")
def root(request: Request) -> Response:
    state = load_setup_state(SHARED_DIR)
    if not state.complete:
        if not state.onion:
            return _render(
                "wait.html",
                reason="Tor is still publishing the onion hostname.",
            )
        return _render(
            "setup.html",
            onion=state.onion,
            suggested_password=random_password(),
        )
    # Setup complete — gate behind login.
    if not auth.authenticated_principal(request, SHARED_DIR):
        return RedirectResponse("/login", status_code=303)
    peers = pair.load_pairings(SHARED_DIR)
    return _render(
        "home.html",
        onion=state.onion,
        admin_user=state.admin_user,
        admin_password=state.admin_password,
        mcp_user=state.mcp_user,
        mcp_token=state.mcp_token,
        qr_data_url=qr_png_data_url(state.phone_payload()),
        # Per-field QRs so the user can scan one piece at a time with
        # their phone's camera, tap "copy", and paste into Element.
        # Each encodes the bare value (no extra prose) — the camera's
        # text preview shows just that field, which copies cleanly.
        homeserver_qr=qr_png_data_url(f"http://{state.onion}") if state.onion else "",
        username_qr=qr_png_data_url(state.admin_user or ""),
        password_qr=qr_png_data_url(state.admin_password or ""),
        # Phone cameras open https URLs natively, so these deep-link
        # straight into the Play Store / App Store on scan.  Element is
        # the messaging client (classic, not Element X); Orbot is the
        # Tor VPN that lets Element reach .onion addresses.  All four
        # are needed for the average user; we surface all four QRs.
        element_android_qr=qr_png_data_url(
            "https://play.google.com/store/apps/details?id=im.vector.app"
        ),
        element_ios_qr=qr_png_data_url(
            "https://apps.apple.com/app/element-messenger/id1083446067"
        ),
        orbot_android_qr=qr_png_data_url(
            "https://play.google.com/store/apps/details?id=org.torproject.android"
        ),
        orbot_ios_qr=qr_png_data_url(
            "https://apps.apple.com/app/orbot/id1609461599"
        ),
        peers=peers,
        mcp_grace_remaining_s=state.mcp_grace_remaining_s,
        recovery_passphrase=state.recovery_passphrase,
        principal="admin",
    )


# ---- first-boot setup (unauthenticated) -----------------------------------


@app.post("/setup")
async def do_setup(
    request: Request,  # noqa: ARG001 — kept so /setup signature matches /
    admin_username: str = Form(...),
    admin_password: str = Form(...),
    setup_token: str = Form(""),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    if state.complete:
        return RedirectResponse("/", status_code=303)

    if not state.onion:
        raise HTTPException(503, "Tor onion hostname is not yet available.")
    if not state.registration_secret:
        raise HTTPException(503, "Registration shared secret is missing.")

    # Out-of-band ownership proof: the operator finds this token in
    # `docker logs pureprivacy-wizard` (or via `pureprivacy info`) and
    # pastes it into the form. Refuses anyone who races the operator on
    # the loopback port.
    #
    # We only *verify* here — the on-disk token is removed at the very
    # end, after every Synapse registration has committed and the
    # sentinel file has been written.  Earlier versions consumed the
    # token before validating the form, so a typo or transient Synapse
    # error would burn the one-time token and lock the operator out.
    if not _verify_setup_token(setup_token):
        raise HTTPException(
            403,
            "Setup token missing or wrong. Run `pureprivacy info` (or "
            "`docker logs pureprivacy-wizard`) to find the one-time setup "
            "token for this box and paste it into the form.",
        )

    admin_username = admin_username.strip().lower()
    # Restrict to ASCII alphanumeric (plus - and _). Python's str.isalnum()
    # is unicode-aware, so without .isascii() we'd accept characters that
    # Synapse might normalize unpredictably.
    if (
        not admin_username
        or not admin_username.isascii()
        or not admin_username.replace("-", "").replace("_", "").isalnum()
    ):
        raise HTTPException(400, "Username must be ASCII alphanumeric (with - or _).")
    if len(admin_password) < 12:
        raise HTTPException(400, "Password must be at least 12 characters.")

    client = SynapseAdminClient(
        base_url=SYNAPSE_URL,
        registration_shared_secret=state.registration_secret,
    )

    # 1. Create the human admin user.
    try:
        admin_full_id = await client.register_user(
            username=admin_username,
            password=admin_password,
            admin=True,
        )
    except Exception as exc:
        log.exception("admin registration failed")
        raise HTTPException(500, f"Could not create admin user: {exc}") from exc

    # 2. Create the MCP bot user (non-admin; the human invites it to rooms).
    mcp_username = "pureprivacy-mcp"
    mcp_password = random_password(32)
    try:
        mcp_full_id = await client.register_user(
            username=mcp_username,
            password=mcp_password,
            admin=False,
        )
    except Exception as exc:
        log.exception("mcp bot registration failed")
        raise HTTPException(500, f"Could not create MCP bot user: {exc}") from exc

    # 3. Hand the bot's credentials over to the MCP container via /shared.
    write_mcp_bot_credentials(
        SHARED_DIR,
        homeserver_url="http://synapse:8008",
        user_id=mcp_full_id,
        password=mcp_password,
    )

    # 4. Generate a recovery key and persist its hash.
    recovery_key = recovery.generate_recovery_key()
    recovery.write_recovery_hash(SHARED_DIR, recovery.hash_recovery_key(recovery_key))

    # 5. Persist the human-readable summary so re-visits show the same info.
    mark_setup_complete(
        SHARED_DIR,
        admin_user=admin_full_id,
        admin_password=admin_password,
        mcp_user=mcp_full_id,
        recovery_passphrase=recovery_key,
    )

    # 6. Only NOW retire the one-time setup token.  Earlier failure
    #    paths (typo, weak password, transient Synapse error) bail out
    #    above with the token still on disk, so the operator can
    #    correct and retry without minting a new one.
    _invalidate_setup_token()

    log.info("setup complete: admin=%s mcp=%s", admin_full_id, mcp_full_id)

    # Auto-login: drop a session cookie so the operator lands on the
    # dashboard without an extra password prompt right after setup.
    response = RedirectResponse("/", status_code=303)
    auth.set_session_cookie(
        response,
        auth.issue_cookie(SHARED_DIR, admin_user=admin_full_id),
    )
    return response


# ---- login / logout --------------------------------------------------------


@app.get("/login")
def login_form(request: Request) -> Response:
    state = load_setup_state(SHARED_DIR)
    if not state.complete:
        return RedirectResponse("/", status_code=303)
    if auth.authenticated_principal(request, SHARED_DIR):
        return RedirectResponse("/", status_code=303)
    return _render("login.html", admin_user=state.admin_user, error=None)


# Per-IP login rate limiter.  In-memory deque of attempt timestamps,
# capped at LOGIN_RATELIMIT_MAX in any LOGIN_RATELIMIT_WINDOW_S window.
# Once tripped, the client is told to back off; this is a soft block and
# resets on wizard restart, which is fine for a single-user appliance.
LOGIN_RATELIMIT_MAX = 5
LOGIN_RATELIMIT_WINDOW_S = 60
_login_attempts: dict[str, list[float]] = {}


def _login_rate_limit_check(ip: str) -> bool:
    """Return True if `ip` is allowed to attempt login now."""
    now = time.time()
    window = now - LOGIN_RATELIMIT_WINDOW_S
    history = [t for t in _login_attempts.get(ip, []) if t >= window]
    if len(history) >= LOGIN_RATELIMIT_MAX:
        _login_attempts[ip] = history
        return False
    history.append(now)
    _login_attempts[ip] = history
    return True


@app.post("/login")
def login_submit(
    request: Request,
    password: str = Form(...),
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    if not state.complete:
        return RedirectResponse("/", status_code=303)
    client_ip = request.client.host if request.client else "unknown"
    if not _login_rate_limit_check(client_ip):
        # Same constant-time delay as a miss — refuse to leak whether the
        # password would have been correct.
        time.sleep(0.5)
        return _render(
            "login.html",
            admin_user=state.admin_user,
            error=f"Too many login attempts from {client_ip}. Try again in a minute.",
        )
    matched = auth.password_matches(state.admin_password, password)
    # Sleep on both paths so the response time does not betray a hit vs
    # miss to a no-cookie attacker. password_matches itself is already
    # constant-time via compare_digest.
    time.sleep(0.5)
    if not matched:
        return _render(
            "login.html",
            admin_user=state.admin_user,
            error="That admin password is wrong.",
        )
    response = RedirectResponse("/", status_code=303)
    auth.set_session_cookie(
        response,
        auth.issue_cookie(SHARED_DIR, admin_user=state.admin_user or "admin"),
    )
    return response


@app.post("/logout")
def logout(_csrf: None = Depends(_csrf_protect)) -> Response:
    response = RedirectResponse("/login", status_code=303)
    auth.clear_session_cookie(response)
    return response


# ---- people (user management) ---------------------------------------------


@app.get("/people")
async def people_list(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    users = await admin_cli.list_users(state)
    return _render(
        "people.html",
        users=users,
        admin_user=state.admin_user,
        mcp_user=state.mcp_user,
        principal=principal,
    )


@app.get("/people/add")
def people_add_form(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),
) -> Response:
    return _render(
        "add_person.html",
        suggested_password=random_password(20),
        error=None,
        principal=principal,
    )


@app.post("/people/add")
async def people_add(
    request: Request,  # noqa: ARG001
    username: str = Form(...),
    password: str = Form(""),
    make_admin: str = Form(""),
    principal: str = Depends(require_session),
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    name = username.strip().lower()
    if (
        not name
        or not name.isascii()
        or not name.replace("-", "").replace("_", "").isalnum()
    ):
        return _render(
            "add_person.html",
            suggested_password=password or random_password(20),
            error="Username must be ASCII alphanumeric (with - or _).",
            principal=principal,
        )
    pw = password or None
    if pw is not None and len(pw) < 12:
        return _render(
            "add_person.html",
            suggested_password=pw,
            error="Password must be at least 12 characters.",
            principal=principal,
        )
    try:
        result = await admin_cli.add_user(
            state,
            name=name,
            admin=bool(make_admin),
            password=pw,
        )
    except admin_cli.UserManagementError as exc:
        return _render(
            "add_person.html",
            suggested_password=pw or random_password(20),
            error=str(exc),
            principal=principal,
        )
    except Exception as exc:  # noqa: BLE001 — surface raw to operator
        log.exception("user add failed")
        return _render(
            "add_person.html",
            suggested_password=pw or random_password(20),
            error=f"Could not create user: {exc}",
            principal=principal,
        )

    # Render the share-with-them page with a phone-onboarding QR for the
    # *new* user (not the admin).  Password only lives in this response;
    # closing the page = `pureprivacy user reset-password` to recover.
    payload = (
        "PUREPRIVACY\n"
        f"server: {result['homeserver_url']}\n"
        f"user: {result['user_id']}\n"
        f"password: {result['password']}\n"
    )
    return _render(
        "share_person.html",
        user_id=result["user_id"],
        password=result["password"],
        homeserver_url=result["homeserver_url"],
        is_admin=result["admin"],
        qr_data_url=qr_png_data_url(payload),
        principal=principal,
    )


@app.post("/people/{name}/reset-password")
async def people_reset_password(
    request: Request,  # noqa: ARG001
    name: str,
    principal: str = Depends(require_session),
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    try:
        result = await admin_cli.reset_user_password(state, name=name)
    except Exception as exc:  # noqa: BLE001
        log.exception("reset-password failed for %s", name)
        raise HTTPException(500, f"Could not reset password: {exc}") from exc
    return _render(
        "share_person.html",
        user_id=result["user_id"],
        password=result["password"],
        homeserver_url=(
            f"http://{state.onion}" if state.onion else SYNAPSE_URL
        ),
        is_admin=False,  # we don't track admin flag through this path
        qr_data_url=qr_png_data_url(
            "PUREPRIVACY\n"
            f"server: http://{state.onion}\n"
            f"user: {result['user_id']}\n"
            f"password: {result['password']}\n"
        ),
        principal=principal,
        reset=True,
    )


@app.post("/people/{name}/remove")
async def people_remove(
    request: Request,  # noqa: ARG001
    name: str,
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    try:
        await admin_cli.remove_user(state, name=name)
    except admin_cli.UserManagementError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("remove failed for %s", name)
        raise HTTPException(500, f"Could not deactivate: {exc}") from exc
    return RedirectResponse("/people", status_code=303)


# ---- pairing ---------------------------------------------------------------


@app.get("/pair")
def pair_view(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    if not state.onion:
        raise HTTPException(409, "Onion hostname not yet available.")
    # Stable code across reloads — the wizard will only mint a new one on
    # explicit operator action (POST /pair/regenerate) or on expiry.
    code = pair.load_or_mint_code(SHARED_DIR, state.onion)
    blob = pair.encode_code(code)
    peers = pair.load_pairings(SHARED_DIR)
    return _render(
        "pair.html",
        onion=state.onion,
        pair_blob=blob,
        pair_qr=qr_png_data_url(blob),
        pair_expires_at=code["expires_at"],
        peers=peers,
        principal=principal,
    )


@app.post("/pair/regenerate")
def pair_regenerate(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    pair.discard_active_code(SHARED_DIR)
    return RedirectResponse("/pair", status_code=303)


async def _apply_federation_change(reason: str) -> None:
    """Restart Synapse so a pairings.json change takes effect.

    Synapse's federation_domain_whitelist is rendered from
    /shared/pairings.json on every container start (see
    docker/synapse/render_config.py).  No live reload — restarting is the
    cheapest correct option.

    Raises HTTPException on failure with a message safe to show the operator.
    """
    docker = docker_default_client()
    if not docker.available():
        raise HTTPException(
            500,
            "Wizard cannot reach the docker socket — change saved, but "
            "Synapse was NOT restarted.  Run `pureprivacy restart synapse` "
            "manually so the new federation list takes effect.",
        )
    try:
        await docker.restart(SYNAPSE_CONTAINER, timeout_s=30)
        await docker.wait_healthy(SYNAPSE_CONTAINER, timeout_s=120)
    except DockerUnavailable as exc:
        raise HTTPException(500, str(exc)) from exc
    except RuntimeError as exc:
        log.exception("synapse restart failed (%s)", reason)
        raise HTTPException(
            500,
            f"Change saved but Synapse failed to restart cleanly: {exc}. "
            "Run `pureprivacy logs synapse` and `pureprivacy restart synapse` "
            "to recover.",
        ) from exc


@app.post("/pair/accept")
async def pair_accept(
    request: Request,  # noqa: ARG001
    pair_code: str = Form(...),
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    state = load_setup_state(SHARED_DIR)
    try:
        code = pair.decode_code(pair_code)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid pair code: {exc}") from exc
    if code["onion"] == state.onion:
        raise HTTPException(400, "Refusing to pair this box with itself.")
    try:
        pair.save_pairing(SHARED_DIR, code)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    log.info("paired with %s; restarting synapse", code["onion"])
    await _apply_federation_change(reason=f"add {code['onion']}")
    log.info("federation now active with %s", code["onion"])
    # Drop the active code we offered — peer is paired, so it would just be
    # confusing to keep showing the same code.  Reload mints a fresh one.
    pair.discard_active_code(SHARED_DIR)
    return RedirectResponse("/pair", status_code=303)


@app.post("/pair/remove")
async def pair_remove(
    request: Request,  # noqa: ARG001
    onion: str = Form(...),
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    if not pair.remove_pairing(SHARED_DIR, onion):
        raise HTTPException(404, "No such peer")
    log.info("unpaired %s; restarting synapse", onion)
    await _apply_federation_change(reason=f"remove {onion}")
    log.info("federation closed for %s", onion)
    return RedirectResponse("/pair", status_code=303)


# ---- MCP token rotation ---------------------------------------------------


@app.post("/rotate-token")
def rotate_mcp_token(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    token_path = SHARED_DIR / "secrets" / "mcp_bearer_token"
    prev_path = SHARED_DIR / "secrets" / "mcp_bearer_token.prev"

    # Stash the current token so already-deployed agents have a grace window
    # to migrate.  The MCP middleware honors the .prev file for
    # MCP_TOKEN_GRACE_SECONDS (default 10 minutes); after that it stops
    # accepting it.  No active cleanup needed: stale .prev is just ignored.
    if token_path.is_file() and token_path.stat().st_size > 0:
        prev_path.write_bytes(token_path.read_bytes())
        prev_path.chmod(0o600)
        # Touch mtime explicitly: read_bytes/write_bytes may not bump it on
        # all filesystems, and the grace window is mtime-based.
        now = time.time()
        os.utime(prev_path, (now, now))

    new_token = stdlib_secrets.token_hex(32)
    # Atomic write via tmp + rename so the MCP server never reads a partial file.
    tmp = token_path.with_suffix(".tmp")
    tmp.write_text(new_token + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(token_path)
    log.info("MCP bearer token rotated; grace window for previous token armed")
    return RedirectResponse("/", status_code=303)


@app.post("/revoke-prev-token")
def revoke_prev_mcp_token(
    request: Request,  # noqa: ARG001
    principal: str = Depends(require_session),  # noqa: ARG001
    _csrf: None = Depends(_csrf_protect),
) -> Response:
    """Hard-revoke the previous MCP token before its grace window ends.

    Operator action for "the old token leaked, kill it now."  Anything
    using the previous token starts getting 403s on the next request.
    """
    prev_path = SHARED_DIR / "secrets" / "mcp_bearer_token.prev"
    if prev_path.is_file():
        prev_path.unlink()
        log.warning("MCP bearer token grace window revoked early")
    return RedirectResponse("/", status_code=303)


# Recovery key has no separate route: once the operator is logged in, the
# dashboard renders it directly (it's persisted plaintext in
# .setup-complete and the auth gate is the operator's admin password).
# done.html still hides the value behind a click-to-reveal for shoulder-surf
# protection — that's pure JS, no server round trip.
