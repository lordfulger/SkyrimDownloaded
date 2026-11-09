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

import copy
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

DEFAULT_GAME = "skyrimspecialedition"  # Skyrim Special / Anniversary Edition

_NEXUS_URL = re.compile(
    r"(?:https?://|(?<![\w./-]))(?:www\.|next\.)?nexusmods\.com/(?:games/)?"  # "https://" may be left off
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


# "## 02 - ENGINE, SKSE LIBRARIES" starts a section (an MO2 separator). "#!" lines are settings.
_SECTION = re.compile(r"^\s*##(?!#)\s*(.*?\S)\s*#*\s*$")


_LINKISH = re.compile(r"nexusmods\.com/|nxm://", re.I)


class ListError(ValueError):
    pass


_MODE = r"(?:ask|primary|main|all|skip|auto)"
_KEY_EQ = r"(?:files?|file_id|id|match)\s*="
# Where one choice ends: a comma, the end, or another choice coming up
# (a choice word only counts when something choice-like follows it).
_NEXT = (r"(?:" + _KEY_EQ + r"|" + _MODE + r"(?:\s*(?:,|$)|\s+(?:" + _KEY_EQ + r"|" + _MODE + r")))")
_RULE_TOKEN = re.compile(
    r"[\s,]*(?P<key>[a-z_]+)"
    r"(?:\s*=\s*(?P<value>\"[^\"]*\"|'[^']*'|\d+(?:\s*,\s*\d+)+|[^,\"']*?))?"
    r"(?=\s*,|\s+" + _NEXT + r"|\s*$)",
    re.IGNORECASE,
)


def _rule_tokens(text: str):
    """Split "match=Pretty Textures 2K, file=12" into (key, value, token) parts.

    Values may contain spaces; quote them if they contain a choice word
    (``match="All in one"``).
    """
    pos, text = 0, text.strip()
    while pos < len(text):
        m = _RULE_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            rest = text[pos:].strip(" ,")
            if rest:
                raise ListError(f"can't read the choice {rest!r}")
            return
        value = (m.group("value") or "").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        yield m.group("key").lower(), value, m.group(0).strip(" ,")
        pos = m.end()


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
        for key, value, token in _rule_tokens(text):
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
    section: str = ""          # the "## Heading" it's under (an MO2 separator)
    from_number: bool = field(default=False, repr=False, compare=False)  # a bare "12604" line

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
    # Choices come after a "|" that follows the links ("| SkyUI | https://... | Required |" from a
    # pasted table has bars before the link too).
    ends = [m.end() for rx in (_NXM_URL, _NEXUS_URL) for m in rx.finditer(line)]
    cut = line.find("|", max(ends)) if ends else line.find("|")
    if cut >= 0:
        link_part, bar, rule_part = line[:cut], "|", line[cut + 1:]
    else:
        link_part, bar, rule_part = line, "", ""
    starts = [m.start() for rx in (_NXM_URL, _NEXUS_URL) for m in rx.finditer(line)]
    table_row = bool(starts) and "|" in line[:min(starts)]  # a row pasted from a table: other columns
    if bar and table_row:
        try:
            rule = Rule.parse(rule_part)
        except ListError:
            rule = Rule()  # "| Required |" etc. are just the table's other columns
    else:
        rule = Rule.parse(rule_part) if bar else Rule()

    entries: list[ListEntry] = []
    taken: list[tuple[int, int]] = []
    for m in _NXM_URL.finditer(link_part):
        taken.append(m.span())
        query = parse_qs(m.group("query") or "")
        expires = (query.get("expires") or [None])[0]
        entries.append(ListEntry(
            game=m.group("game").lower(), mod_id=int(m.group("mod")),
            file_ids=[int(m.group("file"))], rule=copy.deepcopy(rule), note=note, line_no=line_no,
            nxm_key=(query.get("key") or [None])[0],
            nxm_expires=int(expires) if expires and expires.isdigit() else None,
        ))
    for m in _NEXUS_URL.finditer(link_part):
        if any(a <= m.start() < b for a, b in taken):
            continue
        entries.append(ListEntry(
            game=m.group("game").lower(), mod_id=int(m.group("mod")),
            file_ids=_file_ids_from_query(m.group("rest")), rule=copy.deepcopy(rule),
            note=note, line_no=line_no,
        ))
    if not entries:
        bare = _BARE_ID.match(link_part)
        if bare:
            entries.append(ListEntry(game=default_game, mod_id=int(bare.group("mod")),
                                     rule=rule, note=note, line_no=line_no, from_number=True))
        elif bar and link_part.strip():
            raise ListError(f"line {line_no}: no Nexus link or mod number before '|'")
    return entries


def parse_list(text: str, default_game: str = DEFAULT_GAME) -> tuple[list[ListEntry], list[str]]:
    """Return the entries in list order (same mod twice is merged) and any problems."""
    merged: dict[str, ListEntry] = {}
    problems: list[str] = []
    section = ""
    for line_no, line in enumerate(text.splitlines(), start=1):
        heading = _SECTION.match(line)
        if heading and not _LINKISH.search(line):  # "## https://..." is a link commented out, not a heading
            section = heading.group(1).strip()
            continue
        try:
            found = parse_line(line, line_no, default_game)
        except ListError as err:
            msg = str(err)
            problems.append(msg if msg.startswith("line ") else f"line {line_no}: {msg}")
            continue
        for entry in found:
            entry.section = section
            old = merged.get(entry.key)
            if old is None:
                merged[entry.key] = entry
                continue
            # Same mod again: keep the first spot in the list, add any extra files.
            for fid in entry.file_ids:
                if fid not in old.file_ids:
                    old.file_ids.append(fid)
            if old.rule.file_ids and entry.rule.file_ids:  # file=1 on one line, file=2 on another: both
                old.rule.file_ids = old.rule.file_ids + [f for f in entry.rule.file_ids
                                                         if f not in old.rule.file_ids]
            elif entry.rule.mode != "auto" or entry.rule.file_ids or entry.rule.match:
                old.rule = entry.rule
            old.note = old.note or entry.note
            old.nxm_key = old.nxm_key or entry.nxm_key
            old.nxm_expires = old.nxm_expires or entry.nxm_expires
    # A bare number among links is often a step number or a year from a pasted guide.
    links = sum(1 for e in merged.values() if not e.from_number)
    if links >= 3:
        for e in merged.values():
            if e.from_number:
                problems.append(f"line {e.line_no}: just a number, read as mod {e.mod_id} - if that's not "
                                "a mod number, delete the line or put # in front of it")
    return list(merged.values()), problems
