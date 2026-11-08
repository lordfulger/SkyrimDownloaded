"""Start a list from a Nexus Collection.

Each file in the collection becomes a list line with that exact file pinned
(``| file=…``); files the collection marks optional are pinned too but asked
about (``| ask``). Things the collection needs from outside Nexus are listed
as notes. Installer (FOMOD) choices stored in a collection aren't used: your
mod manager asks for those when installing.
"""

from __future__ import annotations

import re

from .links import DEFAULT_GAME

_URL = re.compile(
    r"nexusmods\.com/(?:games/)?(?P<game>[a-z0-9]+)/collections/(?P<slug>[a-z0-9]+)"
    r"(?:/revisions/(?P<rev>\d+))?", re.I)
_SLUG = re.compile(r"^\s*(?P<slug>[a-z0-9]{6,})\s*$", re.I)


def parse_link(text: str) -> tuple[str, str, int | None] | None:
    """(game, slug, revision) from a collection link (or a bare slug)."""
    m = _URL.search(text or "")
    if m:
        return m.group("game").lower(), m.group("slug").lower(), int(m.group("rev")) if m.group("rev") else None
    m = _SLUG.match(text or "")
    if m:
        return DEFAULT_GAME, m.group("slug").lower(), None
    return None


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("|", "/").replace("#", "")).strip()


def to_list(data: dict, game: str) -> tuple[str, int]:
    """The collection as list text, and how many mods are in it."""
    col = data.get("collection") or {}
    name = _clean(col.get("name") or "Nexus Collection")
    slug = col.get("slug") or ""
    game = ((col.get("game") or {}).get("domainName") or game).lower()
    rev = data.get("revisionNumber")
    mods: dict[tuple[str, int], dict] = {}
    for item in data.get("modFiles") or []:
        f = item.get("file") or {}
        mod_id = f.get("modId")
        if not mod_id:
            continue
        g = ((f.get("game") or {}).get("domainName") or game).lower()
        m = mods.setdefault((g, int(mod_id)), {"name": _clean((f.get("mod") or {}).get("name") or ""),
                                               "files": [], "names": [], "optional": True})
        m["files"].append(int(item.get("fileId") or f.get("fileId")))
        m["names"].append(_clean(f.get("name") or ""))
        m["optional"] = m["optional"] and bool(item.get("optional"))
    lines = [f"# {name}" + (f" (revision {rev})" if rev else ""),
             f"# From the Nexus Collection https://www.nexusmods.com/games/{game}/collections/{slug}",
             "# Each line pins the exact file the collection uses; optional ones ask first.",
             f"#! collection: {slug}", ""]
    for (g, mod_id), m in mods.items():
        rule = "file=" + ",".join(map(str, m["files"])) + (" ask" if m["optional"] else "")
        note = f"{m['name']}: {', '.join(n for n in m['names'] if n)}"
        if m["optional"]:
            note += " (optional in the collection)"
        lines.append(f"https://www.nexusmods.com/{g}/mods/{mod_id} | {rule}   # {note}")
    outside = data.get("externalResources") or []
    if outside:
        lines += ["", "# Also needed, from outside Nexus (get these yourself):"]
        for r in outside:
            opt = " (optional)" if r.get("optional") else ""
            lines.append(f"#   {_clean(r.get('name') or '?')}{opt}: {r.get('resourceUrl') or ''}")
    return "\n".join(lines) + "\n", len(mods)
