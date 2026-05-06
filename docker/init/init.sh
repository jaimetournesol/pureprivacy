#!/usr/bin/env bash
# Idempotent secrets bootstrap.  Generates anything that does not already
# exist under /shared/secrets and exits.  Safe to re-run.
set -euo pipefail

SHARED="${SHARED:-/shared}"
SECRETS_DIR="${SHARED}/secrets"

mkdir -p "${SECRETS_DIR}"
chmod 0700 "${SECRETS_DIR}"

generate_if_missing() {
    local path="$1"
    local bytes="${2:-32}"
    if [[ ! -s "${path}" ]]; then
        # Hex-encoded random bytes; safe to embed in YAML, URLs, headers.
        openssl rand -hex "${bytes}" > "${path}"
        chmod 0600 "${path}"
        echo "generated ${path}"
    else
        echo "kept ${path}"
    fi
}

generate_if_missing "${SECRETS_DIR}/postgres_password" 24
generate_if_missing "${SECRETS_DIR}/registration_shared_secret" 32
generate_if_missing "${SECRETS_DIR}/macaroon_secret_key" 32
generate_if_missing "${SECRETS_DIR}/form_secret" 32
generate_if_missing "${SECRETS_DIR}/turn_shared_secret" 32
generate_if_missing "${SECRETS_DIR}/mcp_bearer_token" 32

# Voice (MatrixRTC / LiveKit) — only used when the `voice` profile is active,
# but generated unconditionally so the keys are stable across enable/disable.
generate_if_missing "${SECRETS_DIR}/livekit_api_key" 16
generate_if_missing "${SECRETS_DIR}/livekit_api_secret" 32

# Mirror the postgres password to the docker-secret path the postgres image
# reads from.  The `postgres_password` docker secret is bind-mounted from
# ./.secrets/postgres_password on the host (see docker-compose.yml), so we
# also write the file out there via a tiny indirection: the host-side bind
# is created by scripts/bootstrap.sh before the first `docker compose up`.
# Inside this container we only manage the in-volume copy.

echo "init complete"
