#!/usr/bin/env bash
# Run every available test suite in dependency order.
#
# Layers:
#   1. Python unit tests for the wizard package — no docker required.
#   2. Bash integration tests that talk to a running stack.  These require
#      `pureprivacy up` to have completed.  Set PUREPRIVACY_RESET=1 to
#      destroy and rebuild from scratch first.
#
# Use:
#     scripts/test-all.sh                    # run everything against the
#                                            # currently-up stack
#     PUREPRIVACY_RESET=1 scripts/test-all.sh   # full clean-slate run
#     PUREPRIVACY_NO_DOCKER=1 scripts/test-all.sh   # skip docker-y tests
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
hr()    { printf '%s\n' '────────────────────────────────────────────'; }

# Set to "1" if any layer was skipped so the final summary can stay
# honest: "✓ all available tests" hides the fact that the unit test
# layer (or the docker-dependent layers) was never actually run.
ANY_LAYER_SKIPPED=0

# Pick a Python with dataclass(slots=True) support — wizard's modules
# require Python 3.10+.  Fall back to whatever python3 is on PATH.
PYBIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "${candidate}" >/dev/null 2>&1; then
        if "${candidate}" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
            PYBIN="$(command -v "${candidate}")"
            break
        fi
    fi
done
if [[ -z "${PYBIN}" ]]; then
    red "no Python ≥ 3.10 found on PATH; skipping unit tests"
    ANY_LAYER_SKIPPED=1
fi

bold "=== Layer 1: Python unit tests ==="
if [[ -n "${PYBIN}" ]]; then
    (cd wizard && PYTHONPATH=src "${PYBIN}" -m unittest discover -s tests -v)
    (cd mcp-server && PYTHONPATH=src "${PYBIN}" -m unittest discover -s tests -v)
else
    red "  skipped (no python ≥ 3.10)"
fi

hr

summarize() {
    if [[ "${ANY_LAYER_SKIPPED}" == "1" ]]; then
        yellow "⚠ ran some test layers; others were skipped — see notes above."
    else
        green "✓ all test layers PASSED"
    fi
}

if [[ "${PUREPRIVACY_NO_DOCKER:-0}" == "1" ]]; then
    bold "=== Skipping docker-dependent tests (PUREPRIVACY_NO_DOCKER=1) ==="
    ANY_LAYER_SKIPPED=1
    summarize
    exit 0
fi

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    red "docker not available; skipping integration tests"
    ANY_LAYER_SKIPPED=1
    summarize
    exit 0
fi

bold "=== Layer 2: end-to-end smoke (test-e2e.sh) ==="
PUREPRIVACY_RESET="${PUREPRIVACY_RESET:-0}" ./scripts/test-e2e.sh
hr

bold "=== Layer 3: feature regression (test-features.sh) ==="
./scripts/test-features.sh
hr

bold "=== Layer 4: restart survival (test-restart.sh) ==="
./scripts/test-restart.sh
hr

bold "=== Layer 5: healthcheck failure regression (test-health.sh) ==="
./scripts/test-health.sh
hr

bold "=== Layer 6: backup/restore round-trip (test-backup.sh) ==="
./scripts/test-backup.sh
hr

summarize
