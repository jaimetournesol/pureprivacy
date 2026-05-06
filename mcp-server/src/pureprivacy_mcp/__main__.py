"""PurePrivacy MCP server entry point."""
from __future__ import annotations

import logging
import os

from .server import main


def _resolve_log_level(name: str) -> int:
    """Translate LOG_LEVEL env var into a real logging level int.

    `logging.basicConfig(level="DEBUG")` does work today, but it's an
    accident of CPython internals — strings are converted via
    ``logging.getLevelName`` which special-cases the standard names and
    silently maps everything else to ``Level <name>`` rather than
    erroring.  Resolve explicitly so a typo like ``LOG_LEVEL=DEBG`` is
    caught at startup.
    """
    name = (name or "INFO").strip().upper()
    mapping = logging.getLevelNamesMapping()  # 3.11+
    if name not in mapping:
        raise SystemExit(
            f"unknown LOG_LEVEL {name!r}; expected one of "
            f"{sorted(k for k, v in mapping.items() if isinstance(v, int))}"
        )
    return mapping[name]


logging.basicConfig(
    level=_resolve_log_level(os.environ.get("LOG_LEVEL", "INFO")),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


if __name__ == "__main__":
    main()
