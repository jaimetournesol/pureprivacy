#!/usr/bin/env bash
# Coturn entrypoint: render the config from template using the shared
# secret + onion hostname, then exec coturn.
set -euo pipefail

SHARED="${SHARED:-/shared}"

for _ in $(seq 1 60); do
    if [[ -s "${SHARED}/onion_hostname" && -s "${SHARED}/secrets/turn_shared_secret" ]]; then
        break
    fi
    sleep 1
done
if [[ ! -s "${SHARED}/onion_hostname" || ! -s "${SHARED}/secrets/turn_shared_secret" ]]; then
    echo "coturn: required shared files missing" >&2
    exit 1
fi

export SERVER_NAME="$(tr -d '[:space:]' < "${SHARED}/onion_hostname")"
export TURN_SHARED_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/turn_shared_secret")"

mkdir -p /etc/coturn
envsubst '${SERVER_NAME} ${TURN_SHARED_SECRET}' \
    < /pureprivacy/turnserver.conf.tmpl \
    > /etc/coturn/turnserver.conf
chmod 0640 /etc/coturn/turnserver.conf

exec turnserver -c /etc/coturn/turnserver.conf
