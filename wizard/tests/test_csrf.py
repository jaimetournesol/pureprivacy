"""CSRF token issue/verify round-trip + tampering rejection."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from wizard import csrf


class CSRFTokens(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.shared = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_round_trip_valid(self) -> None:
        tok = csrf.issue_token(self.shared)
        self.assertTrue(csrf.verify_token(self.shared, tok))

    def test_empty_rejected(self) -> None:
        self.assertFalse(csrf.verify_token(self.shared, ""))
        self.assertFalse(csrf.verify_token(self.shared, None))

    def test_tampered_rejected(self) -> None:
        tok = csrf.issue_token(self.shared)
        # Flip one character.
        bad = ("A" if tok[0] != "A" else "B") + tok[1:]
        self.assertFalse(csrf.verify_token(self.shared, bad))

    def test_garbage_rejected(self) -> None:
        self.assertFalse(csrf.verify_token(self.shared, "not-base64!@#"))
        self.assertFalse(csrf.verify_token(self.shared, "AAAA"))

    def test_expired_rejected(self) -> None:
        tok = csrf.issue_token(self.shared)
        future = time.time() + csrf.CSRF_TOKEN_LIFETIME_SECONDS + 60
        with mock.patch("wizard.csrf.time.time", return_value=future):
            self.assertFalse(csrf.verify_token(self.shared, tok))

    def test_different_box_rejected(self) -> None:
        # Tokens from one box's key must not validate against another.
        with tempfile.TemporaryDirectory() as other:
            other_tok = csrf.issue_token(Path(other))
        self.assertFalse(csrf.verify_token(self.shared, other_tok))


class OriginCheck(unittest.TestCase):
    def _req(self, host: str, origin: str | None, referer: str | None = None):
        headers = {"host": host}
        if origin is not None:
            headers["origin"] = origin
        if referer is not None:
            headers["referer"] = referer
        req = mock.Mock()
        req.headers.get = lambda k, default=None: headers.get(k.lower(), default)
        return req

    def test_origin_match(self) -> None:
        req = self._req("127.0.0.1:8088", "http://127.0.0.1:8088")
        self.assertTrue(csrf.origin_matches(req))

    def test_origin_mismatch(self) -> None:
        req = self._req("127.0.0.1:8088", "http://evil.example")
        self.assertFalse(csrf.origin_matches(req))

    def test_referer_fallback(self) -> None:
        req = self._req("127.0.0.1:8088", origin=None, referer="http://127.0.0.1:8088/login")
        self.assertTrue(csrf.origin_matches(req))

    def test_no_origin_no_referer_rejected(self) -> None:
        req = self._req("127.0.0.1:8088", origin=None, referer=None)
        self.assertFalse(csrf.origin_matches(req))


if __name__ == "__main__":
    unittest.main()
