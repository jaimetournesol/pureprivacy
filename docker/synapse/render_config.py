"""Render Synapse's homeserver.yaml from the bundled template.

Replaces the previous envsubst step.  We need actual templating now because
`federation_domain_whitelist` is a list pulled from /shared/pairings.json,
not a scalar.
"""
from __future__ import annotations

import json
import os
import string
import sys
from pathlib import Path


SHARED = Path(os.environ.get("SHARED", "/shared"))
TEMPLATE = Path("/pureprivacy/homeserver.yaml.tmpl")


def federation_whitelist() -> list[str]:
    """List of paired-peer hostnames (typically .onion) to allow federation with."""
    p = SHARED / "pairings.json"
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    peers = data.get("peers", [])
    return [peer["onion"] for peer in peers if peer.get("onion")]


def cert_verification_whitelist(peers: list[str]) -> list[str]:
    """Per-peer hostnames where Synapse should skip CA validation.

    Tor hidden services have no publicly-trusted certs; the QR pairing flow
    is the trust root for their identity.  Clearnet peers (if any are ever
    added in a future version) keep normal CA-based validation, so we only
    list the .onion hostnames that actually need the bypass.
    """
    return [p for p in peers if p.endswith(".onion")]


def main() -> None:
    template_src = TEMPLATE.read_text(encoding="utf-8")

    peers = federation_whitelist()
    own_server = os.environ["SERVER_NAME"]

    # YAML accepts JSON-style list syntax, so json.dumps gives us a clean
    # one-line representation for the template.
    fed_whitelist = json.dumps([own_server, *peers])
    cert_whitelist = json.dumps(cert_verification_whitelist(peers))

    # `federation_enabled` is implicit: an empty whitelist disables federation,
    # a non-empty one enables it but limits which peers can talk to us.
    rendered = string.Template(template_src).substitute(
        SERVER_NAME=own_server,
        POSTGRES_PASSWORD=os.environ["POSTGRES_PASSWORD"],
        REGISTRATION_SHARED_SECRET=os.environ["REGISTRATION_SHARED_SECRET"],
        MACAROON_SECRET_KEY=os.environ["MACAROON_SECRET_KEY"],
        FORM_SECRET=os.environ["FORM_SECRET"],
        TURN_SHARED_SECRET=os.environ["TURN_SHARED_SECRET"],
        FEDERATION_DOMAIN_WHITELIST=fed_whitelist,
        FEDERATION_CERT_WHITELIST=cert_whitelist,
    )
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()
