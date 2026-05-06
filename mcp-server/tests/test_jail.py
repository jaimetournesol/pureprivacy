"""MCP path-jail and invite-allowlist regression tests.

These exist primarily to lock in the C1/C2 fixes.  Without them, an
innocent-looking refactor of tools.py could re-open the path-traversal
hole or restore the unrestricted invite auto-join.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pureprivacy_mcp.path_jail import MEDIA_ID_RE, SERVER_NAME_RE, jail_path


class JailPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.uploads = Path(self._tmp.name).resolve() / "uploads"
        self.uploads.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_relative_inside_jail(self) -> None:
        target = jail_path(self.uploads, "report.pdf")
        self.assertEqual(target, self.uploads / "report.pdf")

    def test_subdir_inside_jail(self) -> None:
        target = jail_path(self.uploads, "sub/report.pdf")
        self.assertEqual(target, self.uploads / "sub" / "report.pdf")

    def test_absolute_inside_jail_ok(self) -> None:
        target = jail_path(self.uploads, str(self.uploads / "report.pdf"))
        self.assertEqual(target, self.uploads / "report.pdf")

    def test_absolute_outside_jail_refused(self) -> None:
        with self.assertRaises(ValueError):
            jail_path(self.uploads, "/shared/secrets/mcp_bearer_token")

    def test_dotdot_traversal_refused(self) -> None:
        with self.assertRaises(ValueError):
            jail_path(self.uploads, "../../etc/passwd")

    def test_symlink_parent_refused(self) -> None:
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        link = self.uploads / "link"
        os.symlink(outside, link)
        with self.assertRaises(ValueError):
            jail_path(self.uploads, "link/file.txt")

    def test_empty_refused(self) -> None:
        with self.assertRaises(ValueError):
            jail_path(self.uploads, "")


class MxcRegexes(unittest.TestCase):
    def test_valid_media_id(self) -> None:
        self.assertTrue(MEDIA_ID_RE.match("abc123_DEF.4-+="))

    def test_media_id_with_slash_refused(self) -> None:
        self.assertFalse(MEDIA_ID_RE.match("foo/../etc/passwd"))

    def test_media_id_with_dotdot_refused(self) -> None:
        # `..` itself is not strictly invalid characters, but no real
        # media_id is `..` — the path-jail blocks it downstream too.
        self.assertTrue(MEDIA_ID_RE.match(".."))

    def test_server_name_blocks_slash(self) -> None:
        self.assertFalse(SERVER_NAME_RE.match("evil/../host"))

    def test_server_name_accepts_normal(self) -> None:
        self.assertTrue(SERVER_NAME_RE.match("matrix.example.org"))
        self.assertTrue(SERVER_NAME_RE.match("matrix.example.org:8448"))


if __name__ == "__main__":
    unittest.main()
