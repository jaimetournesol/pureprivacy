# Installation

PurePrivacy is a Docker Compose stack.  You install it once, point your phone
and your agent at it, and forget it exists.

## Prerequisites

- **Docker 24+** with the `docker compose` plugin (Docker Desktop on macOS
  and Windows; the standard Docker Engine packages on Linux).  `pureprivacy`
  checks the version on every run and refuses to continue if it's too old.
- **`git`** for cloning the repo.
- **About 2 GB of free RAM** at idle, ~3 GB during the first build.
- **About 5 GB of free disk** for images + your message store.
- **Outbound network access** so Tor can reach the Tor relay network.  No
  inbound port forwarding required — that's the whole point.

If you plan to run it on a Raspberry Pi, a Pi 4 (4 GB) or Pi 5 is
comfortable.  Anything older is going to struggle with Synapse's first-run
database migrations.

## Install

There are two paths.  Both leave you with the same setup; pick whichever
fits how you connect to the box.

### Option A: headless one-shot (CLI)

For boxes you reach over SSH, or anywhere you'd rather not tunnel a
browser to loopback:

```bash
git clone https://github.com/jaimetournesol/pureprivacy
cd pureprivacy
./scripts/install.sh             # one-time: puts `pureprivacy` on $PATH
pureprivacy init
```

`init` builds the images (5–10 minutes on first run, longer on a Pi),
brings the stack up, waits for Tor to mint the `.onion`, then prompts
for an admin password (or generates one) and prints:

- the homeserver URL as a terminal QR (so Element can scan it),
- the admin username + password,
- the MCP endpoint, bearer token, and a paste-ready `claude mcp add`,
- a **recovery key** (write this down — it's how you reset the admin
  password without wiping the box; re-displayable later via
  `pureprivacy info --secrets`).

Re-running `init` on a configured box just re-prints the summary; it
won't overwrite anything.  Pass `-y` to non-interactively generate a
password.

`./scripts/install.sh` is optional — if you skip it, every command
also works as `./scripts/pureprivacy <cmd>` from inside the repo.

### Option B: browser wizard

If you'd rather click than type:

```bash
git clone https://github.com/jaimetournesol/pureprivacy
cd pureprivacy
./scripts/install.sh             # one-time: puts `pureprivacy` on $PATH
cp .env.example .env             # optional — defaults are fine
pureprivacy up
open http://127.0.0.1:8088       # local browser only — never expose this
```

The wizard asks for the admin username and password, and shows the same
information `init` prints (including the recovery key).

The first run takes a few minutes — it pulls and builds the images, mints
your `.onion` address, runs Synapse's database migrations, and starts the
MCP bot.  Subsequent boots are under 30 seconds.

Either way, when setup completes, `pureprivacy info` prints:

```
Your PurePrivacy box is ready.
  Onion:        http://<your-onion>.onion
  Setup info:   http://127.0.0.1:8088  (admin credentials, QR, MCP token)
  Pair box:     http://127.0.0.1:8088/pair  (no peers paired)
  MCP endpoint: http://127.0.0.1:8089/mcp
```

Run `pureprivacy info --secrets` later to re-display the admin password,
MCP bearer, and recovery key.

## Surviving a host reboot

Every container has `restart: unless-stopped`, so:

- If you **leave the stack running** and reboot the host, Docker brings the
  containers back automatically when its daemon comes up.  No action needed.
- If you **stopped the stack** with `pureprivacy stop` or `pureprivacy down`,
  the containers stay down across reboot and you need to bring them back
  with `pureprivacy up` (or `start`).

### Linux — systemd

For unconditional autostart on a Linux host (start the stack at boot
regardless of whether you previously stopped it), install the systemd
unit:

```bash
sudo ./scripts/install-systemd.sh
sudo systemctl start pureprivacy
```

The unit calls `pureprivacy up` on every boot and `pureprivacy stop` on
shutdown.  This *overrides* a previous `pureprivacy stop` — it brings
the stack back unconditionally.  Disable with
`sudo systemctl disable pureprivacy` if you want manual control.

### macOS — Docker Desktop

Enable *Settings → General → Start Docker Desktop when you log in* so
the daemon comes back automatically.  Then:

- If the stack was **running** when you rebooted: nothing more to do.
  `unless-stopped` containers come back on their own.
- If the stack was **stopped** (`pureprivacy stop`/`down`): you need to
  run `pureprivacy up` once after login to bring it back.  macOS doesn't
  have an equivalent of the Linux systemd "always start at boot" unit.

## Where things live

| Volume                          | Contents                                          |
|---------------------------------|---------------------------------------------------|
| `pureprivacy_tor_data`          | Tor hidden-service keys.  Lose this = new onion.  |
| `pureprivacy_postgres_data`     | Synapse's Postgres database (your messages).      |
| `pureprivacy_synapse_data`      | Synapse signing key + media + config.             |
| `pureprivacy_mcp_data`          | MCP bot's session + Olm/Megolm key store.         |
| `pureprivacy_shared`            | Inter-service secrets and the setup sentinel.     |

## Backups

```bash
pureprivacy backup            # plain tarball → ./backups/pureprivacy-YYYY-MM-DD-HHMMSS.tar.gz
pureprivacy backup --encrypt  # AES-256-CBC, prompts for a passphrase (recommended)
pureprivacy backup /path/to/somewhere.tar.gz
```

`backup` briefly stops the stack so the snapshot is consistent (Postgres
isn't writing mid-tar), then starts it again.  Total downtime ≈ 30 s.

The resulting tarball contains *all* secrets — your Tor hidden-service
private key, Synapse signing key, Postgres database, Olm/Megolm key store,
admin password, MCP bearer.  **Always encrypt it before sending it
anywhere.**  Use `--encrypt` for built-in passphrase encryption (uses
`openssl enc -aes-256-cbc -pbkdf2`, available on every supported host),
or your own tool:

```bash
age -p -o pureprivacy-2026-05-05.tar.gz.age pureprivacy-2026-05-05.tar.gz
# or
gpg --symmetric --cipher-algo AES256 pureprivacy-2026-05-05.tar.gz
```

To decrypt later:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 \
  -in pureprivacy-2026-05-05.tar.gz.enc \
  -out pureprivacy-2026-05-05.tar.gz
```

To restore:

```bash
pureprivacy down                            # stack must be down
pureprivacy restore /path/to/backup.tar.gz  # asks for confirmation
pureprivacy up
```

Restoring overwrites every PurePrivacy volume on the host.  The onion
identity, admin user, room state, and MCP bot's E2EE keys all come back
exactly as they were.

## Updating

```bash
git pull
pureprivacy down
docker compose -p pureprivacy build
pureprivacy up
```

We pin every base image in `.env.example`; bumping versions is a deliberate
release-time operation, not an automatic background pull.

## Recovering the admin password

`init` prints a recovery key at first setup (and stores its hash in
`/shared/secrets/recovery_hash`).  If you forget the admin password:

```bash
pureprivacy admin reset-password "<your-recovery-key>"
```

This logs in as a temporary recovery user, calls Synapse's admin
`reset_password` endpoint, deactivates the recovery user, and updates
`/shared/.setup-complete` with the new password.  No data wipe.

Lost the recovery key as well?  Last resort is `pureprivacy reset` — wipes
all volumes (onion, messages, keys) and starts over.

## Troubleshooting

| Symptom                                                | Fix                                                              |
|--------------------------------------------------------|------------------------------------------------------------------|
| `pureprivacy up` says `tor` did not become healthy     | Outbound TCP blocked, or your ISP blocks Tor.  Check `pureprivacy logs tor`; on networks that block Tor, you'll need bridges (`docker/tor/torrc` is where to add them). |
| Wizard page shows "Tor is still publishing the onion." | Wait 30 s and reload; first onion mint takes a few seconds       |
| MCP `/healthz` returns `matrix_bot_ready: false`       | Bot is still doing its initial Olm key upload — give it a minute |
| Group voice fails to connect                           | Make sure the `voice` profile is active (`pureprivacy up --voice`) — this brings the synapse-fed-proxy sidecar lk-jwt depends on |
| `pureprivacy user …` says rate-limited / HTTP 429      | Login rate-limit on Synapse; wait a few seconds and retry.  The wizard caches its admin token to avoid this on subsequent calls. |
| Docker version too old                                 | Need Docker 24+ with the `compose` plugin.  Older Docker Engines don't support all the compose v2 features the stack uses. |
| Pi 3 / older ARM hosts struggle on first build         | Synapse's first-run migrations need ~3 GB of RAM; Pi 4 (4 GB) or Pi 5 is the recommended floor. |
| `pureprivacy reset` is needed                          | Last resort — wipes everything, asks for confirmation            |

To check what's actually working end-to-end, run `pureprivacy verify` —
it actively probes the wizard, MCP bot, Synapse client API, and the
.onion via Tor.  For a static dump (containers, volumes, network)
suitable for bug reports, run `pureprivacy doctor`.
