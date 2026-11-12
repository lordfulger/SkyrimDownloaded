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
    NEEDS: "Mods that require other mods in your list",
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
    r"don'?t use (?:this |it )?with|conflicts? with)(?!out)", re.I)
_REQUIRES = re.compile(r"requires?|required|requirements?|needs|dependenc\w*|depends on|you need|must have", re.I)
_PATCHY = re.compile(r"patch|compatib\w*|integrat\w*|support\w*|add-?on|for users of|if you use", re.I)
_TRAILING_VERSION = re.compile(r"\s+v?\d+(?:\.\d+)*[a-z]?\s*$", re.I)
_WORKS = re.compile(r"compatible with|works (?:fine |well )?with|work together", re.I)


_OPTIONAL = re.compile(r"\b(?:optional(?:ly)?|compatib\w*|patch\w*|only (?:if|needed|for|when|with)|"
                       r"if you (?:use|want|have)|for (?:users of|those)|not required|recommended|"
                       r"addon|add-on)\b", re.I)


def optional_note(notes: str | None) -> bool:
    """A requirement whose note says it's optional ("Optional Abandoned Prison compatible
    file", "Compatibility patch", "only if you use X"): not something the mod can't do without."""
    return bool(notes and _OPTIONAL.search(notes))


class ModWarning(str):
    """A warning like "needs X": plain text, plus the mod's name and page for a link."""

    def __new__(cls, before: str, name: str, url: str = "", after: str = "", other=None, quote: str = ""):
        text = " ".join(t for t in (before, name) if t) + after
        self = super().__new__(cls, text)
        self.before, self.name, self.url, self.after = before, name, url, after
        self.other = other  # the mod (ModPlan) it's about, when it's in the list
        self.quote = quote  # the words on the page it's based on
        return self


def _page(plan) -> str:
    try:
        return plan.entry.page_url
    except AttributeError:
        return ""


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

    def warnings(self) -> dict[int, list["ModWarning"]]:
        """Short warnings per mod (id(plan)). Each is text, and also carries the name
        and page of the mod it's about, so it can be shown as a link."""
        out: dict[int, list[ModWarning]] = {}
        for f in self.findings:
            if f.kind == CONFLICT:
                out.setdefault(id(f.plan), []).append(ModWarning("may conflict with", f.other.title, _page(f.other), other=f.other,
                                                                     quote=f.evidence))
                out.setdefault(id(f.other), []).append(
                    ModWarning("", f.plan.title, _page(f.plan), "'s page says it may conflict with this",
                               other=f.plan, quote=f.evidence))
            elif f.kind == NEEDS:
                out.setdefault(id(f.plan), []).append(ModWarning("requires", f.other.title, _page(f.other), " (in your list)", other=f.other))
            elif f.kind == DLC:
                out.setdefault(id(f.plan), []).append(ModWarning("requires", f.evidence or "game content", ""))
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
    variants = [name, base, _SUFFIX.sub("", base).strip(), _SUFFIX.sub("", name).strip()]
    for v in list(variants):  # "DynDOLOD 3", "SkyUI 5.2", "Mod SE v2" -> without the number
        bare = _SUFFIX.sub("", _TRAILING_VERSION.sub("", v)).strip()
        if bare and bare != v:
            variants.append(bare)
    for variant in variants:
        v = variant.strip(" -:")
        if not v or v.lower() in _GENERIC:
            continue
        if len(v) < 5 and " " not in v:
            # short single words ("Ordinator" is fine, "Wet" is not)
            if not (len(v) >= 4 and re.search(r"[A-Z].*[A-Z]|\d", v)):
                continue
        # One word ("Still", "Apothecary") is only the mod when written like its name: "still"
        # in a sentence isn't the music mod.
        single = " " not in v
        if (v, single) not in out:
            out.append((v, single))
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


_CLAUSE = re.compile(r"[;\u2022|]|:\s|\s[-\u2013]\s|,\s(?:but|while)\s|\bbut\b|\bwhile\b|\bhowever\b", re.I)
# "conflicts with other mods that edit X": general advice, not about X
_GENERAL = re.compile(r"\b(?:other|any|anything|everything|some|mods? that|which|that edit|that change)\b", re.I)
_AFTER_CONFLICT = re.compile(r"^\S[^.;:]{0,60}?\b(?:is|are|isn'?t|aren'?t|will be)\s+(?:not compatible|incompatible)|"
                             r"^\S[^.;:]{0,60}?(?<!no )(?<!any )(?<!without )(?<!zero )\bconflicts?\b", re.I)


def _conflict_about(before: str, after: str) -> bool:
    """The conflict words are about this mention: "incompatible with X", "X is not compatible"
    - in the same part of the sentence, not "Conflicts with Y; works fine with X"."""
    url = re.compile(r"\(?\s*https?://\S*|\S*/mods/\d+\)?")  # a link to the mod stands for its name
    before, after = url.sub(" ", before), url.sub(" ", after)
    clause = _CLAUSE.split(before)[-1]
    m = None
    for m in _CONFLICT.finditer(clause):
        pass
    if m is not None and len(clause) - m.end() <= 40 and not _GENERAL.search(clause[m.end():]):
        return True
    rest = _CLAUSE.split(after)[0]
    return bool(_AFTER_CONFLICT.search(rest))


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
    # Word index: a mod can only be named in a text that has the first word of one of its names.
    # Checking just those keeps this fast for lists of hundreds of mods.
    first_words: dict[str, set] = {}
    alias_words: dict[int, list] = {}  # id(plan): [set of words of each name]
    always: list = []
    for p in active:
        sets = []
        for text, _ in aliases(p.mod.name):
            words = re.findall(r"[a-z0-9]+", text.lower())
            if not words:
                sets = None
                break
            sets.append(set(words))
        if not sets:
            always.append(p)
            continue
        alias_words[id(p)] = sets
        for ws in sets:
            first_words.setdefault(min(ws), set()).add(id(p))
    order = {id(p): i for i, p in enumerate(active)}

    def could_mention(*texts, ids=frozenset()):
        """The mods (in list order) a text could name or link to: all the words of one of
        their names are in it (or it links to their page)."""
        tokens = set()
        for text in texts:
            tokens |= set(re.findall(r"[a-z0-9]+", (text or "").lower()))
        hit = {id(p) for p in always}
        for word in tokens:
            for pid in first_words.get(word, ()):
                if pid not in hit and any(ws <= tokens for ws in alias_words[pid]):
                    hit.add(pid)
        hit |= {id(p) for p in active if p.entry.mod_id in ids}
        return sorted((p for p in active if id(p) in hit), key=lambda p: order[id(p)])
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
                    f = Finding(DLC, plan, plan, f"{plan.title} requires {req.name}{note}", evidence=req.name)
                    f.file_id = hash(req.name) & 0xFFFF  # one finding per DLC
                    add(f)
                    continue
                other = by_mod.get((plan.entry.game, req.mod_id)) if req.mod_id else None
                if other:
                    note = f" ({req.notes})" if req.notes else ""
                    if optional_note(req.notes):  # "Optional ... compatible file": not really required
                        add(Finding(WORKS_WITH, plan, other, f"{plan.title} has optional files for {other.title}{note}",
                                    evidence="listed on Nexus as optional"))
                    else:
                        add(Finding(NEEDS, plan, other, f"{plan.title} requires {other.title}{note}",
                                    evidence="listed as a requirement on Nexus"))

    for plan in active:
        game = plan.entry.game
        # 2. Files on this mod's Files tab that are for another mod in the list.
        for opt in plan.options:
            if opt.category not in CURRENT or opt.fit.hidden:
                continue
            raw_desc = str(opt.raw.get("description") or "")
            ids = nexus_mod_ids(raw_desc, game)
            for other in could_mention(opt.name, opt.file_name, opt.description, ids=ids):
                if other is plan:
                    continue
                o_pats = pats[id(other)]
                in_name = _mentions(f"{opt.name} {opt.file_name}", o_pats, set(), other.entry.mod_id)
                if in_name and _mentions(plan.mod.name, o_pats, set(), other.entry.mod_id):
                    # e.g. "Better Container Controls for SkyUI": every file says SkyUI because
                    # the mod itself is for SkyUI - that doesn't make them patches.
                    in_name = []
                desc_spots = _mentions(opt.description, o_pats, ids, other.entry.mod_id)
                patchy = any(_PATCHY.search(ctx) and not _WORKS.search(ctx)  # "compatible with X" isn't a patch
                             for ctx in ("".join(_context(opt.description, s)) for s in desc_spots))
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
        own = {a.lower() for a, _ in aliases(plan.mod.name)}
        for other in could_mention(page, ids=ids):
            if other is plan:
                continue
            if own & {a.lower() for a, _ in aliases(other.mod.name)} and other.entry.mod_id not in ids:
                continue  # "Apothecary" on Apothecary's page is about itself, not "Apothecary - Patches"
            spots = _mentions(page, pats[id(other)], ids, other.entry.mod_id)
            if not spots:
                continue
            kind, at = MENTIONS, spots[0]
            for s in spots:
                before, after = _context(page, s)
                window = before + after
                if _conflict_about(before, after):
                    kind, at = CONFLICT, s
                    break
                if _REQUIRES.search(before) and ORDER[NEEDS] < ORDER[kind]:
                    kind, at = NEEDS, s
                elif _WORKS.search(window) and ORDER[WORKS_WITH] < ORDER[kind]:
                    kind, at = WORKS_WITH, s
            text = {
                CONFLICT: f"{plan.title}'s page may say it conflicts with {other.title}",
                NEEDS: f"{plan.title}'s page says it requires {other.title}",
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


_ALT_MAIN = re.compile(r"\b(?:version|edition|variant|only if you use|if you use|instead of|alternative|"
                       r"(?:don'?t|do not) use both|use (?:only )?one)\b", re.I)


def tick_patch(plan, fid) -> list[int]:
    """Tick a patch file. When it's a main file that's another version of the main file you
    picked (e.g. "DynDOLOD version" next to "Standard version"), it replaces that file.
    Returns the file ids it replaced."""
    from .selection import MAIN
    opt = plan.option(fid)
    replaced: list[int] = []
    if opt is not None and opt.category == MAIN and _ALT_MAIN.search(f"{opt.name} {opt.description}"):
        mains = [o for o in plan.selected_options() if o.category == MAIN and o.file_id != fid]
        if len(mains) == 1:
            replaced = [mains[0].file_id]
            plan.selected = [f for f in plan.selected if f not in replaced]
    if fid not in plan.selected:
        plan.selected.append(fid)
    return replaced


def patches_to_tick(report, skip=lambda plan, file_id: False, texture: str = "") -> list:
    """The patch files worth ticking by themselves: (plan, file_id) pairs.

    Careful on purpose:
    * only files in a mod's Main / Optional / Misc sections (never "Updates"), for your
      game version, and not called beta / legacy / outdated / test...;
    * one file per mod it's for - when a mod has several patches for the same other
      mod (v1.0, v1.2...), only the newest; none if you already picked one yourself;
    * the same patch in several texture sizes (1K / 2K...): only one - your texture
      size, else the size of the mod's own file you picked, else the closest;
    * ``skip`` says no for ones you unticked before.
    """
    from .selection import (MAIN, MISC, OPTIONAL, parse_texture, siblings, texture_fit, texture_siblings,
                            texture_sizes, variant_score)
    best: dict = {}

    def wanted_size(plan):
        want = parse_texture(texture)
        if want:
            return want
        own = [texture_sizes(o) for o in plan.selected_options() if len(texture_sizes(o)) == 1]
        return max(next(iter(x)) for x in own) if own else None

    def rank(plan, opt):
        want = wanted_size(plan)
        fit = texture_fit(texture_sizes(opt), want) if want and texture_sizes(opt) else (0, 0)
        return (tuple(-x for x in fit), variant_score(opt), opt.uploaded)

    for f in report.by_kind(PATCH):
        plan, fid = f.plan, f.file_id
        opt = plan.option(fid) if hasattr(plan, "option") else None
        if (opt is None or plan.error or plan.skipped or fid in plan.selected or skip(plan, fid)
                or opt.category not in (MAIN, OPTIONAL, MISC) or opt.fit.hidden
                or _NOT_FOR_AUTO.search(f"{opt.name} {opt.file_name}")):
            continue
        if any(s.file_id in plan.selected
               for s in siblings(opt, plan.options) + texture_siblings(opt, plan.options)):
            continue  # a variant of it (ESL / packed / loose / another size) is already ticked
        key = (id(plan), id(f.other))
        if key in best and rank(plan, best[key][1]) >= rank(plan, opt):
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
