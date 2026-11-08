"""Which mods in the list refer to each other.

Looks at three places for each mod:

* its **requirements** on Nexus (mod A needs mod B)
* its **files**: a file whose name mentions another mod in the list (or whose
  description calls itself a patch for it) is a compatibility patch you
  probably want, e.g. "USSEP patch" when USSEP is in the list
* its **page description**: "incompatible with X", "patch for X",
  "requires X", or just a mention, where X is another mod in the list

Mods are recognised by their name (and short forms such as "USSEP" for the
Unofficial Skyrim Special Edition Patch) or by a link to their Nexus page.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .text import bbcode_to_text, nexus_mod_ids

NEEDS, PATCH, CONFLICT, WORKS_WITH, MENTIONS = "needs", "patch", "conflict", "works with", "mentions"
DLC = "dlc"
ORDER = {CONFLICT: 0, PATCH: 1, NEEDS: 2, DLC: 3, WORKS_WITH: 4, MENTIONS: 5}
HEADINGS = {
    CONFLICT: "Possible conflicts",
    PATCH: "Patches for other mods in your list",
    NEEDS: "Mods that rely on other mods in your list",
    DLC: "Game content needed (DLC / Creations) - make sure you have it",
    WORKS_WITH: "Said to work with",
    MENTIONS: "Also mentioned on mod pages",
}

_GENERIC = {
    "patch", "patches", "main", "main file", "textures", "texture", "mod", "mods", "fix", "fixes",
    "update", "skyrim", "special edition", "anniversary edition", "skyrim special edition", "se",
    "sse", "ae", "plugin", "core", "framework", "optional", "addon", "add-on", "files", "esp",
    "esm", "esl", "lite", "light", "hd", "remastered", "overhaul", "tweaks", "redone", "enhanced",
    "skse", "skse64", "papyrus", "settings", "config", "presets", "preset", "compatibility",
    "unofficial", "immersive", "realistic", "complete", "ultimate", "simple", "better",
}
_SUFFIX = re.compile(
    r"\s*(?:[-–:|]\s*)?\(?\b(?:SSE|SE|AE|Special Edition|Anniversary Edition|for SSE|for SE|"
    r"SKSE64?|SKSE plugin|Legendary Edition|LE)\b\)?\s*$", re.I)
_CONFLICT = re.compile(
    r"(?<!no )(?<!any )(?:incompatib\w*|not compatible|isn'?t compatible|doesn'?t work with|"
    r"does not work with|won'?t work with|will not work with|do not use (?:this |it )?with|"
    r"don'?t use (?:this |it )?with|conflicts? with)", re.I)
_REQUIRES = re.compile(r"requires?|required|requirements?|needs|dependenc\w*|depends on|you need|must have", re.I)
_PATCHY = re.compile(r"patch|compatib\w*|integrat\w*|support\w*|add-?on|for users of|if you use", re.I)
_WORKS = re.compile(r"compatible with|works (?:fine |well )?with|work together", re.I)


@dataclass
class Finding:
    kind: str
    plan: object          # ModPlan doing the referring
    other: object         # ModPlan it refers to
    text: str
    file_id: int | None = None
    evidence: str = ""

    @property
    def key(self):
        return (self.kind, id(self.plan), id(self.other), self.file_id)


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    requirements_checked: bool = False

    def by_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    def plans_to_review(self) -> list:
        """Mods worth another look: ones with patches to pick or possible conflicts."""
        out = []
        for f in self.findings:
            if f.kind in (PATCH, CONFLICT):
                for p in (f.plan,) if f.kind == PATCH else (f.plan, f.other):
                    if p not in out:
                        out.append(p)
        return out

    def suggestions(self) -> dict[int, dict[int, str]]:
        """{id(plan): {file_id: why}} for patch files."""
        out: dict[int, dict[int, str]] = {}
        for f in self.by_kind(PATCH):
            out.setdefault(id(f.plan), {})[f.file_id] = f"for {f.other.title}, which is in your list"
        return out

    def warnings(self) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        for f in self.findings:
            if f.kind == CONFLICT:
                out.setdefault(id(f.plan), []).append(f"may conflict with {f.other.title}")
                out.setdefault(id(f.other), []).append(f"{f.plan.title}'s page says it may conflict with this")
            elif f.kind == NEEDS:
                out.setdefault(id(f.plan), []).append(f"needs {f.other.title}")
            elif f.kind == DLC:
                out.setdefault(id(f.plan), []).append(f"needs {f.evidence or 'game content'}")
        return out

    def notes_for(self, plan) -> list[str]:
        return [f.text for f in self.findings
                if f.plan is plan or (f.other is plan and f.kind != DLC)]


# -- recognising mods by name ---------------------------------------------------

def aliases(name: str) -> list[tuple[str, bool]]:
    """Ways a mod may be referred to: (text, case_sensitive)."""
    out: list[tuple[str, bool]] = []
    name = re.sub(r"\s+", " ", name or "").strip()
    base = re.split(r"\s+[-–|:]\s+|\s*[(\[]", name)[0].strip()
    for variant in (name, base, _SUFFIX.sub("", base).strip(), _SUFFIX.sub("", name).strip()):
        v = variant.strip(" -:")
        if not v or v.lower() in _GENERIC:
            continue
        if len(v) < 5 and " " not in v:
            # short single words ("Ordinator" is fine, "Wet" is not)
            if not (len(v) >= 4 and re.search(r"[A-Z].*[A-Z]|\d", v)):
                continue
        if (v, False) not in out:
            out.append((v, False))
    # Acronym: "Unofficial Skyrim Special Edition Patch" -> USSEP
    words = re.findall(r"[A-Za-z][A-Za-z']*", base)
    caps = [w for w in words if w[0].isupper()]
    if len(caps) >= 3 and len(caps) == len(words):
        acronym = "".join(w[0] for w in caps).upper()
        if len(acronym) >= 4 and acronym.lower() not in _GENERIC:
            out.append((acronym, True))
    return out


def _patterns(name: str) -> list[re.Pattern]:
    pats = []
    for text, case_sensitive in aliases(name):
        body = r"\s+".join(re.escape(w) for w in text.split())
        pats.append(re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])",
                               0 if case_sensitive else re.I))
    return pats


def _mentions(text: str, pats: list[re.Pattern], link_ids: set[int], mod_id: int) -> list[int]:
    """Where in ``text`` a mod is mentioned (by name, or by a link to its page)."""
    spots = [m.start() for p in pats for m in p.finditer(text)]
    if mod_id in link_ids:
        for m in re.finditer(r"/mods/" + str(mod_id) + r"(?!\d)", text):
            spots.append(m.start())
    return sorted(spots)


def _context(text: str, at: int, width: int = 90) -> tuple[str, str]:
    """The sentence-ish bits before and after a spot."""
    before = text[max(0, at - width):at]
    after = text[at:at + width]
    before = re.split(r"[.!?\n]\s", before)[-1]
    after = re.split(r"[.!?\n]\s", after)[0]
    return before, after


def _snippet(text: str, at: int) -> str:
    before, after = _context(text, at, 70)
    return re.sub(r"\s+", " ", (before + after)).strip()


# -- the check -------------------------------------------------------------------

def check(plans, client=None, *, workers: int = 4) -> Report:
    from .selection import CURRENT

    active = [p for p in plans if getattr(p, "mod", None) and not p.error and not p.skipped]
    report = Report()
    if not active:
        return report
    pats = {id(p): _patterns(p.mod.name) for p in active}
    by_mod = {(p.entry.game, p.entry.mod_id): p for p in active}
    seen: set = set()

    def add(f: Finding) -> None:
        if f.key not in seen and (f.plan is not f.other or f.kind == DLC):
            seen.add(f.key)
            report.findings.append(f)

    # 1. Requirements listed on Nexus.
    if client is not None:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            reqs = list(pool.map(lambda p: client.requirements(p.entry.game, p.entry.mod_id), active))
        for plan, req_list in zip(active, reqs):
            if req_list is None:
                continue
            report.requirements_checked = True
            for req in req_list:
                if getattr(req, "dlc", False):
                    note = f" ({req.notes})" if req.notes else ""
                    f = Finding(DLC, plan, plan, f"{plan.title} needs {req.name}{note}", evidence=req.name)
                    f.file_id = hash(req.name) & 0xFFFF  # one finding per DLC
                    add(f)
                    continue
                other = by_mod.get((plan.entry.game, req.mod_id)) if req.mod_id else None
                if other:
                    note = f" ({req.notes})" if req.notes else ""
                    add(Finding(NEEDS, plan, other, f"{plan.title} needs {other.title}{note}",
                                evidence="listed as a requirement on Nexus"))

    for plan in active:
        game = plan.entry.game
        # 2. Files on this mod's Files tab that are for another mod in the list.
        for opt in plan.options:
            if opt.category not in CURRENT or opt.fit.hidden:
                continue
            raw_desc = str(opt.raw.get("description") or "")
            ids = nexus_mod_ids(raw_desc, game)
            for other in active:
                if other is plan:
                    continue
                o_pats = pats[id(other)]
                in_name = _mentions(f"{opt.name} {opt.file_name}", o_pats, set(), other.entry.mod_id)
                if in_name and _mentions(plan.mod.name, o_pats, set(), other.entry.mod_id):
                    # e.g. "Better Container Controls for SkyUI": every file says SkyUI because
                    # the mod itself is for SkyUI - that doesn't make them patches.
                    in_name = []
                desc_spots = _mentions(opt.description, o_pats, ids, other.entry.mod_id)
                patchy = any(_PATCHY.search("".join(_context(opt.description, s))) for s in desc_spots)
                if not in_name and not (other.entry.mod_id in ids or patchy):
                    continue
                if not in_name and desc_spots and all(
                        _REQUIRES.search(_context(opt.description, s)[0]) for s in desc_spots):
                    continue  # "requires X": a requirement, not a patch
                where = "its name" if in_name else "its description"
                add(Finding(PATCH, plan, other,
                            f"{plan.title}: \"{opt.name}\" is for {other.title} ({where})",
                            file_id=opt.file_id,
                            evidence=_snippet(opt.description, desc_spots[0]) if desc_spots and not in_name else opt.name))

        # 3. The mod's page.
        raw = str((plan.mod.raw or {}).get("description") or "")
        if not raw:
            continue
        page = bbcode_to_text(raw, keep_links=True)
        ids = nexus_mod_ids(raw, game)
        for other in active:
            if other is plan:
                continue
            spots = _mentions(page, pats[id(other)], ids, other.entry.mod_id)
            if not spots:
                continue
            kind, at = MENTIONS, spots[0]
            for s in spots:
                before, after = _context(page, s)
                window = before + after
                if _CONFLICT.search(window):
                    kind, at = CONFLICT, s
                    break
                if _REQUIRES.search(before) and ORDER[NEEDS] < ORDER[kind]:
                    kind, at = NEEDS, s
                elif _WORKS.search(window) and ORDER[WORKS_WITH] < ORDER[kind]:
                    kind, at = WORKS_WITH, s
            text = {
                CONFLICT: f"{plan.title}'s page may say it conflicts with {other.title}",
                NEEDS: f"{plan.title}'s page says it needs {other.title}",
                WORKS_WITH: f"{plan.title}'s page says it works with {other.title}",
                MENTIONS: f"{plan.title}'s page mentions {other.title}",
            }[kind]
            if kind == NEEDS and any(f.kind == NEEDS and f.plan is plan and f.other is other
                                     for f in report.findings):
                continue
            add(Finding(kind, plan, other, text, evidence=_snippet(page, at)))

    report.findings.sort(key=lambda f: (ORDER[f.kind], f.plan.title.lower()))
    return report


_NOT_FOR_AUTO = re.compile(r"\b(?:legacy|outdated|deprecated|obsolete|old(?:er)? versions?|beta|alpha|"
                           r"test(?:ing)?|experimental|wip|dev(?:elopment)? build)\b", re.I)


def patches_to_tick(report, skip=lambda plan, file_id: False) -> list:
    """The patch files worth ticking by themselves: (plan, file_id) pairs.

    Careful on purpose:
    * only files in a mod's Main / Optional / Misc sections (never "Updates"), for your
      game version, and not called beta / legacy / outdated / test...;
    * one file per mod it's for - when a mod has several patches for the same other
      mod (v1.0, v1.2...), only the newest; none if you already picked one yourself;
    * ``skip`` says no for ones you unticked before.
    """
    from .selection import MAIN, MISC, OPTIONAL, siblings, variant_score
    best: dict = {}
    for f in report.by_kind(PATCH):
        plan, fid = f.plan, f.file_id
        opt = plan.option(fid) if hasattr(plan, "option") else None
        if (opt is None or plan.error or plan.skipped or fid in plan.selected or skip(plan, fid)
                or opt.category not in (MAIN, OPTIONAL, MISC) or opt.fit.hidden
                or _NOT_FOR_AUTO.search(f"{opt.name} {opt.file_name}")):
            continue
        if any(s.file_id in plan.selected for s in siblings(opt, plan.options)):
            continue  # a variant of it (ESL / packed / loose) is already ticked
        key = (id(plan), id(f.other))
        if key in best and (variant_score(best[key][1]), best[key][1].uploaded) >= (variant_score(opt), opt.uploaded):
            continue
        best[key] = (plan, opt, f.other)
    picks = []
    for plan, opt, other in best.values():
        # Already picked a patch for that mod yourself? Leave it be.
        mine = [o for o in plan.selected_options()
                if any(g.kind == PATCH and g.plan is plan and g.other is other and g.file_id == o.file_id
                       for g in report.findings)]
        if not mine:
            picks.append((plan, opt.file_id))
    return picks
