#!/usr/bin/env bash
# Restart-survival smoke test.
#
# Verifies that volumes survive `docker compose down/up`, that container
# identities are preserved, and that the setup state is preserved.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
step()  { bold "→ $*"; }
fail()  { red "FAIL: $*"; exit 1; }

# Capture pre-restart state.
step "capturing pre-restart state"
./scripts/pureprivacy up >/dev/null
ONION_BEFORE="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
SETUP_BEFORE="$(docker exec pureprivacy-wizard cat /shared/.setup-complete 2>/dev/null \
    || echo "{}")"
green "  onion = ${ONION_BEFORE}"

# Test 1: stop / start.
step "test 1: stop + start"
./scripts/pureprivacy stop >/dev/null
./scripts/pureprivacy start >/dev/null
ONION_AFTER="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
SETUP_AFTER="$(docker exec pureprivacy-wizard cat /shared/.setup-complete 2>/dev/null \
    || echo "{}")"
[[ "${ONION_AFTER}" == "${ONION_BEFORE}" ]] || fail "onion identity changed after stop/start"
[[ "${SETUP_AFTER}" == "${SETUP_BEFORE}" ]] || fail "setup state changed after stop/start"
green "  onion + setup state preserved"

# Test 2: docker compose restart.
step "test 2: docker compose restart"
./scripts/pureprivacy restart >/dev/null
ONION_AFTER="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
[[ "${ONION_AFTER}" == "${ONION_BEFORE}" ]] || fail "onion identity changed after restart"
green "  onion preserved"

# Test 3: full down + up (host-reboot scenario for users who manually shut down).
step "test 3: down + up (full reboot scenario)"
./scripts/pureprivacy down >/dev/null
./scripts/pureprivacy up >/dev/null
ONION_AFTER="$(docker exec pureprivacy-tor cat /shared/onion_hostname)"
SETUP_AFTER="$(docker exec pureprivacy-wizard cat /shared/.setup-complete 2>/dev/null \
    || echo "{}")"
[[ "${ONION_AFTER}" == "${ONION_BEFORE}" ]] || fail "onion identity changed after down/up"
[[ "${SETUP_AFTER}" == "${SETUP_BEFORE}" ]] || fail "setup state changed after down/up"
green "  onion + setup preserved across down/up"

# Test 4: MCP bot session survives restart.
step "test 4: MCP bot session persists across restart"
docker compose -p pureprivacy restart mcp >/dev/null
for attempt in $(seq 1 20); do
    sleep 2
    ready="$(curl -fsS http://127.0.0.1:8089/healthz 2>/dev/null \
        | python3 -c 'import sys, json; print(json.load(sys.stdin).get("matrix_bot_ready", False))' \
        || echo False)"
    if [[ "${ready}" == "True" ]]; then
        break
    fi
done
[[ "${ready}" == "True" ]] || fail "MCP bot did not return ready within 40s"
# grep -q exits early on match, which races with docker logs and triggers
# SIGPIPE (exit 141) under pipefail.  Stash the output first.
mcp_logs="$(docker logs pureprivacy-mcp --since=2m 2>&1)"
if ! grep -q "restored session" <<<"${mcp_logs}"; then
    fail "MCP bot did not restore session from disk"
fi
green "  MCP bot resumed from saved session"

echo
green "✓ all restart-survival tests PASSED"
