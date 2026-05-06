#!/bin/sh
# Wrapper that:
#   1. Pulls LiveKit credentials out of /shared/secrets
#   2. Plumbs the matrix://<onion> resolver through the synapse-fed-proxy
#      sidecar — see docker/synapse-fed-proxy/entrypoint.sh for the why.
#   3. Execs the upstream lk-jwt-service binary.
set -eu

SHARED="${SHARED:-/shared}"
SYNAPSE_FED_PROXY_IP="${SYNAPSE_FED_PROXY_IP:-172.30.0.13}"

# 1. LiveKit API credentials.
for _ in $(seq 1 60); do
    if [ -s "${SHARED}/secrets/livekit_api_key" ] \
       && [ -s "${SHARED}/secrets/livekit_api_secret" ]; then
        break
    fi
    sleep 1
done
LIVEKIT_KEY="$(tr -d '[:space:]' < "${SHARED}/secrets/livekit_api_key")"
LIVEKIT_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/livekit_api_secret")"
export LIVEKIT_KEY LIVEKIT_SECRET

# 2. Onion → fed-proxy override.  Only meaningful when the Synapse
#    server_name is a .onion AND the synapse-fed-proxy sidecar is up.
ONION=""
for _ in $(seq 1 60); do
    if [ -s "${SHARED}/onion_hostname" ]; then
        ONION="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
        break
    fi
    sleep 1
done

if [ -n "${ONION}" ]; then
    # /etc/hosts override — Go's net.LookupHost honors /etc/hosts before
    # going to DNS, so the matrix://<onion> resolver lands on the sidecar.
    if ! grep -qE "[[:space:]]${ONION}([[:space:]]|$)" /etc/hosts 2>/dev/null; then
        echo "${SYNAPSE_FED_PROXY_IP} ${ONION}" >> /etc/hosts
        echo "lk-jwt: routed ${ONION} → ${SYNAPSE_FED_PROXY_IP} via /etc/hosts"
    fi

    # Trust the sidecar's self-signed CA so https://<onion> validates.
    # Wait up to 60s for the sidecar to publish its cert; if it never
    # shows we still start (maybe the operator wired an external proxy).
    waited=0
    while [ ${waited} -lt 60 ] && [ ! -s "${SHARED}/synapse-fed-proxy-ca.crt" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    if [ -s "${SHARED}/synapse-fed-proxy-ca.crt" ]; then
        cp "${SHARED}/synapse-fed-proxy-ca.crt" \
           /usr/local/share/ca-certificates/synapse-fed-proxy.crt
        update-ca-certificates 2>&1 | sed 's/^/  /'
        echo "lk-jwt: trusted synapse-fed-proxy CA for ${ONION}"
    else
        echo "lk-jwt: WARNING: synapse-fed-proxy cert not found at ${SHARED}/synapse-fed-proxy-ca.crt" >&2
        echo "lk-jwt: matrix://${ONION} validation will fail with x509 errors" >&2
    fi
fi

# 3. LIVEKIT_URL and LK_JWT_PORT come from compose env.
exec /lk-jwt-service
