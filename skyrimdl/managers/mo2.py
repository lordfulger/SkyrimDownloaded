"""Mod Organizer 2.

Two ways in:

* **handoff** - run ``ModOrganizer.exe nxm://...`` for each file. MO2 (which
  should already be open on your Skyrim instance) downloads it with your Nexus
  login, exactly as if you'd clicked "Mod manager download".
* **direct** - this tool downloads the archive into the instance's downloads
  folder and writes the ``.meta`` file MO2 keeps beside each download, so MO2
  shows it with its Nexus name, version and mod ID. Install from MO2's
  Downloads tab (installers / FOMOD options run there).
"""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

from ..nexus import ModInfo
from ..selection import FileOption
from .base import ManagerError, Target, env_path

# Nexus game domain -> the gameName MO2 writes in its .meta files.
MO2_GAME_NAMES = {
    "skyrimspecialedition": "SkyrimSE",
    "skyrim": "Skyrim",
    "skyrimvr": "SkyrimVR",
    "enderal": "Enderal",
    "enderalspecialedition": "EnderalSE",
    "fallout4": "Fallout4",
    "fallout4vr": "Fallout4VR",
    "falloutnv": "FalloutNV",
    "newvegas": "FalloutNV",
    "fallout3": "Fallout3",
    "oblivion": "Oblivion",
    "morrowind": "Morrowind",
    "starfield": "Starfield",
}


def global_instances_dir() -> Path | None:
    return env_path("LOCALAPPDATA", "ModOrganizer")


def find_instances() -> list[Path]:
    """Global MO2 instances (the ones MO2 lists in its instance manager)."""
    root = global_instances_dir()
    if not root or not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / "ModOrganizer.ini").is_file())


def _ini_value(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    m = re.fullmatch(r"@ByteArray\((.*)\)", value)
    if m:
        value = m.group(1)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    # QSettings escapes backslashes as \\ inside values.
    value = value.replace("\\\\", "\\")
    return value or None


def read_instance_ini(path: Path) -> dict[str, str]:
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str  # keep case
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            parser.read_file(fh)
    except (OSError, configparser.Error) as err:
        raise ManagerError(f"Can't read {path}: {err}") from None
    out: dict[str, str] = {}
    for section in parser.sections():
        for key, raw in parser.items(section):
            value = _ini_value(raw)
            if value is not None:
                out[f"{section}/{key}"] = value
    return out


class MO2Target(Target):
    name = "Mod Organizer 2"

    def __init__(self, game: str, *, instance: str | Path | None = None,
                 exe: str | Path | None = None, downloads: str | Path | None = None):
        """``instance`` is the instance folder (the one with ModOrganizer.ini), a
        global instance's name, or the MO2 folder for a portable install."""
        super().__init__(game)
        self._instance = Path(instance) if instance else None
        if instance and not self._instance.exists():
            root = global_instances_dir()
            if root and (root / str(instance)).is_dir():
                self._instance = root / str(instance)
        if self._instance and self._instance.is_file():
            self._instance = self._instance.parent  # pointed at ModOrganizer.ini / .exe
        self._exe = Path(exe) if exe else None
        self._downloads = Path(downloads) if downloads else None

    @property
    def instance_dir(self) -> Path | None:
        if self._instance:
            return self._instance
        found = find_instances()
        if len(found) == 1:
            return found[0]
        if self._exe and (self._exe.parent / "ModOrganizer.ini").is_file():
            return self._exe.parent  # portable
        return None

    @property
    def is_portable(self) -> bool:
        inst = self.instance_dir
        return bool(inst and (inst / "ModOrganizer.exe").is_file())

    def settings(self) -> dict[str, str]:
        inst = self.instance_dir
        if not inst:
            return {}
        ini = inst / "ModOrganizer.ini"
        return read_instance_ini(ini) if ini.is_file() else {}

    def downloads_dir(self) -> Path:
        if self._downloads:
            return self._downloads
        inst = self.instance_dir
        if not inst:
            raise ManagerError(
                "Pick your MO2 instance folder (the folder with ModOrganizer.ini). "
                "Global instances live in %LOCALAPPDATA%\\ModOrganizer\\<name>; "
                "portable ones are the folder MO2 is installed in.")
        settings = self.settings()
        base = settings.get("Settings/base_directory") or str(inst)
        base = base.replace("%BASE_DIR%", str(inst))
        downloads = settings.get("Settings/download_directory") or "%BASE_DIR%/downloads"
        downloads = downloads.replace("%BASE_DIR%", base)
        return Path(os.path.expandvars(downloads))

    def exe(self) -> Path:
        candidates = []
        if self._exe:
            candidates.append(self._exe if self._exe.suffix.lower() == ".exe"
                              else self._exe / "ModOrganizer.exe")
        inst = self.instance_dir
        if inst:
            candidates.append(inst / "ModOrganizer.exe")
        for c in candidates:
            if c.is_file():
                return c
        raise ManagerError("Point the tool at ModOrganizer.exe so it can send links to MO2.")

    def handoff_args(self, url: str, install: bool) -> list[str]:
        # MO2 passes the link to the copy that's already running.
        return [str(self.exe()), url]

    def after_download(self, path: Path, mod: ModInfo, option: FileOption, install: bool) -> str:
        write_meta(path, mod, option, self.game)
        return "in MO2's Downloads tab - install it there"


def _q(value: object) -> str:
    """A QSettings ini string. Quoted so commas aren't read as a list."""
    text = str(value)
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\r\n", "\n").replace("\n", "\\n").replace("\t", "\\t")
    return f'"{text}"'


def write_meta(archive: Path, mod: ModInfo, option: FileOption, game: str) -> Path:
    """Write ``<archive>.meta`` the way MO2 does for its own Nexus downloads."""
    lines = [
        "[General]",
        f"gameName={MO2_GAME_NAMES.get(game, game)}",
        f"modID={mod.mod_id}",
        f"fileID={option.file_id}",
        f"url={_q(f'https://www.nexusmods.com/{game}/mods/{mod.mod_id}?tab=files&file_id={option.file_id}')}",
        f"name={_q(option.name)}",
        f"description={_q(option.description)}",
        f"modName={_q(mod.name)}",
        f"version={_q(option.version or mod.version)}",
        f"newestVersion={_q(mod.version)}",
        f"fileCategory={option.category}",
        f"category={mod.category_id or 0}",
        "repository=Nexus",
        "installed=false",
        "uninstalled=false",
        "paused=false",
        "removed=false",
        "",
    ]
    meta = archive.with_name(archive.name + ".meta")
    meta.write_text("\r\n".join(lines), encoding="utf-8")
    return meta
