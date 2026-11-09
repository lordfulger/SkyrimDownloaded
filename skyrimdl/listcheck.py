"""Checks over the whole list before downloading: plugin count, disk space, duplicates,
mods that were replaced or abandoned, and the download size for each texture size."""

from __future__ import annotations

import json
import re
import shutil
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from .selection import (TEXTURE_SIZES, _ESL, CURRENT, prefer_texture, prefer_variants, texture_sizes)
from .text import bbcode_to_text, nexus_mod_ids

#: Skyrim can load about 254 regular plugins (ESL-flagged ones don't count).
PLUGIN_LIMIT = 254
#: Skyrim.esm, Update.esm, Dawnguard, HearthFires and Dragonborn are always loaded.
BASE_GAME_PLUGINS = 5
#: Installed size is usually bigger than the archive (archives are compressed).
INSTALL_FACTOR = 1.5
OLD_AFTER_YEARS = 4

_PLUGIN = re.compile(r"\.(esp|esm|esl)$", re.I)
_REPLACED = re.compile(
    r"\b(?:no longer (?:supported|maintained|updated|needed|necessary|required)|obsolete|deprecated|"
    r"discontinued|abandoned|(?:has been |was |is now )?(?:merged|integrated|included|incorporated) "
    r"(?:into|in|with)|superseded by|replaced by|(?:now )?part of|use .{1,60}? instead|"
    r"moved to|new (?:version|page) (?:is )?(?:here|at))\b", re.I)


# -- plugins in an archive (Nexus shows each archive's file list) ----------------------

@dataclass
class Plugin:
    name: str
    light: bool              # .esl, or said to be ESL-flagged
    optional: bool = False   # inside an installer (FOMOD) option: only if you pick it


def preview_plugins(tree: dict) -> list[Plugin]:
    """Plugins in a Nexus content preview (the archive's file list). In an archive with
    an installer (a fomod folder), plugins in sub-folders are options you may not pick."""
    out: list[Plugin] = []
    has_fomod = False

    def walk(node, depth):
        nonlocal has_fomod
        for child in node.get("children") or []:
            name = str(child.get("name") or "")
            if child.get("type") == "directory":
                if name.lower() == "fomod":
                    has_fomod = True
                else:
                    walk(child, depth + 1)
            elif _PLUGIN.search(name):
                out.append(Plugin(name, name.lower().endswith(".esl"), depth > 0))

    walk(tree, 0)
    if not has_fomod:  # no installer: everything in it gets installed
        for p in out:
            p.optional = False
    return out


def fetch_preview(url: str, cache=None, timeout: float = 20.0) -> dict | None:
    """An archive's file list from Nexus (not counted as an API request). Kept on disk."""
    if not url:
        return None
    key = "preview:" + url
    if cache is not None:
        saved = cache.get(key, max_age=365 * 86400)
        if saved is not None:
            return saved
    req = urllib.request.Request(url, headers={"User-Agent": f"SkyrimDownloaded/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read(4 * 1024 * 1024).decode("utf-8") or "null")
    except Exception:
        return None
    if isinstance(data, dict) and cache is not None:
        cache.put(key, data)
    return data if isinstance(data, dict) else None


@dataclass
class PluginCount:
    full: int = 0            # count against the limit
    light: int = 0
    optional: int = 0        # in installer options: may or may not be installed
    unknown_files: int = 0   # files whose contents Nexus doesn't show
    by_mod: list = field(default_factory=list)   # (plan, [Plugin])

    @property
    def total_full(self) -> int:
        return self.full + BASE_GAME_PLUGINS


def count_plugins(plans, fetch=fetch_preview, on_progress=None, cancel=None) -> PluginCount:
    result = PluginCount()
    seen: set = set()
    picked = []
    for p in plans:
        if p.error or p.skipped:
            continue
        for o in p.selected_options():
            if (p.entry.mod_id, o.file_id) not in seen:
                seen.add((p.entry.mod_id, o.file_id))
                picked.append((p, o))
    for i, (plan, opt) in enumerate(picked):
        if cancel is not None and cancel.is_set():
            break
        if on_progress:
            on_progress(i, len(picked))
        tree = fetch(opt.raw.get("content_preview_link") or "")
        if tree is None:
            result.unknown_files += 1
            continue
        plugins = preview_plugins(tree)
        flagged = bool(_ESL.search(f"{opt.name} {opt.file_name} {opt.description}"))
        for p in plugins:
            p.light = p.light or (flagged and p.name.lower().endswith(".esp"))
            if p.optional:
                result.optional += 1
            elif p.light:
                result.light += 1
            else:
                result.full += 1
        if plugins:
            result.by_mod.append((plan, opt, plugins))
    return result


# -- disk space -------------------------------------------------------------------

@dataclass
class Space:
    folder: Path
    need: int
    free: int | None

    @property
    def enough(self) -> bool:
        return self.free is None or self.free >= self.need


def free_space(folder: Path) -> int | None:
    folder = Path(folder)
    for p in [folder, *folder.parents]:
        if p.exists():
            try:
                return shutil.disk_usage(p).free
            except OSError:
                return None
    return None


def space_needed(plans, downloads: Path | None, mods: Path | None, already=lambda opt: False) -> list[Space]:
    """Room for the downloads, and for the installed mods (same drive: both together)."""
    archives = sum(o.approx_bytes or 0 for p in plans if not p.error and not p.skipped
                   for o in p.selected_options() if not already(o))
    out = []
    if downloads:
        out.append(Space(Path(downloads), archives, free_space(downloads)))
    if mods:
        installed = int(archives * INSTALL_FACTOR)
        same_drive = downloads and _drive(downloads) == _drive(mods)
        if same_drive:
            out[0].need += installed
        else:
            out.append(Space(Path(mods), installed, free_space(mods)))
    return out


def _drive(path: Path) -> str:
    p = Path(path)
    return (p.drive or p.anchor or "/").lower()


# -- duplicates, replaced and abandoned mods ------------------------------------------

def duplicates(text: str, game: str) -> list[tuple[str, list[int]]]:
    """Mods that are in the list more than once: (mod key "game/id", line numbers). The lookup
    already merges them into one, so this is just to tidy the list."""
    from .links import ListError, parse_line
    lines: dict[str, list[int]] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        try:
            found = parse_line(line, n, game)
        except ListError:
            continue
        for e in found:
            lines.setdefault(e.key, []).append(n)
    return [(key, nums) for key, nums in lines.items() if len(nums) > 1]


@dataclass
class Retired:
    plan: object
    why: str                  # the words on its page, or how old it is
    links: list = field(default_factory=list)   # mod pages it points to
    updated: float = 0.0


def retired(plans, now: float | None = None) -> list[Retired]:
    """Mods whose page says they've been replaced / merged / are no longer needed,
    and mods that haven't been updated in years."""
    now = now or time.time()
    out = []
    for p in plans:
        if p.error or not p.mod:
            continue
        raw = p.mod.raw or {}
        updated = float(raw.get("updated_timestamp") or 0)
        text = bbcode_to_text(str(raw.get("description") or ""), keep_links=True)
        summary = str(raw.get("summary") or p.mod.summary or "")
        why, links = "", []
        for source in (summary, text[:4000]):  # what's said up front
            m = _REPLACED.search(source)
            if m:
                start = max(0, m.start() - 80)
                why = source[start:m.end() + 120].replace("\n", " ").strip()
                ids = nexus_mod_ids(source[start:m.end() + 300], p.entry.game) - {p.entry.mod_id}
                links = [f"https://www.nexusmods.com/{p.entry.game}/mods/{i}" for i in sorted(ids)]
                break
        old = updated and (now - updated) > OLD_AFTER_YEARS * 365 * 86400
        if why or (old and links):
            out.append(Retired(p, why, links, updated))
        elif old:
            out.append(Retired(p, "", [], updated))
    return out


# -- download size for each texture size -------------------------------------------------

def size_by_texture(plans) -> dict[str, int]:
    """Total size of what's picked now, and if every mod used each texture size."""
    def total(pick):
        return sum((p.option(f).approx_bytes or 0) for p in plans if not p.error and not p.skipped
                   for f in pick(p) if p.option(f))
    out = {"now": total(lambda p: p.selected)}
    for size in TEXTURE_SIZES:
        out[size] = total(lambda p, s=size: prefer_variants(p.options, prefer_texture(p.options, p.selected, s)))
    return out


def textured_mods(plans) -> int:
    """How many mods come in more than one texture size."""
    n = 0
    for p in plans:
        sized = {texture_sizes(o) for o in p.options if o.category in CURRENT and texture_sizes(o)}
        if len(sized) > 1:
            n += 1
    return n
