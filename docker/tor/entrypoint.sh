#!/usr/bin/env bash
# Tor entrypoint: ensure hidden-service directory has the right ownership
# and mode, start tor, and publish the resulting .onion hostname into
# /shared/onion_hostname so that Synapse and the wizard can read it.
set -euo pipefail

HSDIR="/var/lib/tor/pureprivacy"
SHARED="${SHARED:-/shared}"

mkdir -p "${HSDIR}"
chown -R tor:tor /var/lib/tor
chmod 0700 "${HSDIR}"

mkdir -p "${SHARED}"

# Render torrc from the template on every boot.  HiddenServicePort lines
# carry literal container IPs, so a second instance running on a
# different docker subnet (PUREPRIVACY_NET_PREFIX != 172.30.0) needs its
# own torrc with its own targets.  envsubst keeps the template static
# in-image and lets a single compose file serve any subnet.
export PUREPRIVACY_NET_PREFIX="${PUREPRIVACY_NET_PREFIX:-172.30.0}"
envsubst '${PUREPRIVACY_NET_PREFIX}' \
    < /etc/tor/torrc.tmpl \
    > /etc/tor/torrc
chmod 0644 /etc/tor/torrc

start_publisher() {
    # Wait for tor to mint the hostname, then copy it to the shared volume.
    # Re-run on each container start to keep the file fresh even if it was
    # accidentally deleted from /shared.
    local i=0
    while [[ ! -s "${HSDIR}/hostname" ]]; do
        i=$((i + 1))
        if [[ $i -gt 60 ]]; then
            echo "tor: timed out waiting for hostname" >&2
            return 1
        fi
        sleep 1
    done
    local host
    host="$(tr -d '[:space:]' < "${HSDIR}/hostname")"
    if [[ -z "${host}" ]]; then
        echo "tor: empty hostname" >&2
        return 1
    fi
    printf '%s\n' "${host}" > "${SHARED}/onion_hostname"
    chmod 0644 "${SHARED}/onion_hostname"
    echo "tor: published ${host} to ${SHARED}/onion_hostname"

    # Also publish the OnionCat-style IPv6 derived from this onion so
    # coturn (and any other consumer) can read it instead of recomputing
    # the SHA-256 in their own entrypoint.  See docs/turn-udp-tor-shim.md
    # for the addressing scheme.
    local nosuf digest ipv6
    nosuf="${host%.onion}"
    # Lowercase + sha256 + first 20 hex chars (= 10 bytes = 80 low bits).
    digest="$(printf '%s' "${nosuf}" | tr 'A-Z' 'a-z' | sha256sum | cut -c1-20)"
    if [[ ${#digest} -ne 20 ]]; then
        echo "tor: sha256 digest unexpected length ${#digest}; skipping onioncat_ipv6" >&2
        return 0
    fi
    ipv6="fd87:d87e:eb43:${digest:0:4}:${digest:4:4}:${digest:8:4}:${digest:12:4}:${digest:16:4}"
    printf '%s\n' "${ipv6}" > "${SHARED}/onioncat_ipv6"
    chmod 0644 "${SHARED}/onioncat_ipv6"
    echo "tor: published ${ipv6} to ${SHARED}/onioncat_ipv6"
}

start_publisher &

exec tor -f /etc/tor/torrc
