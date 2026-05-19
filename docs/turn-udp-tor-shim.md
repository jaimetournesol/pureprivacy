# UDP-over-Tor relay shim (spike)

**Status:** exploratory. Phase 0 only. Do not ship.

## Problem

Element Classic's 1:1 WebRTC always ALLOCATEs UDP relays. For
**same-instance** voice (both users on one PurePrivacy box) the relay
leg is local to coturn and the fix on `main` is enough.

For **cross-instance** voice (two paired boxes), the relay-to-relay
leg has to traverse *something* between the boxes — and the only
network path between them is Tor, which carries TCP. UDP can't ride
Tor's SOCKS, and `torsocks` correctly refuses UDP `sendmsg`. So a
naive wrap of coturn doesn't move the problem.

## Approach

A small Go sidecar per box (`udprelay`) bridges the relay leg:

```
coturn-A ─UDP→ udprelay-A ═TCP/Tor═ udprelay-B ─UDP→ coturn-B
```

Each shim:

1. Listens UDP locally for its coturn's relay traffic.
2. Frames each datagram onto a long-lived TCP stream and ships it
   through Tor SOCKS5 (`tor:9050`) to the peer's onion endpoint.
3. On the other side, decodes frames and emits UDP locally to the
   peer's coturn.

Frame format (Phase 0 minimum):

```
+--------+--------------------+
| len(2) | UDP payload (≤64k) |   length is big-endian, excludes the
+--------+--------------------+   2 header bytes.
```

Phase 1 extends this with `{src_ipv6, src_port, dst_ipv6, dst_port}`
so the receiving shim can preserve coturn's session keying.

## Addressing

Each shim is reachable on a deterministic IPv6 derived from its
`.onion`, OnionCat-style:

```
prefix: fd87:d87e:eb43::/48
suffix: lower 80 bits of SHA-256(onion-address)
```

The pairing flow already exchanges onions, so no extra config needed —
both sides compute the same IPv6 for the peer.

`external-ip` on each coturn becomes the local shim's IPv6, so the
relay candidate that gets put on the wire via Matrix federation is
something the other side can actually route to (it ends up at the
remote shim, which forwards back to coturn).

## Phases

- **Phase 0 (this branch).** Framing + a working two-instance UDP↔TCP
  bridge on this Mac, with no Tor and no coturn. Smoke test: a UDP
  packet sent into `udprelay-A` arrives at the configured local target
  of `udprelay-B` byte-identical.
- **Phase 1.** Replace `--peer-tcp` with `--peer-onion`, dial through
  Tor SOCKS5. Run two PurePrivacy boxes (one to be stood up), make a
  real federated Element Classic call work end-to-end. This is where
  we'll learn whether latency is tolerable.
- **Phase 2.** OnionCat-style IPv6, TUN device so coturn can `bind()`
  on the shim's IPv6 directly. Integration with the pairing flow.
  Docker compose entry. Tests.
- **Phase 3.** Production-shape: graceful reconnects, per-peer state,
  metrics, docs, PR for review.

## Non-goals

- Replacing coturn. The shim is strictly the relay-leg transport.
- Federated group voice. That's LiveKit / MatrixRTC's job and lives
  under the `--voice` profile.
- Carrying TCP. The relay leg coturn opens is UDP; this shim is for
  UDP only.

## Out of scope until later

- Authentication of the peer-shim TCP connection. The shim assumes the
  peer's onion is the trust root (same as PurePrivacy's existing
  pairing model). A shared HMAC over each frame is a reasonable
  hardening step in Phase 2.
- Multi-peer fan-out. Phase 0/1 is point-to-point; Phase 2 generalises.
