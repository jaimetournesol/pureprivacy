"""PurePrivacy MCP server entry point."""
from __future__ import annotations

import logging
import os

from .server import main

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


if __name__ == "__main__":
    main()
