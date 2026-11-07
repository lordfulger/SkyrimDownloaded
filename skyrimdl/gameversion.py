"""Which Skyrim the files are for, so files for other versions can be weeded out.

Nexus doesn't record which game version a file is for, but authors say so in the
file's name (and sometimes its description): "for 1.5.97", "AE 1.6.1170",
"1.6.1130+", "pre-AE", "VR", "GOG version"... This module reads those hints and
compares them with your game.

Versions are compared by *runtime family*, because that's what decides whether
an SKSE plugin loads: a file built for 1.6.1130 works on 1.6.1170, one for
1.6.640 doesn't.

    SE        1.5.x            (Special Edition before the AE update)
    AE-early  1.6.317-1.6.353  (first AE releases)
    AE-640    1.6.629-1.6.659  (Nov 2022 - Dec 2023, incl. GOG 1.6.659)
    AE-1130   1.6.1130 and up  (Creations update and later)
    VR        1.4.x            (Skyrim VR)
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

Version = tuple[int, int, int]

PRESETS: list[tuple[str, str]] = [
    ("Any version (don't filter)", ""),
    ("1.6.1170 - Anniversary Edition, latest (Creations update and later)", "1.6.1170"),
    ("1.6.640 - Anniversary Edition, 2022-2023", "1.6.640"),
    ("1.5.97 - Special Edition, before AE", "1.5.97"),
    ("1.4.15 - Skyrim VR", "1.4.15"),
]
STORES = ("Steam", "GOG", "Game Pass")

FAMILY_LABEL = {
    "SE": "SE 1.5.97", "AE-early": "early AE (1.6.353 and before)", "AE-640": "AE 1.6.640",
    "AE-1130": "AE 1.6.1130+", "VR": "Skyrim VR",
}


def parse_version(text: str | None) -> Version | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def version_text(v: Version | None) -> str:
    return ".".join(map(str, v)) if v else ""


def family(v: Version) -> str:
    if v[:2] == (1, 4):
        return "VR"
    if v[:2] == (1, 5):
        return "SE"
    if v[:2] == (1, 6):
        if v[2] < 354:
            return "AE-early"
        if v[2] < 1130:
            return "AE-640"
        return "AE-1130"
    return f"{v[0]}.{v[1]}"


def preset_label(version: str) -> str:
    for label, value in PRESETS:
        if value == version:
            return label
    return version


@dataclass
class GameTarget:
    """Your game: its version (None = don't filter) and where it's from."""

    version: Version | None = None
    store: str = "Steam"

    @classmethod
    def from_settings(cls, version: str, store: str) -> "GameTarget":
        return cls(parse_version(version), store if store in STORES else "Steam")

    @property
    def active(self) -> bool:
        return self.version is not None

    @property
    def family(self) -> str | None:
        return family(self.version) if self.version else None

    def describe(self) -> str:
        if not self.version:
            return "any version"
        return f"{version_text(self.version)} ({FAMILY_LABEL.get(self.family, self.family)}, {self.store})"


# -- reading a file's name -------------------------------------------------

_SEP = r"[._]"
# Game builds have 2-4 digit build numbers (1.5.97, 1.6.640, 1.6.1170, VR 1.4.15),
# which keeps a mod's own "v1.6.2" from being read as a game version.
_FULL_VERSION = re.compile(
    r"(?<![\d.])1" + _SEP + r"(?:(5)" + _SEP + r"(\d{2})|(6)" + _SEP + r"(\d{3,4})|(4)" + _SEP + r"(\d{2}))"
    r"(?:" + _SEP + r"\d+)?(?![\d])")
_AE_BUILD = re.compile(r"\b(?:AE|anniversary(?: edition)?)\W{0,3}(\d{3,4})\b", re.I)
_LATER = re.compile(r"^\s*(?:\+|and (?:up|later|newer|above|higher)|or (?:later|newer|above|higher)|\(?and newer)", re.I)
_EARLIER = re.compile(r"^\s*(?:and (?:below|earlier|older|lower)|or (?:below|earlier|older|lower))", re.I)
_RANGE = re.compile(r"^\s*(?:-|–|to|through)\s*$", re.I)
_NEUTRAL = re.compile(
    r"\b(?:all (?:game )?versions|any (?:game )?version|version[- ]independent|"
    r"S?SE\s*(?:/|&|and|\+|-|\s)\s*AE|AE\s*(?:/|&|and|\+|-|\s)\s*S?SE)\b", re.I)
_SE_ONLY = re.compile(r"\b(?:pre[- ]?AE|non[- ]?AE|SE[- ]only|before AE|old(?:er)? SE)\b", re.I)
_AE = re.compile(r"\b(?:post[- ]?AE|AE|anniversary(?: edition)?)\b", re.I)
_VR = re.compile(r"\bVR\b")
_STORES = {
    "GOG": re.compile(r"\bGOG\b", re.I),
    "Game Pass": re.compile(r"\bgame ?pass\b|\bMS ?store\b|\bmicrosoft store\b|\bxbox\b", re.I),
    "Steam": re.compile(r"\bsteam\b", re.I),
}


@dataclass
class Hints:
    exact: list[Version] = field(default_factory=list)
    ranges: list[tuple[Version, Version]] = field(default_factory=list)
    families: set[str] = field(default_factory=set)
    stores: set[str] = field(default_factory=set)
    vr: bool = False
    neutral: bool = False

    @property
    def empty(self) -> bool:
        return not (self.exact or self.ranges or self.families or self.stores or self.vr or self.neutral)

    def describe(self) -> str:
        bits = []
        if self.vr:
            bits.append("Skyrim VR")
        fams = {family(v) for v in self.exact} | self.families
        for lo, hi in self.ranges:
            if hi[2] >= 9999:
                bits.append(f"{version_text(lo)}+")
            elif lo == (1, 0, 0):
                bits.append(f"{version_text(hi)} and earlier")
            else:
                bits.append(f"{version_text(lo)}-{version_text(hi)}")
        bits += [FAMILY_LABEL.get(f, f) for f in sorted(fams) if f != "VR"]
        if self.stores:
            bits.append("/".join(sorted(self.stores)))
        return ", ".join(dict.fromkeys(bits)) or "another version"


def read_hints(text: str, *, from_description: bool = False) -> Hints:
    h = Hints()
    if not text:
        return h
    if _NEUTRAL.search(text):
        h.neutral = True
    found = []
    for m in _FULL_VERSION.finditer(text):
        minor, build = next((m.group(i), m.group(i + 1)) for i in (1, 3, 5) if m.group(i))
        found.append((m.start(), m.end(), (1, int(minor), int(build))))
    for m in _AE_BUILD.finditer(text):
        if not any(a <= m.start(1) < b for a, b, _ in found):
            found.append((m.start(1), m.end(1), (1, 6, int(m.group(1)))))
    found.sort()
    used_as_range_end = set()
    for i, (start, end, v) in enumerate(found):
        if i in used_as_range_end:
            continue
        after = text[end:end + 16]
        before = text[max(0, start - 10):start].lower()
        if i + 1 < len(found) and _RANGE.match(text[end:found[i + 1][0]]):
            h.ranges.append((v, found[i + 1][2]))
            used_as_range_end.add(i + 1)
        elif _LATER.match(after) or re.search(r"post[- ]?$", before):
            h.ranges.append((v, (v[0], v[1], 99999)))
        elif _EARLIER.match(after) or re.search(r"up to\s*$", before):
            h.ranges.append(((1, 0, 0), v))
        elif re.search(r"pre[- ]?$", before):
            h.ranges.append(((1, 0, 0), (v[0], v[1], max(v[2] - 1, 0))))
        else:
            h.exact.append(v)
    if not from_description:
        if _VR.search(text):
            h.vr = True
        for store, rx in _STORES.items():
            if rx.search(text):
                h.stores.add(store)
    if not (h.exact or h.ranges):
        if _SE_ONLY.search(text):
            h.families.add("SE")
        elif _AE.search(text) and not from_description:
            h.families.update({"AE-early", "AE-640", "AE-1130"})
    return h


@dataclass
class Fit:
    status: str      # "ok" (for your game), "other" (for another version), "unknown"
    note: str = ""

    @property
    def hidden(self) -> bool:
        return self.status == "other"


def fit(name: str, file_name: str, description: str, target: GameTarget | None) -> Fit:
    """Is this file for the target game?"""
    if not target or not target.active:
        return Fit("unknown")
    # Nexus file names swap spaces/dots for underscores and add -modid-version.
    base = re.sub(r"-\d+-[\d-]+[a-z]*\.\w+$", "", file_name or "", flags=re.I)
    h = read_hints(f"{name} {base}")
    from_description = False
    if h.empty and description:
        h = read_hints(description[:300], from_description=True)
        from_description = True
    if h.empty:
        return Fit("unknown")
    result = _compare(h, target)
    if from_description and result.status == "other":
        # A description saying "works on 1.6.1170" isn't proof it won't work on yours.
        return Fit("unknown", f"description mentions {h.describe()}")
    return result


def _compare(h: Hints, target: GameTarget) -> Fit:
    fam = target.family
    if h.stores and target.store not in h.stores:
        return Fit("other", f"for {'/'.join(sorted(h.stores))}")
    if h.vr != (fam == "VR") and (h.vr or h.exact or h.ranges or h.families):
        return Fit("other", f"for {h.describe()}")
    if h.neutral and not (h.exact or h.ranges):
        return Fit("ok", "all versions")
    v = target.version
    matches = (any(family(e) == fam for e in h.exact)
               or any(lo <= v <= hi for lo, hi in h.ranges)
               or fam in h.families)
    if matches:
        return Fit("ok", "for your version")
    if h.exact or h.ranges or h.families:
        return Fit("other", f"for {h.describe()}")
    return Fit("ok", "for your version")  # only a matching store name


# -- finding your game and its version ---------------------------------------

@dataclass
class GameInstall:
    folder: Path
    exe: Path
    version: Version | None
    store: str
    found_by: str

    def describe(self) -> str:
        v = version_text(self.version) or "unknown version"
        return f"Skyrim {v} ({self.store}) - {self.folder}"


def exe_version(path: Path) -> Version | None:
    """File version of a Windows .exe (e.g. SkyrimSE.exe -> (1, 6, 1170))."""
    if sys.platform != "win32" or not path.is_file():
        return None
    try:
        import ctypes
        from ctypes import wintypes

        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(str(path), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)):
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [(n, wintypes.DWORD) for n in (
                "signature", "struc_version", "file_ms", "file_ls", "product_ms", "product_ls",
                "flags_mask", "flags", "os", "type", "subtype", "date_ms", "date_ls")]

        info = ctypes.cast(ptr, ctypes.POINTER(FixedFileInfo)).contents
        return (info.file_ms >> 16, info.file_ms & 0xFFFF, info.file_ls >> 16)
    except Exception:
        return None


def store_of(folder: Path) -> str:
    try:
        names = {p.name.lower() for p in folder.iterdir()}
    except OSError:
        names = set()
    text = str(folder).lower()
    if any(n.startswith("goggame-") for n in names) or "galaxy64.dll" in names:
        return "GOG"
    if ("xboxgames" in text or "windowsapps" in text or "appxmanifest.xml" in names
            or "microsoftgame.config" in names):
        return "Game Pass"
    return "Steam"


def _install(folder: Path, found_by: str, read_version=exe_version) -> GameInstall | None:
    for exe_name in ("SkyrimSE.exe", "SkyrimVR.exe"):
        exe = folder / exe_name
        if exe.is_file():
            version = read_version(exe)
            if version is None and exe_name == "SkyrimVR.exe":
                version = (1, 4, 15)
            return GameInstall(folder, exe, version, store_of(folder), found_by)
    return None


def _steam_libraries() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        import winreg
        for root, sub, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(root, sub) as key:
                    roots.append(Path(str(winreg.QueryValueEx(key, name)[0])))
            except OSError:
                pass
    libraries = []
    for steam in roots:
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        libraries.append(steam)
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            libraries.append(Path(m.group(1).replace("\\\\", "\\")))
    return libraries


def _gog_folders() -> list[Path]:
    if sys.platform != "win32":
        return []
    import winreg
    out = []
    for sub in (r"SOFTWARE\WOW6432Node\GOG.com\Games", r"SOFTWARE\GOG.com\Games"):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
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
                    with winreg.OpenKey(key, name) as game:
                        title = str(winreg.QueryValueEx(game, "gameName")[0])
                        if "skyrim" in title.lower():
                            out.append(Path(str(winreg.QueryValueEx(game, "path")[0])))
                except OSError:
                    continue
    return out


def find_games(mo2_game_path: str | Path | None = None, *, read_version=exe_version,
               extra_folders: list[Path] | None = None) -> list[GameInstall]:
    """Skyrim SE/AE (and VR) installs on this PC; the MO2 instance's game first."""
    found: list[GameInstall] = []
    seen: set[str] = set()

    def add(folder: Path, how: str) -> None:
        key = os.path.normcase(str(folder))
        if key in seen:
            return
        inst = _install(folder, how, read_version)
        if inst:
            seen.add(key)
            found.append(inst)

    if mo2_game_path:
        add(Path(mo2_game_path), "MO2 instance")
    for folder in extra_folders or []:
        add(folder, "folder")
    for lib in _steam_libraries():
        for game in ("Skyrim Special Edition", "SkyrimVR"):
            add(lib / "steamapps" / "common" / game, "Steam")
    for folder in _gog_folders():
        add(folder, "GOG")
    from .finder import fixed_drives
    for drive in fixed_drives():
        xbox = Path(drive) / "XboxGames"
        if xbox.is_dir():
            for game in xbox.glob("*Skyrim*"):
                add(game / "Content", "Game Pass")
    return found


def mo2_game_path(instance_dir: str | Path | None) -> str | None:
    """The game folder an MO2 instance manages ([General] gamePath)."""
    if not instance_dir:
        return None
    from .managers.mo2 import read_instance_ini
    ini = Path(instance_dir) / "ModOrganizer.ini"
    if not ini.is_file():
        return None
    try:
        return read_instance_ini(ini).get("General/gamePath")
    except Exception:
        return None
