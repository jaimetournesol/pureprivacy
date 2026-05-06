"""Tests for the recovery-key module.

Run with:
    PYTHONPATH=src python3 -m unittest discover -s tests
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wizard.recovery import (
    generate_recovery_key,
    hash_recovery_key,
    hash_path,
    load_recovery_hash,
    normalise_recovery_key,
    verify_recovery_key,
    write_recovery_hash,
)


class GenerateAndShape(unittest.TestCase):
    def test_format(self) -> None:
        for _ in range(20):
            k = generate_recovery_key()
            # 16 base32 chars + 3 dashes
            self.assertEqual(len(k), 19)
            self.assertEqual(k.count("-"), 3)
            # No padding, only RFC 4648 base32 alphabet
            for c in k.replace("-", ""):
                self.assertIn(c, "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")

    def test_uniqueness(self) -> None:
        keys = {generate_recovery_key() for _ in range(200)}
        # 80-bit space, 200 samples — a collision would be a serious bug.
        self.assertEqual(len(keys), 200)


class Normalisation(unittest.TestCase):
    def test_dashes_spaces_case(self) -> None:
        canonical = "ABCD2345EFGH"
        self.assertEqual(normalise_recovery_key("ABCD-2345-EFGH"), canonical)
        self.assertEqual(normalise_recovery_key("abcd-2345-efgh"), canonical)
        self.assertEqual(normalise_recovery_key("ABCD 2345 EFGH"), canonical)
        self.assertEqual(normalise_recovery_key("abcd2345efgh"), canonical)

    def test_strips_invalid_chars(self) -> None:
        # 8/9/0/1 not in base32 alphabet — they get stripped.
        self.assertEqual(normalise_recovery_key("AB!CD@2345#EF$GH"), "ABCD2345EFGH")
        self.assertEqual(normalise_recovery_key("ABCD0189EFGH"), "ABCDEFGH")


class HashAndVerify(unittest.TestCase):
    def test_round_trip(self) -> None:
        k = generate_recovery_key()
        h = hash_recovery_key(k)
        self.assertTrue(verify_recovery_key(k, h))

    def test_lowercase_input_verifies(self) -> None:
        k = generate_recovery_key()
        h = hash_recovery_key(k)
        self.assertTrue(verify_recovery_key(k.lower(), h))

    def test_no_dashes_verifies(self) -> None:
        k = generate_recovery_key()
        h = hash_recovery_key(k)
        self.assertTrue(verify_recovery_key(k.replace("-", ""), h))

    def test_spaces_verify(self) -> None:
        k = generate_recovery_key()
        h = hash_recovery_key(k)
        self.assertTrue(verify_recovery_key(k.replace("-", "  "), h))

    def test_wrong_key_fails(self) -> None:
        h = hash_recovery_key(generate_recovery_key())
        self.assertFalse(verify_recovery_key(generate_recovery_key(), h))

    def test_empty_input_fails(self) -> None:
        h = hash_recovery_key(generate_recovery_key())
        self.assertFalse(verify_recovery_key("", h))
        self.assertFalse(verify_recovery_key("---", h))

    def test_garbage_hash_fails(self) -> None:
        self.assertFalse(verify_recovery_key("ABCD-2345-EFGH-IJKL", "garbage"))
        self.assertFalse(verify_recovery_key("ABCD-2345-EFGH-IJKL", ""))
        self.assertFalse(verify_recovery_key("ABCD-2345-EFGH-IJKL", "scrypt$nope"))

    def test_hash_format_self_describing(self) -> None:
        h = hash_recovery_key(generate_recovery_key())
        # We embed the parameters so future tweaks remain forward-compatible.
        self.assertTrue(h.startswith("pbkdf2$sha256$iter="))
        self.assertEqual(h.count("$"), 4)


class OnDiskRoundTrip(unittest.TestCase):
    def test_write_then_load(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            (shared / "secrets").mkdir()
            k = generate_recovery_key()
            h = hash_recovery_key(k)
            write_recovery_hash(shared, h)
            self.assertEqual(load_recovery_hash(shared), h)
            # Permissions must be 0600.
            mode = os.stat(hash_path(shared)).st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(load_recovery_hash(Path(d)))


if __name__ == "__main__":
    unittest.main()
