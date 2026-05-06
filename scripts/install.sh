#!/usr/bin/env bash
# Put `pureprivacy` on the user's PATH by symlinking
# scripts/pureprivacy into ~/.local/bin (or /usr/local/bin with --system).
# Idempotent: re-running is a no-op if the symlink already points here.
set -euo pipefail

# Resolve through symlinks so the install picks up the real repo even when
# this script itself is being run via a symlink.
SCRIPT_PATH="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}")"
ROOT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")/.." && pwd)"
TARGET="${ROOT_DIR}/scripts/pureprivacy"

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

if [[ ! -x "${TARGET}" ]]; then
    red "Cannot find ${TARGET}.  Run this from inside the PurePrivacy repo."
    exit 1
fi

mode="user"
for arg in "$@"; do
    case "${arg}" in
        --system) mode="system" ;;
        --user)   mode="user" ;;
        -h|--help)
            cat <<'EOF'
Usage: ./scripts/install.sh [--user | --system | --uninstall]

  --user       (default) symlink to ~/.local/bin/pureprivacy.
               Make sure ~/.local/bin is on your PATH.
  --system     symlink to /usr/local/bin/pureprivacy (needs sudo).
  --uninstall  remove the symlink from both locations.
EOF
            exit 0
            ;;
        --uninstall)
            removed=0
            for p in "${HOME}/.local/bin/pureprivacy" "/usr/local/bin/pureprivacy"; do
                if [[ -L "${p}" ]]; then
                    if [[ -w "$(dirname "${p}")" ]]; then
                        rm -f "${p}"
                    else
                        sudo rm -f "${p}"
                    fi
                    green "removed ${p}"
                    removed=$((removed + 1))
                fi
            done
            [[ "${removed}" -eq 0 ]] && yellow "no pureprivacy symlink found."
            exit 0
            ;;
        *)
            red "unknown flag: ${arg}"
            exit 2
            ;;
    esac
done

if [[ "${mode}" == "system" ]]; then
    LINK_DIR="/usr/local/bin"
    if [[ "$(id -u)" -ne 0 ]]; then
        yellow "Re-running with sudo to write to ${LINK_DIR}..."
        exec sudo "$0" --system
    fi
else
    LINK_DIR="${HOME}/.local/bin"
    mkdir -p "${LINK_DIR}"
fi

LINK="${LINK_DIR}/pureprivacy"

# If the link already points where we want, skip the work.
if [[ -L "${LINK}" ]] && [[ "$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${LINK}")" == "${TARGET}" ]]; then
    green "Already installed at ${LINK} → ${TARGET}"
elif [[ -e "${LINK}" ]] && [[ ! -L "${LINK}" ]]; then
    red "${LINK} exists and is not a symlink.  Move it aside and re-run."
    exit 1
else
    ln -snf "${TARGET}" "${LINK}"
    green "Installed: ${LINK} → ${TARGET}"
fi

# Sanity-check PATH.
case ":${PATH}:" in
    *":${LINK_DIR}:"*) ;;
    *)
        echo
        yellow "Note: ${LINK_DIR} is not on your PATH."
        if [[ "${mode}" == "user" ]]; then
            yellow "Add this to your shell profile (~/.zshrc, ~/.bashrc, …):"
            echo
            echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
            echo
            yellow "Then open a new terminal and verify:  pureprivacy help"
        fi
        ;;
esac

if command -v pureprivacy >/dev/null 2>&1 && [[ "$(command -v pureprivacy)" == "${LINK}" ]]; then
    echo
    green "Done.  Try:  pureprivacy help"
fi
