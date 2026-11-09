"""Find newer files for the ones you picked.

Asks Nexus again for each mod's Files tab and uses its record of which file
replaced which (authors upload a new version and Nexus links old -> new),
plus files that moved to "Old versions" or were removed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .gameversion import GameTarget
from .nexus import NexusError
from .selection import ARCHIVED, CURRENT, OLD, FileOption, annotate, primary_file, sort_options


@dataclass
class Update:
    plan: object
    old: FileOption
    new: FileOption | None     # None: no replacement found
    note: str

    @property
    def label(self) -> str:
        if self.new is None:
            return f"{self.plan.title}: {self.old.name} - {self.note}"
        old_v = f" v{self.old.version}" if self.old.version else ""
        new_v = f" v{self.new.version}" if self.new.version else ""
        return f"{self.plan.title}: {self.old.name}{old_v} → {self.new.name}{new_v} ({self.note})"


def _latest(file_id: int, updates: list[dict]) -> int:
    """Follow Nexus's old -> new links to the newest file."""
    nxt = {}
    for u in updates:
        try:
            nxt[int(u["old_file_id"])] = int(u["new_file_id"])
        except (KeyError, TypeError, ValueError):
            continue
    seen = {file_id}
    while file_id in nxt and nxt[file_id] not in seen:
        file_id = nxt[file_id]
        seen.add(file_id)
    return file_id


def check_plan(client, plan, target: GameTarget | None = None) -> list[Update]:
    entry = plan.entry
    raw_files, file_updates = client.files_and_updates(entry.game, entry.mod_id, fresh=True)
    try:
        plan.mod = client.mod(entry.game, entry.mod_id, fresh=True)
    except NexusError:
        pass
    fresh = sort_options([FileOption.from_api(f) for f in raw_files])
    annotate(fresh, target)
    by_id = {o.file_id: o for o in fresh}
    old_by_id = {o.file_id: o for o in plan.options}
    found: list[Update] = []
    for fid in plan.selected:
        old = old_by_id.get(fid) or by_id.get(fid)
        if old is None:
            continue
        now = by_id.get(fid)
        newest = _latest(fid, file_updates)
        if newest != fid and newest in by_id:
            found.append(Update(plan, old, by_id[newest], "newer file uploaded"))
        elif now is None or now.category in (OLD, ARCHIVED):
            # Only suggest a file from the same section (Main / Optional...) that isn't picked already.
            same_kind = [o for o in fresh if o.category == old.category and o.category in CURRENT
                         and not o.fit.hidden and o.file_id not in plan.selected]
            guess = primary_file(same_kind) if same_kind else None
            why = "removed from Nexus" if now is None else "moved to old versions"
            found.append(Update(plan, old, guess, why + ("; is this its replacement?" if guess else "")))
        elif (now.version and old.version and now.version != old.version) or now.uploaded > old.uploaded:
            found.append(Update(plan, old, now, "same file, updated"))
    plan.options = fresh  # show what's on Nexus now
    return found


def check_updates(client, plans, target: GameTarget | None = None, *, workers: int = 4,
                  progress=None) -> tuple[list[Update], list[str]]:
    todo = [p for p in plans if p.mod and not p.error and not p.skipped and p.selected]
    updates: list[Update] = []
    errors: list[str] = []

    def one(plan):
        try:
            return check_plan(client, plan, target), None
        except NexusError as err:
            return [], f"{plan.title}: {err}"
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, (found, err) in enumerate(pool.map(one, todo), start=1):
            updates += found
            if err:
                errors.append(err)
            if progress:
                progress(i, len(todo))
    return updates, errors


def apply(updates: list[Update]) -> int:
    """Swap old files for their replacements in each mod's picks."""
    n = 0
    for u in updates:
        if u.new is None or u.old.file_id not in u.plan.selected:
            continue
        sel = u.plan.selected
        if u.new.file_id in sel:
            sel.remove(u.old.file_id)
        else:
            sel[sel.index(u.old.file_id)] = u.new.file_id
        u.plan.reason = "updated to the newer file"
        n += 1
    return n


def newer_on_nexus(plans, updated: list[dict]) -> list:
    """Mods in the list with a file on Nexus newer than any file we know of (from one
    "updated this week" answer). Marks them with ``newer_files``."""
    latest = {}
    for u in updated:
        try:
            latest[int(u.get("mod_id"))] = int(u.get("latest_file_update") or 0)
        except (TypeError, ValueError):
            continue
    out = []
    for p in plans:
        if p.error or p.skipped or not p.options or p.entry.mod_id not in latest:
            continue
        known = max((o.uploaded for o in p.options), default=0)
        if latest[p.entry.mod_id] > known + 60:
            p.newer_files = True
            out.append(p)
    return out
