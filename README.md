# PurePrivacy

**Your messages. Your hardware. Your keys.**

PurePrivacy turns any Linux box (a Raspberry Pi, an old laptop, a VPS) into a
self-hosted, end-to-end encrypted communication appliance. It runs a
[Matrix](https://matrix.org) homeserver behind a Tor hidden service so your
phone reaches it without port-forwarding, dynamic DNS, or trusting a public
gateway.

It also exposes a [Model Context Protocol](https://modelcontextprotocol.io)
server so your AI agent — Claude Code, Codex, Cursor, Cline, anything that
speaks MCP — can read and write your messages on your behalf.

> **Status:** v0.1 is the first public release. Expect rough edges.
> See [SECURITY.md](SECURITY.md) for the known-issues list.

## What you get

- **End-to-end encrypted** chat and 1:1 voice calls, courtesy of Matrix's Olm/Megolm.
- **Tor-only by default**: the box advertises a `.onion` address; nothing is
  exposed to the public internet. Federation, if you turn it on, also rides Tor.
- **Phone-ready**: scan a QR code from the setup wizard, install
  [Element](https://element.io/download) (the original — recommended for
  v0.1) and [Orbot](https://orbot.app/) (works on both Android and iOS),
  and you're chatting in under five minutes.  Element X also works but
  its sliding-sync over Tor is rougher in v0.1; see
  [docs/phone-setup.md](docs/phone-setup.md).
- **Agent-ready**: a built-in MCP server lets your local AI agent triage your
  inbox, draft replies, search history, and post messages — without any of it
  ever leaving your control.
- **Survives reboots.** It's an appliance. You install it once.

## Quickstart

Requires Docker 24+, `git`, and ~2 GB of free RAM (~3 GB during the
first build, ~5 GB of free disk).  First run takes 5–10 minutes on a
laptop, longer on a Pi — it builds the images, mints your onion, and
runs Synapse's first-time database migrations.

```bash
git clone https://github.com/jaimetournesol/pureprivacy
cd pureprivacy
./scripts/install.sh             # one-time: puts `pureprivacy` on your PATH
pureprivacy init                 # builds, starts, mints an onion,
                                 # creates the admin user, prints
                                 # everything you need.
```

If you'd rather not touch your PATH, every command also works as
`./scripts/pureprivacy <cmd>` from inside the repo.

`init` will:

1. Bring the stack up and wait for Tor to mint your `.onion` address.
2. Prompt for an admin password (or generate one).
3. Print a terminal QR with the homeserver URL for Element.
4. Print the MCP bearer token + paste-ready Claude Code config.
5. Print a **recovery key** — write it down somewhere safe.  It can
   reset the admin password without wiping the box; if you ever lose
   it, you can re-display it with `pureprivacy info --secrets`.

If you'd rather use the browser wizard, run `pureprivacy up` and open
`http://127.0.0.1:8088` instead.  Both paths produce the same outcome.
After setup, the same URL becomes a sign-in page — use it to add people
(*People → Add a person*), pair with another box, or rotate the MCP
token from a browser instead of the CLI.

## Day-to-day commands

(Replace `pureprivacy` with `./scripts/pureprivacy` if you skipped
`./scripts/install.sh`.)

```bash
pureprivacy status     # health, onion, setup state
pureprivacy info       # onion URL, MCP endpoint, where to point your phone
pureprivacy info --secrets    # also dump admin password + MCP bearer + recovery key
pureprivacy verify     # actively probe each service end-to-end
pureprivacy wait       # block until every service is healthy (good for scripts)
pureprivacy logs       # tail every service
pureprivacy logs synapse           # one of: tor, privoxy, postgres, synapse,
                                   # coturn, wizard, mcp (or with --voice:
                                   # synapse-fed-proxy, livekit, lk-jwt)
pureprivacy stop       # stop, keep containers (resume with `start`)
pureprivacy start
pureprivacy restart
pureprivacy down       # stop and remove containers; volumes survive
pureprivacy doctor     # diagnostics for bug reports

pureprivacy user add NAME [--admin]
pureprivacy user list
pureprivacy user reset-password NAME
pureprivacy user remove NAME

pureprivacy pair create        # mint a pair code for another box
pureprivacy pair accept CODE   # paste another box's code
pureprivacy pair list
pureprivacy pair remove ONION

pureprivacy admin reset-password PASSPHRASE  # use the recovery key

pureprivacy backup             # tarball every volume
pureprivacy backup --encrypt   # passphrase-encrypted tarball (recommended)
pureprivacy restore PATH       # restore from a tarball

pureprivacy reset      # WIPE EVERYTHING (asks first)
pureprivacy help
```

## Surviving a host reboot

Every container has `restart: unless-stopped`, so as long as the Docker daemon
comes back up, the stack returns automatically — **unless you stopped it first
with `pureprivacy stop` or `pureprivacy down`**.  In that case you bring it
back manually with `pureprivacy up`.

**On Linux**, install the systemd unit so `pureprivacy up` runs on every boot
regardless of how you left things:

```bash
sudo ./scripts/install-systemd.sh
sudo systemctl start pureprivacy
```

**On macOS** (Docker Desktop), enable
*Settings → General → Start Docker Desktop when you log in*.  Already-running
containers come back when the daemon does; if you previously ran
`pureprivacy stop` or `down`, you'll need `pureprivacy up` to bring the
stack back after reboot.

## Connecting your phone

See **[docs/phone-setup.md](docs/phone-setup.md)** for the full walkthrough,
or **[docs/screencasts.md](docs/screencasts.md)** for short video captures
of the four-step setup (admin login on web, invite a friend, admin phone
setup, friend phone setup) recorded against the friendly-home-page UI.
The short version: install Element (the original — recommended for v0.1),
install Orbot (Android **or iOS**), scan the QR.

## Connecting your agent

See **[docs/mcp-integration.md](docs/mcp-integration.md)** for ready-to-paste
config for the major frameworks. The short version, for Claude Code:

```bash
claude mcp add pureprivacy http://127.0.0.1:8089/mcp \
  --header "Authorization: Bearer <token-from-wizard>"
```

## Architecture

```
┌─ Your PurePrivacy box ─────────────────────────────────────────┐
│                                                                │
│   Tor hidden service ──► Synapse (Matrix) ──► Postgres         │
│              ▲               │                                 │
│              │               ├─ Coturn (1:1 voice)             │
│              │               │                                 │
│   privoxy ───┘               ├─ LiveKit + lk-jwt (group voice, │
│   (federation)               │  --voice profile)               │
│                              │                                 │
│                              └─ MCP Server ◄── your agent      │
│                                                                │
│   Wizard (127.0.0.1:8088, loopback only) — setup, people,      │
│                                            pair, MCP token     │
└────────────────────────────────────────────────────────────────┘
```

Compose profiles:
- **default**: tor, privoxy, postgres, synapse, coturn, wizard, mcp.  Nothing
  is bound to the host except the loopback wizard and loopback MCP.
- **`--voice`** adds livekit, lk-jwt, synapse-fed-proxy for MatrixRTC group calls.

PurePrivacy is Tor-only by design — there is no clearnet path, no public DNS,
no inbound port forwarding.  Your phone, your federation peers, and your
agent all reach the box through Tor (or, in the agent's case, through the
loopback MCP endpoint).

See **[docs/architecture.md](docs/architecture.md)** for the deeper read,
including the threat model and identity / recovery key model.

## License

PurePrivacy is licensed under the **GNU Affero General Public License v3.0**.
See [LICENSE](LICENSE). If you run a modified version as a service, you owe
your users the source.

## Contributing

Issues and PRs welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## Acknowledgements

PurePrivacy stands on the shoulders of [Matrix.org](https://matrix.org),
[Element](https://element.io), [The Tor Project](https://torproject.org),
[Coturn](https://github.com/coturn/coturn),
[matrix-nio](https://github.com/matrix-nio/matrix-nio),
[FastMCP](https://gofastmcp.com/), and the Model Context Protocol community.
