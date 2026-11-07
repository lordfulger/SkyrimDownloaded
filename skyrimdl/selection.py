"""Work out which files on a mod's Files tab to download.

This is the "options" step: when a mod offers more than one file (say 1K and 2K
textures, or a main file plus optional patches) the user is asked, just like
picking options in a collection. A rule in the list (``| primary``,
``| match=2K``...) answers the question ahead of time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .links import ListEntry, Rule

# Nexus file categories, by category_id and by category_name.
MAIN, UPDATE, OPTIONAL, OLD, MISC, DELETED, ARCHIVED = 1, 2, 3, 4, 5, 6, 7
_BY_NAME = {
    "MAIN": MAIN, "UPDATE": UPDATE, "OPTIONAL": OPTIONAL, "OLD_VERSION": OLD,
    "MISCELLANEOUS": MISC, "DELETED": DELETED, "REMOVED": DELETED, "ARCHIVED": ARCHIVED,
}
CATEGORY_LABEL = {
    MAIN: "Main", UPDATE: "Update", OPTIONAL: "Optional", OLD: "Old version",
    MISC: "Misc", DELETED: "Deleted", ARCHIVED: "Archived",
}
# Order the options appear in, as on the Files tab.
_ORDER = {MAIN: 0, UPDATE: 1, OPTIONAL: 2, MISC: 3, OLD: 4, ARCHIVED: 5, DELETED: 6}
CURRENT = (MAIN, UPDATE, OPTIONAL, MISC)


@dataclass
class FileOption:
    file_id: int
    name: str
    file_name: str
    version: str
    category: int
    size_bytes: int | None          # exact, when Nexus gives it
    size_kb: int | None = None      # always given, but rounded
    is_primary: bool = False
    uploaded: int = 0
    description: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict) -> "FileOption":
        cat = data.get("category_id")
        if not isinstance(cat, int):
            cat = _BY_NAME.get(str(data.get("category_name") or "").upper(), MISC)
        # size_in_bytes is exact when present; size_kb / size are kilobytes.
        size = data.get("size_in_bytes")
        kb = data.get("size_kb") if data.get("size_kb") is not None else data.get("size")
        fid = data.get("file_id")
        if fid is None and isinstance(data.get("id"), list) and data["id"]:
            fid = data["id"][0]
        return cls(
            file_id=int(fid),
            name=data.get("name") or data.get("file_name") or f"File {fid}",
            file_name=data.get("file_name") or f"{fid}.7z",
            version=str(data.get("version") or data.get("mod_version") or ""),
            category=cat,
            size_bytes=int(size) if size is not None else None,
            size_kb=int(kb) if kb is not None else None,
            is_primary=bool(data.get("is_primary")),
            uploaded=int(data.get("uploaded_timestamp") or 0),
            description=_plain(data.get("description") or ""),
            raw=data,
        )

    @property
    def category_label(self) -> str:
        return CATEGORY_LABEL.get(self.category, "Other")

    @property
    def approx_bytes(self) -> int | None:
        if self.size_bytes is not None:
            return self.size_bytes
        return self.size_kb * 1024 if self.size_kb is not None else None

    def size_matches(self, actual: int) -> bool:
        """Does a file of ``actual`` bytes look like this one?"""
        if self.size_bytes is not None:
            return actual == self.size_bytes
        if self.size_kb is not None:
            return abs(actual - self.size_kb * 1024) <= 1024
        return actual > 0

    @property
    def size_text(self) -> str:
        return human_size(self.approx_bytes)

    def label(self) -> str:
        bits = [self.name]
        if self.version:
            bits.append(f"v{self.version}")
        return f"[{self.category_label}] " + " ".join(bits) + f"  ({self.size_text})"


@dataclass
class Choice:
    """The files picked for one mod and whether the user still has to decide."""

    selected: list[int]
    needs_choice: bool
    reason: str = ""


def human_size(n: int | None) -> str:
    if n is None:
        return "? MB"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def _plain(html: str) -> str:
    import html as html_mod
    import re
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(text).strip()


def sort_options(files: list[FileOption]) -> list[FileOption]:
    return sorted(files, key=lambda f: (_ORDER.get(f.category, 9), not f.is_primary, -f.uploaded))


def visible_options(files: list[FileOption], include_old: bool = False) -> list[FileOption]:
    """What the user is offered. Old and archived files only if asked for."""
    cats = CURRENT + ((OLD, ARCHIVED) if include_old else ())
    return [f for f in sort_options(files) if f.category in cats]


def primary_file(files: list[FileOption]) -> FileOption | None:
    current = [f for f in files if f.category in CURRENT]
    for pool in (
        [f for f in current if f.is_primary],
        [f for f in current if f.category == MAIN],
        current,
    ):
        if pool:
            return max(pool, key=lambda f: f.uploaded)
    return None


def choose(entry: ListEntry, files: list[FileOption], remembered: list[int] | None = None) -> Choice:
    """Pick files for a mod from its list line, a saved earlier choice, or ask."""
    by_id = {f.file_id: f for f in files}
    rule: Rule = entry.rule

    if rule.mode == "skip":
        return Choice([], False, "skipped in the list")

    # 1. Exact files: from the link itself (file_id=, nxm://) or file= in the rule.
    wanted = list(dict.fromkeys(entry.file_ids + rule.file_ids))
    if wanted:
        found = [fid for fid in wanted if fid in by_id]
        missing = [fid for fid in wanted if fid not in by_id]
        if found and not missing:
            return Choice(found, rule.mode == "ask", "file picked in the list")
        if found:
            return Choice(found, True, f"file {', '.join(map(str, missing))} isn't on Nexus any more")
        # The linked file was removed (often replaced by a newer version).
        fallback = primary_file(files)
        return Choice([fallback.file_id] if fallback else [], True,
                      "the linked file isn't on Nexus any more - pick its replacement")

    current = [f for f in sort_options(files) if f.category in CURRENT]
    if not current:
        return Choice([], True, "no current files on the Files tab")

    # 2. Name matches, e.g. "| match=2K".
    if rule.match:
        needles = [m.lower() for m in rule.match]
        hits = [f.file_id for f in current
                if any(n in f.name.lower() or n in f.file_name.lower() for n in needles)]
        if hits:
            return Choice(hits, rule.mode == "ask", "matched by name")
        fallback = primary_file(files)
        return Choice([fallback.file_id] if fallback else [], True,
                      f"no file name has {', '.join(rule.match)!s} in it")

    # 3. A choice the user made on an earlier run.
    if remembered and (rule.mode == "ask" or (rule.mode == "auto" and len(current) > 1)):
        still_there = [fid for fid in remembered if fid in by_id]
        if still_there and len(still_there) == len(remembered):
            return Choice(still_there, rule.mode == "ask", "your earlier choice")

    if rule.mode == "main":
        mains = [f.file_id for f in current if f.category == MAIN] or [current[0].file_id]
        return Choice(mains, False, "all main files")
    if rule.mode == "all":
        return Choice([f.file_id for f in current], False, "all current files")

    best = primary_file(files)
    selected = [best.file_id] if best else []
    if rule.mode == "primary":
        return Choice(selected, False, "primary file")
    if rule.mode == "ask":
        return Choice(selected, True, "you asked to choose")
    # auto: ask only when there is a real choice to make.
    if len(current) == 1:
        return Choice(selected, False, "only one file")
    return Choice(selected, True, f"{len(current)} files to choose from")
