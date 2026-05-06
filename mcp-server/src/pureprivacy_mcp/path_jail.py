"""Path-jail and mxc:// validators used by the MCP file tools.

Lives in its own module so tests can import the regexes and the jail
function without pulling in fastmcp / matrix-nio.  The bot ingests
untrusted prompts from Matrix rooms; without these guards an attacker
could read /shared/secrets/* or overwrite arbitrary container files via
upload_file / download_file.
"""
from __future__ import annotations

import re
from pathlib import Path

# Matrix media IDs are opaque server-issued tokens; the spec restricts
# them to URL-safe characters.  Refuse anything outside this set.
MEDIA_ID_RE = re.compile(r"^[A-Za-z0-9._=+-]{1,255}$")
# Server names follow host[:port].  Conservative.
SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9.\-:_]{1,255}$")


def jail_path(uploads_dir: Path, raw: str) -> Path:
    """Resolve `raw` and ensure it stays inside `uploads_dir`.

    Refuses absolute paths that escape the jail, paths that traverse via
    `..` after resolution, and any component that is a symlink.
    """
    if not raw:
        raise ValueError("path must not be empty")
    candidate = Path(raw)
    if candidate.is_absolute():
        try:
            rel = candidate.relative_to(uploads_dir)
        except ValueError as exc:
            raise ValueError(
                f"path {raw!r} must be inside {uploads_dir}"
            ) from exc
        target = (uploads_dir / rel).resolve()
    else:
        target = (uploads_dir / candidate).resolve()
    try:
        target.relative_to(uploads_dir)
    except ValueError as exc:
        raise ValueError(
            f"path {raw!r} resolves outside {uploads_dir}"
        ) from exc
    for parent in [target, *target.parents]:
        if parent == uploads_dir:
            break
        if parent.is_symlink():
            raise ValueError(f"refusing symlinked path component: {parent}")
    return target
