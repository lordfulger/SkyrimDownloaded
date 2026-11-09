"""Build a mod list from an MO2 setup: the profile's mods in left-pane order, under their
separators, with the exact files that are installed."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .managers.mo2 import _section, read_instance_ini

SEPARATOR = "_separator"


def profiles_dir(instance: Path) -> Path:
    settings = read_instance_ini(instance / "ModOrganizer.ini") if (instance / "ModOrganizer.ini").is_file() else {}
    base = (settings.get("Settings/base_directory") or str(instance)).replace("%BASE_DIR%", str(instance))
    folder = (settings.get("Settings/profiles_directory") or "%BASE_DIR%/profiles").replace("%BASE_DIR%", base)
    return Path(os.path.expandvars(folder))


def current_profile(instance: Path) -> str:
    settings = read_instance_ini(instance / "ModOrganizer.ini") if (instance / "ModOrganizer.ini").is_file() else {}
    return settings.get("General/selected_profile") or "Default"


def profile_names(instance: Path) -> list[str]:
    try:
        return sorted(d.name for d in profiles_dir(instance).iterdir() if (d / "modlist.txt").is_file())
    except OSError:
        return []


def read_modlist(profile: Path) -> list[tuple[str, bool]]:
    """(mod name, switched on) from top to bottom of MO2's left pane. modlist.txt is stored
    the other way round (highest priority first); game/DLC entries (*) are left out."""
    try:
        lines = (profile / "modlist.txt").read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or line[0] not in "+-":
            continue
        out.append((line[1:], line[0] == "+"))
    out.reverse()
    return out


@dataclass
class Built:
    text: str
    mods: int = 0
    off: int = 0
    not_nexus: int = 0
    separators: int = 0


def build_list(instance: Path, mods_dir: Path, game: str, profile: str | None = None,
               include_off: bool = False) -> Built:
    """The list text for an MO2 profile."""
    profile = profile or current_profile(instance)
    entries = read_modlist(profiles_dir(instance) / profile)
    built = Built("")
    lines = [f"# Built from MO2 profile \"{profile}\" on {time.strftime('%Y-%m-%d')}", ""]
    for name, on in entries:
        if name.endswith(SEPARATOR):
            title = name[: -len(SEPARATOR)].strip()
            lines += ["", f"## {title}"]
            built.separators += 1
            continue
        try:
            text = (Path(mods_dir) / name / "meta.ini").read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        general = _section(text, "General")
        try:
            mod_id = int(general.get("modid", "0").strip('"') or 0)
        except ValueError:
            mod_id = 0
        files = []
        for key, value in _section(text, "installedFiles").items():
            if key.endswith("fileid"):
                try:
                    if int(value) > 0:
                        files.append(int(value))
                except ValueError:
                    pass
        comment = f"    # {name}"
        if mod_id <= 0:
            lines.append(f"# not from Nexus: {name}")
            built.not_nexus += 1
            continue
        from .managers.mo2 import nexus_domain
        domain = nexus_domain(general.get("gamename", ""), game)  # e.g. an LE mod in an SE setup
        line = f"https://www.nexusmods.com/{domain}/mods/{mod_id}"
        if files:
            line += " | file=" + ",".join(str(f) for f in dict.fromkeys(files))
        if not on:
            built.off += 1
            if not include_off:
                lines.append(f"# (off in MO2) {line}{comment}")
                continue
        lines.append(line + comment)
        built.mods += 1
    built.text = "\n".join(lines).strip() + "\n"
    return built
