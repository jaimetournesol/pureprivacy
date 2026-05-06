"""Test the cert-verification-whitelist logic in docker/synapse/render_config.py.

This file lives outside the wizard package so we import it via importlib.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docker" / "synapse" / "render_config.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_config", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CertVerificationWhitelist(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_empty_peers(self) -> None:
        self.assertEqual(self.mod.cert_verification_whitelist([]), [])

    def test_only_onion_peers(self) -> None:
        peers = [
            "abc.onion",
            "def123456789012345678901234567890123456789012345678901234567890.onion",
        ]
        self.assertEqual(self.mod.cert_verification_whitelist(peers), peers)

    def test_only_clearnet_peers(self) -> None:
        # Clearnet peers should NOT be in the cert-verification-whitelist
        # because their CA certs validate normally.
        peers = ["matrix.example.com", "another.org"]
        self.assertEqual(self.mod.cert_verification_whitelist(peers), [])

    def test_mixed(self) -> None:
        # Bug we fixed: only the .onion peer needs the bypass.
        peers = ["abc.onion", "matrix.example.com"]
        self.assertEqual(
            self.mod.cert_verification_whitelist(peers),
            ["abc.onion"],
        )

    def test_no_blanket_wildcard(self) -> None:
        # Earlier versions emitted ['*.onion'] regardless; that broke mixed
        # peer setups.  Confirm we no longer use the wildcard.
        peers = ["xyz.onion"]
        wl = self.mod.cert_verification_whitelist(peers)
        self.assertNotIn("*.onion", wl)


if __name__ == "__main__":
    unittest.main()
