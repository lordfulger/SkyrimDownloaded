"""Is there a newer SkyrimDownloaded? Asks GitHub for the latest release."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from dataclasses import dataclass

from . import __version__

LATEST_URL = "https://api.github.com/repos/lordfulger/SkyrimDownloaded/releases/latest"
RELEASES_PAGE = "https://github.com/lordfulger/SkyrimDownloaded/releases/latest"


@dataclass
class NewVersion:
    version: str
    page: str
    exe_url: str = ""
    sha256: str = ""         # GitHub publishes each release file's checksum
    size: int | None = None


def parse(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or "")[:3]) or (0,)


class CheckFailed(RuntimeError):
    """GitHub couldn't be asked (offline, blocked, rate-limited...)."""


def _from_releases_page(current: str, timeout: float) -> NewVersion | None:
    """Fallback without GitHub's API (which allows 60 checks an hour per connection):
    github.com/<repo>/releases/latest redirects to the newest release's page."""
    req = urllib.request.Request(RELEASES_PAGE, method="HEAD",
                                 headers={"User-Agent": f"SkyrimDownloaded/{current}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final = resp.geturl()
    m = re.search(r"/releases/tag/(v?[\d.]+)", final)
    if not m:
        raise CheckFailed(f"unexpected releases page {final}")
    tag = m.group(1)
    if parse(tag) <= parse(current):
        return None
    base = RELEASES_PAGE.rsplit("/latest", 1)[0]
    return NewVersion(tag.lstrip("v"), f"{base}/tag/{tag}", f"{base}/download/{tag}/SkyrimDownloaded.exe")


def check(url: str = LATEST_URL, current: str = __version__, timeout: float = 10.0,
          fallback: bool = True) -> NewVersion | None:
    """The newer release, or None if this is the latest. Raises CheckFailed (with the
    reason) if GitHub couldn't be asked at all."""
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": f"SkyrimDownloaded/{current}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        if getattr(err, "code", None) == 404:
            raise CheckFailed("GitHub says the SkyrimDownloaded project isn't there - it's probably "
                              "set to private, so the app can't see its releases") from None
        api_error = getattr(err, "reason", None) or err
        if not fallback:
            raise CheckFailed(f"GitHub didn't answer: {api_error}") from None
        try:
            return _from_releases_page(current, timeout)
        except Exception as err2:
            raise CheckFailed(f"GitHub didn't answer ({api_error}; {getattr(err2, 'reason', None) or err2})") from None
    tag = str(data.get("tag_name") or "")
    if not tag or data.get("draft") or data.get("prerelease") or parse(tag) <= parse(current):
        return None
    asset = next((a for a in data.get("assets") or []
                  if str(a.get("name", "")).lower().endswith(".exe")), {}) or {}
    digest = str(asset.get("digest") or "")
    return NewVersion(tag.lstrip("v"), data.get("html_url") or RELEASES_PAGE,
                      asset.get("browser_download_url") or "",
                      digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
                      asset.get("size"))


# -- updating the .exe in place ------------------------------------------------------

def clean_env() -> dict:
    """Environment for programs this app starts, without the packed .exe's own settings.

    The .exe unpacks itself to a temporary folder and notes it in environment variables;
    a program started with those - above all a new SkyrimDownloaded.exe after an update -
    would look for its files in that folder, which is gone once this app closes
    ("Failed to load Python DLL ... python312.dll").
    """
    import os
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_PYI_", "_MEIPASS")) and k not in ("TCL_LIBRARY", "TK_LIBRARY")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # tells a PyInstaller program it's started fresh
    return env


def running_exe() -> Path | None:
    """The .exe this is running from (None when running from source)."""
    return Path(sys.executable) if getattr(sys, "frozen", False) else None


def can_write(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".skyrimdl-write-test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def update_target(current: Path) -> Path:
    """Where the new version goes: over the current .exe if its folder can be written to,
    otherwise %LOCALAPPDATA%\\SkyrimDownloaded\\app."""
    if can_write(current.parent):
        return current
    from .nexuscache import cache_dir
    return cache_dir() / "app" / "SkyrimDownloaded.exe"


def download_update(found: NewVersion, folder: Path, progress=None, cancel=None) -> Path:
    """Download the new .exe next to where it will go, and check its checksum."""
    from .downloader import download
    safe = "".join(c for c in str(found.version) if c.isalnum() or c in ".-") or "new"
    dest = folder / f"SkyrimDownloaded.update-{safe}.exe"  # per version: never resume another one's part
    partial = folder / ".skyrimdl-partial"
    try:
        path = download([found.exe_url], dest, partial_dir=partial,
                        expected_size=found.size, progress=progress, cancel=cancel)
    finally:
        try:
            partial.rmdir()  # only if empty
        except OSError:
            pass
    data = path.read_bytes()
    if found.sha256:
        if hashlib.sha256(data).hexdigest().lower() != found.sha256.lower():
            path.unlink()
            raise ValueError("The downloaded update didn't match its checksum, so it wasn't used. Try again.")
    elif not data.startswith(b"MZ") or len(data) < 1_000_000:
        path.unlink()  # no checksum to go by, and it isn't a program: don't put it in place
        raise ValueError("The download wasn't a complete SkyrimDownloaded.exe, so it wasn't used.")
    return path


SWAP_SCRIPT = r"""@echo off
rem SkyrimDownloaded updater: wait for the app to close, put the new version in place, start it.
set "NEW=%~1"
set "OLD=%~2"
set "PID=%~3"
set /a TRIES=0
:wait
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if errorlevel 1 goto copy
set /a TRIES+=1
if %TRIES% GEQ 60 goto copy
ping -n 2 127.0.0.1 >nul
goto wait
:copy
set /a TRIES=0
:retry
copy /Y "%NEW%" "%OLD%" >nul 2>&1
if not errorlevel 1 goto started
set /a TRIES+=1
if %TRIES% GEQ 30 goto fail
ping -n 2 127.0.0.1 >nul
goto retry
:started
del "%NEW%" >nul 2>&1
if "%~4"=="nostart" goto end
start "" "%OLD%"
goto end
:fail
if "%~4"=="nostart" goto end
start "" "%NEW%"
:end
del "%~f0" >nul 2>&1
"""


def start_swap(new_exe: Path, target: Path, pid: int, *, start_after: bool = True):
    """Hand over to a small script that replaces the .exe once this app has closed."""
    script = Path(tempfile.gettempdir()) / f"skyrimdl-update-{pid}.cmd"
    script.write_text(SWAP_SCRIPT.replace("\n", "\r\n"), encoding="ascii")
    flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    # One command line, quoted the way cmd.exe wants: /s strips just the outer pair of quotes, so
    # paths with spaces (C:\Users\John Smith\AppData\Local\Temp) survive.
    inner = f'"{script}" "{new_exe}" "{target}" {int(pid)}' + ("" if start_after else " nostart")
    command = f'cmd.exe /d /s /c "{inner}"'
    return subprocess.Popen(command, close_fds=True, env=clean_env(),
                            creationflags=flags if sys.platform == "win32" else 0)
