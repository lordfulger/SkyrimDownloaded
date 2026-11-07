"""Command line: ``python -m skyrimdl run my-mods.txt`` (run with no arguments for the window)."""

from __future__ import annotations

import argparse
import getpass
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import Settings, choices_path, load_choices, save_choices
from .engine import (DONE, missing_requirements, FAILED, SENT, SKIPPED, STOPPED, WORKING, Job, ModPlan, Runner,
                     jobs_for, resolve, summary)
from .links import parse_list
from .managers import ManagerError, find_instances, make_target
from .managers.vortex import default_downloads, default_exe_candidates
from .nexus import AuthError, NexusClient, NexusError
from .selection import human_size, visible_options


def _out(msg: str = "") -> None:
    print(msg, flush=True)


# -- choosing files in the console ------------------------------------------

def ask_choice(plan: ModPlan, include_old: bool = False, inp=None) -> None:
    inp = inp or input
    options = visible_options(plan.options, include_old)
    if not options:
        return
    by_author = f" by {plan.mod.author}" if plan.mod and plan.mod.author else ""
    _out()
    _out(f"== {plan.title}{by_author} - {plan.reason}")
    _out(f"   {plan.entry.page_url}?tab=files")

    def show(with_desc: bool) -> None:
        for n, opt in enumerate(options, start=1):
            mark = "x" if opt.file_id in plan.selected else " "
            _out(f"  {n:>2}. [{mark}] {opt.label()}")
            if with_desc and opt.description:
                for line in opt.description.splitlines()[:6]:
                    _out(f"          {line}")

    show(False)
    while True:
        answer = inp("   Files to get (e.g. 1,3), Enter = keep [x], ? = descriptions, 0 = skip mod: ").strip()
        if answer == "":
            if plan.selected:
                break
            _out("   Nothing picked yet: type a number, or 0 to skip this mod.")
            continue
        if answer == "?":
            show(True)
            continue
        if answer == "0":
            plan.selected = []
            break
        try:
            picks = {int(x) for x in answer.replace(" ", ",").split(",") if x}
            if not picks or any(p < 1 or p > len(options) for p in picks):
                raise ValueError
        except ValueError:
            _out(f"   Type numbers from 1 to {len(options)}, separated by commas.")
            continue
        plan.selected = [options[p - 1].file_id for p in sorted(picks)]
        break
    plan.needs_choice = False


# -- commands --------------------------------------------------------------

def cmd_login(args, settings: Settings) -> int:
    key = args.key or getpass.getpass(
        "Paste your Nexus personal API key\n"
        "(https://www.nexusmods.com/settings/api-keys, it won't show as you paste): ")
    try:
        account = NexusClient(key).validate()
    except NexusError as err:
        _out(f"That didn't work: {err}")
        return 1
    settings.set_api_key(key)
    path = settings.save()
    _out(f"Logged in as {account.name} ({account.kind}). Key saved in {path}.")
    if not account.is_premium:
        _out("Note: without Premium, Nexus won't hand out download links to tools, so only "
             "'handoff' mode with links you click on the site will work.")
    return 0


def cmd_detect(args, settings: Settings) -> int:
    _out("Mod Organizer 2 instances (global):")
    instances = find_instances()
    for inst in instances:
        try:
            target = make_target("mo2", settings.game, mo2_instance=str(inst))
            _out(f"  {inst.name}: downloads -> {target.downloads_dir()}")
        except ManagerError as err:
            _out(f"  {inst.name}: {err}")
    if not instances:
        _out("  none found (portable instances: pass --mo2-instance <MO2 folder>)")
    _out("Vortex:")
    d = default_downloads(settings.game)
    _out(f"  downloads -> {d} {'(exists)' if d and d.exists() else '(not found)'}")
    exes = [p for p in default_exe_candidates() if p.is_file()]
    _out(f"  Vortex.exe -> {exes[0] if exes else 'not found (pass --vortex-exe)'}")
    return 0


def _apply_overrides(args, settings: Settings) -> None:
    for name in ("manager", "mode", "parallel", "game", "mo2_instance", "mo2_exe",
                 "vortex_exe"):
        value = getattr(args, name, None)
        if value not in (None, ""):
            setattr(settings, name, value)
    if args.downloads:
        if settings.manager == "mo2":
            settings.mo2_downloads = args.downloads
        else:
            settings.vortex_downloads = args.downloads
    if args.no_install:
        settings.install = False


class _Printer:
    """Prints one line per file as it changes state, plus throttled progress."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last: dict[int, float] = {}

    def __call__(self, job: Job) -> None:
        with self._lock:
            if job.state == WORKING:
                now = time.monotonic()
                if now - self._last.get(id(job), 0) < 5 or not job.done_bytes:
                    return
                self._last[id(job)] = now
                total = f" of {human_size(job.total_bytes)}" if job.total_bytes else ""
                _out(f"  ... {job.label}: {human_size(job.done_bytes)}{total}")
                return
            icon = {DONE: "OK ", SENT: "-> ", SKIPPED: "== ", FAILED: "!! ", STOPPED: "-- "}.get(job.state, "   ")
            _out(f"  {icon}{job.label}: {job.note or job.state}")


def _check_requirements(client, plans, list_path, remembered, args, settings):
    """Warn about requirements missing from the list, and offer to add them."""
    declined: set[str] = set()
    for _round in range(4):  # requirements of requirements, a few levels deep
        missing, checked = missing_requirements(client, plans)
        if not checked:
            _out("(Couldn't ask Nexus for mod requirements; skipping that check.)")
            return plans
        addable = [m for m in missing if not m.requirement.external and m.link not in declined]
        external = [m for m in missing if m.requirement.external]
        if _round == 0 and external:
            _out("Requirements that aren't on Nexus (get these yourself):")
            for m in external:
                _out(f"  - {m.requirement.name} {m.link}  (for {', '.join(m.needed_by)})")
        if not addable:
            return plans
        _out("Requirements missing from your list:")
        for m in addable:
            note = f" - {m.requirement.notes}" if m.requirement.notes else ""
            _out(f"  - {m.requirement.name}  (needed by {', '.join(m.needed_by)}){note}")
        if args.add_requirements:
            add = True
        elif args.yes:
            add = False
        else:
            add = input("Add them to the list? [Y/n] ").strip().lower() in ("", "y", "yes")
        if not add:
            return plans
        lines = [f"{m.link}    # required by {', '.join(m.needed_by)[:80]}" for m in addable]
        declined.update(m.link for m in addable)
        try:
            with open(list_path, "a", encoding="utf-8") as fh:
                fh.write("\n# Added requirements\n" + "\n".join(lines) + "\n")
            _out(f"Added {len(lines)} to {list_path.name}.")
        except OSError as err:
            _out(f"(Couldn't add them to the list file: {err})")
        new_entries, _ = parse_list("\n".join(lines), settings.game)
        plans = plans + resolve(client, new_entries, remembered=remembered)
    return plans


def cmd_run(args, settings: Settings) -> int:
    _apply_overrides(args, settings)
    list_path = Path(args.list)
    try:
        text = list_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as err:
        _out(f"Can't read the list: {err}")
        return 1
    entries, problems = parse_list(text, settings.game)
    for p in problems:
        _out(f"List problem, {p}")
    if not entries:
        _out("No Nexus links or mod numbers found in the list.")
        return 1
    other_games = sorted({e.game for e in entries if e.game != settings.game})
    if other_games:
        _out(f"Note: some links are for other games ({', '.join(other_games)}); "
             f"your mod manager may refuse them.")

    key = args.key or settings.get_api_key()
    try:
        client = NexusClient(key)
        account = client.validate()
    except NexusError as err:
        _out(f"Nexus login failed: {err}\nRun:  python -m skyrimdl login")
        return 1
    _out(f"Logged in as {account.name} ({account.kind}).")
    if settings.mode == "direct" and not account.is_premium:
        _out("Direct downloads need Premium. Use --mode handoff instead.")
        return 1

    try:
        target = make_target(settings.manager, settings.game, **settings.target_paths())
    except ManagerError as err:
        _out(str(err))
        return 1
    issues = [] if args.dry_run else target.problems(settings.mode)
    for issue in issues:
        _out(f"Problem: {issue}")
    if issues:
        return 1

    store = choices_path(list_path)
    remembered = {} if args.fresh else load_choices(store)
    _out(f"Looking up {len(entries)} mods on Nexus...")
    plans = resolve(client, entries, remembered=remembered)
    if not args.no_requirements:
        plans = _check_requirements(client, plans, list_path, remembered, args, settings)

    for plan in plans:
        if plan.error:
            _out(f"  !! {plan.title} ({plan.entry.page_url}): {plan.error}")
    if not args.yes:
        for plan in plans:
            if plan.needs_choice and not plan.error:
                ask_choice(plan, args.include_old)
    save_choices(store, plans)

    jobs = jobs_for(plans)
    total = sum(j.option.approx_bytes or 0 for j in jobs)
    _out()
    _out(f"{len(jobs)} files from {len({id(j.plan) for j in jobs})} mods, about {human_size(total)}.")
    for job in jobs:
        _out(f"  {job.label}  ({job.option.size_text})")
    if args.dry_run:
        _out("Dry run: nothing downloaded.")
        return 0
    if not jobs:
        return 0
    if settings.mode == "handoff":
        _out(f"Sending links to {target.name}. Keep it open on your Skyrim instance/profile.")
    else:
        _out(f"Downloading into {target.downloads_dir()} ({settings.parallel} at a time).")

    cancel = threading.Event()
    runner = Runner(client, target, mode=settings.mode, install=settings.install,
                    parallel=settings.parallel, redownload=args.redownload,
                    on_event=_Printer(), cancel=cancel)
    try:
        runner.run(jobs)
    except KeyboardInterrupt:
        cancel.set()
        _out("Stopping... run the same command again to carry on.")
        return 130
    counts = summary(jobs)
    _out()
    _out("Done: " + ", ".join(f"{n} {state}" for state, n in counts.items()))
    _out(f"Nexus API: {client.rate.describe()}")
    settings.last_list = str(list_path.resolve())
    settings.save()
    return 1 if counts.get(FAILED) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="skyrimdl",
        description="Download a list of Nexus mods into Vortex or Mod Organizer 2. "
                    "Run with no arguments to open the window.")
    p.add_argument("--version", action="version", version=f"SkyrimDownloaded {__version__}")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("gui", help="open the window (the default)")

    login = sub.add_parser("login", help="save your Nexus API key")
    login.add_argument("--key", help="the key (otherwise you're asked for it)")

    sub.add_parser("detect", help="show the MO2 instances and Vortex folders found")

    run = sub.add_parser("run", help="download every mod in a list")
    run.add_argument("list", help="text file of Nexus links / nxm links / mod numbers")
    run.add_argument("--manager", choices=["mo2", "vortex"])
    run.add_argument("--mode", choices=["handoff", "direct"],
                     help="handoff: the mod manager downloads each file; "
                          "direct: this tool downloads into the manager's downloads folder")
    run.add_argument("--no-install", action="store_true",
                     help="Vortex: only download, don't install")
    run.add_argument("--mo2-instance", help="MO2 instance folder or global instance name")
    run.add_argument("--mo2-exe", help="path to ModOrganizer.exe")
    run.add_argument("--vortex-exe", help="path to Vortex.exe")
    run.add_argument("--downloads", help="downloads folder, if not the manager's usual one")
    run.add_argument("--game", help="Nexus game for bare mod numbers (default skyrimspecialedition)")
    run.add_argument("--parallel", type=int, help="downloads at once in direct mode (1-6)")
    run.add_argument("--key", help="Nexus API key for this run (otherwise the saved one)")
    run.add_argument("-y", "--yes", action="store_true",
                     help="don't ask: take the primary file where a mod has options")
    run.add_argument("--fresh", action="store_true", help="ignore the choices saved last time")
    run.add_argument("--include-old", action="store_true", help="also offer old versions")
    run.add_argument("--redownload", action="store_true", help="even if already downloaded")
    run.add_argument("--dry-run", action="store_true", help="look everything up, download nothing")
    run.add_argument("--add-requirements", action="store_true",
                     help="add missing requirements to the list without asking")
    run.add_argument("--no-requirements", action="store_true",
                     help="don't check mods' requirements")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load()
    if args.command in (None, "gui"):
        from .gui import run_gui
        return run_gui(settings)
    try:
        return {"login": cmd_login, "detect": cmd_detect, "run": cmd_run}[args.command](args, settings)
    except AuthError as err:
        _out(str(err))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
