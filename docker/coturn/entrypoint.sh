#!/usr/bin/env bash
# Coturn entrypoint: render the config from template using the shared
# secret + onion hostname, then exec coturn.
set -euo pipefail

SHARED="${SHARED:-/shared}"

# Wait for tor to publish both files we need.  onioncat_ipv6 is the
# OnionCat-derived IPv6 the cross-instance voice path uses as coturn's
# external-ip and relay-ip — without it, coturn's RELAY-ADDRESS in TURN
# replies would point at a non-routable docker-internal address.
for _ in $(seq 1 60); do
    if [[ -s "${SHARED}/onion_hostname" \
       && -s "${SHARED}/secrets/turn_shared_secret" \
       && -s "${SHARED}/onioncat_ipv6" ]]; then
        break
    fi
    sleep 1
done
if [[ ! -s "${SHARED}/onion_hostname" \
   || ! -s "${SHARED}/secrets/turn_shared_secret" \
   || ! -s "${SHARED}/onioncat_ipv6" ]]; then
    echo "coturn: required shared files missing (need onion_hostname, turn_shared_secret, onioncat_ipv6)" >&2
    exit 1
fi

export SERVER_NAME="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
export TURN_SHARED_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/turn_shared_secret")"
export ONIONCAT_IPV6="$(tr -d '[:space:]' < "${SHARED}/onioncat_ipv6")"

# Configure the OnionCat IPv6 on eth0 so coturn can bind() on it for
# relay sockets.  /128 because the udprelay sidecar (sharing this
# netns) owns the whole /48 onlink route via its TUN — we only need
# this single IPv6 to *exist* locally for bind().  Idempotent: ip
# returns 2 ("File exists") if we re-run after a restart, which we
# treat as success.
if ! ip -6 addr show dev eth0 | grep -q "${ONIONCAT_IPV6}/128"; then
    if out="$(ip -6 addr add "${ONIONCAT_IPV6}/128" dev eth0 2>&1)"; then
        echo "coturn: added ${ONIONCAT_IPV6}/128 to eth0"
    elif echo "${out}" | grep -q "File exists"; then
        :
    else
        echo "coturn: ip -6 addr add failed: ${out}" >&2
        echo "coturn: continuing without IPv6 binding — cross-instance voice will not work" >&2
    fi
fi

mkdir -p /etc/coturn
envsubst '${SERVER_NAME} ${TURN_SHARED_SECRET} ${ONIONCAT_IPV6}' \
    < /pureprivacy/turnserver.conf.tmpl \
    > /etc/coturn/turnserver.conf
chmod 0640 /etc/coturn/turnserver.conf

exec turnserver -c /etc/coturn/turnserver.conf
