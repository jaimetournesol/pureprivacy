#!/usr/bin/env bash
# Synapse entrypoint: template homeserver.yaml on first boot, then exec the
# upstream entrypoint which drops privileges and runs the homeserver.
set -euo pipefail

SHARED="${SHARED:-/shared}"
DATA="/data"
CONFIG="${DATA}/homeserver.yaml"

# 1. Decide what server_name to use.
#    Priority:
#      (a) An existing signing key — server_name is locked once minted.
#      (b) /shared/onion_hostname — first-boot, written by the tor service.
EXISTING_KEY="$(ls "${DATA}"/*.signing.key 2>/dev/null | head -1 || true)"
if [[ -n "${EXISTING_KEY}" ]]; then
    SERVER_NAME="$(basename "${EXISTING_KEY}" .signing.key)"
    echo "synapse: reusing existing server_name = ${SERVER_NAME}"
else
    echo "synapse: first-boot — waiting for ${SHARED}/onion_hostname"
    for _ in $(seq 1 120); do
        if [[ -s "${SHARED}/onion_hostname" ]]; then
            break
        fi
        sleep 1
    done
    if [[ ! -s "${SHARED}/onion_hostname" ]]; then
        echo "synapse: tor onion hostname not available after 120s" >&2
        exit 1
    fi
    SERVER_NAME="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
fi

# 2. Wait for postgres password (init container writes it).
PG_PASS_FILE="${SHARED}/secrets/postgres_password"
for _ in $(seq 1 60); do
    if [[ -s "${PG_PASS_FILE}" ]]; then
        break
    fi
    sleep 1
done
if [[ ! -s "${PG_PASS_FILE}" ]]; then
    echo "synapse: postgres password file missing" >&2
    exit 1
fi
POSTGRES_PASSWORD="$(tr -d '[:space:]' < "${PG_PASS_FILE}")"

# 3. Read the rest of the secrets (init container generates them).
REGISTRATION_SHARED_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/registration_shared_secret")"
MACAROON_SECRET_KEY="$(tr -d '[:space:]' < "${SHARED}/secrets/macaroon_secret_key")"
FORM_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/form_secret")"
TURN_SHARED_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/turn_shared_secret")"

# 4. Generate signing key on first boot — never overwrite.
SIGNING_KEY="${DATA}/${SERVER_NAME}.signing.key"
if [[ ! -s "${SIGNING_KEY}" ]]; then
    echo "synapse: generating signing key for ${SERVER_NAME}"
    mkdir -p "${DATA}"
    TMP="$(mktemp -d)"
    # --generate-config writes a starter homeserver.yaml AND a signing key.
    # We discard everything except the signing key — our real config is
    # rendered from the template a few lines below.
    python -m synapse.app.homeserver \
        --server-name="${SERVER_NAME}" \
        --config-path="${TMP}/homeserver.yaml" \
        --generate-config \
        --report-stats=no \
        --data-directory="${TMP}" >/dev/null 2>&1 || true
    if [[ -s "${TMP}/${SERVER_NAME}.signing.key" ]]; then
        cp "${TMP}/${SERVER_NAME}.signing.key" "${SIGNING_KEY}"
    else
        echo "synapse: failed to generate signing key" >&2
        ls -la "${TMP}" >&2 || true
        rm -rf "${TMP}"
        exit 1
    fi
    rm -rf "${TMP}"
fi

# 5. Render homeserver.yaml from template on every boot — picks up env changes
#    AND any new federation peers added through the wizard.
export SERVER_NAME POSTGRES_PASSWORD REGISTRATION_SHARED_SECRET \
       MACAROON_SECRET_KEY FORM_SECRET TURN_SHARED_SECRET SHARED="${SHARED}"
python3 /pureprivacy/render_config.py > "${CONFIG}"
cp /pureprivacy/log.config "${DATA}/log.config"
chmod 0640 "${CONFIG}"

# 6. Make sure the synapse user owns its data directory.
chown -R 991:991 "${DATA}" || true

# 7. Hand off to the upstream entrypoint.  It expects SYNAPSE_CONFIG_PATH
#    plus standard Synapse env vars.
export SYNAPSE_CONFIG_PATH="${CONFIG}"
export SYNAPSE_DATA_DIR="${DATA}"
exec /start.py "$@"
