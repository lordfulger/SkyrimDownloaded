"""Save the work in progress so closing and reopening the app picks up where you were:
the list, every looked-up mod with its files and your picks, what's still to
choose, and the compatibility results.

It lives next to the settings (``%APPDATA%\\SkyrimDownloaded\\session.json``).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path

from .config import config_dir
from .engine import ModPlan
from .links import ListEntry, Rule
from .nexus import ModInfo, Requirement
from .selection import FileOption

FORMAT = 1
SESSION_FILE = "session.json"


def session_path(folder: Path | None = None) -> Path:
    return (folder or config_dir()) / SESSION_FILE


# -- to and from plain data ---------------------------------------------------

def _entry_to(e: ListEntry) -> dict:
    return asdict(e)


def _entry_from(d: dict) -> ListEntry:
    d = dict(d)
    d["rule"] = Rule(**d.get("rule", {}))
    return ListEntry(**d)


def _plan_to(p: ModPlan) -> dict:
    return {
        "entry": _entry_to(p.entry),
        "mod": p.mod.raw if p.mod else None,
        "files": [o.raw for o in p.options],
        "selected": list(p.selected),
        "needs_choice": p.needs_choice,
        "reason": p.reason,
        "error": p.error,
    }


def _plan_from(d: dict) -> ModPlan:
    entry = _entry_from(d["entry"])
    mod = ModInfo.from_api(entry.game, d["mod"]) if d.get("mod") else None
    return ModPlan(
        entry=entry, mod=mod,
        options=[FileOption.from_api(f) for f in d.get("files") or []],
        selected=[int(x) for x in d.get("selected") or []],
        needs_choice=bool(d.get("needs_choice")), reason=d.get("reason") or "",
        error=d.get("error"),
    )


def save(path: Path, **parts) -> None:
    write(path, snapshot(**parts))


def snapshot(*, list_text: str, list_path: str, plans: list[ModPlan], report=None,
             requirements: dict[str, list[Requirement]] | None = None, declined=(),
             ui: dict | None = None) -> dict:
    """The work in progress as plain data (quick; writing it out is the slow part)."""
    index = {id(p): i for i, p in enumerate(plans)}
    findings = []
    if report is not None:
        for f in report.findings:
            if id(f.plan) in index and id(f.other) in index:
                findings.append({"kind": f.kind, "plan": index[id(f.plan)], "other": index[id(f.other)],
                                 "text": f.text, "file_id": f.file_id, "evidence": f.evidence})
    data = {
        "format": FORMAT,
        "saved_at": time.time(),
        "list_text": list_text,
        "list_path": list_path,
        "plans": [_plan_to(p) for p in plans],
        "compat": None if report is None else {
            "findings": findings, "requirements_checked": report.requirements_checked},
        "requirements": {k: [asdict(r) for r in v] for k, v in (requirements or {}).items() if v is not None},
        "declined": sorted(declined),
        "ui": ui or {},
    }
    return data


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


class Restored:
    def __init__(self, data: dict):
        from . import compat
        self.saved_at: float = float(data.get("saved_at") or 0)
        self.list_text: str = data.get("list_text") or ""
        self.list_path: str = data.get("list_path") or ""
        self.plans: list[ModPlan] = [_plan_from(p) for p in data.get("plans") or []]
        self.report = None
        c = data.get("compat")
        if c is not None:
            self.report = compat.Report(requirements_checked=bool(c.get("requirements_checked")))
            for f in c.get("findings") or []:
                try:
                    self.report.findings.append(compat.Finding(
                        f["kind"], self.plans[f["plan"]], self.plans[f["other"]], f["text"],
                        f.get("file_id"), f.get("evidence") or ""))
                except (IndexError, KeyError):
                    continue
        self.requirements = {k: [Requirement(**r) for r in v]
                             for k, v in (data.get("requirements") or {}).items()}
        self.declined: set[str] = set(data.get("declined") or [])
        self.ui: dict = data.get("ui") or {}

    @property
    def when(self) -> str:
        return time.strftime("%d %b %Y %H:%M", time.localtime(self.saved_at)) if self.saved_at else "earlier"

    @property
    def empty(self) -> bool:
        return not self.plans and not self.list_text.strip()


def load(path: Path) -> Restored | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return None
    try:
        return Restored(data)
    except (TypeError, KeyError, ValueError):
        return None  # from an incompatible version: start fresh


def clear(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
