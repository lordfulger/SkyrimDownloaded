"""Finding mods: browse Nexus (most endorsed / downloaded, recently updated, newest, over a
time frame), and suggestions for your list - patches and add-ons made for the mods you have.

Suggestions come from Nexus's requirement lists: a mod that lists two of your mods as
requirements (and nothing you don't have) is almost always a patch between them.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .selection import _LANG

from .nexus import GAME_IDS

SHOW = {  # what to show: (sort field, which date the time frame applies to)
    "Most endorsed": ("endorsements", "createdAt"),
    "Most downloaded": ("downloads", "createdAt"),
    "Recently updated": ("updatedAt", "updatedAt"),
    "Newest": ("createdAt", "createdAt"),
}
PERIODS = {"Last 24 hours": 1, "Last week": 7, "Last month": 30, "Last 3 months": 90,
           "Last year": 365, "All time": None}

#: Mods required by more mods than this (SkyUI, SKSE...) say little about what fits your list.
TOO_COMMON = 240
PAGE = 80
DETAILS_BATCH = 40
MAX_SINGLE = 600  # add-on candidates (made for one of your mods) to look at

_FIELDS = ("modId name author endorsements downloads createdAt updatedAt category adultContent "
           "status summary thumbnailUrl version")
BROWSE_QUERY = """
query browse($f: [ModsFilter!], $s: [ModsSort!], $count: Int, $offset: Int) {
  mods(filter: {filter: $f, op: AND}, sort: $s, count: $count, offset: $offset) {
    totalCount nodes { %s }
  }
}""" % _FIELDS
REQUIRING_QUERY = """
query requiring($modId: ID!, $gameId: ID!, $count: Int, $offset: Int) {
  mod(modId: $modId, gameId: $gameId) {
    modRequirements {
      modsRequiringThisMod(count: $count, offset: $offset) { totalCount nodes { modId modName gameId } }
    }
  }
}"""
DETAILS_QUERY = """
query details($f: [ModsFilter!], $count: Int) {
  mods(filter: {filter: $f, op: OR}, count: $count) {
    nodes { %s modRequirements { nexusRequirements(count: 50) { nodes { modId modName externalRequirement } } } }
  }
}""" % _FIELDS


@dataclass
class Found:
    game: str
    mod_id: int
    name: str
    author: str = ""
    endorsements: int = 0
    downloads: int = 0
    created: str = ""
    updated: str = ""
    category: str = ""
    adult: bool = False
    status: str = "published"
    summary: str = ""
    thumbnail: str = ""
    version: str = ""
    # suggestions only
    kind: str = ""                                 # "patch" or "add-on"
    ties: list = field(default_factory=list)       # names of your mods it's made for

    @property
    def url(self) -> str:
        return f"https://www.nexusmods.com/{self.game}/mods/{self.mod_id}"

    @classmethod
    def from_node(cls, game: str, n: dict) -> "Found":
        return cls(game, int(n.get("modId") or 0), str(n.get("name") or "?"), str(n.get("author") or ""),
                   int(n.get("endorsements") or 0), int(n.get("downloads") or 0), str(n.get("createdAt") or ""),
                   str(n.get("updatedAt") or ""), str(n.get("category") or ""), bool(n.get("adultContent")),
                   str(n.get("status") or "published"), str(n.get("summary") or ""),
                   str(n.get("thumbnailUrl") or ""), str(n.get("version") or ""))


def browse(client, game: str, show: str, period: str, search: str = "", adult: bool = False,
           offset: int = 0, count: int = 40, now: float | None = None) -> tuple[list[Found], int]:
    """A page of Nexus mods. ``show`` and ``period`` are keys of SHOW and PERIODS."""
    sort_by, date_field = SHOW.get(show, SHOW["Most endorsed"])
    filters: list[dict] = [{"gameDomainName": [{"value": game, "op": "EQUALS"}]}]
    days = PERIODS.get(period)
    if days:
        since = int((now or time.time()) - days * 86400)
        filters.append({date_field: [{"value": str(since), "op": "GTE"}]})
    if search.strip():
        filters.append({"nameStemmed": [{"value": search.strip(), "op": "MATCHES"}]})
    if not adult:
        filters.append({"adultContent": {"value": False}})
    data = client._graphql(BROWSE_QUERY, {"f": filters, "s": [{sort_by: {"direction": "DESC"}}],
                                          "count": count, "offset": offset}, "mods", raise_errors=True)
    nodes = (data or {}).get("nodes") or []
    found = [Found.from_node(game, n) for n in nodes]
    found = [f for f in found if f.status == "published"]
    return found, int((data or {}).get("totalCount") or 0)


# -- suggestions for your list ------------------------------------------------------------

def requiring(client, game: str, mod_id: int, cache=None) -> list[tuple[int, int, str]] | None:
    """Mods that list this one as a requirement: [(game id, mod id, name)], or None when
    there are too many to be telling (or Nexus couldn't say)."""
    key = f"requiring:{game}/{mod_id}"
    if cache is not None:
        saved = cache.get(key)
        if saved is not None:
            return [tuple(x) for x in saved] if saved != "many" else None
    if game not in GAME_IDS:
        return None
    ids = {"modId": str(int(mod_id)), "gameId": str(GAME_IDS[game])}

    def fetch(offset):
        data = client._graphql(REQUIRING_QUERY, dict(ids, count=PAGE, offset=offset), "mod")
        return ((data or {}).get("modRequirements") or {}).get("modsRequiringThisMod") if data else None
    page = fetch(0)
    if page is None:
        return None
    total = int(page.get("totalCount") or 0)
    if total > TOO_COMMON:
        if cache is not None:
            cache.put(key, "many")
        return None
    nodes = list(page.get("nodes") or [])
    offset = PAGE
    while offset < total:
        got = (fetch(offset) or {}).get("nodes") or []
        if not got:
            break
        nodes += got
        offset += PAGE
    out = [(int(n.get("gameId") or 0), int(n.get("modId") or 0), str(n.get("modName") or ""))
           for n in nodes if n.get("modId")]
    if cache is not None:
        cache.put(key, [list(x) for x in out])
    return out


def details(client, game: str, keys: list[tuple[int, int]], cache=None) -> dict[int, tuple[Found, list]]:
    """{mod id: (Found, [required mod ids])} for these (game id, mod id)s, in batches."""
    out: dict = {}
    todo = []
    for gid, mid in keys:
        saved = cache.get(f"details:{gid}/{mid}") if cache is not None else None
        if saved is not None:
            out[mid] = (Found(**saved[0]), saved[1])
        else:
            todo.append((gid, mid))
    for i in range(0, len(todo), DETAILS_BATCH):
        chunk = todo[i:i + DETAILS_BATCH]
        filters = [{"gameId": [{"value": str(g), "op": "EQUALS"}], "modId": [{"value": str(m), "op": "EQUALS"}]}
                   for g, m in chunk]
        data = client._graphql(DETAILS_QUERY, {"f": filters, "count": len(chunk)}, "mods")
        gid_of = {m: g for g, m in chunk}
        for n in (data or {}).get("nodes") or []:
            found = Found.from_node(game, n)
            reqs = (((n.get("modRequirements") or {}).get("nexusRequirements") or {}).get("nodes") or [])
            ids = [int(r["modId"]) for r in reqs if r.get("modId") not in (None, "0", 0) and not r.get("externalRequirement")]
            out[found.mod_id] = (found, ids)
            if cache is not None:
                from dataclasses import asdict
                cache.put(f"details:{gid_of.get(found.mod_id, 0)}/{found.mod_id}", [asdict(found), ids])
    return out


def suggest(client, plans, cache=None, adult: bool = False, hidden=frozenset(), on_progress=None,
            cancel=None, workers: int = 6) -> list[Found]:
    """Patches and add-ons for the mods in your list, best first. Only mods whose Nexus
    requirements are all in your list are suggested."""
    mods = [p for p in plans if not p.error and p.mod]
    if not mods:
        return []
    game = mods[0].entry.game
    listed = {p.entry.mod_id: p.title for p in mods if p.entry.game == game}
    hits: dict[tuple[int, int], set] = {}
    done = 0

    def one(plan):
        if cancel is not None and cancel.is_set():
            return plan, None
        return plan, requiring(client, game, plan.entry.mod_id, cache)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for plan, got in pool.map(one, [p for p in mods if p.entry.game == game]):
            done += 1
            if on_progress:
                on_progress(done, len(listed))
            for gid, mid, _name in got or []:
                if mid not in listed and mid not in hidden:
                    hits.setdefault((gid or GAME_IDS.get(game, 0), mid), set()).add(plan.entry.mod_id)
    if cancel is not None and cancel.is_set():
        return []
    several = [k for k, v in hits.items() if len(v) >= 2]
    single = [k for k, v in hits.items() if len(v) == 1][:MAX_SINGLE]
    info = details(client, game, several + single, cache)
    out = []
    for (gid, mid), _by in hits.items():
        if mid not in info:
            continue
        found, reqs = info[mid]
        reqs = set(reqs)
        if not reqs or not reqs <= set(listed):
            continue  # needs something you don't have
        if found.status != "published" or (found.adult and not adult) or "deleted" in found.name.lower():
            continue
        if _LANG.search(found.name):
            continue  # translations
        found.ties = [listed[r] for r in sorted(reqs, key=lambda r: list(listed).index(r))]
        found.kind = "patch" if len(reqs) >= 2 else "add-on"
        out.append(found)
    out.sort(key=lambda f: (f.kind != "patch", -f.endorsements))
    patches = [f for f in out if f.kind == "patch"]
    addons = [f for f in out if f.kind != "patch"][:150]
    return patches + addons
