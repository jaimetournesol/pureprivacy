#!/bin/sh
# PurePrivacy one-line installer.
#
# Designed to be served as a static asset and consumed via:
#
#     curl -fsSL https://pureprivacy.app/install | sh
#
# What it does, in order:
#   1. Detects the OS.
#   2. Verifies Docker is installed and running.  Does NOT auto-install
#      Docker — that's hostile in a curl-pipe.  Prints a one-line pointer
#      to the official installer if it's missing.
#   3. Clones (or updates) the repo at $PUREPRIVACY_DIR (default
#      ~/.pureprivacy).
#   4. Runs scripts/install.sh to symlink `pureprivacy` onto your PATH.
#   5. Runs `pureprivacy init` to bring the box up.  Curl-piped stdin
#      is not a TTY, so init runs non-interactively (-y) and generates
#      a random admin password.  Reveal it later with
#      `pureprivacy info --secrets`.
#
# Environment overrides:
#   PUREPRIVACY_DIR     install location (default ~/.pureprivacy)
#   PUREPRIVACY_REPO    git URL (default: upstream)
#   PUREPRIVACY_REF     git ref to check out (default: latest tag, else main)
#   NONINTERACTIVE      force -y even when stdin is a tty
#
# Strict POSIX sh; no bashisms.  Tested under bash, zsh, and dash.

set -eu

PUREPRIVACY_DIR="${PUREPRIVACY_DIR:-$HOME/.pureprivacy}"
PUREPRIVACY_REPO="${PUREPRIVACY_REPO:-https://github.com/jaimetournesol/pureprivacy.git}"
PUREPRIVACY_REF="${PUREPRIVACY_REF:-}"

# ---- pretty-printing -------------------------------------------------------
if [ -t 1 ]; then
    BOLD="$(printf '\033[1m')"
    DIM="$(printf '\033[2m')"
    RED="$(printf '\033[31m')"
    GREEN="$(printf '\033[32m')"
    NC="$(printf '\033[0m')"
else
    BOLD=""; DIM=""; RED=""; GREEN=""; NC=""
fi

err()  { printf '%s%s%s\n' "${RED}" "$*" "${NC}" >&2; }
ok()   { printf '%s%s%s\n' "${GREEN}" "$*" "${NC}"; }
note() { printf '%s%s%s\n' "${DIM}" "$*" "${NC}"; }
hdr()  { printf '\n%s%s%s\n' "${BOLD}" "$*" "${NC}"; }

abort() { err "$*"; exit 1; }

# ---- platform detection ----------------------------------------------------
detect_os() {
    case "$(uname -s 2>/dev/null)" in
        Linux*)   echo "linux" ;;
        Darwin*)  echo "macos" ;;
        MINGW*|MSYS*|CYGWIN*) echo "windows" ;;
        *)        echo "unknown" ;;
    esac
}

check_docker() {
    os="$1"
    if ! command -v docker >/dev/null 2>&1; then
        err "Docker is not installed."
        case "${os}" in
            macos|windows)
                err "  Install Docker Desktop:  https://docs.docker.com/desktop/" ;;
            linux)
                err "  Install Docker Engine:   https://docs.docker.com/engine/install/" ;;
            *)
                err "  See:                      https://docs.docker.com/get-docker/" ;;
        esac
        err "Then re-run this installer."
        exit 1
    fi
    if ! docker info >/dev/null 2>&1; then
        err "Docker is installed but the daemon isn't running."
        err "  Start Docker (or Docker Desktop) and wait for it to come up,"
        err "  then re-run this installer."
        exit 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        err "The 'docker compose' v2 plugin is not available."
        err "  On Linux, install the docker-compose-plugin package."
        err "  On macOS/Windows, update Docker Desktop."
        exit 1
    fi
}

# ---- repo fetch ------------------------------------------------------------
fetch_repo() {
    if [ -d "${PUREPRIVACY_DIR}/.git" ]; then
        hdr "Updating ${PUREPRIVACY_DIR}…"
        ( cd "${PUREPRIVACY_DIR}" && git fetch --tags --quiet origin ) \
            || abort "git fetch failed in ${PUREPRIVACY_DIR}"
    else
        hdr "Cloning into ${PUREPRIVACY_DIR}…"
        git clone --quiet "${PUREPRIVACY_REPO}" "${PUREPRIVACY_DIR}" \
            || abort "git clone failed"
    fi

    cd "${PUREPRIVACY_DIR}"
    if [ -n "${PUREPRIVACY_REF}" ]; then
        ref="${PUREPRIVACY_REF}"
    else
        # Latest tag wins; fall back to upstream main if there are none.
        ref="$(git tag --sort=-creatordate | head -1 || true)"
        if [ -z "${ref}" ]; then
            ref="origin/main"
        fi
    fi
    git -c advice.detachedHead=false checkout --quiet "${ref}" \
        || abort "git checkout ${ref} failed"
    note "  on ref: ${ref}"
}

# ---- main ------------------------------------------------------------------
hdr "PurePrivacy installer"

OS="$(detect_os)"
case "${OS}" in
    linux|macos)
        ;;
    windows)
        err "Windows: please run this inside WSL Ubuntu, not cmd/PowerShell."
        err "  PurePrivacy bundles Tor in a Linux container; cmd.exe can't"
        err "  drive Docker the way the appliance expects.  After installing"
        err "  WSL2 + Ubuntu, re-run the curl line inside Ubuntu's shell."
        exit 1
        ;;
    unknown)
        note "Could not identify your OS.  Continuing — Docker checks will"
        note "catch most incompatibilities." ;;
esac

if ! command -v git >/dev/null 2>&1; then
    abort "git is not installed.  Install it (it's tiny) and re-run."
fi

check_docker "${OS}"

fetch_repo

hdr "Putting \`pureprivacy\` on your PATH…"
sh "${PUREPRIVACY_DIR}/scripts/install.sh" --user

hdr "Bringing the box up…"
init_args=""
if [ ! -t 0 ] || [ -n "${NONINTERACTIVE:-}" ]; then
    # curl-piped stdin or explicit non-interactive: auto-generate the
    # admin password.  Reveal it via `pureprivacy info --secrets`.
    init_args="-y"
fi
# shellcheck disable=SC2086
sh "${PUREPRIVACY_DIR}/scripts/pureprivacy" init ${init_args}

ok ""
ok "Done."
note "Try:  pureprivacy help"
