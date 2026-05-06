#!/usr/bin/env bash
# Healthcheck-failure regression test.
#
# Validates two things the appliance promises:
#   1. Healthchecks actually fail when the underlying service breaks
#      (not just on first boot).  We pause postgres and assert its
#      status flips to "unhealthy" within the start_period × retries
#      window declared in docker-compose.yml.
#   2. Recovery: unpausing brings the service back to "healthy" without
#      manual intervention.
#
# Plus a SIGKILL test on synapse to verify the unless-stopped restart
# policy actually does fail-over recovery, not just first-boot startup.
#
# Assumes the stack is already up.  Idempotent; cleans up via trap so a
# half-finished run doesn't leave services paused.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
step()  { bold "→ $*"; }
fail()  { red "FAIL: $*"; exit 1; }

cleanup() {
    # Make sure we don't leave anything paused if the test errors out.
    docker unpause pureprivacy-postgres >/dev/null 2>&1 || true
    docker unpause pureprivacy-synapse >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "ensuring stack is up + initially healthy"
./scripts/pureprivacy up >/dev/null

container_health() {
    docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null \
        || echo "absent"
}

container_running() {
    docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null \
        || echo "false"
}

wait_for_health() {
    # wait_for_health <container> <expected> <timeout-seconds>
    local container="$1" expected="$2" timeout="$3"
    local deadline=$((SECONDS + timeout))
    while [[ ${SECONDS} -lt ${deadline} ]]; do
        local current
        current="$(container_health "${container}")"
        if [[ "${current}" == "${expected}" ]]; then
            return 0
        fi
        sleep 2
    done
    red "  timed out: ${container} health = $(container_health "${container}") (expected ${expected})"
    return 1
}

wait_for_running() {
    local container="$1" timeout="$2"
    local deadline=$((SECONDS + timeout))
    while [[ ${SECONDS} -lt ${deadline} ]]; do
        if [[ "$(container_running "${container}")" == "true" ]]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# =========================================================================
# Test 1: pause postgres → healthcheck flips to unhealthy → unpause recovers
# =========================================================================
step "Test 1: pausing postgres should drive its healthcheck unhealthy"
[[ "$(container_health pureprivacy-postgres)" == "healthy" ]] \
    || fail "postgres not healthy at start"
docker pause pureprivacy-postgres >/dev/null

# Compose has interval=5s, retries=5 → ~25s to flip.  Allow generous slack.
if ! wait_for_health pureprivacy-postgres unhealthy 90; then
    fail "postgres healthcheck did not detect pause within 90s"
fi
green "  postgres flipped to unhealthy after pause"

step "Test 1: unpause → recovery to healthy"
docker unpause pureprivacy-postgres >/dev/null
if ! wait_for_health pureprivacy-postgres healthy 60; then
    fail "postgres did not recover to healthy within 60s after unpause"
fi
green "  postgres recovered after unpause"

# =========================================================================
# Test 2: SIGKILL synapse → unless-stopped policy auto-restarts → healthy
# =========================================================================
step "Test 2: SIGKILL synapse should be auto-restarted by Docker"
SYNAPSE_PID_BEFORE="$(docker inspect -f '{{.State.Pid}}' pureprivacy-synapse)"
[[ -n "${SYNAPSE_PID_BEFORE}" ]] || fail "could not read synapse pid"

# Use docker kill instead of kill -9 the host pid, so we don't need
# CAP_KILL on the test runner.
docker kill --signal=SIGKILL pureprivacy-synapse >/dev/null

# unless-stopped should bring it back.  Synapse takes a while to come up
# (DB migrations on every cold start are short, but Synapse itself is
# slow); allow up to 4 minutes including the start_period.
if ! wait_for_running pureprivacy-synapse 60; then
    fail "synapse not running 60s after SIGKILL"
fi
SYNAPSE_PID_AFTER="$(docker inspect -f '{{.State.Pid}}' pureprivacy-synapse)"
[[ "${SYNAPSE_PID_BEFORE}" != "${SYNAPSE_PID_AFTER}" ]] \
    || fail "synapse pid unchanged after SIGKILL — restart didn't happen"

if ! wait_for_health pureprivacy-synapse healthy 240; then
    fail "synapse did not return to healthy within 4 minutes of SIGKILL"
fi
green "  synapse auto-restarted by Docker and returned to healthy"

# =========================================================================
# Test 3: pureprivacy wait correctly times out on a paused service.
# Ensures the user-facing wait_healthy() helper doesn't hang forever.
# =========================================================================
step "Test 3: pureprivacy wait reports failure when a service is unhealthy"
docker pause pureprivacy-postgres >/dev/null
if ! wait_for_health pureprivacy-postgres unhealthy 90; then
    docker unpause pureprivacy-postgres >/dev/null
    fail "postgres did not flip unhealthy in setup for Test 3"
fi
# WAIT_TIMEOUT keeps Test 3 short; the real wait_healthy() defaults to 300s.
WAIT_OUT="$(WAIT_TIMEOUT=15 ./scripts/pureprivacy wait 2>&1 || true)"
docker unpause pureprivacy-postgres >/dev/null
[[ "${WAIT_OUT}" == *"unhealthy"* ]] || [[ "${WAIT_OUT}" == *"FAILED"* ]] \
    || fail "pureprivacy wait did not surface unhealthy postgres (got: ${WAIT_OUT:0:300})"
# Wait for recovery so subsequent tests aren't affected.
wait_for_health pureprivacy-postgres healthy 60 \
    || fail "postgres did not recover for downstream tests"
green "  pureprivacy wait correctly reported the failure and exited"

echo
green "✓ all healthcheck tests PASSED"
