#!/bin/sh
# Wait for the onion hostname to be written by the tor container, then
# exec udprelay with --local-onion populated from it.  TUN mode only
# (Phase 1b); UDP mode users skip this entrypoint by overriding cmd.
set -eu

SHARED="${SHARED:-/shared}"

if [ "${1:-}" = "--mode=tun" ] && [ -z "${UDPRELAY_LOCAL_ONION:-}" ]; then
    for _ in $(seq 1 120); do
        if [ -s "${SHARED}/onion_hostname" ]; then
            UDPRELAY_LOCAL_ONION="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
            export UDPRELAY_LOCAL_ONION
            break
        fi
        sleep 1
    done
    if [ -z "${UDPRELAY_LOCAL_ONION:-}" ]; then
        echo "udprelay: timed out waiting for ${SHARED}/onion_hostname" >&2
        exit 1
    fi
    exec /usr/local/bin/udprelay --local-onion="${UDPRELAY_LOCAL_ONION}" "$@"
fi

exec /usr/local/bin/udprelay "$@"
