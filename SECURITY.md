# Security Policy

## Reporting a vulnerability

If you find a security bug in PurePrivacy, please **do not open a public issue**.
Email the maintainers at `security@<your-domain>` (or open a
[GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories)
on the repository) with:

- A description of the issue
- Steps to reproduce
- The PurePrivacy version (`git rev-parse HEAD` from your checkout, or the
  release tag)
- Whether you'd like public credit when we publish a fix

We aim to acknowledge reports within 72 hours.

## Threat model (v0.1.x)

PurePrivacy is designed to protect:

- **Message contents in transit and at rest on the homeserver**, via Matrix's
  Olm/Megolm end-to-end encryption between the user's clients (phone, desktop)
  and the MCP bot user.
- **Server identity and reachability**, via Tor hidden services. The box does
  not advertise a public IP; an attacker cannot directly probe it without
  knowing its `.onion`.  PurePrivacy is Tor-only by design — there is no
  clearnet exposure path, no public DNS record, no inbound port forwarding.
- **Federation traffic** rides Tor by default (privoxy → tor:9050).
  Pair codes are exchanged out-of-band by operator-readable QR (TOFU by
  eyeballs); Synapse's normal server-key exchange takes over once
  federation begins.

PurePrivacy is **not** designed to protect against:

- A compromised host. If the attacker has root on the box, they have your
  Synapse database, Olm key store, the recovery-key hash, the MCP bearer,
  the admin password (stored plaintext in `/shared/.setup-complete` mode
  0600), and the cached admin access token.  Disk encryption is your
  responsibility.
- Metadata leakage from the user's Tor entry guard. Tor is not a
  silver bullet; read the Tor Project's threat model.
- An attacker who has joined a room. Megolm's forward secrecy stops at the
  room boundary — anyone in the room can read the room.
- The MCP bot's host machine. The bot holds Megolm keys for every room it
  has been invited to. Treat the box as a trusted device, the same way you
  treat your phone.
- Anyone who has your **recovery key**.  Treat it the same as a root
  password: it can reset the admin password without prior auth.

## Known issues in v0.1.x

Carried forward from the prior `pureprivacy2docker` security audit
(2026-02-15) and reviewed for the v0.1 release:

| ID  | Severity | Issue                                                                                  | Status                                                                |
|-----|----------|----------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| H1  | High     | No multi-user RBAC in the wizard — anyone with `127.0.0.1:8088` access is admin        | Mitigated in v0.1.x: ongoing routes (`/people`, `/pair`, `/rotate-token`) require a cookie issued by `/login` against the admin password.  Loopback binding is still defense-in-depth.  CLI scripts use a separate token at `/shared/secrets/cli_token`. |
| H3  | High     | Wizard stores the admin password in `/shared/.setup-complete` for re-display           | Mitigated by file mode `0600` and docker volume isolation.  v0.2 will encrypt it under the recovery key. |
| H5  | High     | MCP bearer token stored plaintext in the secrets volume                                | Mitigated: rotation via wizard is instant, with a 10-minute grace window.  Use `Revoke previous token now` for compromise. |
| H6  | High     | Wizard mounts `/var/run/docker.sock` so it can restart Synapse on pair changes         | Loopback-only HTTP surface.  If you rebind `WIZARD_PORT` to a non-loopback interface, you also expose the docker control plane — don't. |
| H7  | High     | Recovery key is a single secret that can reset admin without prior auth                | Hashed with PBKDF2-HMAC-SHA256 (600k iters).  Treat the plaintext as a sensitive secret; don't paste it into chat. |
| M3  | Medium   | Internal HTTP between wizard, Synapse, and MCP is unencrypted                          | Acceptable: confined to docker net.  `synapse-fed-proxy` adds TLS for lk-jwt's specific path. |
| M4  | Medium   | Pair codes are not signed; trust root is operator-verified QR (TOFU)                   | Verify the peer's onion through a side channel before pasting their code. |
| M5  | Medium   | Federation cert verification is bypassed for paired `.onion` peers                     | Per-peer (not blanket `*.onion`).  No clearnet peers exist — Tor-only. |
| M8  | Medium   | Wizard cookie is not `Secure` (no HTTPS on loopback)                                   | Documented; loopback only.                                            |

## What you should do

- **Back up everything** with `pureprivacy backup` and store the resulting
  tarball encrypted (it contains your Tor private key, Synapse signing key,
  Postgres, Olm keys, recovery hash — *every* secret).  `age -p` or
  `gpg --symmetric` are good options.
- **Write down the recovery key** that `pureprivacy init` (or the wizard
  done page) prints.  Without it, a forgotten admin password forces a
  full `pureprivacy reset`.
- **Back up your Element X recovery key** — without it, encrypted history is
  unrecoverable client-side regardless of what you do server-side.
- **Encrypt your host disk.** PurePrivacy's at-rest secrets are not designed
  to defeat physical access.
- **Verify peer onions out-of-band before pairing.**  The wizard's pair
  flow is QR-based but the codes themselves are unsigned in v0.1; a
  malicious side-channel could swap them.
- **Keep Docker images current.** Run `git pull && docker compose -p pureprivacy build && pureprivacy restart`
  monthly until we ship in-app update.
