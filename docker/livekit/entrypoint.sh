#!/usr/bin/env bash
set -euo pipefail

SHARED="${SHARED:-/shared}"

for _ in $(seq 1 60); do
    if [[ -s "${SHARED}/secrets/livekit_api_key" \
       && -s "${SHARED}/secrets/livekit_api_secret" ]]; then
        break
    fi
    sleep 1
done
if [[ ! -s "${SHARED}/secrets/livekit_api_key" ]]; then
    echo "livekit: missing /shared/secrets/livekit_api_key" >&2
    exit 1
fi

export LIVEKIT_API_KEY="$(tr -d '[:space:]' < "${SHARED}/secrets/livekit_api_key")"
export LIVEKIT_API_SECRET="$(tr -d '[:space:]' < "${SHARED}/secrets/livekit_api_secret")"

mkdir -p /etc/livekit
envsubst '${LIVEKIT_API_KEY} ${LIVEKIT_API_SECRET}' \
    < /pureprivacy/livekit.yaml.tmpl \
    > /etc/livekit/livekit.yaml

exec /livekit-server --config /etc/livekit/livekit.yaml
