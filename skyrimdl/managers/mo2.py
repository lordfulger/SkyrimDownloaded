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
        if self._exe:  # a portable MO2 keeps its instance next to the exe: that's the one in use
            folder = self._exe if self._exe.is_dir() else self._exe.parent
            if (folder / "ModOrganizer.ini").is_file():
                return folder
        found = find_instances()
        if len(found) == 1:
            return found[0]
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

    def mods_dir(self) -> Path | None:
        """MO2's mods folder (where installed mods live)."""
        inst = self.instance_dir
        if not inst:
            return None
        settings = self.settings()
        base = (settings.get("Settings/base_directory") or str(inst)).replace("%BASE_DIR%", str(inst))
        mods = (settings.get("Settings/mod_directory") or "%BASE_DIR%/mods").replace("%BASE_DIR%", base)
        return Path(os.path.expandvars(mods))

    def installed(self) -> dict:
        """What's installed in MO2: {(mod id, file id): version} and {mod id: version}."""
        folder = self.mods_dir()
        return read_installed(folder) if folder else {}

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

    def prepare(self, jobs, install: bool = False) -> None:
        """Leave an install plan for the SkyrimDownloaded add-on in MO2 (list order).
        With ``install`` the add-on installs everything by itself once it has downloaded."""
        from ..mo2addon import write_plan
        try:
            write_plan(self.downloads_dir(), [j for j in jobs], auto_install=install)
        except (OSError, ManagerError):
            pass

    def after_download(self, path: Path, mod: ModInfo, option: FileOption, install: bool) -> str:
        write_meta(path, mod, option, self.game)
        return "in MO2's Downloads tab"


NEXUS_DOMAINS = {v.lower(): k for k, v in MO2_GAME_NAMES.items()}


def nexus_domain(game_name: str, default: str) -> str:
    """The Nexus site a mod came from, from MO2's gameName= (\"SkyrimSE\" -> skyrimspecialedition)."""
    return NEXUS_DOMAINS.get((game_name or "").strip().strip('"').lower(), default)


def read_installed(mods_dir: Path) -> dict:
    """Read each installed mod's meta.ini. Returns {"files": {(mod id, file id): version},
    "mods": {mod id: version}, "names": {mod id: folder name}}."""
    files: dict = {}
    mods: dict = {}
    names: dict = {}
    try:
        folders = [d for d in Path(mods_dir).iterdir() if d.is_dir()]
    except OSError:
        return {"files": files, "mods": mods, "names": names}
    for d in folders:
        try:
            text = (d / "meta.ini").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        general = _section(text, "General")
        try:
            mod_id = int(general.get("modid", "0").strip('"') or 0)
        except ValueError:
            mod_id = 0
        version = general.get("version", "").strip('"')
        if mod_id > 0:
            mods[mod_id] = version
            names[mod_id] = d.name
        for key, value in _section(text, "installedFiles").items():
            if key.endswith("\\fileid") or key.endswith("/fileid"):
                prefix = key[: -len("fileid")]
                try:
                    fid = int(value)
                    mid = int(_section(text, "installedFiles").get(prefix + "modid", mod_id) or mod_id)
                except ValueError:
                    continue
                if mid > 0 and fid > 0:
                    files[(mid, fid)] = version
    return {"files": files, "mods": mods, "names": names}


def _section(text: str, name: str) -> dict:
    out, inside = {}, False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            inside = line[1:-1].lower() == name.lower()
            continue
        if inside and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().lower()] = v.strip()
    return out


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
