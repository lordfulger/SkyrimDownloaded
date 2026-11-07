"""Read a mod list: Nexus links, nxm:// links or bare mod IDs, one per line.

A line looks like::

    https://www.nexusmods.com/skyrimspecialedition/mods/266   | primary   # SkyUI
    https://www.nexusmods.com/skyrimspecialedition/mods/12604?tab=files&file_id=123
    nxm://skyrimspecialedition/mods/17230/files/456789
    32444 | match=2K

Anything after ``#`` (when it starts a line or follows a space) is a comment.
Anything after ``|`` is a list of choices for that line (see ``Rule``).
Lines without a link are ignored, so a guide pasted straight from a web page
works too: every Nexus link in it is picked up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

DEFAULT_GAME = "skyrimspecialedition"  # Skyrim Special / Anniversary Edition

_NEXUS_URL = re.compile(
    r"https?://(?:www\.|next\.)?nexusmods\.com/(?:games/)?"
    r"(?P<game>[a-z0-9]+)/mods/(?P<mod>\d+)(?P<rest>[^\s<>\"'|)\]]*)",
    re.IGNORECASE,
)
_NXM_URL = re.compile(
    r"nxm://(?P<game>[a-z0-9]+)/mods/(?P<mod>\d+)/files/(?P<file>\d+)"
    r"(?:\?(?P<query>[^\s<>\"'|)\]]*))?",
    re.IGNORECASE,
)
_BARE_ID = re.compile(r"^\s*(?P<mod>\d+)\s*$")
_COMMENT = re.compile(r"(^|\s)#.*$")


class ListError(ValueError):
    pass


@dataclass
class Rule:
    """How to pick files from a mod's Files tab.

    ``mode`` is one of:

    * ``auto``    - no choice given: take the only file, or ask when there are options
    * ``ask``     - always show the options, even if there is only one file
    * ``primary`` - just the primary main file, never ask
    * ``main``    - every main file
    * ``all``     - every main, update, optional and miscellaneous file
    * ``skip``    - leave this mod out

    ``file_ids`` and ``match`` pick exact files and win over ``mode``.
    """

    mode: str = "auto"
    file_ids: list[int] = field(default_factory=list)
    match: list[str] = field(default_factory=list)

    MODES = ("auto", "ask", "primary", "main", "all", "skip")

    @classmethod
    def parse(cls, text: str) -> "Rule":
        rule = cls()
        for token in re.split(r"[,\s]+(?=[a-z]+(?:=|$|[,\s]))", text.strip(), flags=re.I):
            token = token.strip().strip(",")
            if not token:
                continue
            key, _, value = token.partition("=")
            key = key.strip().lower()
            value = value.strip().strip('"').strip("'")
            if key in cls.MODES and not value:
                rule.mode = key
            elif key in ("file", "files", "file_id", "id"):
                for part in re.split(r"[,\s]+", value):
                    if part.isdigit():
                        rule.file_ids.append(int(part))
                    elif part:
                        raise ListError(f"file= wants file numbers, got {part!r}")
            elif key == "match" and value:
                rule.match.append(value)
            else:
                raise ListError(
                    f"unknown choice {token!r} (use ask, primary, main, all, skip, "
                    "file=<id> or match=<text>)"
                )
        return rule

    def describe(self) -> str:
        bits = []
        if self.mode != "auto":
            bits.append(self.mode)
        if self.file_ids:
            bits.append("file=" + ",".join(map(str, self.file_ids)))
        bits += [f"match={m}" for m in self.match]
        return " ".join(bits) or "auto"


@dataclass
class ListEntry:
    game: str
    mod_id: int
    file_ids: list[int] = field(default_factory=list)
    rule: Rule = field(default_factory=Rule)
    note: str = ""            # the comment on the line, shown next to the mod
    line_no: int = 0
    nxm_key: str | None = None   # from an nxm:// link clicked on the site
    nxm_expires: int | None = None

    @property
    def key(self) -> str:
        return f"{self.game}/{self.mod_id}"

    @property
    def page_url(self) -> str:
        return f"https://www.nexusmods.com/{self.game}/mods/{self.mod_id}"


def _file_ids_from_query(rest: str) -> list[int]:
    if "?" not in rest:
        return []
    query = parse_qs(urlsplit("x://y" + rest[rest.index("?"):]).query)
    ids = []
    for name in ("file_id", "fileid", "id"):
        for value in query.get(name, []):
            if value.isdigit():
                ids.append(int(value))
    return ids


def parse_line(line: str, line_no: int = 0, default_game: str = DEFAULT_GAME) -> list[ListEntry]:
    comment_match = _COMMENT.search(line)
    note = ""
    if comment_match:
        note = comment_match.group(0).strip().lstrip("#").strip()
        line = line[: comment_match.start()]
    link_part, bar, rule_part = line.partition("|")
    rule = Rule.parse(rule_part) if bar else Rule()

    entries: list[ListEntry] = []
    taken: list[tuple[int, int]] = []
    for m in _NXM_URL.finditer(link_part):
        taken.append(m.span())
        query = parse_qs(m.group("query") or "")
        expires = (query.get("expires") or [None])[0]
        entries.append(ListEntry(
            game=m.group("game").lower(), mod_id=int(m.group("mod")),
            file_ids=[int(m.group("file"))], rule=rule, note=note, line_no=line_no,
            nxm_key=(query.get("key") or [None])[0],
            nxm_expires=int(expires) if expires and expires.isdigit() else None,
        ))
    for m in _NEXUS_URL.finditer(link_part):
        if any(a <= m.start() < b for a, b in taken):
            continue
        entries.append(ListEntry(
            game=m.group("game").lower(), mod_id=int(m.group("mod")),
            file_ids=_file_ids_from_query(m.group("rest")), rule=rule,
            note=note, line_no=line_no,
        ))
    if not entries:
        bare = _BARE_ID.match(link_part)
        if bare:
            entries.append(ListEntry(game=default_game, mod_id=int(bare.group("mod")),
                                     rule=rule, note=note, line_no=line_no))
        elif bar and link_part.strip():
            raise ListError(f"line {line_no}: no Nexus link or mod number before '|'")
    return entries


def parse_list(text: str, default_game: str = DEFAULT_GAME) -> tuple[list[ListEntry], list[str]]:
    """Return the entries in list order (same mod twice is merged) and any problems."""
    merged: dict[str, ListEntry] = {}
    problems: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        try:
            found = parse_line(line, line_no, default_game)
        except ListError as err:
            msg = str(err)
            problems.append(msg if msg.startswith("line ") else f"line {line_no}: {msg}")
            continue
        for entry in found:
            old = merged.get(entry.key)
            if old is None:
                merged[entry.key] = entry
                continue
            # Same mod again: keep the first spot in the list, add any extra files.
            for fid in entry.file_ids:
                if fid not in old.file_ids:
                    old.file_ids.append(fid)
            if entry.rule.mode != "auto" or entry.rule.file_ids or entry.rule.match:
                old.rule = entry.rule
            old.note = old.note or entry.note
            old.nxm_key = old.nxm_key or entry.nxm_key
            old.nxm_expires = old.nxm_expires or entry.nxm_expires
    return list(merged.values()), problems
