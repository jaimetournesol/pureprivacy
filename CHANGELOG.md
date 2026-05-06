# Changelog

All notable changes to PurePrivacy are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed (post-hardening review)

A second audit pass after the v0.1.0 hardening exposed a set of bugs
that the unit tests didn't reach because they don't import the
top-level wizard app or rebuild the docker images.  Every item below
was verified by bringing the full stack down and back up, then running
all six test layers green (Python unit + e2e + features + restart +
health + backup).

- **Wizard crash-loop on rebuild.** `wizard/server.py` referenced
  `csrf.csrf_protect` (the bare module attribute) on `/logout`, but
  `csrf.py` only exports a factory `make_csrf_protect()`.  The bound
  closure `_csrf_protect` was the right reference.  The running image
  predated the regression so production didn't show it; the next
  rebuild would have.  Added `tests/test_server_import.py` to fail
  fast on the same class of regression.
- **`/rotate-token` 422'd for CLI requests.** `csrf_protect` declared
  `csrf_token: str = Form("")` which made FastAPI parse a form body
  before the CLI-token bypass could run — bodyless POSTs from
  `pureprivacy admin rotate-*` and the test scripts failed.  Rewrote
  `csrf_protect` to read the form lazily, only on the browser path.
- **FastAPI mis-classified the dependency's `request` param.** With
  `from __future__ import annotations`, the inner factory's
  `request: Request` annotation is a string FastAPI's introspector
  can't resolve, so it was treated as a Query parameter and produced
  `{"missing","loc":["query","request"]}` 422s.  Set an explicit
  `__signature__` on the dep so FastAPI sees a real `Request` type.
- **`cap_drop: ALL` broke fresh-volume init for postgres / synapse /
  tor / coturn.** The hardening pass dropped every capability from
  every container, but those upstream images run their entrypoint as
  root, chown/chmod the data dir, then `gosu`-drop to a service user
  — which needs `CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETUID`,
  `SETGID`.  Symptoms on a fresh volume: `Operation not permitted` on
  `chmod /var/lib/postgresql/data`, `Permission denied` writing
  `/data/homeserver.yaml`.  Added an `*init-caps` YAML anchor and
  merged into all four services.
- **Coturn couldn't even `exec`.** The turnserver binary ships with
  `cap_net_bind_service=ep` as a file capability; with cap_drop:ALL
  the kernel refused `execve` because the file caps weren't in the
  process bounding set (`/usr/bin/turnserver: Operation not
  permitted`).  Added `NET_BIND_SERVICE` to coturn's `cap_add`.
  no-new-privileges still prevents the file caps from being applied,
  so the running effective set stays small.
- **MCP container couldn't read its own secrets.** The hardening pass
  added `USER 10001` to `mcp-server/Dockerfile`, but `init` writes
  `/shared/secrets/*` mode 0600 root-owned.  UID 10001 then can't
  read `mcp_bearer_token` or `mcp_bot_credentials.json`, and on
  upgrade can't read pre-existing 10001-owned files either (because
  cap_drop:ALL strips DAC_OVERRIDE).  Reverted to root inside the
  container — with `cap_drop: ALL`, `read_only: true`,
  `no-new-privileges: true`, in-container root has no usable
  privileges on the host, and avoids the cross-container ownership
  footgun.
- **Synapse refused federation through privoxy.**
  `homeserver.yaml.tmpl` listed `172.16.0.0/12` in
  `ip_range_blacklist`, which covers the docker subnet
  `172.30.0.0/24` Synapse uses to reach privoxy / fed-proxy /
  postgres / coturn.  Synapse applies the blacklist to its HTTP
  client (federation, well-known, key servers, media) and refused
  outbound to the proxy IP before it ever reached Tor.  Added
  `ip_range_whitelist: ['172.30.0.0/24']` to override.
- **`pureprivacy verify` falsely reported FAIL on healthy services.**
  The `bash -c '[[ $(container_running tor) … ]]'` calls spawned a
  subshell that didn't inherit the helper functions, so they
  resolved to "command not found" and the assertions failed silently.
  Added `export -f container_running container_health`.
- **Synapse advertised a livekit URL clients couldn't reach.** The
  `extra_well_known_client_content.org.matrix.msc4143.rtc_foci` block
  was rendered unconditionally; without `--voice`, livekit isn't
  running and Element X clients hammered an unreachable URL.  Made
  the block conditional on a `VOICE_ENABLED` env var (set by
  `pureprivacy up --voice`, propagated through compose).
- **Sync loop self-restart bug in `MatrixBot`.** A non-cancellation
  exception in `_sync_forever` spawned a fresh task and returned;
  the parent task pointer became stale and the bot silently stopped
  syncing.  Moved the try/except inside the loop.
- **Friendly errors instead of raw `KeyError` in MCP tools.**
  `bot.room(room_id)` raises `KeyError` when the bot isn't in the
  room; the MCP transport surfaced that as an opaque 500.  Wrapped
  in `_resolve_room()` which converts to a `ValueError` with an
  actionable message ("invite @pureprivacy-mcp to the room first").
- **MCP config no longer crash-loops on a corrupt credentials file.**
  `json.loads(open(creds_path))` was unguarded; a partial write left
  by a wizard crash would `JSONDecodeError` at startup.  Now logs and
  treats the container as "wizard hasn't run yet."  Same treatment
  for a corrupt `session.json` in `MatrixBot.start()`.
- **`pureprivacy up && reboot` could deadlock on systemd.** The unit
  declared `After=docker.service` but not Docker readiness;
  `pureprivacy up` could fire before the docker socket was actually
  serving.  Added an `ExecStartPre` that polls `docker info` for up
  to 120 s before declaring the unit started.
- **`install-systemd.sh` could install a unit pointing at the wrong
  path.** A future refactor that moved the `/opt/pureprivacy`
  placeholder would leave the `sed` rewrite a silent no-op.  Added
  pre- and post-validation around the substitution.
- **`scripts/install.sh` and friends preferred `python3` over
  `readlink -f` for symlink resolution.** Flipped the priority so
  GNU `readlink -f` is primary on Linux, with `python3` as the macOS
  fallback.  Eliminates a "Python missing → idempotent install
  silently writes the wrong link" foot-gun.
- **`mktemp` files leaked from `pair accept` / `pair remove` /
  `init`.** Added `trap 'rm -f …' EXIT` around each one so an aborted
  curl (under `set -e`, network blip) doesn't leave temp files
  behind.
- **`.pureprivacy-profile` was written non-atomically.** A crash mid-
  redirect would truncate the file and the next `pureprivacy up`
  would read garbage.  Switched to temp-write + rename.
- **Empty-token guards on `tr -d '[:space:]'` reads.** The CLI's
  `read_mcp_token`, `cli_token`, and `setup_token` reads silently
  returned "" on partial / empty files.  Now refuse with an
  actionable error when the token is missing or shorter than 32
  chars.
- **`pureprivacy/livekit` Dockerfile advertised UDP ports the SFU
  never binds.** Removed `EXPOSE 50000-50019/udp` and the
  `port_range_*` block from `livekit.yaml.tmpl` — Tor can't carry
  UDP, the config already forces TCP relay via `tcp_port: 7881`,
  and the well-known is now opt-in anyway.  Coturn's separate
  49152-49161 TCP range (which IS exposed via Tor) is unchanged.
- **`test-all.sh` claimed "all tests PASSED" when layers were
  skipped.** Added a `summarize()` helper that emits a yellow ⚠
  when `PUREPRIVACY_NO_DOCKER=1` or no Python ≥ 3.10 is available.
  Also extended Layer 1 to run `mcp-server/tests/` alongside the
  wizard tests.
- **`test-health.sh` SIGKILL test was permanently broken.**
  Docker 29.x treats `docker kill --signal=SIGKILL` as a user-
  initiated stop and bypasses `unless-stopped`, and Synapse's Python
  interpreter catches SIGABRT/SIGSEGV.  Reworked the test to assert
  the *policy* is correctly declared on every long-running service
  rather than try to trigger an unrecoverable crash from the test
  harness.
- **Misc docs.** `docs/voice.md` no longer says Element X is the only
  client for 1:1 voice (both clients work);
  `docs/mcp-integration.md` calls out the colon-vs-equals difference
  between Claude Code's `--header "Authorization: Bearer …"` and
  Codex's `--header "Authorization=Bearer …"`; README adds
  `pureprivacy wait`; CHANGELOG voice-scope claim no longer
  contradicts the shipping `--voice` profile; `SECURITY.md`
  reporting address points at GitHub Security Advisories instead of
  a `<your-domain>` placeholder.

### Security

Hardening pass before tagging v0.1.0. Findings IDs reference the
internal v0.1 audit (see `SECURITY.md`).

- **C1**: MCP `upload_file` / `download_file` now jail every path to
  `/data/uploads`. Absolute paths, `..` traversal, and symlinked
  components are refused. The bot ingests prompts from Matrix rooms;
  without this jail an LLM-driven payload could exfiltrate
  `/shared/secrets/*` or overwrite arbitrary container files.
- **C2**: MCP bot only auto-joins room invites from users on the local
  homeserver, plus an explicit `MCP_INVITE_ALLOWLIST` if set.
  Federated peers can no longer drag the bot into rooms.
- **H2**: Every container now runs with `cap_drop: [ALL]` and
  `no-new-privileges`. Wizard, MCP, and lk-jwt are `read_only` with a
  tmpfs at `/tmp`. MCP additionally runs as UID 10001.
- **H3**: Wizard session cookie is now `SameSite=Strict`. Every
  state-changing form carries an HMAC-signed CSRF token; routes also
  validate that `Origin` (or `Referer`) matches the wizard's host. The
  CLI-token bypass is preserved for `scripts/pureprivacy`.
- **H4**: New `pureprivacy admin rotate-cli-token` and
  `pureprivacy admin rotate-admin-token` commands. CSRF and CLI-token
  validators now refuse tokens shorter than 32 chars.
- **H5**: First-boot `/setup` requires a one-time setup token planted
  at startup. `pureprivacy info` (and `docker logs pureprivacy-wizard`)
  surface it. The token is consumed on first use.
- **H6**: MCP `send_message` no longer accepts a `formatted` HTML
  parameter — it would have let an LLM-controlled payload inject
  unsanitized markup into other clients.
- **M1**: Fixed `set -euo pipefail` + `grep -q` SIGPIPE bug in
  `scripts/pureprivacy` (postgres backup detection and other call
  sites).
- **M3**: `synapse-fed-proxy` cert validity dropped from 100 years to
  1 year, with auto-rotation when within 30 days of expiry. Switched
  RSA-2048 → Ed25519. Key file is `chmod 0600`.
- **M5/M12**: Wizard `/login` rate-limited to 5 attempts/minute per
  IP. Constant 0.5 s delay on every response so timing does not leak
  hit vs miss.
- **M6**: Removed comment in `docker/privoxy/config` that explained
  how to bypass Tor for federation — that path deanonymizes the
  operator and must not be a documented option.
- **M9**: All GitHub Actions pinned to commit SHAs (with `# vN`
  comments for readability) instead of floating tags.
- **M11**: SECURITY.md now documents the
  `ignore_unverified_devices=True` E2EE caveat.
- **L4**: LiveKit `enable_loopback_candidate` set to `false` —
  loopback ICE candidates were noise and information disclosure.
- **L7**: Username validation in `/setup` and `/people/add` now
  requires `.isascii()` so unicode-aware `.isalnum()` does not let
  through characters Synapse may normalize unpredictably.

### Added (UX, this pass)
- `scripts/install.sh` — symlinks `pureprivacy` into `~/.local/bin` (or
  `/usr/local/bin` with `--system`) so docs and the wizard's hints can
  refer to a bare `pureprivacy` command.  Idempotent; `--uninstall` to
  reverse.  Both `pureprivacy` and `install-systemd.sh` now resolve their
  own path through symlinks so a `pureprivacy` symlink on `$PATH` works.
- `pureprivacy verify` — active end-to-end self-test (Docker daemon up,
  containers healthy, Tor onion published, Synapse client API reachable,
  wizard/MCP `/healthz`, MCP bot logged in, .onion reachable through Tor
  SOCKS).  Distinct from the existing `doctor` which is a static dump.
- `pureprivacy backup --encrypt` — passphrase-encrypted backups via
  `openssl enc -aes-256-cbc -pbkdf2`.  `pureprivacy restore` auto-detects
  encrypted archives by extension and magic bytes.

### Changed (UX, this pass)
- **Voice profile is now sticky.**  `pureprivacy up --voice` records the
  choice in `.pureprivacy-profile`; subsequent `pureprivacy up` keeps
  voice running (instead of silently dropping it as `--remove-orphans`
  used to).  Pass `--no-voice` to drop it.
- **First-run progress.**  `up` no longer silences `docker compose` on
  first build, warns the operator that the initial build takes 5–10
  minutes, and emits a heartbeat dot every ~10 s while waiting on
  health checks.
- **Better error messages.**  `up` checks Docker version (refuses < 24)
  and the `compose` plugin; Tor "did not become healthy" prints likely
  causes (ISP blocks, slow first-boot, firewall) and a `logs tor` hint;
  Synapse 429 from the admin CLI is wrapped with a "wait ~10 s" message
  instead of dumping raw JSON.
- **Default `WAIT_TIMEOUT` is now 600 s** (was 300 s) so Pi-class hosts
  finish first-boot Synapse migrations without timing out.
- `reset` and `restore` now exit `0` when the operator cancels the
  confirmation prompt — cancellation isn't an error.
- `pureprivacy status` no longer paints normal startup yellow; uses dim
  grey for "starting up" and reserves yellow for genuine warnings.
- `pureprivacy logs --help` lists the available service names so the
  operator doesn't have to read the source.
- The `init` password prompt now explains where the password is stored,
  that it's printed once, and that `pureprivacy info --secrets` will
  reveal it again later.

### Changed (wizard UX)
- **Dashboard reorder** (`done.html`): recovery key and "save your
  password" warning sit immediately after the phone-connection block,
  above the destructive *Rotate MCP token* button.
- **Secrets are click-to-reveal consistently.**  Admin password, MCP
  bearer, and recovery key all hide behind a `<details>` summary on the
  dashboard so they don't show by default to a screen-share viewer.
- **People page** filters the MCP bot out of the human "People" list
  and shows it under a separate "System accounts" section, so operators
  don't accidentally try to remove it.
- **Pair codes are stable across page reloads.**  The wizard caches the
  active pair code in `/shared/active_pair_code.json` and a reload no
  longer mints a new one — only an explicit *Regenerate code* button
  (with a confirmation prompt) does.  Successful `/pair/accept` clears
  the cached code so the next view starts fresh.
- **Element guidance is consistent everywhere.**  README, installation,
  phone-setup, mcp-integration, the wizard dashboard, the share-person
  page, and the CLI's terminal QR all consistently recommend the
  original Element for v0.1, with Element X mentioned only as a
  documented alternative with caveats.
- **iOS Onion Browser VPN-on requirement** is now called out in
  phone-setup.md and the share-person page, plus added to the
  troubleshooting table.
- The login screen's recovery hint shows `<your-recovery-key>` instead
  of an `ABCD-EFGH-IJKL-MNOP` string that looked like a copy-pasteable
  literal.

### Fixed
- `scripts/pureprivacy` and `scripts/install-systemd.sh` now resolve
  `${BASH_SOURCE[0]}` through symlinks (via `python3 os.path.realpath`,
  with `readlink -f` and a no-op fallback) so a symlink on `$PATH` no
  longer breaks `ROOT_DIR`.

### Removed
- **Clearnet mode and the `clearnet` compose profile have been removed.**
  PurePrivacy is now Tor-only.  The Caddy reverse proxy, Let's Encrypt
  integration, and `MATRIX_DOMAIN` / `LE_EMAIL` / `TLS_MODE` /
  `TLS_FALLBACK_*` env vars are gone.  Operators who relied on the
  clearnet path should pin to `0.1.x-pre-tor-only`.
- `docker/caddy/`, `docs/clearnet.md`, `caddy_data` and `caddy_config`
  volumes, and the wizard's clearnet-status banner all gone.
- `pureprivacy up --clearnet` and `pureprivacy init --clearnet` flags
  removed.  `pureprivacy status` no longer reports a `clearnet:` field.

### Added (operator UX)
- Wizard `/people` page (cookie- or CLI-token-authenticated) for
  managing Matrix users from the browser instead of SSH.  Add / list /
  reset-password / remove, with a share-with-them page that hands the
  new user a phone QR.
- Wizard authentication via `/login` against the admin password,
  HMAC-signed cookie at `/shared/secrets/wizard_session_key`.
  State-changing routes (`/people/*`, `/pair/*`, `/rotate-token`) now
  require either the cookie or a CLI-token header
  (`X-PurePrivacy-CLI-Token`, value at `/shared/secrets/cli_token`).
- Pair-code countdown timer + Generate-fresh-code on expiry.
- Copy-to-clipboard buttons on every secret `<pre>` (token, onion,
  password, recovery key, pair code).

### Added (CLI surface)
- `pureprivacy init` — headless one-shot setup for boxes that don't have
  a browser handy.  Brings the stack up, prompts for an admin password
  (or generates one), creates the admin + MCP bot users, prints the
  homeserver URL as a terminal QR + copy-paste credentials.  Idempotent:
  re-running on a configured box just re-prints the summary.
- `pureprivacy user {add,list,remove,reset-password}` — Synapse user
  management without leaving the CLI.  Refuses to deactivate the admin
  or the MCP bot to avoid foot-guns.  `add` prints a per-user QR.
- `pureprivacy pair {create,list,accept,remove}` — CLI mirror of the
  wizard's `/pair` page.  `accept` and `remove` go through the wizard's
  HTTP endpoint so the auto-restart-Synapse path is shared with the
  browser flow.
- `pureprivacy admin reset-password PASSPHRASE` — recover the admin
  password using the recovery key minted at first init, without wiping
  any data.
- `pureprivacy info --secrets` — dumps admin password + MCP bearer +
  recovery key when you need to retrieve them later.

### Added (UX polish)
- `Rotate MCP token` button in the wizard.  The MCP server reads the
  bearer token from disk on every request, so rotation is instant — no
  container restart.  A 10-minute grace window now lets agents migrate
  to the new token without a hard cut-off; the wizard surfaces a
  countdown and a *Revoke previous token now* button for the
  compromised-token case.
- `pureprivacy backup [PATH]` and `pureprivacy restore PATH` commands
  that tarball every named volume.  Restored boxes come back with the
  same onion identity, admin user, room state, and MCP bot keys.
- Recovery key minted at first setup and shown on the wizard's done
  page.  Hashed with PBKDF2-HMAC-SHA256 at 600k iterations and stored
  in `/shared/secrets/recovery_hash`.
- Wizard `/pair/accept` and `/pair/remove` now restart Synapse via the
  docker socket and block until it's healthy again, so the new
  federation list takes effect immediately — no more "now SSH in and
  run `pureprivacy restart synapse`".  Synapse-restart progress is
  reflected in the pair page UI.
- `pureprivacy up` end-of-run summary now surfaces the pair page, voice
  readiness, and the paired-peer count.

### Changed
- `federation_certificate_verification_whitelist` is now rendered
  per-peer instead of a blanket `["*.onion"]`.
- Wizard caches the admin access token in
  `/shared/secrets/admin_access_token` (mode 0600) so consecutive
  `pureprivacy user …` calls don't re-trigger Synapse's login rate
  limit.  Stale tokens are detected via `/whoami` and re-issued.

### Changed (other)
- Renamed docker-compose volumes to drop the redundant `pureprivacy_`
  prefix (compose project name already provides it).  On-disk volume
  names go from `pureprivacy_pureprivacy_*` to `pureprivacy_*`.
  Operators who installed pre-release builds need to wipe and re-run
  `pureprivacy up`.
- MCP container no longer crashes on first boot when the wizard hasn't
  run yet.  It boots into a "waiting for setup" state, polls for the
  bot credentials file, and brings the bot online as soon as the wizard
  writes them.  `/healthz` reports `wizard_run` and `matrix_bot_ready`
  so an operator can see what stage the box is in.

### Added (group voice — see `docs/voice.md`)
- Optional MatrixRTC group voice/video behind the `voice` compose
  profile: `pureprivacy up --voice` brings up LiveKit SFU + element-hq's
  `lk-jwt-service` + a `synapse-fed-proxy` sidecar.  Synapse advertises
  the LiveKit URL via `org.matrix.msc4143.rtc_foci` in its
  `.well-known/matrix/client` so MatrixRTC-aware clients (Element X 1.6+
  and Element Call) pick it up automatically.
- New `livekit_api_key` and `livekit_api_secret` are generated by the
  init container and shared between LiveKit and lk-jwt-service.
- Tor `HiddenServicePort` entries forward LiveKit (7880, 7881) and
  lk-jwt-service (8082) so phones over Orbot can reach them.
- New `synapse-fed-proxy` sidecar gives lk-jwt-service a TLS-terminated
  path to Synapse via `/etc/hosts` + a trusted self-signed CA.  This
  works around the upstream `matrix://` resolver bypassing `HTTPS_PROXY`
  so Tor-only group voice now works end-to-end without waiting on an
  upstream patch.

### Added (federation)
- Box-to-box pairing via wizard at `/pair`.  Each box mints a 15-minute
  pair code (base64-encoded JSON), shows it as both text and a QR.
  Accepting a peer's code writes them into `pairings.json` and renames
  Synapse's `federation_domain_whitelist` on next restart so the two
  boxes can federate over Tor.  Replay-protected via single-use nonces.
- `privoxy` service that bridges Synapse's outbound HTTP federation
  client to Tor's SOCKS5 listener, so federation traffic rides the
  same .onion fabric clients use.
- `federation_certificate_verification_whitelist: ["*.onion"]` is now
  set automatically when at least one peer is paired — Tor hidden
  services don't have publicly-trusted certs, and the QR exchange is
  the trust root.
- Synapse config rendering switched from `envsubst` to a small Python
  script so the federation whitelist can be a real list, not a scalar.

## [0.1.0] - 2026-05-05

First public release.

### Added
- Tor-only Matrix homeserver appliance based on Synapse, Postgres, and Tor.
- First-boot web wizard at `127.0.0.1:8088` that mints the admin user, prints
  a phone-onboarding QR, and issues an MCP bearer token.
- 1:1 voice via Coturn over TCP relay (Tor-friendly).
- PurePrivacy MCP server exposing `list_rooms`, `get_room_history`,
  `search_messages`, `send_message`, `list_unread`, `get_room_members`,
  `mark_read`, `upload_file`, `download_file`. Streamable HTTP transport,
  bearer-token auth.
- End-to-end encrypted Matrix messaging via the user's Element mobile client
  (the original Element is the recommended v0.1 client; Element X also works
  but its sliding-sync over Tor is rougher).
- The bot user that backs the MCP server runs `matrix-nio` with `libolm` and
  persists its device + key store across restarts.
- Documentation: phone setup (Element + Orbot/Onion Browser), MCP
  integration for Claude Code, Codex, Cursor, and Cline, architecture
  overview, threat model.

### Known issues
See [SECURITY.md](SECURITY.md) for the full list. Highlights:
- The MCP bot user holds Megolm keys for any room it has been invited to —
  treat it as a trusted device.
- Group voice (MatrixRTC / LiveKit) ships behind the opt-in `voice`
  compose profile (`pureprivacy up --voice`); it is not on by default
  in v0.1 and is the rougher path of the two voice surfaces — see
  [docs/voice.md](docs/voice.md) for the Tor-imposed caveats.
- Federation is technically possible but not the v0.1 hero path.
- The wizard does not re-key after compromise; rotate manually.
