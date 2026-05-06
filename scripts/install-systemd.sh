#!/usr/bin/env bash
# Install the PurePrivacy systemd unit so the appliance starts on host boot.
# Linux only.  Run as root or via sudo.
set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null \
    || echo "${BASH_SOURCE[0]}")"
ROOT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")/.." && pwd)"
TARGET_DIR="${TARGET_DIR:-/opt/pureprivacy}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "This installer is Linux-only.  On macOS, enable Docker Desktop's"
    echo "\"Start Docker Desktop when you log in\" option instead."
    exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Run with sudo:  sudo ./scripts/install-systemd.sh"
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd not found.  Install the unit manually for your init system."
    exit 1
fi

echo "Installing PurePrivacy as a systemd-managed service."
echo "  Repo:   ${ROOT_DIR}"
echo "  Target: ${TARGET_DIR}"
echo "  Unit:   ${UNIT_DIR}/pureprivacy.service"
echo

# Make the repo reachable at the path the unit references.  We don't move
# the repo — we symlink it, so the operator can `git pull` in place.
if [[ "${ROOT_DIR}" != "${TARGET_DIR}" ]]; then
    mkdir -p "$(dirname "${TARGET_DIR}")"
    if [[ -L "${TARGET_DIR}" || ! -e "${TARGET_DIR}" ]]; then
        ln -snf "${ROOT_DIR}" "${TARGET_DIR}"
    elif [[ "$(readlink -f "${TARGET_DIR}")" != "${ROOT_DIR}" ]]; then
        echo "${TARGET_DIR} exists and is not the right repo."
        echo "Either remove it, or set TARGET_DIR=$(pwd) before re-running."
        exit 1
    fi
fi

SRC_UNIT="${ROOT_DIR}/systemd/pureprivacy.service"
DST_UNIT="${UNIT_DIR}/pureprivacy.service"

# Sanity-check that the template still uses the placeholder we expect.
# A future refactor that moves the path string would otherwise leave the
# installed unit silently wrong (pointing at /opt/pureprivacy on a host
# where TARGET_DIR is something else).
if ! grep -q "/opt/pureprivacy" "${SRC_UNIT}"; then
    echo "Template ${SRC_UNIT} no longer contains '/opt/pureprivacy'."
    echo "Refusing to install — the placeholder path the installer rewrites is gone."
    exit 1
fi

cp "${SRC_UNIT}" "${DST_UNIT}"
sed -i "s|/opt/pureprivacy|${TARGET_DIR}|g" "${DST_UNIT}"

# Verify the rewrite landed.  If TARGET_DIR happened to equal
# /opt/pureprivacy this is a no-op and that's fine.
if [[ "${TARGET_DIR}" != "/opt/pureprivacy" ]] \
   && grep -q "/opt/pureprivacy" "${DST_UNIT}"; then
    echo "sed rewrite did not replace every /opt/pureprivacy in ${DST_UNIT}."
    echo "The installed unit would point at the wrong path; refusing to enable."
    exit 1
fi

systemctl daemon-reload
systemctl enable pureprivacy.service
echo
echo "Done.  Useful commands:"
echo "  sudo systemctl start pureprivacy        # bring it up now"
echo "  sudo systemctl status pureprivacy"
echo "  sudo systemctl stop pureprivacy"
echo "  sudo systemctl disable pureprivacy      # don't autostart"
echo "  sudo journalctl -u pureprivacy -f       # follow logs"
