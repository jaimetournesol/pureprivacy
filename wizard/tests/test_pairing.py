"""Tests for the pairing module."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from wizard import pairing


ONION_SELF = "abcdefghijklmnopqrstuvwxyz234567abcdefghijklmnopqrstuvwx234567a.onion"
ONION_PEER = "zyxwvutsrqponmlkjihgfedcba765432zyxwvutsrqponmlkjihgfedcba765432.onion"


class CodeGeneration(unittest.TestCase):
    def test_generate_requires_onion(self) -> None:
        with self.assertRaises(ValueError):
            pairing.generate_code("not-an-onion.example.com")

    def test_generate_includes_required_fields(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        self.assertEqual(code["version"], pairing.PAIR_VERSION)
        self.assertEqual(code["onion"], ONION_SELF)
        self.assertGreater(code["expires_at"], int(time.time()))
        self.assertIsInstance(code["nonce"], str)
        self.assertGreaterEqual(len(code["nonce"]), 16)


class EncodeDecode(unittest.TestCase):
    def test_round_trip(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        blob = pairing.encode_code(code)
        decoded = pairing.decode_code(blob)
        self.assertEqual(decoded, code)

    def test_decode_bad_base64(self) -> None:
        with self.assertRaises(ValueError):
            pairing.decode_code("!!!not-base64!!!")

    def test_decode_bad_json(self) -> None:
        import base64

        bad = base64.urlsafe_b64encode(b"not-json").decode()
        with self.assertRaises(ValueError):
            pairing.decode_code(bad)

    def test_decode_wrong_version(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        code["version"] = 999
        blob = pairing.encode_code(code)
        with self.assertRaises(ValueError) as ctx:
            pairing.decode_code(blob)
        self.assertIn("version", str(ctx.exception))

    def test_decode_expired(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        code["expires_at"] = int(time.time()) - 60
        blob = pairing.encode_code(code)
        with self.assertRaises(ValueError) as ctx:
            pairing.decode_code(blob)
        self.assertIn("expired", str(ctx.exception))

    def test_decode_missing_nonce(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        code["nonce"] = ""
        blob = pairing.encode_code(code)
        with self.assertRaises(ValueError):
            pairing.decode_code(blob)

    def test_decode_non_onion(self) -> None:
        code = pairing.generate_code(ONION_SELF)
        code["onion"] = "matrix.example.com"
        blob = pairing.encode_code(code)
        with self.assertRaises(ValueError):
            pairing.decode_code(blob)


class StoreRoundTrip(unittest.TestCase):
    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            self.assertEqual(pairing.load_pairings(shared), [])
            code = pairing.generate_code(ONION_PEER)
            new = pairing.save_pairing(shared, code)
            self.assertEqual(new.onion, ONION_PEER)
            peers = pairing.load_pairings(shared)
            self.assertEqual([p.onion for p in peers], [ONION_PEER])

    def test_replay_protection(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            code = pairing.generate_code(ONION_PEER)
            pairing.save_pairing(shared, code)
            # Same nonce: rejected.
            with self.assertRaises(ValueError):
                pairing.save_pairing(shared, code)

    def test_re_pair_with_fresh_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            pairing.save_pairing(shared, pairing.generate_code(ONION_PEER))
            # Different nonce, same peer: refresh entry, not duplicate.
            time.sleep(0.001)
            pairing.save_pairing(shared, pairing.generate_code(ONION_PEER))
            peers = pairing.load_pairings(shared)
            self.assertEqual(len(peers), 1)

    def test_remove(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            pairing.save_pairing(shared, pairing.generate_code(ONION_PEER))
            self.assertTrue(pairing.remove_pairing(shared, ONION_PEER))
            self.assertEqual(pairing.load_pairings(shared), [])
            # Removing a non-existent peer returns False, doesn't error.
            self.assertFalse(pairing.remove_pairing(shared, ONION_PEER))

    def test_load_handles_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            (shared / "pairings.json").write_text("{not json")
            self.assertEqual(pairing.load_pairings(shared), [])


if __name__ == "__main__":
    unittest.main()
