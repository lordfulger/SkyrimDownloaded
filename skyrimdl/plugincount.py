"""The exact plugin count of an MO2 profile: which plugins are switched on, where each one
comes from (the mod that wins, Overwrite, or the game's Data folder), and whether its header
says it's light (ESL-flagged) - the way the game itself counts them.

Skyrim loads at most 254 regular plugins (.esm / .esp) and 4096 light ones (.esl or flagged).
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .mo2import import profiles_dir, read_modlist
from .gameversion import mo2_game_path

REGULAR_LIMIT = 254
LIGHT_LIMIT = 4096
LIGHT_FLAG = 0x200     # TES4 record flag: ESL
MASTER_FLAG = 0x1
#: Loaded by the game itself, whatever plugins.txt says.
GAME_MASTERS = ["Skyrim.esm", "Update.esm", "Dawnguard.esm", "HearthFires.esm", "Dragonborn.esm"]
_EXTS = (".esp", ".esm", ".esl")


@dataclass
class Plugin:
    name: str
    light: bool
    master: bool
    source: str        # MO2 mod name, "Overwrite" or "game"
    found: bool = True


@dataclass
class Count:
    profile: str
    regular: list = field(default_factory=list)   # [Plugin]
    light: list = field(default_factory=list)
    off: int = 0                                   # in the profile but switched off
    missing: list = field(default_factory=list)    # switched on, but no file found

    @property
    def regular_count(self) -> int:
        return len(self.regular)

    @property
    def light_count(self) -> int:
        return len(self.light)


def read_header(path: Path) -> tuple[bool, bool] | None:
    """(light, master) from a plugin's TES4 header, or None if it can't be read."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
    except OSError:
        return None
    if len(head) < 12 or head[:4] != b"TES4":
        return None
    flags = struct.unpack_from("<I", head, 8)[0]
    return bool(flags & LIGHT_FLAG), bool(flags & MASTER_FLAG)


def profile_plugins(profile: Path) -> list[tuple[str, bool]]:
    """(plugin, switched on) in load order. MO2 keeps the order in loadorder.txt and what's on
    in plugins.txt (lines starting with *)."""
    def lines(name):
        try:
            text = (profile / name).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return []
        return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]

    enabled = {ln[1:].lower() for ln in lines("plugins.txt") if ln.startswith("*")}
    listed = [ln.lstrip("*") for ln in lines("plugins.txt")]
    order = lines("loadorder.txt") or listed
    out, seen = [], set()
    for name in GAME_MASTERS + order + listed:
        low = name.lower()
        if low in seen or not low.endswith(_EXTS):
            continue
        seen.add(low)
        is_game = name in GAME_MASTERS or low.startswith("cc") or low == "_resourcepack.esl"
        out.append((name, low in enabled or (is_game and low not in {x.lower() for x in listed})))
    return out


def plugin_files(instance: Path, mods_dir: Path, profile: Path) -> dict[str, tuple[Path, str]]:
    """{plugin (lower case): (file, where from)} as MO2 shows the game: switched-on mods by
    priority (the higher one wins), Overwrite on top, the game's Data folder underneath."""
    sources: list[tuple[Path, str]] = []
    game = mo2_game_path(instance)
    if game:
        sources.append((Path(game) / "Data", "game"))
    for name, on in read_modlist(profile):   # top of the left pane (lowest priority) first
        if on and not name.endswith("_separator"):
            sources.append((Path(mods_dir) / name, name))
    sources.append((instance / "overwrite", "Overwrite"))
    files: dict[str, tuple[Path, str]] = {}
    for folder, label in sources:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for n in names:
            if n.lower().endswith(_EXTS):
                files[n.lower()] = (folder / n, label)
    return files


def count(instance: Path, mods_dir: Path, profile_name: str) -> Count:
    profile = profiles_dir(instance) / profile_name
    files = plugin_files(instance, mods_dir, profile)
    result = Count(profile_name)
    for name, on in profile_plugins(profile):
        if not on:
            result.off += 1
            continue
        hit = files.get(name.lower())
        if hit is None:
            result.missing.append(name)
            continue
        path, source = hit
        header = read_header(path)
        light = name.lower().endswith(".esl") or bool(header and header[0])
        master = name.lower().endswith((".esm", ".esl")) or bool(header and header[1])
        (result.light if light else result.regular).append(Plugin(name, light, master, source))
    return result
