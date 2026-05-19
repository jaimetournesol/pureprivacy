# udprelay — UDP-over-Tor relay shim (Phase 1a, exploratory).
# Built from the Go source in this directory.  Static binary, no
# runtime dependencies — runs on the same alpine base every other
# PurePrivacy sidecar uses.

# hadolint global ignore=DL3018
FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY frame.go socks5.go main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o /udprelay .

FROM alpine:3.20
RUN adduser -D -u 1000 udprelay
COPY --from=build /udprelay /usr/local/bin/udprelay
USER udprelay
ENTRYPOINT ["/usr/local/bin/udprelay"]
