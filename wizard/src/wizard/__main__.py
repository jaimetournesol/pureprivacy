"""PurePrivacy first-boot setup wizard."""
from __future__ import annotations

import os
import uvicorn

from .server import app


def main() -> None:
    host = os.environ.get("WIZARD_HOST", "0.0.0.0")
    port = int(os.environ.get("WIZARD_PORT", "8088"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
