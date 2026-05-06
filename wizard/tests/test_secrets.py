"""Tests for the secrets module: setup state load/save, MCP grace window."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from wizard import secrets as wizsec


class LoadEmpty(unittest.TestCase):
    def test_clean_dir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            state = wizsec.load_setup_state(Path(d))
            self.assertFalse(state.complete)
            self.assertIsNone(state.onion)
            self.assertIsNone(state.admin_user)
            self.assertEqual(state.mcp_grace_remaining_s, 0)


class MarkSetupComplete(unittest.TestCase):
    def test_round_trip_with_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            (shared / "secrets").mkdir()
            (shared / "onion_hostname").write_text("abc.onion\n")
            (shared / "secrets" / "registration_shared_secret").write_text("secret\n")
            (shared / "secrets" / "mcp_bearer_token").write_text("token\n")
            wizsec.mark_setup_complete(
                shared,
                admin_user="@admin:abc.onion",
                admin_password="hunter2-very-long",
                mcp_user="@pureprivacy-mcp:abc.onion",
                recovery_passphrase="ABCD-EFGH-IJKL-MNOP",
            )
            state = wizsec.load_setup_state(shared)
            self.assertTrue(state.complete)
            self.assertEqual(state.admin_user, "@admin:abc.onion")
            self.assertEqual(state.admin_password, "hunter2-very-long")
            self.assertEqual(state.mcp_user, "@pureprivacy-mcp:abc.onion")
            self.assertEqual(state.recovery_passphrase, "ABCD-EFGH-IJKL-MNOP")
            self.assertEqual(state.onion, "abc.onion")
            # mode is 0600
            mode = os.stat(shared / ".setup-complete").st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_optional_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            wizsec.mark_setup_complete(
                shared,
                admin_user="@a:o",
                admin_password="pw",
                mcp_user="@b:o",
            )
            state = wizsec.load_setup_state(shared)
            self.assertIsNone(state.recovery_passphrase)


class UpdateAdminPassword(unittest.TestCase):
    def test_only_password_changes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            wizsec.mark_setup_complete(
                shared,
                admin_user="@admin:abc.onion",
                admin_password="old-password",
                mcp_user="@bot:abc.onion",
                recovery_passphrase="ABCD-EFGH-IJKL-MNOP",
            )
            wizsec.update_admin_password(shared, new_password="new-password")
            state = wizsec.load_setup_state(shared)
            self.assertEqual(state.admin_password, "new-password")
            # Other fields preserved.
            self.assertEqual(state.admin_user, "@admin:abc.onion")
            self.assertEqual(state.mcp_user, "@bot:abc.onion")
            self.assertEqual(state.recovery_passphrase, "ABCD-EFGH-IJKL-MNOP")

    def test_missing_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):
                wizsec.update_admin_password(Path(d), new_password="x")


class MCPTokenGrace(unittest.TestCase):
    def test_no_prev_file(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(
                wizsec.previous_mcp_token_grace_remaining_s(Path(d)), 0
            )

    def test_within_window(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            (shared / "secrets").mkdir()
            prev = shared / "secrets" / "mcp_bearer_token.prev"
            prev.write_text("oldtoken\n")
            # mtime = now → ~MCP_TOKEN_GRACE_SECONDS remaining.
            remaining = wizsec.previous_mcp_token_grace_remaining_s(shared)
            self.assertGreater(remaining, wizsec.MCP_TOKEN_GRACE_SECONDS - 5)
            self.assertLessEqual(remaining, wizsec.MCP_TOKEN_GRACE_SECONDS)

    def test_expired(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            shared = Path(d)
            (shared / "secrets").mkdir()
            prev = shared / "secrets" / "mcp_bearer_token.prev"
            prev.write_text("oldtoken\n")
            # Push mtime back beyond the window.
            past = time.time() - wizsec.MCP_TOKEN_GRACE_SECONDS - 60
            os.utime(prev, (past, past))
            self.assertEqual(
                wizsec.previous_mcp_token_grace_remaining_s(shared), 0
            )


if __name__ == "__main__":
    unittest.main()
