"""Turn a list into a plan (look up every mod and its files), then carry it out."""

from __future__ import annotations

import logging
import time

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .gameversion import GameTarget
from .downloader import Cancelled, download, safe_file_name
from .links import ListEntry
from .managers import ManagerError, Target, nxm_url
from .nexus import ModInfo, NexusClient, NexusError, Requirement
from .selection import FileOption, choose, sort_options


@dataclass
class ModPlan:
    entry: ListEntry
    mod: ModInfo | None = None
    options: list[FileOption] = field(default_factory=list)
    selected: list[int] = field(default_factory=list)
    needs_choice: bool = False
    reason: str = ""
    error: str | None = None

    @property
    def title(self) -> str:
        if self.mod:
            return self.mod.name
        return self.entry.note or f"Mod {self.entry.mod_id}"

    def option(self, file_id: int) -> FileOption | None:
        return next((o for o in self.options if o.file_id == file_id), None)

    def selected_options(self) -> list[FileOption]:
        return [o for o in (self.option(fid) for fid in self.selected) if o]

    @property
    def skipped(self) -> bool:
        return self.entry.rule.mode == "skip"


def resolve_one(client: NexusClient, entry: ListEntry,
                remembered: dict[str, list[int]] | None = None,
                target: GameTarget | None = None) -> ModPlan:
    plan = ModPlan(entry)
    if entry.rule.mode == "skip":
        plan.reason = "skipped in the list"
        return plan
    try:
        plan.mod = client.mod(entry.game, entry.mod_id)
        if not plan.mod.available or plan.mod.status not in ("published", ""):
            plan.error = f"not available on Nexus ({plan.mod.status})"
            return plan
        plan.options = sort_options([FileOption.from_api(f) for f in client.files(entry.game, entry.mod_id)])
    except NexusError as err:
        plan.error = str(err) if err.status != 404 else "not found on Nexus (removed, hidden or wrong link)"
        return plan
    rechoose(plan, (remembered or {}).get(entry.key), target)
    return plan


def rechoose(plan: ModPlan, remembered: list[int] | None = None,
             target: GameTarget | None = None) -> None:
    """(Re)pick a looked-up mod's files, e.g. after the game version changed."""
    choice = choose(plan.entry, plan.options, remembered, target)
    plan.selected, plan.needs_choice, plan.reason = choice.selected, choice.needs_choice, choice.reason


def resolve(client: NexusClient, entries: list[ListEntry], *,
            remembered: dict[str, list[int]] | None = None,
            on_progress: Callable[[int, int, ModPlan], None] | None = None,
            workers: int = 4, target: GameTarget | None = None) -> list[ModPlan]:
    """Look up every mod in the list. Order is kept."""
    plans: list[ModPlan | None] = [None] * len(entries)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(resolve_one, client, e, remembered, target): i for i, e in enumerate(entries)}
        done = 0
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                plans[i] = fut.result()
            except Exception as err:  # never lose the whole list over one mod
                plans[i] = ModPlan(entries[i], error=f"unexpected error: {err}")
            done += 1
            if on_progress:
                on_progress(done, len(entries), plans[i])
    return [p for p in plans if p is not None]


@dataclass
class MissingRequirement:
    needed_by: list[str]
    requirement: Requirement

    @property
    def link(self) -> str:
        return self.requirement.url or f"dlc:{self.requirement.name}"


def missing_requirements(client: NexusClient, plans: list[ModPlan], *,
                         workers: int = 4) -> tuple[list[MissingRequirement], bool]:
    """Requirements of the mods in the list that the list doesn't have.

    Returns (missing, checked): ``checked`` is False when Nexus couldn't be asked.
    """
    wanted = [p for p in plans if p.mod and not p.error and not p.skipped]
    have = {(p.entry.game, p.entry.mod_id) for p in plans}
    found: dict[str, MissingRequirement] = {}
    checked = False
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = list(pool.map(lambda p: (p, client.requirements(p.entry.game, p.entry.mod_id)), wanted))
    for plan, reqs in results:
        if reqs is None:
            continue
        checked = True
        for req in reqs:
            if not req.external and req.mod_id and (plan.entry.game, req.mod_id) in have:
                continue
            if not req.external and not req.mod_id:
                continue
            key = (f"dlc:{req.name}" if req.dlc else f"ext:{req.url or req.name}" if req.external
                   else f"{plan.entry.game}/{req.mod_id}")
            if not req.url and not req.external:
                req.url = f"https://www.nexusmods.com/{plan.entry.game}/mods/{req.mod_id}"
            if key in found:
                if plan.title not in found[key].needed_by:
                    found[key].needed_by.append(plan.title)
            else:
                found[key] = MissingRequirement([plan.title], req)
    # Nexus mods first (they can be added), then outside downloads.
    # Nexus mods first (they can be added), then outside downloads, then DLC / Creations.
    return sorted(found.values(), key=lambda m: (m.requirement.dlc, m.requirement.external,
                                                 m.requirement.name.lower())), checked


# -- carrying it out ---------------------------------------------------------

QUEUED, WORKING, DONE, SENT, SKIPPED, FAILED, STOPPED = (
    "queued", "downloading", "done", "sent", "already there", "failed", "stopped")


@dataclass
class Job:
    plan: ModPlan
    option: FileOption
    state: str = QUEUED
    done_bytes: int = 0
    total_bytes: int | None = None
    note: str = ""
    path: Path | None = None
    speed: float = 0.0            # bytes per second, smoothed
    _last: tuple[float, int] | None = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return f"{self.plan.title} - {self.option.name}"

    def track(self, done: int, now: float | None = None) -> None:
        """Update the download speed from the bytes done so far."""
        now = time.monotonic() if now is None else now
        if self._last is None:
            self._last = (now, done)
            return
        t0, d0 = self._last
        if now - t0 >= 0.5:
            current = max(0.0, (done - d0) / (now - t0))
            self.speed = current if not self.speed else 0.7 * self.speed + 0.3 * current
            self._last = (now, done)

    @property
    def seconds_left(self) -> float | None:
        if not self.speed or not self.total_bytes:
            return None
        return max(0.0, (self.total_bytes - self.done_bytes) / self.speed)


EventFn = Callable[[Job], None]


def jobs_for(plans: list[ModPlan]) -> list[Job]:
    jobs = []
    for plan in plans:
        if plan.error or plan.skipped:
            continue
        for option in plan.selected_options():
            jobs.append(Job(plan, option, total_bytes=option.approx_bytes))
    return jobs


class Runner:
    def __init__(self, client: NexusClient, target: Target, *, mode: str = "handoff",
                 install: bool = True, parallel: int = 3, redownload: bool = False,
                 on_event: EventFn | None = None, cancel: threading.Event | None = None):
        if mode not in ("handoff", "direct"):
            raise ValueError("mode must be 'handoff' or 'direct'")
        self.client = client
        self.target = target
        self.mode = mode
        self.install = install
        self.parallel = max(1, min(int(parallel), 6))
        self.redownload = redownload
        self.on_event = on_event or (lambda job: None)
        self.cancel = cancel or threading.Event()
        self._launch_lock = threading.Lock()

    def _emit(self, job: Job, state: str | None = None, note: str | None = None) -> None:
        if state is not None and state != job.state and state in (FAILED, DONE, SENT):
            log = logging.getLogger("skyrimdl")
            (log.warning if state == FAILED else log.info)("%s: %s %s", job.label, state, note or "")
        if state is not None:
            job.state = state
        if note is not None:
            job.note = note
        self.on_event(job)

    def _key_for(self, job: Job) -> tuple[str | None, int | None]:
        entry = job.plan.entry
        if entry.nxm_key and job.option.file_id in entry.file_ids:
            return entry.nxm_key, entry.nxm_expires
        return None, None

    def run(self, jobs: list[Job]) -> list[Job]:
        try:
            self.target.prepare(jobs)
        except Exception:
            logging.getLogger("skyrimdl").exception("preparing the mod manager")
        todo = []
        for job in jobs:
            existing = None if self.redownload else self.target.existing(job.option)
            if existing:
                job.path = existing
                job.done_bytes = job.total_bytes or 0
                self._emit(job, SKIPPED, f"already in the downloads folder ({existing.name})")
            else:
                todo.append(job)
        if self.mode == "handoff":
            for job in todo:
                if self.cancel.is_set():
                    self._emit(job, STOPPED, "")
                    continue
                self._handoff(job)
        else:
            with ThreadPoolExecutor(max_workers=self.parallel) as pool:
                for fut in [pool.submit(self._direct, job) for job in todo]:
                    fut.result()
            try:
                self.target.partial_dir().rmdir()  # only if empty
            except (OSError, ManagerError):
                pass
        return jobs

    def _handoff(self, job: Job) -> None:
        key, expires = self._key_for(job)
        account = self.client._account
        url = nxm_url(job.plan.entry.game, job.plan.entry.mod_id, job.option.file_id,
                      key=key, expires=expires, user_id=account.user_id if account else None)
        try:
            self.target.handoff(url, install=self.install)
            self._emit(job, SENT, f"sent to {self.target.name}")
        except ManagerError as err:
            self._emit(job, FAILED, str(err))

    def _direct(self, job: Job) -> None:
        if self.cancel.is_set():
            self._emit(job, STOPPED, "")
            return
        entry = job.plan.entry
        try:
            key, expires = self._key_for(job)
            self._emit(job, WORKING, "asking Nexus for the link")
            urls = self.client.download_links(entry.game, entry.mod_id, job.option.file_id,
                                              key=key, expires=expires)
            folder = self.target.downloads_dir()
            dest = folder / safe_file_name(job.option.file_name)

            def progress(done: int, total: int | None) -> None:
                job.done_bytes, job.total_bytes = done, total or job.total_bytes
                job.track(done)
                self._emit(job, WORKING, "")

            job.path = download(urls, dest, partial_dir=self.target.partial_dir(),
                                expected_size=job.option.size_bytes, progress=progress,
                                cancel=self.cancel)
            with self._launch_lock:
                note = self.target.after_download(job.path, job.plan.mod, job.option, self.install)
            self._emit(job, DONE, note)
        except Cancelled:
            self._emit(job, STOPPED, "stopped - start again to pick up where it left off")
        except (NexusError, ManagerError, OSError, RuntimeError) as err:
            self._emit(job, FAILED, str(err))


def summary(jobs: list[Job]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for job in jobs:
        counts[job.state] = counts.get(job.state, 0) + 1
    return counts
