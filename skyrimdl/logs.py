"""A log file, so problems can be tracked down: what happened and any errors.

Written to %LOCALAPPDATA%\\SkyrimDownloaded\\skyrimdl.log (kept small: three
files of 1 MB). "Copy debug info" in the window puts the useful bits on the
clipboard to send along with a problem report. The API key is never logged.
"""

from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
from pathlib import Path

from . import __version__
from .nexuscache import cache_dir

log = logging.getLogger("skyrimdl")
_handler: logging.Handler | None = None


def log_path() -> Path:
    return cache_dir() / "skyrimdl.log"


def setup() -> Path:
    """Start writing the log file (once)."""
    global _handler
    path = log_path()
    if _handler is None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2,
                                                            encoding="utf-8")
        except OSError:
            _handler = logging.NullHandler()
        _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
        log.addHandler(_handler)
        log.setLevel(logging.INFO)
        log.info("SkyrimDownloaded %s starting (Python %s, %s)", __version__,
                 platform.python_version(), platform.platform())
    return path


def debug_info(extra: dict[str, str] | None = None, lines: int = 150) -> str:
    """Version, system and the end of the log, ready to paste into a problem report."""
    out = [f"SkyrimDownloaded {__version__}",
           f"Python {platform.python_version()} ({'exe' if getattr(sys, 'frozen', False) else 'source'})",
           f"System: {platform.platform()}"]
    try:
        import tkinter
        out.append(f"Tk {tkinter.TkVersion}")
    except Exception:
        pass
    for k, v in (extra or {}).items():
        out.append(f"{k}: {v}")
    out.append("")
    out.append(f"--- last {lines} lines of {log_path()} ---")
    try:
        text = log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        out += text
    except OSError:
        out.append("(no log yet)")
    return "\n".join(out)
