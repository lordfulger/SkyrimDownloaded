"""Mod pictures for the info panel.

Nexus pictures are JPG/WebP, which Tk can't show by itself, so this uses Pillow
(bundled in the .exe; optional when running from source - without it there are
simply no pictures). Pictures are saved on disk so each is downloaded once.
"""

from __future__ import annotations

import hashlib
import io
import re
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


# -- pictures in a mod's description, matched to its files ------------------------------

_IMG = re.compile(r"\[img[^\]]*\]\s*(https?://[^\[\s]+?)\s*\[/img\]|<img[^>]+src=[\"'](https?://[^\"']+)[\"']", re.I)
_TOKEN = re.compile(r"[a-z]+(?:\s?\d+(?:\.\d+)?)?|\d+k", re.I)
_DULL = {"se", "sse", "ae", "le", "v", "ver", "file", "files", "main", "optional", "mod", "the", "for",
         "and", "or", "with", "a", "of", "to", "in", "by", "esp", "esl", "bsa", "loose", "k"}


def description_images(raw: str) -> list[tuple[str, str]]:
    """Pictures in a mod's description: (url, the text around it, mostly what comes before)."""
    from .text import bbcode_to_text
    out = []
    last = 0
    for m in _IMG.finditer(raw or ""):
        url = m.group(1) or m.group(2)
        before = bbcode_to_text(raw[last:m.start()]).strip()[-220:]
        if not before:  # pictures in a row: the caption may come after
            before = bbcode_to_text(raw[m.end():m.end() + 200]).split("[img")[0].strip()[:80]
        out.append((url, before))
        last = m.end()
    return out


def _tokens(text: str) -> set[str]:
    toks = set()
    for t in _TOKEN.findall((text or "").lower()):
        t = re.sub(r"\s+", " ", t).strip()
        if t and t not in _DULL and not re.fullmatch(r"\d+k|v?\d+(\.\d+)*", t):
            toks.add(t)
    return toks


def match_images(options, images: list[tuple[str, str]], mod_name: str = "") -> dict[int, str]:
    """{file_id: picture url}: a picture whose nearby text names what's special about a file
    ("Version 1", "Desaturated"...). Files with nothing special, or a tie, get none."""
    if not images or len(options) < 2:
        return {}
    names = {o.file_id: _tokens(o.name) for o in options}
    shared = set.intersection(*names.values()) if names else set()
    title = _tokens(mod_name)
    out: dict[int, str] = {}
    for o in options:
        special = names[o.file_id] - shared - title
        special = {t for t in special if len(t) > 2 and t.split(" ")[0] not in title}
        if not special:
            continue
        scored = []
        for url, context in images:
            ctx = context.lower()
            score = sum(1 for t in special if re.search(r"\b" + re.escape(t) + r"\b", ctx))
            scored.append((score, url))
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            out[o.file_id] = scored[0][1]
    return out
