# Changelog

All notable changes to PurePrivacy are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
- Group voice (MatrixRTC / LiveKit) is out of scope for v0.1.
- Federation is technically possible but not the v0.1 hero path.
- The wizard does not re-key after compromise; rotate manually.
