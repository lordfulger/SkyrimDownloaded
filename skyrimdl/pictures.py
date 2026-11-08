"""Mod pictures for the info panel.

Nexus pictures are JPG/WebP, which Tk can't show by itself, so this uses Pillow
(bundled in the .exe; optional when running from source - without it there are
simply no pictures). Pictures are saved on disk so each is downloaded once.
"""

from __future__ import annotations

import hashlib
import io
import urllib.request

from . import __version__
from .nexuscache import cache_dir

try:
    from PIL import Image, ImageTk  # noqa: F401
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - depends on the install
    HAVE_PILLOW = False


def _file_for(url: str):
    return cache_dir() / "pictures" / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".img")


def fetch(url: str, timeout: float = 15.0) -> bytes | None:
    """The picture's bytes (from disk if seen before), or None."""
    if not url:
        return None
    path = _file_for(url)
    try:
        return path.read_bytes()
    except OSError:
        pass
    req = urllib.request.Request(url, headers={"User-Agent": f"SkyrimDownloaded/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(8 * 1024 * 1024)
    except Exception:
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except OSError:
        pass
    return data


def to_photo(data: bytes, max_width: int, max_height: int = 260):
    """A Tk image scaled to fit, or None if it can't be shown."""
    if not data:
        return None
    if HAVE_PILLOW:
        try:
            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            img.thumbnail((max(80, max_width), max_height))
            return ImageTk.PhotoImage(img)
        except Exception:
            return None
    try:  # without Pillow Tk can still show PNG and GIF
        import base64
        import tkinter as tk
        photo = tk.PhotoImage(data=base64.b64encode(data))
        factor = max(1, -(-photo.width() // max(80, max_width)))
        return photo.subsample(factor) if factor > 1 else photo
    except Exception:
        return None
