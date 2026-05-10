#!/usr/bin/env bash
# Integration tests for the new v0.1.x feature surface:
#   1. Pair create/list/accept/remove via CLI — verifies Synapse restarts
#      when /pair/accept and /pair/remove are hit, and that the new peer
#      appears in the rendered homeserver.yaml.
#   2. User add / list / remove / reset-password via CLI.
#   3. MCP token rotation: grace window honoured + early-revoke endpoint.
#   4. Wizard auth + /people web UI (cookie + CLI-token paths).
#   5. Recovery key resets the admin password without a full reset.
#   6. cmd_info / cmd_init idempotency.
#
# Assumes the stack is already up and the wizard is complete (run
# scripts/test-e2e.sh first to guarantee that, or set PUREPRIVACY_RESET=1).
set -euo pipefail

# Git Bash: docker.exe mangles container paths.  No-op elsewhere.
if [[ "${MSYSTEM:-}" == MINGW* || "${MSYSTEM:-}" == MSYS ]]; then
    docker() { MSYS_NO_PATHCONV=1 command docker "$@"; }
    export -f docker
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
step()  { bold "→ $*"; }
fail()  { red "FAIL: $*"; exit 1; }

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "missing dependency: $1"
}

require_command curl
require_command python3
require_command docker

step "ensuring stack is up + setup is complete"
./scripts/pureprivacy up >/dev/null
docker exec pureprivacy-wizard test -f /shared/.setup-complete \
    || fail "setup not complete; run scripts/test-e2e.sh first"

ONION="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
green "  onion = ${ONION}"

# The wizard now gates state-changing routes behind cookie auth (admin
# password) OR a CLI-token header.  The CLI and these tests use the latter.
# See wizard/auth.py.
CLI_TOKEN="$(docker exec pureprivacy-wizard cat /shared/secrets/cli_token \
    | tr -d '[:space:]')"
[[ -n "${CLI_TOKEN}" ]] || fail "wizard did not mint a cli_token at startup"

# =========================================================================
# Test 1: MCP token rotation grace window
# =========================================================================
step "MCP token rotation: capture old token"
OLD_TOKEN="$(docker exec pureprivacy-wizard cat /shared/secrets/mcp_bearer_token | tr -d '[:space:]')"
[[ -n "${OLD_TOKEN}" ]] || fail "no MCP token on disk"

step "MCP token rotation: hit /rotate-token"
curl -fsS -X POST http://127.0.0.1:8088/rotate-token \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}" -o /dev/null
NEW_TOKEN="$(docker exec pureprivacy-wizard cat /shared/secrets/mcp_bearer_token | tr -d '[:space:]')"
[[ "${NEW_TOKEN}" != "${OLD_TOKEN}" ]] || fail "token did not change after rotate"
[[ -n "${NEW_TOKEN}" ]] || fail "new token is empty"

step "MCP token rotation: .prev exists with old token"
PREV_TOKEN="$(docker exec pureprivacy-wizard cat /shared/secrets/mcp_bearer_token.prev | tr -d '[:space:]')"
[[ "${PREV_TOKEN}" == "${OLD_TOKEN}" ]] || fail ".prev does not match old token"

step "MCP token rotation: both new and old tokens accepted (grace window)"
# Hit /healthz to spin up an MCP session, then a tools/list call with each token.
mcp_call_token() {
    local tok="$1"
    local headers
    headers="$(mktemp)"
    curl -fsS -X POST http://127.0.0.1:8089/mcp \
        -H "Authorization: Bearer ${tok}" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}' \
        -D "${headers}" -o /dev/null \
        -w '%{http_code}'
    rm -f "${headers}"
}
NEW_CODE="$(mcp_call_token "${NEW_TOKEN}")"
[[ "${NEW_CODE}" == "200" ]] || fail "new token rejected (HTTP ${NEW_CODE})"
OLD_CODE="$(mcp_call_token "${OLD_TOKEN}")"
[[ "${OLD_CODE}" == "200" ]] || fail "old token (within grace) rejected (HTTP ${OLD_CODE})"
green "  new + old both accepted within grace window"

step "MCP token rotation: revoke /prev immediately"
curl -fsS -X POST http://127.0.0.1:8088/revoke-prev-token \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}" -o /dev/null
docker exec pureprivacy-wizard test -f /shared/secrets/mcp_bearer_token.prev \
    && fail ".prev should have been deleted"
OLD_CODE="$(mcp_call_token "${OLD_TOKEN}")"
[[ "${OLD_CODE}" == "403" ]] || fail "old token still accepted after revoke (HTTP ${OLD_CODE})"
NEW_CODE="$(mcp_call_token "${NEW_TOKEN}")"
[[ "${NEW_CODE}" == "200" ]] || fail "new token rejected after revoke (HTTP ${NEW_CODE})"
green "  prev revoked: old → 403, new → 200"

# =========================================================================
# Test 2: pureprivacy info / cmd_info accuracy
# =========================================================================
step "pureprivacy info shows onion + MCP endpoint"
INFO_OUT="$(./scripts/pureprivacy info 2>&1)"
[[ "${INFO_OUT}" == *"${ONION}"* ]] || fail "info missing onion"
[[ "${INFO_OUT}" == *"127.0.0.1:8089"* ]] || fail "info missing MCP endpoint"
[[ "${INFO_OUT}" == *"127.0.0.1:8088"* ]] || fail "info missing wizard URL"
[[ "${INFO_OUT}" == *"Pair box:"* ]] || fail "info missing pair URL"
green "  info covers onion / MCP / wizard / pair"

step "pureprivacy info --secrets reveals admin password + bearer"
SECRETS_OUT="$(./scripts/pureprivacy info --secrets 2>&1)"
ADMIN_PW="$(docker exec pureprivacy-wizard python3 -c 'import json;print(json.load(open("/shared/.setup-complete"))["admin_password"])')"
[[ "${SECRETS_OUT}" == *"${ADMIN_PW}"* ]] || fail "info --secrets did not reveal admin password"
[[ "${SECRETS_OUT}" == *"${NEW_TOKEN}"* ]] || fail "info --secrets did not reveal new MCP token"
green "  info --secrets reveals secrets"

# =========================================================================
# Test 3: pureprivacy user — add, list, reset-password, remove
# =========================================================================
step "pureprivacy user list: at least admin + bot"
USER_LIST="$(./scripts/pureprivacy user list 2>&1)"
[[ "${USER_LIST}" == *"admin:"* ]] || fail "user list missing admin (got: ${USER_LIST:0:200})"
[[ "${USER_LIST}" == *"pureprivacy-mcp"* ]] || fail "user list missing mcp bot"
green "  user list ok"

TEST_USER="alice-feature-$$"
step "pureprivacy user add ${TEST_USER}"
ADD_OUT="$(./scripts/pureprivacy user add "${TEST_USER}" 2>&1)"
[[ "${ADD_OUT}" == *"@${TEST_USER}:${ONION}"* ]] || fail "user add did not echo full ID (got: ${ADD_OUT:0:200})"
[[ "${ADD_OUT}" == *"Password:"* ]] || fail "user add did not echo password"

step "pureprivacy user list: ${TEST_USER} now visible"
LIST_AFTER="$(./scripts/pureprivacy user list 2>&1)"
[[ "${LIST_AFTER}" == *"@${TEST_USER}:${ONION}"* ]] || fail "user list missing ${TEST_USER}"

step "pureprivacy user reset-password ${TEST_USER}"
RESET_OUT="$(./scripts/pureprivacy user reset-password "${TEST_USER}" 2>&1)"
[[ "${RESET_OUT}" == *"Reset password for"* ]] || fail "reset-password did not confirm"

step "pureprivacy user remove ${TEST_USER}"
RM_OUT="$(./scripts/pureprivacy user remove "${TEST_USER}" 2>&1)"
[[ "${RM_OUT}" == *"Deactivated"* ]] || fail "remove did not deactivate"
LIST_FINAL="$(./scripts/pureprivacy user list 2>&1)"
# Synapse keeps deactivated users in the list flagged accordingly.
[[ "${LIST_FINAL}" == *"@${TEST_USER}:${ONION}"*"deactivated"* ]] \
    || [[ "${LIST_FINAL}" == *"deactivated"*"@${TEST_USER}:${ONION}"* ]] \
    || fail "deactivated user not flagged in list"
green "  user add → list → reset-password → remove all work"

step "pureprivacy user remove refuses to deactivate admin"
ADMIN_RM_OUT="$(./scripts/pureprivacy user remove admin 2>&1 || true)"
if [[ "${ADMIN_RM_OUT}" == *"refusing to deactivate the admin"* ]]; then
    green "  admin removal refused (expected)"
else
    fail "user remove of admin should refuse (got: ${ADMIN_RM_OUT})"
fi

step "pureprivacy user remove refuses to deactivate the MCP bot"
BOT_RM_OUT="$(./scripts/pureprivacy user remove pureprivacy-mcp 2>&1 || true)"
if [[ "${BOT_RM_OUT}" == *"refusing to deactivate the MCP bot"* ]]; then
    green "  MCP bot removal refused (expected)"
else
    fail "user remove of MCP bot should refuse (got: ${BOT_RM_OUT})"
fi

# =========================================================================
# Test 4: pureprivacy pair — create + list + accept (synapse restart) + remove
# =========================================================================
step "pureprivacy pair create produces a valid base64 code"
CREATE_OUT="$(./scripts/pureprivacy pair create 2>&1)"
PAIR_CODE="$(printf '%s' "${CREATE_OUT}" | grep -E '^  [A-Za-z0-9_-]{40,}' | head -1 | tr -d ' ')"
[[ -n "${PAIR_CODE}" ]] || fail "pair create did not emit a base64 code (got: ${CREATE_OUT:0:300})"
green "  pair code minted (${#PAIR_CODE} chars)"

# We can't actually pair the box with itself (refused).  Instead, fake a
# peer by hand-crafting a code with a different .onion and feeding it to
# /pair/accept; that exercises the same restart-on-write path.
step "fabricate a synthetic peer code and accept it"
FAKE_ONION="0000000000000000000000000000000000000000000000000000aaaaa.onion"
FAKE_CODE="$(python3 - <<PY
import base64, json, secrets, time
payload = {
    "version": 1,
    "onion": "${FAKE_ONION}",
    "expires_at": int(time.time()) + 60,
    "nonce": secrets.token_hex(16),
}
print(base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode())
PY
)"

# Capture Synapse start time before pair to verify restart actually happens.
SYNAPSE_START_BEFORE="$(docker inspect -f '{{.State.StartedAt}}' pureprivacy-synapse)"
ACCEPT_OUT="$(./scripts/pureprivacy pair accept "${FAKE_CODE}" 2>&1)"
[[ "${ACCEPT_OUT}" == *"Paired and Synapse restarted"* ]] \
    || fail "pair accept did not confirm restart (got: ${ACCEPT_OUT:0:300})"
SYNAPSE_START_AFTER="$(docker inspect -f '{{.State.StartedAt}}' pureprivacy-synapse)"
[[ "${SYNAPSE_START_BEFORE}" != "${SYNAPSE_START_AFTER}" ]] \
    || fail "Synapse StartedAt unchanged — restart didn't happen"
green "  pair accept restarted Synapse"

step "homeserver.yaml now whitelists the fake onion"
HS_YAML="$(docker exec pureprivacy-synapse cat /data/homeserver.yaml)"
[[ "${HS_YAML}" == *"${FAKE_ONION}"* ]] \
    || fail "homeserver.yaml does not contain the new peer in its federation_domain_whitelist"
[[ "${HS_YAML}" == *"federation_certificate_verification_whitelist:"*"${FAKE_ONION}"* ]] \
    || fail "homeserver.yaml does not include the peer in the cert whitelist"
green "  Synapse rendered new federation list correctly"

step "pureprivacy pair list shows the synthetic peer"
LIST_OUT="$(./scripts/pureprivacy pair list 2>&1)"
[[ "${LIST_OUT}" == *"${FAKE_ONION}"* ]] \
    || fail "pair list missing fake onion (got: ${LIST_OUT})"

step "pair remove also restarts Synapse"
SYNAPSE_START_BEFORE="$(docker inspect -f '{{.State.StartedAt}}' pureprivacy-synapse)"
RM_OUT="$(./scripts/pureprivacy pair remove "${FAKE_ONION}" 2>&1)"
[[ "${RM_OUT}" == *"Unpaired"* ]] || fail "pair remove did not confirm"
SYNAPSE_START_AFTER="$(docker inspect -f '{{.State.StartedAt}}' pureprivacy-synapse)"
[[ "${SYNAPSE_START_BEFORE}" != "${SYNAPSE_START_AFTER}" ]] \
    || fail "Synapse did not restart on pair remove"
HS_YAML_AFTER="$(docker exec pureprivacy-synapse cat /data/homeserver.yaml)"
[[ "${HS_YAML_AFTER}" != *"${FAKE_ONION}"* ]] \
    || fail "fake onion still in federation_domain_whitelist after remove"
green "  pair remove cleaned up homeserver.yaml + restarted"

step "self-pair refused"
SELF_CODE="$(python3 - <<PY
import base64, json, secrets, time
payload = {
    "version": 1,
    "onion": "${ONION}",
    "expires_at": int(time.time()) + 60,
    "nonce": secrets.token_hex(16),
}
print(base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode())
PY
)"
SELF_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST http://127.0.0.1:8088/pair/accept \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}" \
    --data-urlencode "pair_code=${SELF_CODE}")"
[[ "${SELF_HTTP}" == "400" ]] || fail "self-pair should return 400, got ${SELF_HTTP}"
green "  self-pair correctly refused"

# Verify the auth gate itself: an unauthenticated request to a gated route
# must redirect to /login (303) instead of executing.
step "wizard auth: unauthenticated POST is redirected to /login"
UNAUTH_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST http://127.0.0.1:8088/rotate-token)"
[[ "${UNAUTH_HTTP}" == "303" ]] \
    || fail "expected 303 redirect for unauthenticated /rotate-token, got ${UNAUTH_HTTP}"
green "  unauthenticated /rotate-token correctly redirected (HTTP ${UNAUTH_HTTP})"

# =========================================================================
# Test 4b: Wizard /people web UI (auth-gated user management)
# =========================================================================
step "wizard /people: unauthenticated GET redirects to /login"
PEOPLE_UNAUTH="$(curl -s -o /dev/null -w '%{http_code}' \
    http://127.0.0.1:8088/people)"
[[ "${PEOPLE_UNAUTH}" == "303" ]] \
    || fail "expected 303 for unauthenticated /people, got ${PEOPLE_UNAUTH}"

step "wizard /people: GET with CLI token renders user list"
PEOPLE_HTML="$(curl -fsS http://127.0.0.1:8088/people \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}")"
[[ "${PEOPLE_HTML}" == *"People on this box"* ]] \
    || fail "/people did not render the people page"
[[ "${PEOPLE_HTML}" == *"pureprivacy-mcp"* ]] \
    || fail "/people did not list the MCP bot"
green "  /people GET works with CLI token"

step "wizard /people/add: create user via web POST"
WIZ_USER="bob-feature-$$"
ADD_BODY="$(mktemp)"
ADD_HTTP="$(curl -s -o "${ADD_BODY}" -w '%{http_code}' \
    -X POST http://127.0.0.1:8088/people/add \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}" \
    --data-urlencode "username=${WIZ_USER}" \
    --data-urlencode "password=test-password-12345")"
[[ "${ADD_HTTP}" == "200" ]] \
    || fail "expected 200 from /people/add, got ${ADD_HTTP} (body: $(head -c 300 "${ADD_BODY}"))"
[[ "$(cat "${ADD_BODY}")" == *"Account ready"* ]] \
    || fail "/people/add response did not render share page"
[[ "$(cat "${ADD_BODY}")" == *"@${WIZ_USER}:${ONION}"* ]] \
    || fail "/people/add response missing new user_id"
rm -f "${ADD_BODY}"

step "wizard /people/{name}/remove: deactivate via web POST"
RM_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "http://127.0.0.1:8088/people/${WIZ_USER}/remove" \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}")"
[[ "${RM_HTTP}" == "303" ]] \
    || fail "expected 303 from /people/{name}/remove, got ${RM_HTTP}"

step "wizard /people refuses to deactivate the admin"
ADMIN_LP="$(docker exec pureprivacy-wizard python3 -c '
import json
u = json.load(open("/shared/.setup-complete"))["admin_user"]
print(u.lstrip("@").split(":", 1)[0])
')"
ADMIN_RM_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "http://127.0.0.1:8088/people/${ADMIN_LP}/remove" \
    -H "X-PurePrivacy-CLI-Token: ${CLI_TOKEN}")"
[[ "${ADMIN_RM_HTTP}" == "409" ]] \
    || fail "expected 409 when deactivating admin, got ${ADMIN_RM_HTTP}"
green "  /people web flow: create / share / remove all gated and working"

# =========================================================================
# Test 4c: Wizard cookie login flow
# =========================================================================
# /login is CSRF-protected: the form requires a hidden csrf_token field
# whose value we have to scrape from the GET /login page, plus a matching
# Origin header.  This is what real browsers do; the test exercises the
# same path.
fetch_csrf_token() {
    # $1 = path to GET (e.g. /login).  Echos the csrf_token value.
    curl -s "http://127.0.0.1:8088${1}" \
        | grep -oE 'name="csrf_token" value="[^"]+"' \
        | head -n1 \
        | sed -E 's/.*value="([^"]+)".*/\1/'
}

step "wizard /login: wrong password rejected"
WRONG_BODY="$(mktemp)"
WRONG_CSRF="$(fetch_csrf_token /login)"
[[ -n "${WRONG_CSRF}" ]] || fail "could not scrape csrf_token from /login"
curl -s -o "${WRONG_BODY}" -X POST http://127.0.0.1:8088/login \
    -H "Origin: http://127.0.0.1:8088" \
    --data-urlencode "csrf_token=${WRONG_CSRF}" \
    --data-urlencode "password=wrong-password" >/dev/null
[[ "$(cat "${WRONG_BODY}")" == *"That admin password is wrong"* ]] \
    || fail "wrong /login should re-render with error message"
rm -f "${WRONG_BODY}"

step "wizard /login: correct admin password issues a cookie"
LIVE_ADMIN_PW="$(docker exec pureprivacy-wizard python3 -c '
import json;print(json.load(open("/shared/.setup-complete"))["admin_password"])
')"
COOKIE_JAR="$(mktemp)"
LOGIN_CSRF="$(fetch_csrf_token /login)"
[[ -n "${LOGIN_CSRF}" ]] || fail "could not scrape csrf_token from /login"
LOGIN_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -c "${COOKIE_JAR}" \
    -X POST http://127.0.0.1:8088/login \
    -H "Origin: http://127.0.0.1:8088" \
    --data-urlencode "csrf_token=${LOGIN_CSRF}" \
    --data-urlencode "password=${LIVE_ADMIN_PW}")"
[[ "${LOGIN_HTTP}" == "303" ]] || fail "/login should redirect on success (got ${LOGIN_HTTP})"
grep -q "pureprivacy_wizard" "${COOKIE_JAR}" \
    || fail "/login did not set the pureprivacy_wizard cookie"

step "wizard /people: cookie-authenticated GET works"
PEOPLE_COOKIE_HTTP="$(curl -s -o /dev/null -w '%{http_code}' \
    -b "${COOKIE_JAR}" \
    http://127.0.0.1:8088/people)"
[[ "${PEOPLE_COOKIE_HTTP}" == "200" ]] \
    || fail "cookie-authenticated /people GET should be 200, got ${PEOPLE_COOKIE_HTTP}"
rm -f "${COOKIE_JAR}"
green "  /login → cookie → /people works end-to-end"

# =========================================================================
# Test 5: Recovery key flow
# =========================================================================
step "recovery key is in /shared/.setup-complete and hash file"
RECOVERY="$(docker exec pureprivacy-wizard python3 -c '
import json
d = json.load(open("/shared/.setup-complete"))
print(d.get("recovery_passphrase", ""))
')"
[[ -n "${RECOVERY}" ]] || fail "no recovery_passphrase in .setup-complete"
docker exec pureprivacy-wizard test -f /shared/secrets/recovery_hash \
    || fail "recovery_hash file missing"
green "  recovery key minted (${#RECOVERY} chars), hash on disk"

step "pureprivacy admin reset-password rotates admin password using key"
OLD_ADMIN_PW="$(docker exec pureprivacy-wizard python3 -c '
import json
d = json.load(open("/shared/.setup-complete"))
print(d.get("admin_password", ""))
')"
RESET_OUT="$(./scripts/pureprivacy admin reset-password "${RECOVERY}" 2>&1)"
[[ "${RESET_OUT}" == *"Reset password for"* ]] || fail "admin reset did not confirm: ${RESET_OUT:0:200}"
NEW_ADMIN_PW="$(docker exec pureprivacy-wizard python3 -c '
import json
d = json.load(open("/shared/.setup-complete"))
print(d.get("admin_password", ""))
')"
[[ "${NEW_ADMIN_PW}" != "${OLD_ADMIN_PW}" ]] || fail "admin password unchanged after reset"
green "  admin password rotated via recovery key"

step "logging in with the new admin password works"
LOGIN_HTTP="$(curl -s -o /tmp/login.body -w '%{http_code}' \
    -X POST "http://127.0.0.1:8088/healthz" -o /dev/null) "
ADMIN_USER="$(docker exec pureprivacy-wizard python3 -c '
import json
print(json.load(open("/shared/.setup-complete"))["admin_user"])
')"
ADMIN_LOCAL="${ADMIN_USER#@}"; ADMIN_LOCAL="${ADMIN_LOCAL%%:*}"
LOGIN_HTTP="$(docker exec pureprivacy-synapse curl -s -o /tmp/login.body \
    -w '%{http_code}' -X POST http://localhost:8008/_matrix/client/r0/login \
    --data-binary "{\"type\":\"m.login.password\",\"identifier\":{\"type\":\"m.id.user\",\"user\":\"${ADMIN_LOCAL}\"},\"password\":\"${NEW_ADMIN_PW}\"}")"
[[ "${LOGIN_HTTP}" == "200" ]] || fail "new admin password did not work for login (HTTP ${LOGIN_HTTP})"
green "  new admin password validated against Synapse"

step "wrong recovery key rejected"
BAD="$(./scripts/pureprivacy admin reset-password 'AAAA-BBBB-CCCC-DDDD' 2>&1 || true)"
[[ "${BAD}" == *"recovery key did not match"* ]] || fail "bad recovery key should be rejected"
green "  wrong key correctly rejected"

echo
green "✓ all feature tests PASSED"
