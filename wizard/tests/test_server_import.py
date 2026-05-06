"""Smoke test: importing wizard.server must not raise.

A previous regression had `Depends(csrf.csrf_protect)` referencing a
module attribute that didn't exist; the wizard container would
crash-loop at startup. Other unit tests didn't catch it because they
import the helper modules directly. This test imports `server` so any
top-level evaluation error fails fast.
"""
from __future__ import annotations

import importlib
import unittest


class WizardServerImportTest(unittest.TestCase):
    def test_imports(self) -> None:
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest("fastapi not installed in this venv")
        module = importlib.import_module("wizard.server")
        self.assertTrue(hasattr(module, "app"))
        # Spot-check that /logout is registered (the route whose CSRF
        # binding regressed).  Routes is a list of Starlette Route objs.
        paths = {getattr(r, "path", None) for r in module.app.routes}
        self.assertIn("/logout", paths)
        self.assertIn("/healthz", paths)


if __name__ == "__main__":
    unittest.main()
