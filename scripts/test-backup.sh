#!/usr/bin/env bash
# Backup → restore round-trip test.
#
# What it proves:
#   1. `pureprivacy backup` produces a tarball that contains real state.
#   2. `pureprivacy restore` actually overwrites every PurePrivacy volume
#      from that tarball — state added AFTER the backup is gone post-restore.
#   3. State that existed BEFORE the backup survives the round-trip
#      intact: onion identity, admin password, the marker user we added.
#
# The negative half (post-backup state must not survive restore) is the
# important part — it catches a restore that leaves stale data behind.
#
# Long: takes ~4 minutes because it does a full down/restore/up cycle
# including Synapse's first-run sanity checks.  Idempotent; cleans up
# the tarball + marker users on exit.
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

BACKUP_DIR="$(mktemp -d -t pureprivacy-backup-test.XXXXXX)"
TARBALL=""
MARKER_PRE="marker-pre-$$"
MARKER_POST="marker-post-$$"

cleanup() {
    [[ -n "${TARBALL}" ]] && rm -f "${TARBALL}"
    rm -rf "${BACKUP_DIR}"
    # Best-effort: deactivate the marker users we added so they don't
    # accumulate across CI runs against a re-used host.
    ./scripts/pureprivacy user remove "${MARKER_PRE}" >/dev/null 2>&1 || true
    ./scripts/pureprivacy user remove "${MARKER_POST}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "ensuring stack is up + setup complete"
./scripts/pureprivacy up >/dev/null
docker exec ${WIZARD} test -f /shared/.setup-complete \
    || fail "setup not complete; run scripts/test-e2e.sh first"

ONION_BEFORE="$(docker exec ${TOR} cat /shared/onion_hostname)"
ADMIN_PW_BEFORE="$(docker exec ${WIZARD} python3 -c '
import json
print(json.load(open("/shared/.setup-complete"))["admin_password"])
')"
[[ -n "${ONION_BEFORE}" ]] || fail "no onion hostname"
[[ -n "${ADMIN_PW_BEFORE}" ]] || fail "no admin password"

# =========================================================================
# Step 1: add a marker user that should survive the round-trip
# =========================================================================
step "adding pre-backup marker user @${MARKER_PRE}"
./scripts/pureprivacy user add "${MARKER_PRE}" >/dev/null

# =========================================================================
# Step 2: backup
# =========================================================================
step "backing up to ${BACKUP_DIR}/snapshot.tar.gz"
TARBALL="${BACKUP_DIR}/snapshot.tar.gz"
./scripts/pureprivacy backup "${TARBALL}" >/dev/null
[[ -s "${TARBALL}" ]] || fail "backup tarball is empty"
# Stash du's output before piping to awk: with `set -o pipefail`, awk
# closing the pipe early can turn a transient du stderr into an exit
# 141 that kills the whole test.
DU_OUT="$(du -h "${TARBALL}")" || fail "du failed for ${TARBALL}"
green "  backup wrote $(awk '{print $1}' <<<"${DU_OUT}")"

# Backup briefly stops the stack; bring it back so Step 3 works.
./scripts/pureprivacy up >/dev/null

# =========================================================================
# Step 3: add a marker that should NOT survive (added AFTER backup)
# =========================================================================
step "adding post-backup marker user @${MARKER_POST}"
./scripts/pureprivacy user add "${MARKER_POST}" >/dev/null

# Verify both markers visible right now (sanity).
LIST_NOW="$(./scripts/pureprivacy user list)"
[[ "${LIST_NOW}" == *"@${MARKER_PRE}:"* ]] \
    || fail "pre-marker missing from current state"
[[ "${LIST_NOW}" == *"@${MARKER_POST}:"* ]] \
    || fail "post-marker missing from current state"

# =========================================================================
# Step 4: down → restore → up
# =========================================================================
step "tearing the stack down"
./scripts/pureprivacy down >/dev/null

step "restoring from ${TARBALL}"
echo "restore" | ./scripts/pureprivacy restore "${TARBALL}" >/dev/null

step "bringing the stack back up (Synapse cold-start; takes a few minutes)"
./scripts/pureprivacy up >/dev/null

# =========================================================================
# Step 5: verify pre-backup state survived, post-backup state did not
# =========================================================================
step "verifying the round-trip"
ONION_AFTER="$(docker exec ${TOR} cat /shared/onion_hostname)"
[[ "${ONION_AFTER}" == "${ONION_BEFORE}" ]] \
    || fail "onion identity changed: ${ONION_BEFORE} → ${ONION_AFTER}"

ADMIN_PW_AFTER="$(docker exec ${WIZARD} python3 -c '
import json
print(json.load(open("/shared/.setup-complete"))["admin_password"])
')"
[[ "${ADMIN_PW_AFTER}" == "${ADMIN_PW_BEFORE}" ]] \
    || fail "admin password changed across restore"

# user list goes through the cached admin token, which may have been
# captured in the backup (still valid) or invalidated.  _admin_session
# self-heals via whoami → re-login on stale, so just call it.
LIST_AFTER="$(./scripts/pureprivacy user list)"
[[ "${LIST_AFTER}" == *"@${MARKER_PRE}:"* ]] \
    || fail "pre-backup marker @${MARKER_PRE} disappeared (restore corrupted Synapse state)"

# This is the load-bearing assertion: post-backup state must be gone.
if [[ "${LIST_AFTER}" == *"@${MARKER_POST}:"* ]]; then
    # Synapse keeps deactivated localparts in the listing — but the marker
    # was created AFTER the backup, so it shouldn't appear at all.
    fail "post-backup marker @${MARKER_POST} survived restore — restore did not clean stale state"
fi
green "  pre-backup state survived; post-backup state did not"

echo
green "✓ backup → restore round-trip PASSED"
