"""What every mod manager target can do."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from ..nexus import ModInfo
from ..selection import FileOption

PARTIAL_DIR_NAME = ".skyrimdl-partial"
IS_WINDOWS = sys.platform == "win32"


class ManagerError(RuntimeError):
    pass


def nxm_url(game: str, mod_id: int, file_id: int, *, key: str | None = None,
            expires: int | None = None, user_id: int | None = None) -> str:
    url = f"nxm://{game}/mods/{int(mod_id)}/files/{int(file_id)}"
    if key and expires:
        params = {"key": key, "expires": int(expires)}
        if user_id:
            params["user_id"] = int(user_id)
        url += "?" + urlencode(params)
    return url


def env_path(var: str, *parts: str) -> Path | None:
    base = os.environ.get(var)
    return Path(base, *parts) if base else None


class Target:
    """A place downloads go, and a mod manager that can take them."""

    name = "mod manager"
    #: How long to wait between links sent to the manager, so it isn't flooded.
    handoff_gap = 1.5

    def __init__(self, game: str):
        self.game = game
        self._last_handoff = 0.0

    # -- where files go ---------------------------------------------------

    def downloads_dir(self) -> Path:
        raise NotImplementedError

    def partial_dir(self) -> Path:
        return self.downloads_dir() / PARTIAL_DIR_NAME

    def existing(self, option: FileOption) -> Path | None:
        """The archive if it's already in the downloads folder (same size)."""
        try:
            folder = self.downloads_dir()
        except ManagerError:
            return None
        from ..downloader import safe_file_name
        path = folder / safe_file_name(option.file_name)
        if path.is_file() and option.size_matches(path.stat().st_size):
            return path
        return None

    def problems(self, mode: str) -> list[str]:
        """Things to fix before starting (missing folders, missing exe...)."""
        issues = []
        try:
            folder = self.downloads_dir()
            if mode == "direct" and not folder.exists():
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError as err:
                    issues.append(f"Can't create the downloads folder {folder}: {err}")
        except ManagerError as err:
            issues.append(str(err))
        if mode == "handoff":
            try:
                self.exe()
            except ManagerError as err:
                issues.append(str(err))
        return issues

    # -- talking to the manager ------------------------------------------

    def exe(self) -> Path:
        raise NotImplementedError

    def handoff_args(self, url: str, install: bool) -> list[str]:
        raise NotImplementedError

    def handoff(self, url: str, install: bool = True) -> None:
        """Ask the mod manager to download (and maybe install) an nxm:// link itself."""
        self._launch(self.handoff_args(url, install))

    def prepare(self, jobs, install: bool = False) -> None:
        """Called before downloads start (MO2 writes its install plan here)."""

    def after_download(self, path: Path, mod: ModInfo, option: FileOption,
                       install: bool) -> str:
        """Called when this tool finished downloading a file. Returns a status note."""
        return "in the downloads folder"

    def _launch(self, args: list[str]) -> None:
        wait = self.handoff_gap - (time.monotonic() - self._last_handoff)
        if wait > 0:
            time.sleep(wait)
        try:
            from ..appupdate import clean_env
            kwargs = {"close_fds": True, "env": clean_env(), "stdin": subprocess.DEVNULL,
                      "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if IS_WINDOWS:
                kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS
            subprocess.Popen(args, **kwargs)
        except OSError as err:
            raise ManagerError(f"Couldn't start {args[0]}: {err}") from None
        finally:
            self._last_handoff = time.monotonic()
