"""Share a list with every choice locked in, so someone else gets exactly your setup.

The shared file is an ordinary mod list - each mod's line pins the exact files
you picked (``| file=…``), mods you left out are marked ``| skip``, and lines
starting ``#!`` say which Skyrim it was made for. Open it in SkyrimDownloaded
(or run it with the command line) like any other list.
"""

from __future__ import annotations

import re
import time

from . import __version__
from .gameversion import GameTarget, family, parse_version, version_text

_META = re.compile(r"^\s*#!\s*([A-Za-z][\w-]*)\s*:\s*(.*?)\s*$")


def list_meta(text: str) -> dict[str, str]:
    """``#! key: value`` lines at the top of a shared list."""
    meta = {}
    for line in text.splitlines():
        m = _META.match(line)
        if m:
            meta[m.group(1).lower()] = m.group(2)
    return meta


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("|", "/")).strip()


def export_text(plans, target: GameTarget | None, *, title: str = "") -> str:
    lines = [
        f"# {title or 'Skyrim mod list'}",
        f"# Made with SkyrimDownloaded {__version__}. Open it in SkyrimDownloaded to get exactly these files",
        "# (each line pins the exact file IDs that were picked).",
    ]
    if target and target.active:
        lines.append(f"#! game-version: {version_text(target.version)}")
        lines.append(f"#! store: {target.store}")
    lines.append(f"#! exported: {time.strftime('%Y-%m-%d')}")
    lines.append("")
    section = ""
    for plan in plans:
        if getattr(plan.entry, "section", "") != section:
            section = plan.entry.section
            if section:
                lines += ["", f"## {section}"]
        url = plan.entry.page_url
        name = _clean(plan.title)
        note = f" - {_clean(plan.entry.note)}" if plan.entry.note and plan.entry.note != plan.title else ""
        if plan.error:
            lines.append(f"# {url}   # {name}: {plan.error}")
            continue
        picked = plan.selected_options()
        if plan.skipped or not picked:
            lines.append(f"{url} | skip   # {name} (left out){note}")
            continue
        ids = ",".join(str(o.file_id) for o in picked)
        files = ", ".join(_clean(o.name) for o in picked)
        lines.append(f"{url} | file={ids}   # {name}: {files}{note}")
    return "\n".join(lines) + "\n"


def version_warning(meta: dict[str, str], target: GameTarget | None) -> str | None:
    """A note when a shared list was made for a different Skyrim than yours."""
    made_for = parse_version(meta.get("game-version"))
    if not made_for:
        return None
    store = meta.get("store") or ""
    if not target or not target.active:
        return (f"This list was made for Skyrim {version_text(made_for)}"
                f"{f' ({store})' if store else ''}. Set your Skyrim version so files that don't "
                "fit yours are flagged.")
    if family(made_for) != target.family or (store and store != target.store) or made_for > target.version:
        return (f"This list was made for Skyrim {version_text(made_for)}{f' ({store})' if store else ''}, "
                f"and yours is {target.describe()}. Files it picked that don't fit your version are "
                "flagged for you to choose again.")
    return None
