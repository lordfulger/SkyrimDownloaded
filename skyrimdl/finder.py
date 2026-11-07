"""Find Mod Organizer 2 and Vortex on this PC, so nobody has to browse for folders.

Two levels:

* ``quick`` (instant): the Windows registry (who handles ``nxm://`` links,
  installed programs), MO2's global instances in %LOCALAPPDATA%, Vortex's own
  settings and its default folders.
* ``deep`` (a few seconds to a minute): also walks your drives, a few folders
  deep, looking for ``ModOrganizer.exe`` (portable and Wabbajack installs),
  ``Vortex.exe`` and the ``__vortex_downloads_folder`` marker Vortex writes
  into its downloads folder.
"""

from __future__ import annotations

import json
import os
import re
import string
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .managers.mo2 import global_instances_dir, read_instance_ini
from .managers.vortex import VORTEX_GAME_IDS, default_exe_candidates

VORTEX_DOWNLOADS_TAG = "__vortex_downloads_folder"
MO2_EXE = "modorganizer.exe"
VORTEX_EXE = "vortex.exe"

# MO2 [General] gameName values that mean Skyrim Special / Anniversary Edition.
SKYRIM_SE_NAMES = {"skyrim special edition", "skyrimse", "skyrim se", "skyrim anniversary edition"}

# Folders never worth walking into.
_SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "recovery", "perflogs",
    "programdata", "msocache", "$windows.~bt", "$windows.~ws", "windows.old",
    "winsxs", "windowsapps", "node_modules", ".git", "__pycache__", "appdata",
    "config.msi", "intel", "amd", "nvidia", "drivers", "temp", "tmp",
    # inside a mod setup: huge and never holds what we look for
    "mods", "overwrite", "profiles", "webcache", "crashdumps", "logs", "data",
    "textures", "meshes", "shadercache", "workshop", "compatdata", "downloading",
}


@dataclass
class MO2Install:
    instance_dir: Path
    exe: Path | None
    name: str
    game: str = ""            # as MO2 writes it, e.g. "Skyrim Special Edition"
    portable: bool = False
    downloads: Path | None = None
    found_by: str = ""

    @property
    def is_skyrim_se(self) -> bool:
        return self.game.strip().lower() in SKYRIM_SE_NAMES

    def describe(self) -> str:
        kind = "portable" if self.portable else "instance"
        game = self.game or "unknown game"
        return f"{self.name} ({kind}, {game}) - {self.instance_dir}"


@dataclass
class VortexInstall:
    exe: Path | None = None
    downloads_root: Path | None = None      # the folder that holds one folder per game
    found_by: list[str] = field(default_factory=list)

    def game_downloads(self, game: str) -> Path | None:
        if not self.downloads_root:
            return None
        return self.downloads_root / VORTEX_GAME_IDS.get(game, game)


@dataclass
class Findings:
    mo2: list[MO2Install] = field(default_factory=list)
    mo2_exes: list[Path] = field(default_factory=list)
    vortex: VortexInstall = field(default_factory=VortexInstall)
    vortex_exes: list[Path] = field(default_factory=list)
    vortex_download_roots: list[Path] = field(default_factory=list)
    searched_drives: list[str] = field(default_factory=list)
    timed_out: bool = False

    def best_mo2(self) -> MO2Install | None:
        """The obvious pick, or None if the user should choose."""
        skyrim = [m for m in self.mo2 if m.is_skyrim_se]
        if len(skyrim) == 1:
            return skyrim[0]
        if not skyrim and len(self.mo2) == 1:
            return self.mo2[0]
        return None

    def sorted_mo2(self) -> list[MO2Install]:
        return sorted(self.mo2, key=lambda m: (not m.is_skyrim_se, m.name.lower()))


ProgressFn = Callable[[str], None]


# -- helpers ---------------------------------------------------------------

def _norm(p: Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def _add_path(paths: list[Path], p: Path | None) -> None:
    if p and p.exists() and _norm(p) not in {_norm(x) for x in paths}:
        paths.append(p)


def _exe_from_command(command: str) -> Path | None:
    """'"C:\\MO2\\nxmhandler.exe" "%1"' -> C:\\MO2\\nxmhandler.exe"""
    command = os.path.expandvars(command.strip())
    m = re.match(r'"([^"]+)"', command) or re.match(r"(.+?\.exe)", command, re.I)
    return Path(m.group(1)) if m else None


def _registry_values() -> list[tuple[str, str]]:
    """(where, value) pairs from the registry that may point at MO2 or Vortex."""
    if sys.platform != "win32":
        return []
    import winreg

    out: list[tuple[str, str]] = []

    def read(root, sub, name=""):
        try:
            with winreg.OpenKey(root, sub) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except OSError:
            return None

    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT, winreg.HKEY_LOCAL_MACHINE):
        for sub in (r"Software\Classes\nxm\shell\open\command", r"nxm\shell\open\command"):
            value = read(root, sub)
            if value:
                out.append(("nxm link handler", value))

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
                            display = str(winreg.QueryValueEx(app, "DisplayName")[0])
                            if not re.search(r"vortex|mod organizer", display, re.I):
                                continue
                            for field_name in ("InstallLocation", "DisplayIcon"):
                                try:
                                    out.append((f"installed programs ({display})",
                                                str(winreg.QueryValueEx(app, field_name)[0])))
                                except OSError:
                                    pass
                    except OSError:
                        continue
    return out


def _classify_exe(path: Path, findings: Findings) -> None:
    """Add a ModOrganizer.exe / Vortex.exe (or a folder holding one) we were pointed at."""
    candidates = [path] if path.suffix.lower() == ".exe" else []
    folder = path.parent if path.suffix.lower() == ".exe" else path
    candidates += [folder / "ModOrganizer.exe", folder / "Vortex.exe"]
    for c in candidates:
        if not c.is_file():
            continue
        if c.name.lower() == MO2_EXE:
            _add_path(findings.mo2_exes, c)
        elif c.name.lower() == VORTEX_EXE:
            _add_path(findings.vortex_exes, c)
    # nxmhandler.exe lives next to ModOrganizer.exe
    if path.name.lower() == "nxmhandler.exe":
        _add_path(findings.mo2_exes, path.parent / "ModOrganizer.exe")


def _mo2_instance(folder: Path, exe: Path | None, portable: bool, found_by: str) -> MO2Install | None:
    ini = folder / "ModOrganizer.ini"
    if not ini.is_file():
        return None
    try:
        settings = read_instance_ini(ini)
    except Exception:
        settings = {}
    from .managers.mo2 import MO2Target
    try:
        downloads = MO2Target("skyrimspecialedition", instance=folder).downloads_dir()
    except Exception:
        downloads = None
    return MO2Install(
        instance_dir=folder, exe=exe, portable=portable, downloads=downloads,
        name=folder.name, game=settings.get("General/gameName", ""), found_by=found_by,
    )


def vortex_saved_downloads_root() -> Path | None:
    """The downloads folder set in Vortex's settings, read from its state database.

    Vortex keeps settings in a LevelDB folder (%APPDATA%\\Vortex\\state.v2); the
    newest copy of the ``settings###downloads###path`` entry is the current one.
    Best effort: returns None if it can't be read.
    """
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    vortex_home = Path(appdata) / "Vortex"
    db = vortex_home / "state.v2"
    if not db.is_dir():
        return None
    key = b"settings###downloads###path"
    best: tuple[float, int, str] | None = None
    try:
        files = [p for p in db.iterdir() if p.suffix.lower() in (".log", ".ldb")]
    except OSError:
        return None
    for f in files:
        try:
            data = f.read_bytes()
            mtime = f.stat().st_mtime
        except OSError:
            continue
        for m in re.finditer(re.escape(key), data):
            tail = data[m.end(): m.end() + 1024]
            s = re.search(rb'"((?:[^"\\]|\\.){1,500})"', tail)
            if not s:
                continue
            try:
                value = json.loads(b'"' + s.group(1) + b'"')
            except ValueError:
                continue
            rank = (mtime, m.start(), value)
            if best is None or rank[:2] > best[:2]:
                best = rank
    if not best:
        return None
    value = best[2].replace("{USERDATA}", str(vortex_home)).replace("{userdata}", str(vortex_home))
    path = Path(os.path.expandvars(value))
    return path if path.is_dir() else None


def fixed_drives() -> list[str]:
    if sys.platform != "win32":
        return []
    import ctypes
    drives = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            root = f"{letter}:\\"
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                drives.append(root)
    return drives


def walk_for_targets(roots: list[Path], *, max_depth: int = 5, budget: float = 60.0,
                     progress: ProgressFn | None = None) -> tuple[list[Path], bool]:
    """Breadth-first walk; returns paths of ModOrganizer.exe, Vortex.exe and Vortex
    download markers found, and whether it ran out of time."""
    wanted = {MO2_EXE, VORTEX_EXE, VORTEX_DOWNLOADS_TAG}
    hits: list[Path] = []
    deadline = time.monotonic() + budget
    queue: deque[tuple[Path, int]] = deque((r, 0) for r in roots)
    seen: set[str] = set()
    last_report = 0.0
    while queue:
        if time.monotonic() > deadline:
            return hits, True
        folder, depth = queue.popleft()
        key = _norm(folder)
        if key in seen:
            continue
        seen.add(key)
        if progress and time.monotonic() - last_report > 0.3:
            progress(f"Searching {folder}")
            last_report = time.monotonic()
        try:
            with os.scandir(folder) as it:
                entries = list(it)
        except OSError:
            continue
        for entry in entries:
            name = entry.name.lower()
            try:
                if entry.is_file(follow_symlinks=False):
                    if name in wanted:
                        hits.append(Path(entry.path))
                elif (entry.is_dir(follow_symlinks=False) and depth < max_depth
                      and name not in _SKIP_DIRS and not name.startswith((".", "$"))):
                    queue.append((Path(entry.path), depth + 1))
            except OSError:
                continue
    return hits, False


# -- the search ------------------------------------------------------------

def find(deep: bool = False, *, budget: float = 60.0, progress: ProgressFn | None = None,
         extra_roots: list[Path] | None = None) -> Findings:
    findings = Findings()
    say = progress or (lambda msg: None)

    # 1. Registry: whoever handles nxm:// links, and installed programs.
    say("Checking the Windows registry")
    for where, value in _registry_values():
        exe = _exe_from_command(value) if (".exe" in value.lower() or '"' in value) else None
        target = exe or Path(os.path.expandvars(value.strip().strip('"')))
        _classify_exe(target, findings)

    # 2. Usual install places.
    for p in default_exe_candidates():
        _classify_exe(p, findings)
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            for sub in ("Mod Organizer 2", "ModOrganizer2", "ModOrganizer", r"Programs\Mod Organizer 2"):
                _classify_exe(Path(base, sub), findings)

    # 3. MO2 global instances.
    say("Looking at MO2 instances")
    root = global_instances_dir()
    if root and root.is_dir():
        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            inst = _mo2_instance(folder, None, False, "MO2 global instances")
            if inst:
                findings.mo2.append(inst)

    # 4. Vortex downloads folder: its settings first, then the default place.
    say("Looking at Vortex's settings")
    saved = vortex_saved_downloads_root()
    if saved:
        findings.vortex.downloads_root = saved
        findings.vortex.found_by.append("Vortex settings")
        _add_path(findings.vortex_download_roots, saved)
    appdata = os.environ.get("APPDATA")
    if appdata:
        _add_path(findings.vortex_download_roots, Path(appdata, "Vortex", "downloads"))

    # 5. Deep search of the drives.
    if deep:
        roots = [Path(d) for d in fixed_drives()] + list(extra_roots or [])
        home = Path.home()
        for sub in ("Desktop", "Documents", "Downloads", "Games"):
            roots.append(home / sub)
        findings.searched_drives = [str(r) for r in roots]
        hits, findings.timed_out = walk_for_targets(roots, budget=budget, progress=say)
        for hit in hits:
            if hit.name.lower() == VORTEX_DOWNLOADS_TAG:
                _add_path(findings.vortex_download_roots, hit.parent)
            else:
                _classify_exe(hit, findings)

    # Portable MO2 installs: an exe with a ModOrganizer.ini beside it.
    known = {_norm(m.instance_dir) for m in findings.mo2}
    for exe in findings.mo2_exes:
        if _norm(exe.parent) not in known:
            inst = _mo2_instance(exe.parent, exe, True, "next to ModOrganizer.exe")
            if inst:
                findings.mo2.append(inst)
                known.add(_norm(exe.parent))
    # Give global instances an exe to send links through.
    shared_exe = next((e for e in findings.mo2_exes
                       if not (e.parent / "ModOrganizer.ini").is_file()), None)
    shared_exe = shared_exe or (findings.mo2_exes[0] if findings.mo2_exes else None)
    for inst in findings.mo2:
        if inst.exe is None:
            inst.exe = shared_exe

    if findings.vortex_exes:
        findings.vortex.exe = findings.vortex_exes[0]
        findings.vortex.found_by.append("Vortex.exe")
    if not findings.vortex.downloads_root:
        # Prefer a folder Vortex has tagged as its own, then the default.
        tagged = [p for p in findings.vortex_download_roots if (p / VORTEX_DOWNLOADS_TAG).exists()]
        pick = (tagged or findings.vortex_download_roots or [None])[0]
        if pick:
            findings.vortex.downloads_root = pick
            findings.vortex.found_by.append("downloads folder")
    say("Done")
    return findings
