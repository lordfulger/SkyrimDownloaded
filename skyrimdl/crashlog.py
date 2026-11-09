"""Read a Skyrim crash log (Crash Logger SSE/AE, or .NET Script Framework) and point at the
mods it names: the DLLs in the call stack and the plugins of the objects involved.

The full lists of loaded modules and plugins at the end of a log name everything, so only
the parts before them are read.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# "0x7FFA1C2B3A10 po3_PapyrusExtender.dll+00B3A10", "(void* -> Some Mod.dll+0012)", "(SomeMod.dll+12)"
_DLL = re.compile(r"(?:0x[0-9A-F]+\s+|->\s*|\(\s*|^\s*)([A-Za-z0-9_][A-Za-z0-9_\-. ]{0,80}?\.dll)\s*\+",
                  re.I | re.M)
# File: "Mod.esp", Modified by: A.esm -> B.esp, (Mod.esp), [Mod.esp]
_PLUGIN = re.compile(r"""(?:"|->\s|<-\s|:\s|\(|\[)\s*([^\s"'()\[\]<>|:][^"'()\[\]\r\n<>|:]{0,118}?\.(?:esp|esm|esl))\b""",
                     re.I)
_EXCEPTION = re.compile(r"(Unhandled (?:native )?exception[^\r\n]*)", re.I)
# Where the long "everything that's loaded" lists start.
_LISTS = re.compile(r"^\s*(?:MODULES:|SKSE PLUGINS:|PLUGINS:|Modules\s*\(|Plugins\s*\(|Loaded modules)", re.I | re.M)
_CALLSTACK = re.compile(r"^\s*(?:PROBABLE CALL STACK:|Probable callstack)", re.I | re.M)

#: Game, driver and system files: in every crash, not the cause.
NOT_MODS = {
    "skyrimse.exe", "skyrimvr.exe", "kernel32.dll", "kernelbase.dll", "ntdll.dll", "ucrtbase.dll",
    "user32.dll", "win32u.dll", "gdi32.dll", "d3d11.dll", "dxgi.dll", "d3dcompiler_47.dll",
    "nvwgf2umx.dll", "nvldumdx.dll", "amdxx64.dll", "atidxx64.dll", "igd10iumd64.dll", "xinput1_3.dll",
    "msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "combase.dll", "ole32.dll",
    "binkw64.dll", "steam_api64.dll", "x3daudio1_7.dll", "xaudio2_7.dll", "dinput8.dll", "bink2w64.dll",
}
GAME_PLUGINS = {"skyrim.esm", "update.esm", "dawnguard.esm", "hearthfires.esm", "dragonborn.esm",
                "_resourcepack.esl"}


@dataclass
class Named:
    name: str             # e.g. "po3_PapyrusExtender.dll" or "SomeMod.esp"
    kind: str             # "dll" or "plugin"
    count: int = 1
    in_stack: bool = False  # in the call stack (the code that crashed)
    first: int = 0        # where it first comes up (earlier = closer to the crash)
    mod: str = ""         # the mod it's from (your list or MO2), if known
    url: str = ""


@dataclass
class Crash:
    kind: str = "unknown"
    exception: str = ""
    game: str = ""
    named: list = field(default_factory=list)


def parse(text: str) -> Crash:
    crash = Crash()
    if "NetScriptFramework" in text[:3000]:
        crash.kind = ".NET Script Framework"
    elif "CrashLogger" in text[:3000] or "PROBABLE CALL STACK" in text:
        crash.kind = "Crash Logger"
    m = _EXCEPTION.search(text)
    crash.exception = m.group(1).strip() if m else ""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    if "Skyrim" in first_line:
        crash.game = first_line.strip()
    lists = _LISTS.search(text)
    head = text[: lists.start()] if lists else text
    stack_at = _CALLSTACK.search(head)
    stack = head[stack_at.end():] if stack_at else ""
    stack = re.split(r"^\s*(?:REGISTERS:|Registers|STACK:|Stack\s*\(|Possible relevant objects)", stack,
                     maxsplit=1, flags=re.I | re.M)[0]
    if stack:  # the rest of the log, without the call stack (so it isn't counted twice)
        start = stack_at.end()
        rest = head[:start] + " " * len(stack) + head[start + len(stack):]
    else:
        rest = head
    found: dict[str, Named] = {}

    def add(name, kind, pos, in_stack=False):
        key = name.lower().strip()
        if key in NOT_MODS or key in GAME_PLUGINS or re.match(r"^cc\w+\.esl$", key) or key.startswith("skse64_"):
            return
        if key in found:
            found[key].count += 1
            found[key].in_stack = found[key].in_stack or in_stack
        else:
            found[key] = Named(name.strip(), kind, 1, in_stack, pos)

    for m in _DLL.finditer(stack):
        add(os.path.basename(m.group(1)), "dll", m.start(), True)
    for m in _DLL.finditer(rest):
        add(os.path.basename(m.group(1)), "dll", m.start() + 100000)
    for m in _PLUGIN.finditer(rest):
        add(m.group(1), "plugin", m.start() + 100000)
    crash.named = sorted(found.values(), key=lambda n: (not n.in_stack, -n.count, n.first))
    return crash


# -- which mod a plugin or DLL comes from ------------------------------------------------------

def index_mo2(mods_dir: Path) -> dict[str, str]:
    """{file name (lower case): MO2 mod folder} for plugins and SKSE DLLs of installed mods."""
    out: dict[str, str] = {}
    try:
        folders = [d for d in Path(mods_dir).iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in folders:
        for where in (d, d / "SKSE" / "Plugins", d / "skse" / "plugins"):
            try:
                names = os.listdir(where)
            except OSError:
                continue
            for n in names:
                low = n.lower()
                if low.endswith((".esp", ".esm", ".esl", ".dll")):
                    out.setdefault(low, d.name)
    return out


def mo2_mod_ids(mods_dir: Path, folders) -> dict[str, int]:
    """{MO2 mod folder: Nexus mod id} for these folders."""
    from .managers.mo2 import _section
    out = {}
    for name in set(folders):
        try:
            text = (Path(mods_dir) / name / "meta.ini").read_text(encoding="utf-8", errors="replace")
            out[name] = int(_section(text, "General").get("modid", "0").strip('"') or 0)
        except (OSError, ValueError):
            out[name] = 0
    return out


def match(crash: Crash, plans, mo2_files: dict[str, str] | None = None,
          mo2_ids: dict[str, int] | None = None, previews: dict[str, object] | None = None) -> None:
    """Fill in ``mod`` / ``url`` for each name: from MO2's mods folder, the archives' file lists,
    or a mod whose name matches."""
    by_id = {p.entry.mod_id: p for p in plans if not getattr(p, "error", None)}
    for n in crash.named:
        key = n.name.lower()
        plan = None
        folder = (mo2_files or {}).get(key)
        if folder:
            plan = by_id.get((mo2_ids or {}).get(folder, 0))
            n.mod = plan.title if plan else folder
        elif previews and key in previews:
            plan = previews[key]
            n.mod = plan.title
        else:
            stem = re.sub(r"[^a-z0-9]", "", key.rsplit(".", 1)[0])
            if len(stem) >= 4:
                for p in plans:
                    title = re.sub(r"[^a-z0-9]", "", p.title.lower())
                    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", p.title)).lower()
                    if stem in title or (len(title) >= 5 and title in stem) or stem == initials:
                        plan = p
                        n.mod = p.title
                        break
        if plan is not None:
            n.url = plan.entry.page_url


def preview_index(plans, cache) -> dict:
    """{file name: plan} from the file lists already saved by Check list (no downloading)."""
    out = {}
    if cache is None:
        return out
    for p in plans:
        for o in p.selected_options():
            url = o.raw.get("content_preview_link") or ""
            tree = cache.get("preview:" + url, max_age=365 * 86400) if url else None
            stack = [tree] if isinstance(tree, dict) else []
            while stack:
                node = stack.pop()
                for c in node.get("children") or []:
                    if c.get("type") == "directory":
                        stack.append(c)
                    else:
                        name = str(c.get("name") or "").lower()
                        if name.endswith((".esp", ".esm", ".esl", ".dll")):
                            out.setdefault(name, p)
    return out


def log_folders() -> list[Path]:
    """Where crash logs usually are."""
    docs = Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents" / "My Games"
    out = []
    for game in ("Skyrim Special Edition", "Skyrim Special Edition GOG", "Skyrim VR"):
        out += [docs / game / "SKSE", docs / game / "SKSE" / "Crashlogs"]
    return [p for p in out if p.is_dir()]


def newest_logs(limit: int = 5) -> list[Path]:
    logs = []
    for folder in log_folders():
        try:
            logs += [p for p in folder.iterdir() if p.suffix.lower() in (".log", ".txt") and "crash" in p.name.lower()]
        except OSError:
            pass
    return sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
