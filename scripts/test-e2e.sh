#!/usr/bin/env bash
# End-to-end smoke test for PurePrivacy.
#
# Drives the full happy path: wizard → Synapse admin/bot users → invite bot →
# MCP protocol round-trip (initialize, tools/list, list_rooms, send_message)
# → verify the message arrived in Synapse.
#
# Assumes either:
#   - the stack is already up and the wizard is complete (fast path), OR
#   - $PUREPRIVACY_RESET=1 is set (full clean-slate run via `pureprivacy reset`).
#
# Exits 0 on success, non-zero with a diagnostic on failure.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-test-password-12345}"

# If setup is already complete with a different password (e.g. the feature
# tests rotated it via the recovery-key flow), trust the on-disk value so
# this script remains idempotent.
if docker exec pureprivacy-wizard test -f /shared/.setup-complete 2>/dev/null; then
    LIVE_PASS="$(docker exec pureprivacy-wizard python3 -c '
import json
try:
    print(json.load(open("/shared/.setup-complete"))["admin_password"])
except Exception:
    pass
' 2>/dev/null)"
    if [[ -n "${LIVE_PASS}" ]] && [[ "${LIVE_PASS}" != "${ADMIN_PASS}" ]]; then
        ADMIN_PASS="${LIVE_PASS}"
    fi
fi

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

step() {
    bold "→ $*"
}

fail() {
    red "FAIL: $*"
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "missing dependency: $1"
}

require_command curl
require_command python3
require_command docker

# ---------------------------------------------------------------------------
# Step 0: optionally wipe and rebuild from scratch.
# ---------------------------------------------------------------------------
if [[ "${PUREPRIVACY_RESET:-0}" == "1" ]]; then
    step "PUREPRIVACY_RESET=1 — destroying existing data"
    yes reset | ./scripts/pureprivacy reset || true
fi

# ---------------------------------------------------------------------------
# Step 1: stack up + healthy.
# ---------------------------------------------------------------------------
step "bringing the stack up"
./scripts/pureprivacy up >/dev/null
green "  stack healthy"

# ---------------------------------------------------------------------------
# Step 2: wizard.  Idempotent — POST is a no-op if already complete.
# ---------------------------------------------------------------------------
step "ensuring wizard setup is complete"
if docker exec pureprivacy-wizard test -f /shared/.setup-complete; then
    green "  setup already complete — skipping POST"
else
    curl -fsS -X POST http://127.0.0.1:8088/setup \
        --data-urlencode "admin_username=${ADMIN_USER}" \
        --data-urlencode "admin_password=${ADMIN_PASS}" \
        -o /dev/null
    docker exec pureprivacy-wizard test -f /shared/.setup-complete \
        || fail "wizard did not write .setup-complete"
    green "  wizard ran successfully"
fi

ONION="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
[[ -n "${ONION}" ]] || fail "no onion hostname"
green "  onion = ${ONION}"

# ---------------------------------------------------------------------------
# Step 3: admin can log in to Synapse client API.
# ---------------------------------------------------------------------------
step "logging in as admin via Synapse client API"
LOGIN_JSON="$(docker exec pureprivacy-synapse curl -fsS -X POST \
    http://localhost:8008/_matrix/client/r0/login \
    --data-binary "{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"${ADMIN_USER}\"},\"password\":\"${ADMIN_PASS}\"}")"
ADMIN_TOKEN="$(echo "${LOGIN_JSON}" | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')"
[[ -n "${ADMIN_TOKEN}" ]] || fail "could not obtain admin access token"
green "  admin token obtained"

# ---------------------------------------------------------------------------
# Step 4: create a room and invite the bot.
# ---------------------------------------------------------------------------
step "creating a test room and inviting the bot"
BOT_ID="@pureprivacy-mcp:${ONION}"
ROOM_JSON="$(docker exec pureprivacy-synapse curl -fsS -X POST \
    "http://localhost:8008/_matrix/client/r0/createRoom?access_token=${ADMIN_TOKEN}" \
    --data-binary "{\"name\":\"e2e-test-$$\",\"invite\":[\"${BOT_ID}\"]}")"
ROOM_ID="$(echo "${ROOM_JSON}" | python3 -c 'import sys, json; print(json.load(sys.stdin)["room_id"])')"
[[ -n "${ROOM_ID}" ]] || fail "could not create test room"
green "  room = ${ROOM_ID}"

# ---------------------------------------------------------------------------
# Step 5: wait for the bot to auto-join.
# ---------------------------------------------------------------------------
step "waiting for the bot to auto-accept the invite"
TOKEN="$(docker exec pureprivacy-mcp cat /shared/secrets/mcp_bearer_token)"
for attempt in $(seq 1 15); do
    sleep 2
    members="$(docker exec pureprivacy-synapse curl -fsS \
        "http://localhost:8008/_matrix/client/r0/rooms/${ROOM_ID}/joined_members?access_token=${ADMIN_TOKEN}" \
        | python3 -c 'import sys, json; print(",".join(json.load(sys.stdin)["joined"]))')"
    if [[ "${members}" == *"${BOT_ID}"* ]]; then
        green "  bot joined (attempt ${attempt})"
        break
    fi
    if [[ ${attempt} -eq 15 ]]; then
        fail "bot never joined the room (members: ${members})"
    fi
done

# ---------------------------------------------------------------------------
# Step 6: drive the MCP protocol from outside.
# ---------------------------------------------------------------------------
step "MCP initialize"
HEADERS="$(mktemp)"
curl -fsS -X POST http://127.0.0.1:8089/mcp \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"e2e","version":"1"}}}' \
    -D "${HEADERS}" -o /dev/null
SID="$(grep -i 'mcp-session-id' "${HEADERS}" | awk -F': ' '{print $2}' | tr -d '\r\n')"
[[ -n "${SID}" ]] || fail "MCP did not return a session id"
green "  session = ${SID:0:8}..."

mcp_call() {
    curl -fsS -X POST http://127.0.0.1:8089/mcp \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -H "Mcp-Session-Id: ${SID}" \
        -d "$1"
}

mcp_call '{"jsonrpc":"2.0","method":"notifications/initialized"}' -o /dev/null \
    >/dev/null

step "MCP tools/list"
TOOLS_RESP="$(mcp_call '{"jsonrpc":"2.0","id":2,"method":"tools/list"}')"
TOOL_COUNT="$(echo "${TOOLS_RESP}" | python3 -c '
import sys, re, json
data = sys.stdin.read()
m = re.search(r"data: (.*)", data)
print(len(json.loads(m.group(1))["result"]["tools"]))
')"
[[ "${TOOL_COUNT}" == "9" ]] || fail "expected 9 tools, got ${TOOL_COUNT}"
green "  ${TOOL_COUNT} tools listed"

step "MCP tools/call list_rooms"
ROOMS_RESP="$(mcp_call '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_rooms","arguments":{}}}')"
ROOM_COUNT="$(echo "${ROOMS_RESP}" | python3 -c "
import sys, re, json
data = sys.stdin.read()
m = re.search(r'data: (.*)', data)
rooms = json.loads(m.group(1))['result']['structuredContent']['rooms']
print(sum(1 for r in rooms if r['room_id'] == '${ROOM_ID}'))
")"
[[ "${ROOM_COUNT}" == "1" ]] || fail "test room not visible to MCP bot"
green "  list_rooms sees the test room"

step "MCP tools/call send_message"
SEND_BODY="hello from e2e test pid=$$ ts=$(date +%s)"
SEND_RESP="$(mcp_call "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"send_message\",\"arguments\":{\"room_id\":\"${ROOM_ID}\",\"body\":\"${SEND_BODY}\"}}}")"
EVENT_ID="$(echo "${SEND_RESP}" | python3 -c "
import sys, re, json
data = sys.stdin.read()
m = re.search(r'data: (.*)', data)
print(json.loads(m.group(1))['result']['structuredContent']['event_id'])
")"
[[ -n "${EVENT_ID}" ]] || fail "send_message did not return an event id"
green "  message sent, event = ${EVENT_ID}"

# ---------------------------------------------------------------------------
# Step 7: verify the message arrived (read via Synapse, decrypt via admin).
# ---------------------------------------------------------------------------
step "verifying the message reached Synapse"
sleep 2
ROOM_MSG_JSON="$(docker exec pureprivacy-synapse curl -fsS \
    "http://localhost:8008/_matrix/client/r0/rooms/${ROOM_ID}/messages?access_token=${ADMIN_TOKEN}&limit=20&dir=b")"
FOUND="$(echo "${ROOM_MSG_JSON}" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ev in data.get('chunk', []):
    if ev.get('event_id') == '${EVENT_ID}':
        print('yes')
        break
")"
[[ "${FOUND}" == "yes" ]] || fail "send_message event not found in room timeline"
green "  message present in Synapse timeline"

echo
green "✓ end-to-end test PASSED"
