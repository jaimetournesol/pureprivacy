#!/usr/bin/env bash
# synapse-fed-proxy — TLS-terminated path to Synapse for in-network callers.
#
# Why: lk-jwt-service uses a `matrix://` URL scheme to validate OpenID
# tokens against the issuing homeserver.  That scheme bypasses HTTPS_PROXY
# and tries to reach the homeserver directly.  In Tor-only mode the
# homeserver is a .onion which Go's net.LookupHost can't resolve, so
# validation fails and group calls don't connect.
#
# This sidecar provides a stable internal IP, mints a self-signed cert
# for the .onion, and reverse-proxies HTTPS → http://synapse:8008.
# lk-jwt's entrypoint then adds an /etc/hosts entry pointing the .onion
# at this sidecar and trusts our CA, so matrix://<onion> resolves to a
# fast in-docker TLS hop and the call back into Synapse works.
#
# Listens on 80, 443, 8448 so all the URL shapes lk-jwt might construct
# (well-known then host:8448 fallback) end up here.
set -euo pipefail

SHARED="${SHARED:-/shared}"

mkdir -p /etc/sidecar

# Wait for the onion hostname; that's the CN we mint.
ONION=""
for _ in $(seq 1 120); do
    if [[ -s "${SHARED}/onion_hostname" ]]; then
        ONION="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
        break
    fi
    sleep 1
done
if [[ -z "${ONION}" ]]; then
    echo "synapse-fed-proxy: tor onion hostname not available after 120s" >&2
    exit 1
fi

# Mint cert if missing, stale (different onion), or expiring within 30 days.
# The cert lives in the container's writable layer, but we publish a copy to
# /shared so lk-jwt can append it to its CA bundle.
#
# Validity: 1 year.  No renewal automation in v0.1 — the next container
# restart after expiry mints a fresh cert and lk-jwt picks it up via the
# entrypoint trust step.  Expect to restart at least once a year for
# image updates anyway.
#
# Algorithm: Ed25519 (RFC 8032).  Smaller, faster, no parameter selection
# footguns.  The downside is some old TLS clients refuse Ed25519; lk-jwt
# uses Go's crypto/tls which has supported Ed25519 since 1.13, and Caddy
# uses the same stack — so we are safe.
CERT_VALIDITY_DAYS=365
CERT_RENEW_WITHIN_DAYS=30

need_mint=false
if [[ ! -f /etc/sidecar/cert.pem ]] || ! grep -q "${ONION}" /etc/sidecar/cert.pem 2>/dev/null; then
    need_mint=true
elif ! openssl x509 -checkend $((CERT_RENEW_WITHIN_DAYS * 24 * 3600)) \
        -noout -in /etc/sidecar/cert.pem >/dev/null 2>&1; then
    echo "synapse-fed-proxy: existing cert expires within ${CERT_RENEW_WITHIN_DAYS} days; rotating"
    need_mint=true
fi
if "${need_mint}"; then
    echo "synapse-fed-proxy: minting self-signed Ed25519 cert for ${ONION}"
    openssl req -x509 -newkey ed25519 -nodes \
        -keyout /etc/sidecar/key.pem \
        -out /etc/sidecar/cert.pem \
        -days "${CERT_VALIDITY_DAYS}" \
        -subj "/CN=${ONION}" \
        -addext "subjectAltName=DNS:${ONION},DNS:localhost" \
        2>&1 | sed 's/^/  /'
    chmod 0600 /etc/sidecar/key.pem
fi

# Publish the cert so lk-jwt can trust it.  Atomic write.
cp /etc/sidecar/cert.pem "${SHARED}/synapse-fed-proxy-ca.crt.tmp"
mv "${SHARED}/synapse-fed-proxy-ca.crt.tmp" "${SHARED}/synapse-fed-proxy-ca.crt"
chmod 0644 "${SHARED}/synapse-fed-proxy-ca.crt"

# Render Caddyfile.  No automatic HTTPS, no ACME; we hand it the cert.
cat > /etc/sidecar/Caddyfile <<EOF
{
    auto_https off
    admin off
}

:443, :8448 {
    tls /etc/sidecar/cert.pem /etc/sidecar/key.pem
    reverse_proxy synapse:8008
}

:80 {
    reverse_proxy synapse:8008
}
EOF

echo "synapse-fed-proxy: serving https://${ONION}:{443,8448} → synapse:8008"
exec caddy run --config /etc/sidecar/Caddyfile --adapter caddyfile
