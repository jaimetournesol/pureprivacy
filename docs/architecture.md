# Architecture

```
┌─ PurePrivacy box ──────────────────────────────────────────────────────┐
│                                                                        │
│             ┌──────────┐                                               │
│             │   tor    │── SOCKS5 9050 ──┐                             │
│             │ .onion   │                 │                             │
│             └────┬─────┘                 ▼                             │
│                  │                ┌────────────┐                       │
│                  │                │  privoxy   │                       │
│                  │                │ HTTP→SOCKS │                       │
│                  │                └─────┬──────┘                       │
│                  ▼                      │ HTTPS_PROXY                  │
│             ┌────────────┐              │                              │
│             │  synapse   │◄─────────────┘                              │
│             │  Matrix    │── postgres                                  │
│             │  homeserver│                                             │
│             └─┬───┬───┬──┘                                             │
│   ┌───────────┘   │   └─────────┐                                      │
│   ▼               ▼             ▼                                      │
│ ┌──────┐    ┌────────────┐   ┌───────┐                                 │
│ │coturn│    │   mcp      │   │wizard │  loopback only:                 │
│ │ TURN │    │  server    │   │       │  127.0.0.1:8088 (wizard)        │
│ └──────┘    └─────┬──────┘   └───────┘  127.0.0.1:8089 (mcp)           │
│                   ▲                                                    │
│                   │ bot user                                           │
│                                                                        │
│ ─── voice profile (--voice) ────────────────────────────────────────── │
│   ┌────────┐   ┌──────────┐   ┌──────────────────┐                     │
│   │livekit │   │ lk-jwt   │   │ synapse-fed-proxy│ ── 172.30.0.13     │
│   │  SFU   │   │ service  │   │ TLS→synapse:8008 │                     │
│   └────────┘   └──────────┘   └──────────────────┘                     │
└────────────────────────────────────────────────────────────────────────┘
       ▲                                ▲
       │  via Tor                       │  via Tor (paired peers only)
       │                                │
   Element (phone)                 Another PurePrivacy box
```

## Service responsibilities

### Always running (default profile)

- **`tor`** — runs a v3 Hidden Service that maps the box's `.onion` to
  Synapse, Coturn, and (when active) LiveKit / lk-jwt.  Also exposes a
  SOCKS5 proxy (`tor:9050`) that privoxy uses to reach paired peers.
- **`privoxy`** — bridges Synapse's outbound HTTP federation client to
  Tor's SOCKS5 listener.  Synapse only understands `HTTP_PROXY` /
  `HTTPS_PROXY`, not raw SOCKS, so privoxy is the adapter.
- **`synapse`** — the Matrix reference homeserver.  Handles client/server
  API, federation API, media repository, push, and Olm/Megolm key
  distribution.  Federation traffic is routed through privoxy → Tor;
  the federation allowlist is rendered from `/shared/pairings.json` on
  every container start by `docker/synapse/render_config.py`.
- **`postgres`** — Synapse's database.
- **`coturn`** — TURN/STUN server for 1:1 voice calls.  Configured for
  TCP-only relay so it can traverse Tor.
- **`init`** — one-shot container that generates secrets (Postgres
  password, Synapse internal secrets, MCP bearer token, LiveKit API
  key/secret) on first boot.  Idempotent: subsequent boots are no-ops.
- **`wizard`** — web UI on `127.0.0.1:8088` (loopback only) and CLI
  backend (`wizard.admin_cli` is what `pureprivacy user`, `pair`, and
  `admin` shell out to).  Has `/var/run/docker.sock` mounted so it can
  restart Synapse after a pairing change without operator intervention.
- **`mcp`** — the MCP server.  Logs in as the bot user via matrix-nio,
  persists its Olm key store across restarts, exposes nine tools over
  Streamable HTTP at `127.0.0.1:8089/mcp`.  Honors a 10-minute grace
  window for the previous bearer token after rotation.

### `--voice` profile

- **`livekit`** — Selective Forwarding Unit on ports 7880 (WS) and 7881
  (TCP).  Forwards encrypted media without decrypting; the Megolm keys
  live on the clients.  TCP-only relay so it can ride a Tor tunnel.
- **`lk-jwt`** — element-hq's small Go service that converts a Matrix
  OpenID token into a short-lived LiveKit JWT.  Listens on 8080 inside
  the docker network; exposed at `${onion}:8082` over Tor.
- **`synapse-fed-proxy`** — small TLS-termination sidecar at
  `172.30.0.13` that mints a self-signed cert for the `.onion` and
  reverse-proxies HTTPS to `synapse:8008`.  lk-jwt's entrypoint adds an
  `/etc/hosts` override mapping the onion to this IP and trusts the
  cert, so lk-jwt's `matrix://<onion>` resolver works in Tor-only mode.
  See `docs/voice.md` for the full story.

## Network

Single bridge network `pureprivacy_net` on `172.30.0.0/24`.

| Container                       | IP                     | Notes                                  |
|---------------------------------|------------------------|----------------------------------------|
| `pureprivacy-synapse`           | `172.30.0.10` (static) | Tor's HiddenServicePort points here    |
| `pureprivacy-coturn`            | `172.30.0.11` (static) | Tor's HiddenServicePort points here    |
| `pureprivacy-livekit`           | `172.30.0.12` (static) | Tor's HiddenServicePort points here (voice profile) |
| `pureprivacy-synapse-fed-proxy` | `172.30.0.13` (static) | lk-jwt /etc/hosts override target (voice profile) |
| everything else                 | dynamic                |                                        |

Tor routes the `.onion`'s ports as follows:

| Onion port | Container         | Used by                              |
|-----------:|-------------------|--------------------------------------|
| 80, 8008   | synapse:8008      | Matrix client API + federation       |
| 8448       | synapse:8008      | Matrix federation (legacy port)      |
| 3478, 5349 | coturn:3478/5349  | TURN signaling                       |
| 49152-61   | coturn:49152-61   | TURN TCP relay                       |
| 7880, 7881 | livekit:7880/7881 | LiveKit (voice profile)              |
| 8082       | lk-jwt:8080       | OpenID-token → LiveKit JWT (voice)   |

Nothing is bound to the host except the loopback wizard (`127.0.0.1:8088`)
and loopback MCP (`127.0.0.1:8089`).  No service binds to a non-loopback
host interface; nothing is reachable from the public internet directly.

## Identity model

- **Server identity = `server_name`, locked at first boot** when Synapse
  mints its signing key.  It's always the `.onion` — the appliance is
  Tor-only.  The choice cannot be changed afterwards without
  `pureprivacy reset`.  Username `@admin:<server_name>` ties to that
  specific server.  If you destroy `pureprivacy_tor_data`, the onion
  changes and Matrix considers all your users invalid.
- **Server signing key** lives in `pureprivacy_synapse_data`.  Lose this
  and remote homeservers stop trusting your federation traffic.  Back it
  up (or use `pureprivacy backup`).
- **Recovery key** is minted at first setup, hashed with PBKDF2-HMAC-SHA256
  (600k iters), stored in `/shared/secrets/recovery_hash`.  The plaintext
  is shown once on the wizard done page (and re-displayable via
  `pureprivacy info --secrets`).  `pureprivacy admin reset-password
  PASSPHRASE` uses it to bootstrap a temporary recovery user with admin
  privileges, reset the original admin's password through the admin API,
  then deactivate the recovery user.
- **Per-user device keys** live on the user's client (Element — original
  recommended for v0.1, Element X also works) and on the bot's
  `pureprivacy_mcp_data` for the bot.

## Federation pairing

Federation is allowlist-only.  The wizard's `/pair` page (mirrored by
`pureprivacy pair create / accept / list / remove`) lets two boxes
exchange short-lived (15-minute) base64-encoded JSON pair codes:

```json
{"version": 1, "onion": "abc...d.onion", "expires_at": 1761234567, "nonce": "..."}
```

Trust root is the operator's eyeballs (the QR is read off two devices
they control, side-channel verified) — the codes are not Ed25519-signed
in v0.1.  Once a pair is accepted, `/shared/pairings.json` gains the
peer, the wizard restarts Synapse via the docker socket, and Synapse
re-renders `homeserver.yaml` (federation_domain_whitelist +
federation_certificate_verification_whitelist) on its way back up.  The
pair page blocks until Synapse is healthy again, so the operator never
needs to "now go restart Synapse" by hand.

## Threat model

In scope for PurePrivacy to defend against:

- **Network adversaries.**  Synapse and Coturn never expose a public IP.
  All traffic between phone and box is end-to-end encrypted by Matrix's
  Olm/Megolm and then onion-routed by Tor.
- **Other tenants on shared homeservers.**  There aren't any — the box
  is yours.
- **Server-side reads of message contents.**  Megolm encrypts message
  bodies before they reach Synapse.  Synapse stores ciphertext.

Out of scope:

- **Compromised host.**  Root on the host = full access to volumes =
  game over.  Disk encryption is your responsibility.
- **Tor itself.**  Your guard relay can see *that* you're talking to
  some onion service; it can't see *what* you're saying.  Read the Tor
  Project's threat model for the deeper picture.
- **Compromised in-room peer.**  Megolm protects the room boundary, not
  inside it: anyone who joined a room can read it.  Don't invite the
  attacker.
- **The MCP bot.**  It holds Megolm keys for every room it has joined.
  Treat the box as a trusted device (because it is).

See [SECURITY.md](../SECURITY.md) for the open-issues list and how to
report new ones.

## Tor-only by design

PurePrivacy is a Tor-only appliance.  A Tor-only deployment skips a long
list of operational complexity:

- No DNS or domain ownership.
- No Let's Encrypt automation.
- No SRV / `.well-known` delegation.
- No public-IP exposure decisions.
- No CGNAT/firewall workarounds.

There is no clearnet exposure path in v0.1.x.  The wizard binds to
`127.0.0.1` only; everything reachable from outside the host (phone,
federation peers, group voice) rides Tor.

## Why these specific dependencies?

- **Synapse** because it is the reference Matrix homeserver and is the
  only implementation that supports every feature we'd want to ship in
  the next year (MAS, Sliding Sync, Element Call, Element Server Suite
  parity).
- **matrix-nio** because it's the most mature Python Matrix client
  library and ships proper Olm/Megolm support via `python-olm`.
- **FastMCP** because it gives us a Flask-style decorator API on top of
  the official MCP Python SDK and handles transport negotiation for free.
- **Tor** because nothing else gives you "reachable from anywhere with
  zero firewall config" without trusting a third party.
