#!/usr/bin/env bash
# Phase-0 smoke test for udprelay.
#
#   relay A (udp 127.0.0.1:40001) ──tcp 127.0.0.1:40010──► relay B (udp 127.0.0.1:40002)
#   relay B (udp 127.0.0.1:40003) ──tcp 127.0.0.1:40011──► relay A (udp 127.0.0.1:40004)
#
# We only exercise the A→B direction here; the inverse path is wired up
# but unused.  A `nc -u` listener on port 40002 should receive the
# original payload byte-identical.
set -euo pipefail
cd "$(dirname "$0")"

BIN="$(mktemp -d)/udprelay"
go build -o "$BIN" .

cleanup() {
    for p in "${A_PID:-}" "${B_PID:-}" "${NC_PID:-}"; do
        [[ -n "$p" ]] && kill "$p" 2>/dev/null || true
    done
    rm -rf "$(dirname "$BIN")"
}
trap cleanup EXIT

# Receiver — nc -u prints what arrives.
RECV_OUT="$(mktemp)"
(nc -u -l 127.0.0.1 40002 >"$RECV_OUT" 2>/dev/null) &
NC_PID=$!
sleep 0.2

# Relay B: TCP listen 40010, emit UDP to 127.0.0.1:40002 (the nc).
"$BIN" \
    --udp-listen 127.0.0.1:40003 \
    --tcp-listen 127.0.0.1:40010 \
    --peer-tcp   127.0.0.1:40011 \
    --udp-target 127.0.0.1:40002 \
    >/tmp/relay-b.log 2>&1 &
B_PID=$!

# Relay A: UDP listen 40001, ship TCP to relay-B at 40010.
"$BIN" \
    --udp-listen 127.0.0.1:40001 \
    --tcp-listen 127.0.0.1:40011 \
    --peer-tcp   127.0.0.1:40010 \
    --udp-target 127.0.0.1:40004 \
    >/tmp/relay-a.log 2>&1 &
A_PID=$!

sleep 0.5

PAYLOAD="hello-from-box-a-$(date +%s%N)"
printf '%s' "$PAYLOAD" | nc -u -w1 127.0.0.1 40001

# Give the chain a moment.
sleep 0.5

if grep -qF "$PAYLOAD" "$RECV_OUT"; then
    echo "PASS: payload made it through A→B"
    echo "  sent: $PAYLOAD"
    echo "  recv: $(cat "$RECV_OUT")"
    exit 0
else
    echo "FAIL: payload did not arrive at receiver"
    echo "  sent: $PAYLOAD"
    echo "  recv: $(cat "$RECV_OUT" 2>/dev/null || true)"
    echo "--- relay-a log ---"; cat /tmp/relay-a.log
    echo "--- relay-b log ---"; cat /tmp/relay-b.log
    exit 1
fi
