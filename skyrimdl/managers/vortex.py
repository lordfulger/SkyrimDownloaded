"""Vortex.

* **handoff** - run ``Vortex.exe -i nxm://...`` (or ``-d`` to only download).
  Vortex downloads the file with your Nexus login and, with ``-i``, installs
  it, showing the mod's installer options (FOMOD) when it has them.
* **direct** - this tool downloads the archive into Vortex's downloads folder
  for the game, then (if "install" is on) runs ``Vortex.exe --install-archive``
  on it.
"""

from __future__ import annotations

from pathlib import Path

from ..nexus import ModInfo
from ..selection import FileOption
from .base import ManagerError, Target, env_path

# Nexus game domain -> Vortex's game id (also its downloads sub-folder).
VORTEX_GAME_IDS = {
    "skyrimspecialedition": "skyrimse",
    "skyrim": "skyrim",
    "skyrimvr": "skyrimvr",
    "enderal": "enderal",
    "enderalspecialedition": "enderalspecialedition",
    "fallout4": "fallout4",
    "falloutnv": "falloutnv",
    "newvegas": "falloutnv",
    "fallout3": "fallout3",
    "oblivion": "oblivion",
    "morrowind": "morrowind",
    "starfield": "starfield",
}


def default_downloads(game: str) -> Path | None:
    base = env_path("APPDATA", "Vortex", "downloads")
    return base / VORTEX_GAME_IDS.get(game, game) if base else None


def default_exe_candidates() -> list[Path]:
    out = []
    for var, parts in (
        ("ProgramFiles", ("Black Tree Gaming Ltd", "Vortex", "Vortex.exe")),
        ("ProgramW6432", ("Black Tree Gaming Ltd", "Vortex", "Vortex.exe")),
        ("LOCALAPPDATA", ("Programs", "vortex", "Vortex.exe")),
    ):
        p = env_path(var, *parts)
        if p:
            out.append(p)
    return out


class VortexTarget(Target):
    name = "Vortex"

    def __init__(self, game: str, *, downloads: str | Path | None = None,
                 exe: str | Path | None = None):
        super().__init__(game)
        self._downloads = Path(downloads) if downloads else None
        self._exe = Path(exe) if exe else None

    @property
    def game_id(self) -> str:
        return VORTEX_GAME_IDS.get(self.game, self.game)

    def downloads_dir(self) -> Path:
        if self._downloads:
            # Accept either the shared downloads folder or the game's own folder.
            if self._downloads.name.lower() != self.game_id and (self._downloads / self.game_id).is_dir():
                return self._downloads / self.game_id
            return self._downloads
        default = default_downloads(self.game)
        if default is None:
            raise ManagerError(
                "Pick Vortex's downloads folder for Skyrim SE (Vortex: Settings > Downloads; "
                "the game's folder is the 'skyrimse' folder inside it).")
        return default

    def exe(self) -> Path:
        candidates = []
        if self._exe:
            candidates.append(self._exe if self._exe.suffix.lower() == ".exe"
                              else self._exe / "Vortex.exe")
        candidates += default_exe_candidates()
        for c in candidates:
            if c.is_file():
                return c
        raise ManagerError("Point the tool at Vortex.exe so it can send links to Vortex.")

    def handoff_args(self, url: str, install: bool) -> list[str]:
        # A second Vortex.exe hands the link to the Vortex that's already open.
        return [str(self.exe()), "--install" if install else "--download", url]

    def after_download(self, path: Path, mod: ModInfo, option: FileOption, install: bool) -> str:
        if install:
            try:
                self._launch([str(self.exe()), "--install-archive", str(path)])
                return "sent to Vortex to install"
            except ManagerError as err:
                return f"downloaded, but couldn't ask Vortex to install it: {err}"
        return "in Vortex's downloads folder (Vortex lists it on its Downloads tab)"
