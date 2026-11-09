"""Work out which files on a mod's Files tab to download.

This is the "options" step: when a mod offers more than one file (say 1K and 2K
textures, or a main file plus optional patches) the user is asked, just like
picking options in a collection. A rule in the list (``| primary``,
``| match=2K``...) answers the question ahead of time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gameversion import Fit, GameTarget, fit
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
    fit: Fit = field(default_factory=lambda: Fit("unknown"))   # for your game version?
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


def human_time(seconds: float | None) -> str:
    """12 s, 3 min, 1 h 5 min."""
    if seconds is None:
        return "?"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{max(1, s // 60)} min"
    return f"{s // 3600} h {round((s % 3600) / 60)} min"


def _plain(html: str) -> str:
    """File descriptions are BBCode and HTML; show them as plain text."""
    from .text import bbcode_to_text
    return bbcode_to_text(html or "")


def sort_options(files: list[FileOption]) -> list[FileOption]:
    return sorted(files, key=lambda f: (_ORDER.get(f.category, 9), not f.is_primary, -f.uploaded))


def annotate(files: list[FileOption], target: GameTarget | None) -> None:
    """Work out which files are for your game version."""
    for f in files:
        f.fit = fit(f.name, f.file_name, f.description, target)


def for_other_versions(files: list[FileOption]) -> list[FileOption]:
    return [f for f in files if f.category in CURRENT and f.fit.hidden]


def visible_options(files: list[FileOption], include_old: bool = False,
                    include_other: bool = False) -> list[FileOption]:
    """What the user is offered. Old versions, and files for other game versions,
    only if asked for (or if nothing would be left)."""
    cats = CURRENT + ((OLD, ARCHIVED) if include_old else ())
    shown = [f for f in sort_options(files) if f.category in cats]
    if include_other:
        return shown
    fitting = [f for f in shown if not f.fit.hidden]
    current_fitting = [f for f in fitting if f.category in CURRENT]
    if not current_fitting:
        return shown  # every file looks like it's for another version: show them all
    return fitting


def _rank(f: FileOption) -> int:
    return {"ok": 0, "unknown": 1}.get(f.fit.status, 2)


# -- variants of the same file: ESL or not, packed (BSA) or loose -----------------------

_ESL = re.compile(r"\b(?:esl(?:[- ]?(?:flagged|ified|version|plugin))?|espfe|light ?plugin)\b", re.I)
_PACKED = re.compile(r"\b(?:bsa|ba2|packed|archived?)\b", re.I)
_LOOSE = re.compile(r"\bloose(?: ?files?)?\b", re.I)
_ALTERNATIVE = re.compile(r"alternative (?:to|version of)|instead of the main|(?:don'?t|do not) use both|"
                          r"use (?:only )?one of (?:them|these)|replaces? the main", re.I)
_VARIANT_WORDS = re.compile(r"\b(?:esl(?:[- ]?(?:flagged|ified|version|plugin))?|espfe|light|plugins?|bsa|ba2|"
                            r"packed|archived?|loose|files?|version|edition|ver)\b", re.I)


def variant_key(opt: FileOption) -> str:
    """The file's name without the ESL / BSA / loose words: variants share it."""
    text = re.sub(r"[-_.()\[\]+]", " ", opt.name.lower())
    text = _VARIANT_WORDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def variant_score(opt: FileOption) -> int:
    """Higher is better: ESL-flagged beats regular, packed (BSA) beats loose."""
    text = f"{opt.name} {opt.file_name}"
    return (2 if _ESL.search(text) else 0) + (1 if _PACKED.search(text) else 0) - (1 if _LOOSE.search(text) else 0)


def _is_variant_kind(opt: FileOption) -> bool:
    text = f"{opt.name} {opt.file_name}"
    return bool(_ESL.search(text) or _PACKED.search(text) or _LOOSE.search(text))


def siblings(opt: FileOption, files: list[FileOption]) -> list[FileOption]:
    """Other files that are the same thing in another form (use one, not both)."""
    key = variant_key(opt)
    out = []
    for o in files:
        if o.file_id == opt.file_id or o.category not in CURRENT or o.fit.hidden:
            continue
        same_name = bool(key) and variant_key(o) == key and (_is_variant_kind(o) or _is_variant_kind(opt))
        said_so = ((o.category != MAIN and opt.category == MAIN and o.description and _ALTERNATIVE.search(o.description)
                    and _is_variant_kind(o) and opt.is_primary)
                   or (opt.category != MAIN and o.category == MAIN and opt.description
                       and _ALTERNATIVE.search(opt.description) and _is_variant_kind(opt) and o.is_primary))
        if same_name or said_so:
            out.append(o)
    return out


def prefer_variants(files: list[FileOption], selected: list[int]) -> list[int]:
    """Swap each picked file for its best variant (ESL, then packed), never two of a kind."""
    by_id = {f.file_id: f for f in files}
    result: list[int] = []
    taken: set[int] = set()
    for fid in selected:
        opt = by_id.get(fid)
        if opt is None:
            result.append(fid)
            continue
        if fid in taken:
            continue
        group = [opt] + siblings(opt, files)
        best = max(group, key=lambda o: (variant_score(o), o.is_primary, o.uploaded))
        taken.update(o.file_id for o in group)
        if best.file_id not in result:
            result.append(best.file_id)
    return result


# -- texture sizes: 1K, 2K, 4K, mixes like "2K4K" ---------------------------------------

TEXTURE_SIZES = ["1K", "2K", "4K", "8K"]
_RES_K = re.compile(r"(?<![a-jl-z\d.])(0?\.5|512|1|2|4|8|16)\s?k(?![a-z])", re.I)  # "2K4K" and "2k_4k" too
_RES_PX = re.compile(r"(?<![a-z\d.])(512|1024|2048|4096|8192)(?:\s?px)?(?![a-z\d.])", re.I)
_PX_TO_K = {"512": 0.5, "1024": 1, "2048": 2, "4096": 4, "8192": 8}
_RES_WORDS = re.compile(r"\b(?:textures?|tex|res(?:olution)?|mix(?:ed)?|and|version|ver|edition|"
                        r"performance|quality|hd|uhd)\b", re.I)


def texture_sizes(opt: FileOption) -> frozenset:
    """Texture sizes a file says it has, in K: "2K" -> {2}, "2K4K" or "2K-4K mix" -> {2, 4}."""
    text = opt.name or ""
    sizes = {0.5 if m.group(1) == "512" else float(m.group(1)) for m in _RES_K.finditer(text)}
    sizes |= {float(_PX_TO_K[m.group(1)]) for m in _RES_PX.finditer(text)}
    return frozenset(sizes)


def texture_key(opt: FileOption) -> str:
    """The file's name without the size words: the same textures in other sizes share it."""
    text = _RES_K.sub(" ", opt.name or "")
    text = _RES_PX.sub(" ", text)
    text = re.sub(r"[-_.()\[\]+/&,|]", " ", text.lower())
    text = _RES_WORDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_texture(pref: str | None) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*k", pref or "", re.I)
    return float(m.group(1)) if m else None


def texture_fit(sizes: frozenset, want: float) -> tuple:
    """Lower is better: exactly your size, then a mix with your size, then the next
    size down, then the next size up."""
    if sizes == {want}:
        return (0, 0)
    if want in sizes:
        return (1, len(sizes))
    if max(sizes) < want:
        return (2, want / max(sizes))
    return (3, min(sizes) / want)


def texture_siblings(opt: FileOption, files: list[FileOption]) -> list[FileOption]:
    """The same file in other texture sizes (use one of them)."""
    if not texture_sizes(opt):
        return []
    key = texture_key(opt)
    return [o for o in files if o.file_id != opt.file_id and o.category in CURRENT and not o.fit.hidden
            and texture_sizes(o) and texture_key(o) == key]


def prefer_texture(files: list[FileOption], selected: list[int], pref: str | None) -> list[int]:
    """Swap each picked file for the same file in your texture size (or the closest)."""
    want = parse_texture(pref)
    if not want:
        return selected
    by_id = {f.file_id: f for f in files}
    result: list[int] = []
    for fid in selected:
        opt = by_id.get(fid)
        group = [opt] + texture_siblings(opt, files) if opt else []
        if len(group) > 1:
            fid = min(group, key=lambda o: (texture_fit(texture_sizes(o), want), not o.is_primary,
                                            -o.uploaded)).file_id
        if fid not in result:
            result.append(fid)
    return result


# -- extras nobody needs to be asked about: translations, readmes, sources, old builds --------

_LANG = re.compile(
    r"\b(?:russian|rus|chinese|chs|cht|japanese|korean|german|deutsch|french|fran[cç]ais|spanish|"
    r"espa[nñ]ol|italian|italiano|polish|polski|portuguese|pt[- ]?br|brazilian|czech|turkish|ukrainian|"
    r"hungarian|swedish|dutch|translation|translated|traduction|traducci[oó]n|[uü]bersetzung|"
    r"locali[sz]ation)\b", re.I)
_DOCS = re.compile(r"\b(?:readme|read me|documentation|manual|sources?(?: ?code| ?files| ?scripts)?|"
                   r"psc files|modders? resources?|resources? for modders|dev(?:eloper)? files)\b", re.I)
_OLDISH = re.compile(r"\b(?:legacy|outdated|deprecated|obsolete|old(?:er)? versions?|beta|alpha|"
                     r"test(?:ing)?|experimental|wip)\b", re.I)


def extra_kind(opt: FileOption) -> str:
    """"translation", "docs" or "old" for files you'd rarely want; "" otherwise."""
    text = f"{opt.name} {opt.file_name}"
    if _LANG.search(text):
        return "translation"
    if _DOCS.search(text):
        return "docs"
    if _OLDISH.search(opt.name):
        return "old"
    return ""


def _alike(opt: FileOption, files: list[FileOption]) -> set[int]:
    """This file and the same thing in another form (ESL / BSA / loose / texture size)."""
    return {opt.file_id} | {o.file_id for o in siblings(opt, files) + texture_siblings(opt, files)}


def real_choices(pool: list[FileOption], files: list[FileOption]) -> list[FileOption]:
    """The different main files to pick between (forms of the same file count once)."""
    mains = [f for f in pool if f.category == MAIN] or list(pool)
    reps: list[FileOption] = []
    covered: set[int] = set()
    for f in mains:
        if f.file_id in covered:
            continue
        reps.append(f)
        covered |= _alike(f, files)
    return reps


def word_score(opt: FileOption, prefer, avoid) -> int:
    text = f"{opt.name} {opt.file_name}".lower()
    hit = lambda w: re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", text)
    return sum(1 for w in prefer if w and hit(w)) - 10 * sum(1 for w in avoid if w and hit(w))


_DULL_WORDS = {"se", "sse", "ae", "le", "v", "ver", "version", "file", "files", "main", "optional", "mod",
               "the", "for", "and", "or", "with", "a", "of", "to", "in", "by", "esp", "esl", "bsa", "loose", "k"}


def _words(name: str) -> set[str]:
    """Words of a file name and the pairs next to each other ("no snow", "version 2")."""
    words = [w for w in re.findall(r"[a-z]+|\d+", (name or "").lower())
             if not re.fullmatch(r"\d+k|\d{3,}", w)]
    pairs = {f"{a} {b}" for a, b in zip(words, words[1:])}
    return {w for w in words if w not in _DULL_WORDS} | pairs


def pick_like(chosen: list[FileOption], all_files: list[FileOption], title: str,
              other_files: list[FileOption], other_title: str) -> list[int]:
    """Your pick for one mod, applied to a similar mod: the file in ``other_files`` whose
    name has the most of the same telling words (e.g. "No Snow", "Desaturated", "Version 2").
    [] when it isn't clear."""
    current_all = [f for f in all_files if f.category in CURRENT]
    if not chosen or len(real_choices(current_all, all_files)) < 2:
        return []
    shared = set.intersection(*[_words(f.name) for f in current_all])
    want = set().union(*[_words(f.name) for f in chosen]) - shared - _words(title)
    if not want:
        return []
    current = [f for f in other_files if f.category in CURRENT and not f.fit.hidden]
    reps = real_choices(current, other_files)
    if len(reps) < 2:
        return []
    scored = sorted(((len(want & _words(r.name)), r) for r in reps), key=lambda t: -t[0])
    if scored[0][0] == 0 or scored[0][0] == scored[1][0]:
        return []
    return prefer_variants(other_files, [scored[0][1].file_id])


def primary_file(files: list[FileOption]) -> FileOption | None:
    current = [f for f in files if f.category in CURRENT]
    if not current:
        return None
    best = min(_rank(f) for f in current)
    current = [f for f in current if _rank(f) == best]  # prefer files for your version
    for pool in (
        [f for f in current if f.is_primary],
        [f for f in current if f.category == MAIN],
        current,
    ):
        if pool:
            return max(pool, key=lambda f: f.uploaded)
    return None


def choose(entry: ListEntry, files: list[FileOption], remembered: list[int] | None = None,
           target: GameTarget | None = None) -> Choice:
    """Pick files for a mod from its list line, a saved earlier choice, or ask.

    With a ``target`` game version, files for other versions are left out
    (when that leaves a single file, there's nothing to ask).
    """
    annotate(files, target)
    by_id = {f.file_id: f for f in files}
    rule: Rule = entry.rule

    if rule.mode == "skip":
        return Choice([], False, "skipped in the list")

    # 1. Exact files: from the link itself (file_id=, nxm://) or file= in the rule.
    wanted = list(dict.fromkeys(entry.file_ids + rule.file_ids))
    if wanted:
        found = [fid for fid in wanted if fid in by_id]
        missing = [fid for fid in wanted if fid not in by_id]
        wrong_version = [fid for fid in found if by_id[fid].fit.hidden]
        if found and not missing and wrong_version:
            return Choice(found, True, "the list picked a file for another game version - check it")
        if found and not missing:
            return Choice(found, rule.mode == "ask", "file picked in the list")
        if found:
            return Choice(found, True, f"file {', '.join(map(str, missing))} isn't on Nexus any more")
        # The linked file was removed (often replaced by a newer version).
        fallback = primary_file(files)
        return Choice([fallback.file_id] if fallback else [], True,
                      "the linked file isn't on Nexus any more - pick its replacement")

    all_current = [f for f in sort_options(files) if f.category in CURRENT]
    if not all_current:
        return Choice([], True, "no current files on the Files tab")
    current = [f for f in all_current if not f.fit.hidden]
    hidden = len(all_current) - len(current)
    if not current:
        # Everything looks like it's for another version: let the user decide.
        best = primary_file(files)
        return Choice([best.file_id] if best else [], True,
                      f"no file seems to be for {target.describe() if target else 'your game'}")
    note = f" ({hidden} for other game versions left out)" if hidden else ""
    if any(f.category == MAIN for f in all_current) and not any(f.category == MAIN for f in current):
        # Every main file looks like it's for another version: don't quietly take only the extras.
        return Choice([], True,
                      "the main file looks like it's for another game version - check it" + note)

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
    if remembered is not None and len(remembered) == 0 and rule.mode in ("auto", "ask"):
        return Choice([], False, "left out by you")
    if remembered and (rule.mode == "ask" or (rule.mode == "auto" and len(current) > 1)):
        still_there = [fid for fid in remembered if fid in by_id]
        if still_there and len(still_there) == len(remembered):
            stale = [fid for fid in still_there
                     if by_id[fid].fit.hidden or by_id[fid].category not in CURRENT]
            if not stale:
                return Choice(still_there, rule.mode == "ask", "your earlier choice")
            # Picked before, but now for another game version or moved to old files: ask again.
            return Choice(still_there, True, "your earlier pick is for another game version or an "
                                             "old file now - check it")

    if rule.mode == "main":
        mains = [f.file_id for f in current if f.category == MAIN] or [current[0].file_id]
        return Choice(prefer_variants(files, mains), False, "all main files" + note)
    if rule.mode == "all":
        return Choice(prefer_variants(files, [f.file_id for f in current]), False, "all current files" + note)

    best = primary_file(files)
    selected = prefer_variants(files, [best.file_id]) if best else []
    pref = target.texture if target is not None else ""
    if pref and selected:
        sized = prefer_texture(files, selected, pref)
        if sized != selected:
            selected = prefer_variants(files, sized)
        # Only sizes of the same textures to pick from: no need to ask.
        chosen = [by_id[f] for f in selected if f in by_id]
        alike = {f.file_id for c in chosen for f in [c] + texture_siblings(c, files) + siblings(c, files)}
        if (rule.mode == "auto" and chosen and len(current) > 1 and texture_siblings(chosen[0], files)
                and all(f.file_id in alike for f in current)):
            return Choice(selected, False, f"your texture size ({pref})" + note)
    if rule.mode == "primary":
        return Choice(selected, False, "primary file" + note)
    if rule.mode == "ask":
        return Choice(selected, True, "you asked to choose" + note)
    # auto: ask only when there is a real choice to make.
    if len(current) == 1:
        return Choice(selected, False,
                      "the only file for your game version" + note if hidden else "only one file")
    if target is not None and getattr(target, "smart", False):
        decided = _auto_pick(files, current, selected, target, note)
        if decided is not None:
            return decided
    return Choice(selected, True, f"{len(current)} files to choose from" + note)


def _auto_pick(files, current, selected, target, note) -> "Choice | None":
    """Your auto-pick settings: leave extras off, follow your word preferences, and only ask
    when there are several different main files. None = ask as usual."""
    by_id = {f.file_id: f for f in files}
    pool = list(current)
    left_off = ""
    if target.skip_extras:
        extras = [f for f in current if extra_kind(f)]
        if extras and len(extras) < len(current):
            pool = [f for f in current if f not in extras]
            kinds = sorted({extra_kind(f) for f in extras})
            left_off = f" ({len(extras)} {'/'.join(k + 's' if k != 'old' else 'old files' for k in kinds)} left off)"
            selected[:] = [fid for fid in selected if by_id.get(fid) not in extras] or \
                prefer_variants(files, [real_choices(pool, files)[0].file_id])
    reps = real_choices(pool, files)
    if len(reps) > 1 and (target.prefer or target.avoid):
        scored = sorted(((word_score(r, target.prefer, target.avoid), r) for r in reps),
                        key=lambda t: -t[0])
        if scored[0][0] > scored[1][0] and scored[0][0] >= 0:
            best = scored[0][1]
            pick = prefer_variants(files, prefer_texture(files, [best.file_id], target.texture))
            words = [w for w in target.prefer if word_score(best, [w], [])] or ["not " + w for w in target.avoid]
            selected[:] = pick
            reps = [best]
            if not target.only_real_choices:
                return Choice(pick, True, f"picked by your words ({', '.join(words[:3])})" + note)
            return Choice(pick, False, f"picked by your words ({', '.join(words[:3])})" + left_off + note)
    if len(reps) == 1 and target.only_real_choices:
        others = [f for f in pool if f.file_id not in _alike(reps[0], files)]
        why = "only one main file" + (f" - {len(others)} optional file(s) left off" if others else "")
        return Choice(selected, False, why + left_off + note)
    if len(pool) < len(current) and len(pool) == 1:
        return Choice(selected, False, "only one file" + left_off + note)
    return None
