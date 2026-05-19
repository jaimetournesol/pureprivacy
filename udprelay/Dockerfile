# udprelay — UDP-over-Tor relay shim (Phase 1a, exploratory).
# Built from the Go source in this directory.  Static binary, no
# runtime dependencies — runs on the same alpine base every other
# PurePrivacy sidecar uses.

# hadolint global ignore=DL3018
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /udprelay .

FROM alpine:3.20
# iproute2 supplies `ip` for TUN address + link config; tini reaps the
# few sh subprocesses we exec.  No netcat needed — the shim's TCP/UDP
# both go through Go stdlib.
RUN apk add --no-cache iproute2 tini
COPY --from=build /udprelay /usr/local/bin/udprelay
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh
# Run as root inside the container so the entrypoint can ioctl(/dev/net/tun)
# and `ip` can configure the TUN device.  Host-side hardening:
# cap_drop:ALL + only cap_add:NET_ADMIN (set in compose) keeps the
# blast radius small.
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
