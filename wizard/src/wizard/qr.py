"""QR code rendering helpers."""
from __future__ import annotations

import base64
import io

import qrcode


def qr_png_data_url(data: str) -> str:
    """Return a `data:image/png;base64,…` URL for embedding in HTML."""
    if not data:
        return ""
    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
