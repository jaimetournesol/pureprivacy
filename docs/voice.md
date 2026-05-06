# Voice and group calls

PurePrivacy supports two voice paths.  The default 1:1 path is always on;
group voice is opt-in behind the `voice` compose profile.

## 1:1 voice (default, always on)

Both the original Element and Element X use the standard Matrix VoIP
signaling: an `m.call.invite` event in the room kicks off a WebRTC
peer connection, and Coturn provides TURN/STUN for NAT traversal.
(For v0.1 we recommend the original Element overall — see
[docs/phone-setup.md](phone-setup.md) — but 1:1 voice works the same
in both clients.)

Coturn is configured for **TCP-only relay**, so all audio rides through
Tor's hidden service.  That works but adds latency: expect 200–400 ms
above what a direct WebRTC call would feel like.  Voice quality is fine
for a chat with a friend, choppy for fast back-and-forth.

## Group voice (MatrixRTC, opt-in)

Element X 1.6+ supports group calls via [MatrixRTC](https://element.io/blog/exploring-matrixrtc-real-time-communication-in-rooms/).
PurePrivacy ships the LiveKit SFU + `lk-jwt-service` from element-hq
behind the `voice` compose profile:

```bash
./scripts/pureprivacy up --voice
```

After this, Synapse advertises an `org.matrix.msc4143.rtc_foci` entry in
its well-known JSON pointing Element X at the `lk-jwt-service` URL.
Element X reads the well-known on login, sees the foci, and group calls
"just work" — assuming the deployment can validate the OpenID token
exchange (see caveats below).

### What's running

- **`livekit`** — the LiveKit SFU (Selective Forwarding Unit) on ports
  7880 (WS) and 7881 (TCP).  Forwards encrypted media without decrypting;
  the Megolm keys live on the clients.
- **`lk-jwt-service`** — element-hq's small Go service that converts a
  Matrix OpenID token into a short-lived LiveKit JWT.  Listens on 8080
  inside the docker network; exposed at `${onion}:8082` over Tor.

### How Tor-only group voice works

`lk-jwt-service` validates the user's OpenID token by calling back into
the Matrix homeserver.  It uses a `matrix://` URL scheme internally that
**does not respect `HTTPS_PROXY` env vars** — so it can't reach a
`.onion` homeserver through the privoxy → tor pipeline the rest of the
stack uses.

PurePrivacy works around this with a tiny `synapse-fed-proxy` sidecar
(see `docker/synapse-fed-proxy/`):

1. The sidecar (built from the Caddy base image as a small TLS
   terminator — no Let's Encrypt, no public exposure) runs in the
   `pureprivacy_net` docker network with a fixed IP (172.30.0.13), and
   reverse-proxies `https://*:443` and `https://*:8448` to
   `http://synapse:8008`.  At startup it mints a self-signed cert with
   the `.onion` as the CN/SAN.
2. The lk-jwt container's entrypoint, on each boot, reads
   `/shared/onion_hostname`, appends an `/etc/hosts` entry mapping
   `<onion>.onion` → `172.30.0.13`, and trusts the sidecar's CA via
   `update-ca-certificates`.
3. lk-jwt's `matrix://<onion>` resolver hits the local /etc/hosts
   entry, lands on the sidecar, the cert validates, and the OpenID
   userinfo fetch succeeds.

The sidecar is profile-gated with `voice`, so it only runs when group
voice is enabled.

## What works today, in summary

|                                    | Status         |
|------------------------------------|----------------|
| 1:1 audio (Element built-in)       | ✓ (TCP relay)  |
| 1:1 video                          | ✓ (laggy)      |
| Group call with `--voice`          | ✓              |
| MatrixRTC well-known advertisement | ✓              |

All paths ride Tor.  PurePrivacy does not expose voice on the public
internet.
