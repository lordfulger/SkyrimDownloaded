"""Sort the load order with LOOT.

* **Mod Organizer 2:** LOOT has to run *through* MO2, or it can't see the mods
  (they live in MO2's virtual folder, not the game's Data folder). So this asks
  MO2 to run it: ``ModOrganizer.exe run -e "LOOT"`` when LOOT is one of the
  instance's executables, otherwise ``ModOrganizer.exe run "<path to LOOT.exe>"``.
* **Vortex** sorts plugins itself (Plugins tab, "Sort now"), so LOOT isn't
  needed; it can still be opened on its own because Vortex deploys mods into
  the game's Data folder.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .managers.base import ManagerError
from .managers.mo2 import read_instance_ini

LOOT_GAME_NAMES = {"skyrimspecialedition": "Skyrim Special Edition", "skyrim": "Skyrim",
                   "skyrimvr": "Skyrim VR", "enderalspecialedition": "Enderal Special Edition"}


def mo2_executables(instance_dir: str | Path | None) -> list[tuple[str, str]]:
    """(title, binary) of the executables set up in an MO2 instance."""
    if not instance_dir:
        return []
    ini = Path(instance_dir) / "ModOrganizer.ini"
    if not ini.is_file():
        return []
    try:
        settings = read_instance_ini(ini)
    except ManagerError:
        return []
    rows: dict[str, dict[str, str]] = {}
    for key, value in settings.items():
        section, _, rest = key.partition("/")
        if section != "customExecutables":
            continue
        num, sep, field = rest.partition("\\")
        if not sep:
            num, sep, field = rest.partition("/")
        if num.isdigit() and field:
            rows.setdefault(num, {})[field] = value
    return [(r.get("title", ""), r.get("binary", "")) for _, r in sorted(rows.items(), key=lambda x: int(x[0]))]


def loot_in_mo2(instance_dir) -> tuple[str, str] | None:
    for title, binary in mo2_executables(instance_dir):
        if "loot" in title.lower() or Path(binary).name.lower() == "loot.exe":
            return title, binary
    return None


def find_loot(instance_dir=None) -> Path | None:
    """LOOT.exe: from the MO2 instance's executables, the registry, or the usual places."""
    found = loot_in_mo2(instance_dir)
    if found and Path(found[1]).is_file():
        return Path(found[1])
    candidates: list[Path] = []
    if sys.platform == "win32":
        import winreg
        uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (0, winreg.KEY_WOW64_32KEY):
                try:
                    key = winreg.OpenKey(root, uninstall, 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with key:
                    i = 0
                    while True:
                        try:
                            name = winreg.EnumKey(key, i)
                        except OSError:
                            break
                        i += 1
                        try:
                            with winreg.OpenKey(key, name) as app:
                                if str(winreg.QueryValueEx(app, "DisplayName")[0]).strip().lower().startswith("loot"):
                                    loc = str(winreg.QueryValueEx(app, "InstallLocation")[0])
                                    candidates.append(Path(loc) / "LOOT.exe")
                        except OSError:
                            continue
    for var, parts in (("ProgramFiles", ("LOOT", "LOOT.exe")), ("ProgramW6432", ("LOOT", "LOOT.exe")),
                       ("ProgramFiles(x86)", ("LOOT", "LOOT.exe")),
                       ("LOCALAPPDATA", ("Programs", "LOOT", "LOOT.exe"))):
        base = os.environ.get(var)
        if base:
            candidates.append(Path(base, *parts))
    if instance_dir:  # Wabbajack lists often ship LOOT in a tools folder
        for sub in ("tools/LOOT/LOOT.exe", "Tools/LOOT/LOOT.exe", "LOOT/LOOT.exe"):
            candidates.append(Path(instance_dir) / sub)
    return next((c for c in candidates if c.is_file()), None)


def command(manager: str, game: str, *, mo2_exe: Path | None = None, instance_dir=None,
            instance_name: str | None = None, portable: bool = True) -> list[str]:
    """The command that opens LOOT for this setup. Raises ManagerError with advice."""
    if manager == "mo2":
        if not mo2_exe:
            raise ManagerError("Point the tool at ModOrganizer.exe first (step 2), so LOOT can run through MO2.")
        args = [str(mo2_exe)]
        if instance_name and not portable:
            args += ["-i", instance_name]
        configured = loot_in_mo2(instance_dir)
        if configured and configured[0]:
            return args + ["run", "-e", configured[0]]
        loot = find_loot(instance_dir)
        if loot:
            return args + ["run", str(loot)]
        raise ManagerError("Couldn't find LOOT. Install it from https://loot.github.io (MO2 usually adds it "
                           "to its executables by itself), or add it in MO2's executables list.")
    loot = find_loot()
    if not loot:
        raise ManagerError("Couldn't find LOOT. Vortex sorts plugins itself (Plugins tab, \"Sort now\"); "
                           "install LOOT from https://loot.github.io if you'd like it as well.")
    return [str(loot), f"--game={LOOT_GAME_NAMES.get(game, 'Skyrim Special Edition')}"]
