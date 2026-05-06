"""Test the cert-verification-whitelist logic in docker/synapse/render_config.py.

This file lives outside the wizard package so we import it via importlib.
"""
from __future__ import annotations

import importlib.util
import os
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


class WellKnownVoiceGating(unittest.TestCase):
    """`extra_well_known_client_content` should only render under voice."""

    def setUp(self) -> None:
        self.mod = load_module()
        self._prev = os.environ.get("VOICE_ENABLED")

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("VOICE_ENABLED", None)
        else:
            os.environ["VOICE_ENABLED"] = self._prev

    def test_off_yields_empty_string(self) -> None:
        os.environ["VOICE_ENABLED"] = "0"
        self.assertEqual(self.mod.well_known_block("foo.onion"), "")

    def test_unset_yields_empty_string(self) -> None:
        os.environ.pop("VOICE_ENABLED", None)
        self.assertEqual(self.mod.well_known_block("foo.onion"), "")

    def test_on_advertises_livekit_url(self) -> None:
        os.environ["VOICE_ENABLED"] = "1"
        block = self.mod.well_known_block("foo.onion")
        self.assertIn("rtc_foci", block)
        self.assertIn("foo.onion:8082", block)

    def test_truthy_strings(self) -> None:
        for v in ("true", "TRUE", "yes", "1"):
            os.environ["VOICE_ENABLED"] = v
            self.assertIn("rtc_foci", self.mod.well_known_block("a.onion"))


if __name__ == "__main__":
    unittest.main()
