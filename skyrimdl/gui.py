"""The window: log in, pick a mod manager, load a list, choose options, download."""

from __future__ import annotations

import queue
import re
import threading
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .config import Settings, choices_path, load_choices, save_choices
from .engine import (DONE, missing_requirements, FAILED, SENT, SKIPPED, STOPPED, WORKING, Job, ModPlan, Runner,
                     jobs_for, resolve, summary)
from .links import parse_list
from . import finder
from . import theme as theme_mod
from .managers import ManagerError, make_target
from .nexus import NexusClient, NexusError
from . import gameversion
from .engine import rechoose
from .selection import annotate, for_other_versions, human_size, visible_options

API_KEY_PAGE = "https://www.nexusmods.com/settings/api-keys"
ON, OFF = "\u2611", "\u2610"  # ☑ ☐
# A Nexus personal API key: one long run of base64-ish characters, no spaces.
_KEY_SHAPE = re.compile(r"^[A-Za-z0-9+/=_\-]{40,400}$")
CLIPBOARD_WAIT_MS = 5 * 60 * 1000


class App:
    def __init__(self, root: tk.Tk, settings: Settings):
        self.root = root
        self.settings = settings
        self.client: NexusClient | None = None
        self.plans: list[ModPlan] = []
        self.jobs: list[Job] = []
        self.list_path: Path | None = Path(settings.last_list) if settings.last_list else None
        self.events: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self._job_rows: dict[int, str] = {}
        self._row_option: dict[str, tuple[ModPlan, int]] = {}
        self._row_plan: dict[str, ModPlan] = {}
        self.declined: set[str] = set()     # requirement links already offered
        self._list_was_saved = False

        root.title(f"SkyrimDownloaded {__version__}")
        root.geometry("1060x800")
        root.minsize(820, 600)
        self.theme = theme_mod.Theme(root, settings.theme)
        root._theme = self.theme  # dialogs pick it up from their parent
        self._watching_clipboard = False
        self._clip_seen: set[str] = set()
        self._build()
        self.theme.apply()
        self._load_settings()
        root.after(100, self._pump)
        root.protocol("WM_DELETE_WINDOW", self._close)

    # -- layout ---------------------------------------------------------------

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        # Account
        acct = ttk.LabelFrame(outer, text="1. Nexus Mods account")
        acct.pack(fill="x", **pad)
        top_row = ttk.Frame(acct)
        top_row.pack(fill="x", padx=6, pady=(6, 2))
        self.nexus_btn = ttk.Button(top_row, text="Log in with Nexus", style="Accent.TButton",
                                    command=self.nexus_login)
        self.nexus_btn.pack(side="left")
        self.account_var = tk.StringVar(value="Not logged in")
        ttk.Label(top_row, textvariable=self.account_var).pack(side="left", padx=10)
        self.theme_var = tk.StringVar(value=self.settings.theme if self.settings.theme in theme_mod.MODES
                                      else "System")
        theme_box = ttk.Combobox(top_row, textvariable=self.theme_var, values=theme_mod.MODES,
                                 state="readonly", width=8)
        theme_box.pack(side="right")
        theme_box.bind("<<ComboboxSelected>>", lambda e: self._theme_changed())
        ttk.Label(top_row, text="Theme:").pack(side="right", padx=(0, 4))

        key_row = ttk.Frame(acct)
        key_row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Label(key_row, text="Or paste your API key:", style="Muted.TLabel").pack(side="left")
        self.key_var = tk.StringVar()
        ttk.Entry(key_row, textvariable=self.key_var, show="\u2022").pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(key_row, text="Use key", command=self.login).pack(side="left")
        self.logout_btn = ttk.Button(key_row, text="Log out", command=self.logout)
        self.logout_btn.pack(side="left", padx=(4, 0))

        # Mod manager
        mgr = ttk.LabelFrame(outer, text="2. Mod manager")
        mgr.pack(fill="x", **pad)
        self.manager_var = tk.StringVar(value="mo2")
        self.mode_var = tk.StringVar(value="handoff")
        self.install_var = tk.BooleanVar(value=True)
        top = ttk.Frame(mgr)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Radiobutton(top, text="Mod Organizer 2", value="mo2", variable=self.manager_var,
                        command=self._manager_changed).pack(side="left")
        ttk.Radiobutton(top, text="Vortex", value="vortex", variable=self.manager_var,
                        command=self._manager_changed).pack(side="left", padx=12)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Radiobutton(top, text="Mod manager downloads (recommended)", value="handoff",
                        variable=self.mode_var).pack(side="left")
        ttk.Radiobutton(top, text="Download here, into its downloads folder", value="direct",
                        variable=self.mode_var).pack(side="left", padx=12)
        self.install_check = ttk.Checkbutton(top, text="Install after download", variable=self.install_var)
        self.install_check.pack(side="left", padx=12)

        self.paths = ttk.Frame(mgr)
        self.paths.pack(fill="x", padx=6, pady=(0, 6))
        self.path_vars = {k: tk.StringVar() for k in
                          ("mo2_instance", "mo2_exe", "mo2_downloads", "vortex_downloads", "vortex_exe")}
        self.path_rows = {
            "mo2": [
                ("MO2 instance (folder with ModOrganizer.ini)", "mo2_instance", "dir"),
                ("ModOrganizer.exe", "mo2_exe", "exe"),
                ("Downloads folder (blank = instance's)", "mo2_downloads", "dir"),
            ],
            "vortex": [
                ("Vortex downloads folder (blank = default)", "vortex_downloads", "dir"),
                ("Vortex.exe (blank = default)", "vortex_exe", "exe"),
            ],
        }
        found = ttk.Frame(mgr)
        found.pack(fill="x", padx=6, pady=(0, 6))
        self.find_btn = ttk.Button(found, text="\U0001F50D Find automatically",
                                   command=lambda: self.find_folders(deep=True))
        self.find_btn.pack(side="left")
        self.where_var = tk.StringVar()
        ttk.Label(found, textvariable=self.where_var, style="Muted.TLabel").pack(side="left", fill="x", padx=8)
        self.found: finder.Findings | None = None

        game = ttk.Frame(mgr)
        game.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Label(game, text="Your Skyrim:").pack(side="left")
        self.version_var = tk.StringVar()
        self.version_box = ttk.Combobox(game, textvariable=self.version_var, width=58,
                                        values=[label for label, _ in gameversion.PRESETS])
        self.version_box.pack(side="left", padx=6)
        self.version_box.bind("<<ComboboxSelected>>", lambda e: self._version_changed())
        self.version_box.bind("<Return>", lambda e: self._version_changed())
        self.version_box.bind("<FocusOut>", lambda e: self._version_changed())
        ttk.Label(game, text="from").pack(side="left")
        self.store_var = tk.StringVar(value="Steam")
        store_box = ttk.Combobox(game, textvariable=self.store_var, values=gameversion.STORES,
                                 state="readonly", width=10)
        store_box.pack(side="left", padx=6)
        store_box.bind("<<ComboboxSelected>>", lambda e: self._version_changed())
        self.detect_btn = ttk.Button(game, text="Detect", command=lambda: self.detect_game(quiet=False))
        self.detect_btn.pack(side="left")
        self.game_note_var = tk.StringVar(value="Files for other versions are left out.")
        ttk.Label(game, textvariable=self.game_note_var, style="Muted.TLabel").pack(side="left", padx=8)

        # List
        lst = ttk.LabelFrame(outer, text="3. Mod list (Nexus links, nxm:// links or mod numbers, one per line)")
        lst.pack(fill="x", **pad)
        bar = ttk.Frame(lst)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Open list…", command=self.open_list).pack(side="left")
        ttk.Button(bar, text="Save list…", command=self.save_list).pack(side="left", padx=4)
        self.list_label = tk.StringVar(value="(type or paste links below)")
        ttk.Label(bar, textvariable=self.list_label).pack(side="left", padx=8)
        self.lookup_btn = ttk.Button(bar, text="Look up mods ▶", command=self.lookup)
        self.lookup_btn.pack(side="right")
        self.fresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Forget last choices", variable=self.fresh_var).pack(side="right", padx=8)
        self.list_text = tk.Text(lst, height=5, wrap="none", undo=True, relief="flat",
                                 highlightthickness=1)
        self.list_text.pack(fill="x", padx=6, pady=(0, 6))

        # Plan
        plan = ttk.LabelFrame(outer, text="4. Files to get (click the box or double-click a file to tick/untick it)")
        plan.pack(fill="both", expand=True, **pad)
        tools = ttk.Frame(plan)
        tools.pack(fill="x", padx=6, pady=4)
        ttk.Button(tools, text="Choose options…", command=self.walk_choices).pack(side="left")
        ttk.Button(tools, text="Open mod page", command=self.open_page).pack(side="left", padx=4)
        self.old_var = tk.BooleanVar(value=False)
        self.other_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="Show files for other game versions", variable=self.other_var,
                        command=self._fill_tree).pack(side="left", padx=8)
        ttk.Checkbutton(tools, text="Show old versions", variable=self.old_var,
                        command=self._fill_tree).pack(side="left", padx=8)
        self.plan_var = tk.StringVar()
        ttk.Label(tools, textvariable=self.plan_var).pack(side="right")

        cols = ("get", "type", "version", "size", "status")
        frame = ttk.Frame(plan)
        frame.pack(fill="both", expand=True, padx=6)
        self.tree = ttk.Treeview(frame, columns=cols, show="tree headings", selectmode="browse")
        for col, text, width in (("#0", "Mod / file", 420), ("get", "Get", 44), ("type", "Type", 80),
                                 ("version", "Version", 90), ("size", "Size", 80),
                                 ("status", "Status", 260)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=col in ("#0", "status"),
                             anchor="center" if col == "get" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._tree_click)
        self.tree.bind("<space>", lambda e: self._toggle(self.tree.focus()))
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        self.tree.bind("<Double-1>", self._tree_double)

        self.details = tk.Text(plan, height=4, wrap="word", state="disabled", relief="flat",
                               highlightthickness=1)
        self.details._details = True
        self.details.pack(fill="x", padx=6, pady=6)

        # Go
        go = ttk.Frame(outer)
        # Packed first at the bottom, so it never gets squeezed off a small window.
        go.pack(side="bottom", fill="x", before=outer.winfo_children()[0], **pad)
        self.progress = ttk.Progressbar(go, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(go, textvariable=self.status_var, width=46).pack(side="left", padx=8)
        self.stop_btn = ttk.Button(go, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right")
        self.start_btn = ttk.Button(go, text="Start downloads ▶", command=self.start)
        self.start_btn.pack(side="right", padx=4)

    def _manager_changed(self) -> None:
        for child in self.paths.winfo_children():
            child.destroy()
        kind = self.manager_var.get()
        for row, (label, key, what) in enumerate(self.path_rows[kind]):
            ttk.Label(self.paths, text=label + ":").grid(row=row, column=0, sticky="w", pady=2)
            if key == "mo2_instance":
                names = [str(m.instance_dir) for m in self.found.sorted_mo2()] if self.found else []
                widget = ttk.Combobox(self.paths, textvariable=self.path_vars[key], values=names)
                widget.bind("<<ComboboxSelected>>", lambda e: self._instance_picked())
            else:
                widget = ttk.Entry(self.paths, textvariable=self.path_vars[key])
            widget.grid(row=row, column=1, sticky="we", padx=6)
            ttk.Button(self.paths, text="Browse…",
                       command=lambda k=key, w=what: self._browse(k, w)).grid(row=row, column=2)
        self.paths.columnconfigure(1, weight=1)
        self.install_check.configure(state="normal" if kind == "vortex" else "disabled")
        self._update_where()

    # -- your game version ------------------------------------------------------

    def _target_game(self) -> "gameversion.GameTarget":
        text = self.version_var.get().strip()
        version = next((v for label, v in gameversion.PRESETS if label == text), None)
        if version is None:
            version = text if gameversion.parse_version(text) else ""
        return gameversion.GameTarget.from_settings(version, self.store_var.get())

    def _version_changed(self) -> None:
        target = self._target_game()
        if target.describe() == getattr(self, "_last_target", None):
            return
        self._last_target = target.describe()
        if not target.active and self.version_var.get().strip() not in ("", gameversion.PRESETS[0][0]):
            self.game_note_var.set("Type a version like 1.6.1170, or pick one from the list.")
            return
        self.game_note_var.set("Files for other versions are left out." if target.active
                               else "Showing files for every game version.")
        self._save_settings()
        # Re-pick files for mods you haven't chosen by hand.
        for plan in self.plans:
            if plan.error or plan.skipped or not plan.options:
                continue
            if plan.reason in ("your choice", "your earlier choice"):
                annotate(plan.options, target)
                if not any(o.fit.hidden for o in plan.selected_options()):
                    continue  # still fine for the new version: keep it
                rechoose(plan, None, target)
                plan.needs_choice = True
                plan.reason = "your pick was for another game version - check it"
            else:
                rechoose(plan, None, target)
        if self.plans:
            self._fill_tree()

    def detect_game(self, quiet: bool) -> None:
        instance = self.path_vars["mo2_instance"].get().strip() if self.manager_var.get() == "mo2" else ""

        def work():
            games = gameversion.find_games(gameversion.mo2_game_path(instance))
            self.events.put(("games", (games, quiet)))
        threading.Thread(target=work, daemon=True).start()

    def _games_found(self, games, quiet: bool) -> None:
        with_version = [g for g in games if g.version]
        if not with_version:
            if not quiet:
                messagebox.showinfo(
                    "Detect", "Couldn't find SkyrimSE.exe to read its version.\n\nPick your version "
                    "from the list instead: the game's version is shown at the bottom left of "
                    "the main menu.", parent=self.root)
            return
        game = with_version[0]
        if not quiet and len({(g.version, g.store) for g in with_version}) > 1:
            game = pick_one(self.root, "Which Skyrim?", "More than one Skyrim install was found:",
                            with_version, lambda g: g.describe()) or game
        self.version_var.set(gameversion.preset_label(gameversion.version_text(game.version)))
        self.store_var.set(game.store)
        self._version_changed()
        self.game_note_var.set(f"Detected from {game.exe} (via {game.found_by})")

    # -- finding MO2 / Vortex -------------------------------------------------

    def find_folders(self, deep: bool) -> None:
        """Search this PC for MO2 / Vortex and fill in the folders."""
        interactive = deep

        def work():
            found = finder.find(deep=deep, budget=60.0,
                                progress=lambda msg: self.events.put(("where", msg)))
            self.events.put(("found", (found, interactive)))
        if deep:
            self.where_var.set("Searching this PC for Mod Organizer 2 and Vortex\u2026")
        self._background(work)

    def _apply_found(self, found: "finder.Findings", interactive: bool) -> None:
        self.found = found
        filled: list[str] = []
        v = self.path_vars

        # MO2: the instance (and its exe).
        instances = found.sorted_mo2()
        if instances and (interactive or not v["mo2_instance"].get()):
            pick = found.best_mo2()
            if pick is None and interactive:
                pick = pick_one(self.root, "Which MO2 setup?",
                                "More than one Mod Organizer 2 setup was found. Pick the one "
                                "for Skyrim Special / Anniversary Edition:",
                                instances, lambda m: m.describe())
            elif pick is None:
                pick = instances[0] if instances[0].is_skyrim_se else None
            if pick:
                v["mo2_instance"].set(str(pick.instance_dir))
                filled.append(f"MO2 instance: {pick.describe()}")
                if pick.exe and (interactive or not v["mo2_exe"].get()):
                    v["mo2_exe"].set(str(pick.exe))
                    filled.append(f"ModOrganizer.exe: {pick.exe}")
        elif found.mo2_exes and (interactive or not v["mo2_exe"].get()):
            v["mo2_exe"].set(str(found.mo2_exes[0]))
            filled.append(f"ModOrganizer.exe: {found.mo2_exes[0]}")

        # Vortex: exe and downloads folder.
        vx = found.vortex
        if vx.exe and (interactive or not v["vortex_exe"].get()):
            v["vortex_exe"].set(str(vx.exe))
            filled.append(f"Vortex.exe: {vx.exe}")
        if vx.downloads_root and (interactive or not v["vortex_downloads"].get()):
            v["vortex_downloads"].set(str(vx.downloads_root))
            filled.append(f"Vortex downloads: {vx.downloads_root}")

        self._manager_changed()  # refresh the instance list and "Downloads go to"
        if interactive:
            if filled:
                more = ""
                if found.timed_out:
                    more = "\n\n(The drive search stopped after a minute; use Browse if something's missing.)"
                messagebox.showinfo("Found", "Filled in:\n\n" + "\n".join(filled) + more, parent=self.root)
            else:
                messagebox.showinfo(
                    "Nothing found",
                    "Couldn't find Mod Organizer 2 or Vortex on this PC.\n\n"
                    "Use Browse to pick the folders yourself: for MO2, the folder with "
                    "ModOrganizer.ini in it.", parent=self.root)

    def _instance_picked(self) -> None:
        """Choosing an instance from the list also fills in its ModOrganizer.exe."""
        if not self.found:
            return
        chosen = self.path_vars["mo2_instance"].get()
        for inst in self.found.mo2:
            if str(inst.instance_dir) == chosen and inst.exe:
                self.path_vars["mo2_exe"].set(str(inst.exe))
        self._update_where()

    def _browse(self, key: str, what: str) -> None:
        if what == "dir":
            path = filedialog.askdirectory(title="Choose folder", mustexist=False)
        else:
            path = filedialog.askopenfilename(title="Choose program",
                                              filetypes=[("Programs", "*.exe"), ("All files", "*")])
        if path:
            self.path_vars[key].set(path)
            self._update_where()

    def _update_where(self) -> None:
        try:
            target = self._target()
            self.where_var.set(f"Downloads go to: {target.downloads_dir()}")
        except ManagerError as err:
            self.where_var.set(str(err))

    # -- settings ---------------------------------------------------------------

    def _load_settings(self) -> None:
        s = self.settings
        # Fill these in first: logging in below saves settings, which reads them.
        self.version_var.set(gameversion.preset_label(s.game_version))
        self.store_var.set(s.game_store if s.game_store in gameversion.STORES else "Steam")
        self._last_target = self._target_game().describe()
        self.key_var.set(s.get_api_key())
        self.manager_var.set(s.manager if s.manager in ("mo2", "vortex") else "mo2")
        self.mode_var.set(s.mode if s.mode in ("handoff", "direct") else "handoff")
        self.install_var.set(s.install)
        for key, var in self.path_vars.items():
            var.set(getattr(s, key, ""))
        for var in self.path_vars.values():
            var.trace_add("write", lambda *a: self._update_where())
        self._manager_changed()
        if self.list_path and self.list_path.is_file():
            self._read_list(self.list_path)
        if self.key_var.get():
            self.login(quiet=True)
        # Fill in whatever's still blank from a quick look around (registry, usual places).
        self.find_folders(deep=False)
        if not s.game_version:
            self.root.after(300, lambda: self.detect_game(quiet=True))

    def _save_settings(self) -> None:
        s = self.settings
        s.manager = self.manager_var.get()
        s.mode = self.mode_var.get()
        s.install = self.install_var.get()
        for key, var in self.path_vars.items():
            setattr(s, key, var.get().strip())
        s.set_api_key(self.key_var.get())
        s.theme = self.theme_var.get()
        s.game_version = gameversion.version_text(self._target_game().version)
        s.game_store = self.store_var.get()
        s.last_list = str(self.list_path) if self.list_path else ""
        try:
            s.save()
        except OSError:
            pass

    def _target(self):
        paths = {k: v.get().strip() for k, v in self.path_vars.items()}
        return make_target(self.manager_var.get(), self.settings.game, **paths)

    # -- background work --------------------------------------------------------

    def _background(self, fn, *args) -> None:
        def work():
            try:
                fn(*args)
            except Exception as err:  # report, don't die silently
                self.events.put(("error", str(err)))
            finally:
                self.events.put(("idle", None))
        self._set_busy(True)
        threading.Thread(target=work, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self._busy_count = max(0, getattr(self, "_busy_count", 0) + (1 if busy else -1))
        busy = self._busy_count > 0
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.lookup_btn.configure(state=state)
        self.find_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _pump(self) -> None:
        dirty_jobs = set()
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "account":
                    self.account_var.set(payload)
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "lookup-progress":
                    done, total = payload
                    self.progress.configure(maximum=total, value=done)
                    self.status_var.set(f"Looked up {done} of {total} mods")
                elif kind == "plans":
                    self.plans = payload
                    self._fill_tree()
                    waiting = sum(1 for p in self.plans if p.needs_choice and not p.error)
                    self.status_var.set(f"{len(self.plans)} mods looked up"
                                        + (f", {waiting} have options to choose" if waiting else "")
                                        + ". Checking requirements\u2026")
                    self._check_requirements()
                elif kind == "clipboard-login":
                    self._clipboard_login_done(*payload)
                elif kind == "where":
                    self.where_var.set(payload)
                elif kind == "games":
                    self._games_found(*payload)
                elif kind == "found":
                    self._apply_found(*payload)
                elif kind == "requirements":
                    self._requirements_done(*payload)
                elif kind == "job":
                    dirty_jobs.add(id(payload))
                elif kind == "finished":
                    self._finished(payload)
                elif kind == "error":
                    messagebox.showerror("SkyrimDownloaded", payload, parent=self.root)
                elif kind == "idle":
                    self._set_busy(False)
        except queue.Empty:
            pass
        if dirty_jobs:
            self._refresh_jobs(dirty_jobs)
        self.root.after(150, self._pump)

    # -- account ----------------------------------------------------------------

    # -- logging in with Nexus ------------------------------------------------

    def nexus_login(self) -> None:
        """Open Nexus's key page and log in as soon as the key is copied."""
        if self._watching_clipboard:
            self._stop_clipboard_watch("Not logged in")
            return
        webbrowser.open(API_KEY_PAGE)
        self._watching_clipboard = True
        self._clip_seen = set()
        self.nexus_btn.configure(text="Cancel")
        self.account_var.set("In your browser: log in to Nexus if asked, then click Copy next to "
                             "your Personal API Key (or select it and press Ctrl+C)\u2026")
        self.root.after(CLIPBOARD_WAIT_MS, lambda: self._watching_clipboard and
                        self._stop_clipboard_watch("Gave up waiting for the key - try again"))
        self._poll_clipboard()

    def _poll_clipboard(self) -> None:
        if not self._watching_clipboard:
            return
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if text and text not in self._clip_seen and _KEY_SHAPE.match(text):
            self._clip_seen.add(text)
            self._try_clipboard_key(text)
        self.root.after(700, self._poll_clipboard)

    def _try_clipboard_key(self, key: str) -> None:
        def work():
            try:
                client = NexusClient(key)
                acct = client.validate()
            except NexusError:
                return  # not a key (or not this one): keep waiting
            self.events.put(("clipboard-login", (key, client, acct)))
        threading.Thread(target=work, daemon=True).start()

    def _clipboard_login_done(self, key, client, acct) -> None:
        if not self._watching_clipboard:
            return
        self._stop_clipboard_watch(f"Logged in as {acct.name} ({acct.kind})")
        self.client = client
        self.key_var.set(key)
        self._save_settings()
        try:  # don't leave the key sitting on the clipboard
            self.root.clipboard_clear()
        except tk.TclError:
            pass
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if not acct.is_premium:
            messagebox.showwarning("SkyrimDownloaded", "This account isn't Premium. Nexus only gives "
                                   "download links to tools for Premium accounts.", parent=self.root)

    def _stop_clipboard_watch(self, message: str) -> None:
        self._watching_clipboard = False
        self.nexus_btn.configure(text="Log in with Nexus")
        self.account_var.set(message)

    def logout(self) -> None:
        self._watching_clipboard = False
        self.client = None
        self.key_var.set("")
        self.settings.set_api_key("")
        self.nexus_btn.configure(text="Log in with Nexus")
        self.account_var.set("Logged out")
        self._save_settings()

    def _theme_changed(self) -> None:
        self.theme.apply(self.theme_var.get())
        self.settings.theme = self.theme_var.get()
        self._save_settings()

    def login(self, quiet: bool = False) -> None:
        key = self.key_var.get().strip()
        if not key:
            if not quiet:
                messagebox.showinfo("SkyrimDownloaded",
                                    "Paste your personal API key from Nexus Mods first.\n\n"
                                    "It's at the bottom of " + API_KEY_PAGE, parent=self.root)
            return

        def work():
            try:
                client = NexusClient(key)
                acct = client.validate()
            except NexusError as err:
                self.events.put(("account", f"Login failed: {err}"))
                return
            self.client = client
            self.events.put(("account", f"Logged in as {acct.name} ({acct.kind})"))
            if not acct.is_premium and not quiet:
                self.events.put(("error", "This account isn't Premium. Nexus only gives "
                                          "download links to tools for Premium accounts."))
        self.account_var.set("Checking…")
        threading.Thread(target=work, daemon=True).start()
        self._save_settings()

    # -- list -------------------------------------------------------------------

    def _read_list(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as err:
            messagebox.showerror("SkyrimDownloaded", f"Can't read {path}:\n{err}", parent=self.root)
            return
        self.list_path = path
        self.list_label.set(str(path))
        self.list_text.delete("1.0", "end")
        self.list_text.insert("1.0", text)

    def open_list(self) -> None:
        path = filedialog.askopenfilename(title="Open mod list",
                                          filetypes=[("Text files", "*.txt *.md *.csv"), ("All files", "*")])
        if path:
            self._read_list(Path(path))

    def save_list(self) -> None:
        path = filedialog.asksaveasfilename(title="Save mod list", defaultextension=".txt",
                                            filetypes=[("Text files", "*.txt")])
        if path:
            Path(path).write_text(self.list_text.get("1.0", "end-1c"), encoding="utf-8")
            self.list_path = Path(path)
            self.list_label.set(path)

    def _list_is_saved(self) -> bool:
        if not self.list_path or not self.list_path.is_file():
            return False
        try:
            on_disk = self.list_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return False
        return on_disk.rstrip() == self.list_text.get("1.0", "end-1c").rstrip()

    def lookup(self) -> None:
        if self.client is None:
            messagebox.showinfo("SkyrimDownloaded", "Log in with your API key first.", parent=self.root)
            return
        entries, problems = parse_list(self.list_text.get("1.0", "end-1c"), self.settings.game)
        if problems:
            messagebox.showwarning("Problems in the list", "\n".join(problems[:20]), parent=self.root)
        if not entries:
            messagebox.showinfo("SkyrimDownloaded", "No Nexus links or mod numbers in the list.", parent=self.root)
            return
        others = sorted({e.game for e in entries if e.game != self.settings.game})
        if others and not messagebox.askyesno(
                "Other games", "Some links are for other games (" + ", ".join(others)
                + "). Your mod manager may refuse them. Carry on?", parent=self.root):
            return
        self._list_was_saved = self._list_is_saved()
        store = choices_path(self.list_path) if self._list_was_saved else None
        remembered = {} if self.fresh_var.get() else load_choices(store)
        if not self.fresh_var.get():  # keep what was ticked in this window
            remembered.update({p.entry.key: list(p.selected) for p in self.plans
                               if p.selected and not p.needs_choice and not p.error
                               and p.reason in ("your choice", "your earlier choice")})
        self._save_settings()
        client = self.client
        target = self._target_game()

        def work():
            plans = resolve(client, entries, remembered=remembered, target=target,
                            on_progress=lambda d, t, p: self.events.put(("lookup-progress", (d, t))))
            self.events.put(("plans", plans))
        self._background(work)

    def _check_requirements(self) -> None:
        client, plans = self.client, list(self.plans)

        def work():
            missing, checked = missing_requirements(client, plans)
            self.events.put(("requirements", (missing, checked)))
        self._background(work)

    def _requirements_done(self, missing, checked) -> None:
        waiting = sum(1 for p in self.plans if p.needs_choice and not p.error)
        self.status_var.set(f"{len(self.plans)} mods looked up"
                            + (f", {waiting} have options to choose" if waiting else "")
                            + ("" if checked else " (couldn't check requirements)"))
        addable = [m for m in missing if not m.requirement.external and m.link not in self.declined]
        external = [m for m in missing if m.requirement.external and m.link not in self.declined]
        if addable or external:
            lines = []
            if addable:
                lines.append("These mods need others that aren't in your list:\n")
                lines += [f"\u2022 {m.requirement.name}  (needed by {', '.join(m.needed_by)})"
                          + (f"\n     {m.requirement.notes}" if m.requirement.notes else "")
                          for m in addable[:25]]
            if external:
                lines.append("\nNot on Nexus, get these yourself:")
                lines += [f"\u2022 {m.requirement.name}: {m.link}" for m in external[:10]]
            self.declined.update(m.link for m in external)
            if addable:
                lines.append("\nAdd the missing Nexus mods to the list?")
                add = messagebox.askyesno("Missing requirements", "\n".join(lines), parent=self.root)
                self.declined.update(m.link for m in addable)
                if add:
                    text = "\n# Added requirements\n" + "\n".join(
                        f"{m.link}    # required by {', '.join(m.needed_by)[:80]}" for m in addable)
                    body = self.list_text.get("1.0", "end-1c").rstrip("\n")
                    self.list_text.delete("1.0", "end")
                    self.list_text.insert("1.0", body + "\n" + text + "\n")
                    if self.list_path and self._list_was_saved:
                        self.list_path.write_text(self.list_text.get("1.0", "end-1c"), encoding="utf-8")
                    self.root.after(50, self.lookup)
                    return
            else:
                messagebox.showinfo("Requirements", "\n".join(lines), parent=self.root)
        if waiting:
            self.root.after(50, self.walk_choices)

    # -- the plan tree -------------------------------------------------------

    def _fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._row_option.clear()
        self._row_plan.clear()
        self._job_rows.clear()
        for plan in self.plans:
            tags = ("error",) if plan.error else ("choose",) if plan.needs_choice else ()
            if plan.error:
                status = plan.error
            elif plan.skipped:
                status, tags = "skipped in the list", ("off",)
            elif plan.needs_choice:
                status = "Choose files: " + plan.reason
            else:
                status = plan.reason
            author = f"  by {plan.mod.author}" if plan.mod and plan.mod.author else ""
            row = self.tree.insert("", "end", text=f"{plan.title}{author}", open=plan.needs_choice,
                                   values=("", "", plan.mod.version if plan.mod else "", "", status),
                                   tags=tags)
            self._row_plan[row] = plan
            for opt in visible_options(plan.options, self.old_var.get(), self.other_var.get()):
                on = opt.file_id in plan.selected
                child = self.tree.insert(row, "end", text=opt.name,
                                         values=(ON if on else OFF, opt.category_label, opt.version,
                                                 opt.size_text, _file_status(opt)),
                                         tags=() if on else ("off",))
                self._row_option[child] = (plan, opt.file_id)
            # Selected files that are hidden (e.g. an old version linked in the list).
            shown = {fid for (_, fid) in (self._row_option[c] for c in self.tree.get_children(row))}
            for fid in plan.selected:
                opt = plan.option(fid)
                if opt and fid not in shown:
                    child = self.tree.insert(row, "end", text=opt.name,
                                             values=(ON, opt.category_label, opt.version, opt.size_text, ""))
                    self._row_option[child] = (plan, fid)
        self._update_plan_summary()

    def _update_plan_summary(self) -> None:
        jobs = jobs_for(self.plans)
        size = sum(j.option.approx_bytes or 0 for j in jobs)
        self.plan_var.set(f"{len(jobs)} files, about {human_size(size)}")

    def _tree_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1":
            self._toggle(row)

    def _tree_double(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row in self._row_option:
            if self.tree.identify_column(event.x) != "#1":  # single click there already toggled
                self._toggle(row)
        elif row:
            self.open_page()

    def _toggle(self, row: str) -> None:
        if self.busy or row not in self._row_option:
            return
        plan, fid = self._row_option[row]
        if fid in plan.selected:
            plan.selected.remove(fid)
        else:
            plan.selected.append(fid)
        on = fid in plan.selected
        self.tree.set(row, "get", ON if on else OFF)
        self.tree.item(row, tags=() if on else ("off",))
        self._mark_chosen(plan)
        self._update_plan_summary()

    def _mark_chosen(self, plan: ModPlan) -> None:
        plan.needs_choice = False
        plan.reason = "your choice" if plan.selected else "nothing ticked - mod left out"
        for row, p in self._row_plan.items():
            if p is plan:
                self.tree.item(row, tags=())
                self.tree.set(row, "status", plan.reason)

    def _show_details(self, _event=None) -> None:
        row = self.tree.focus()
        text = ""
        if row in self._row_option:
            plan, fid = self._row_option[row]
            opt = plan.option(fid)
            if opt:
                text = f"{opt.name}  ({opt.file_name}, {opt.size_text})\n{opt.description or 'No description.'}"
        elif row in self._row_plan:
            plan = self._row_plan[row]
            text = plan.entry.page_url + "\n" + (plan.mod.summary if plan.mod else (plan.error or ""))
            if plan.entry.note:
                text += f"\nYour note: {plan.entry.note}"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _focused_plan(self) -> ModPlan | None:
        row = self.tree.focus()
        if row in self._row_option:
            return self._row_option[row][0]
        return self._row_plan.get(row)

    def open_page(self) -> None:
        plan = self._focused_plan()
        if plan:
            webbrowser.open(plan.entry.page_url + "?tab=files")

    def walk_choices(self) -> None:
        """Step through every mod with options, one at a time, like a collection install."""
        waiting = [p for p in self.plans if p.needs_choice and not p.error]
        plans = waiting or [p for p in self.plans if not p.error and len(visible_options(p.options)) > 1]
        if not plans:
            messagebox.showinfo("SkyrimDownloaded", "No mods with options to choose.", parent=self.root)
            return
        ChoiceDialog(self.root, plans, self.old_var.get(), self.other_var.get()).wait_window()
        self._fill_tree()

    # -- downloading ------------------------------------------------------------

    def start(self) -> None:
        if not self.plans:
            messagebox.showinfo("SkyrimDownloaded", "Look up the mods in your list first.", parent=self.root)
            return
        waiting = [p for p in self.plans if p.needs_choice and not p.error]
        if waiting and not messagebox.askyesno(
                "Options not chosen",
                f"{len(waiting)} mods have options you haven't looked at "
                "(highlighted). Use the ticked files for them?", parent=self.root):
            self.walk_choices()
            return
        try:
            target = self._target()
        except ManagerError as err:
            messagebox.showerror("SkyrimDownloaded", str(err), parent=self.root)
            return
        mode = self.mode_var.get()
        issues = target.problems(mode)
        if issues:
            messagebox.showerror("SkyrimDownloaded", "\n\n".join(issues), parent=self.root)
            return
        if mode == "direct" and self.client and self.client._account and not self.client._account.is_premium:
            messagebox.showerror("SkyrimDownloaded", "Downloading here needs a Premium account. "
                                 "Choose 'Mod manager downloads' instead.", parent=self.root)
            return
        if mode == "handoff" and not messagebox.askokcancel(
                "Ready?", f"Open {target.name} on your Skyrim setup now, then press OK.\n\n"
                f"Each file is sent to {target.name}, which downloads it with your Nexus login"
                + (" and installs it (you'll see installer options there)."
                   if target.name == "Vortex" and self.install_var.get() else "."),
                parent=self.root):
            return
        self._save_settings()
        if self._list_is_saved():
            try:
                save_choices(choices_path(self.list_path), self.plans)
            except OSError:
                pass
        self.jobs = jobs_for(self.plans)
        if not self.jobs:
            messagebox.showinfo("SkyrimDownloaded", "No files ticked.", parent=self.root)
            return
        self._map_job_rows()
        for row, plan in self._row_plan.items():  # show each file's progress
            self.tree.item(row, open=bool(plan.selected) and not plan.error)
        total = sum(j.option.approx_bytes or 0 for j in self.jobs) or 1
        self.progress.configure(maximum=total, value=0)
        self.cancel = threading.Event()
        runner = Runner(self.client, target, mode=mode, install=self.install_var.get(),
                        parallel=self.settings.parallel,
                        on_event=lambda job: self.events.put(("job", job)), cancel=self.cancel)
        jobs = self.jobs

        def work():
            runner.run(jobs)
            self.events.put(("finished", jobs))
        self._background(work)

    def _map_job_rows(self) -> None:
        self._job_rows.clear()
        for row, (plan, fid) in self._row_option.items():
            for job in self.jobs:
                if job.plan is plan and job.option.file_id == fid:
                    self._job_rows[id(job)] = row

    def _refresh_jobs(self, ids: set[int]) -> None:
        for job in self.jobs:
            if id(job) not in ids:
                continue
            row = self._job_rows.get(id(job))
            if not row or not self.tree.exists(row):
                continue
            if job.state == WORKING and job.total_bytes:
                pct = 100 * job.done_bytes // max(job.total_bytes, 1)
                text = f"downloading {pct}% of {human_size(job.total_bytes)}"
            else:
                text = job.note or job.state
            self.tree.set(row, "status", text)
            if job.state in (DONE, SENT, SKIPPED):
                self.tree.item(row, tags=("done",))
            elif job.state == FAILED:
                self.tree.item(row, tags=("error",))
        done_bytes = sum(min(j.done_bytes, j.total_bytes or j.done_bytes) for j in self.jobs
                         if j.state in (WORKING, DONE, SKIPPED, STOPPED))
        done_bytes += sum(j.option.approx_bytes or 0 for j in self.jobs if j.state == SENT)
        self.progress.configure(value=done_bytes)
        finished = sum(1 for j in self.jobs if j.state in (DONE, SENT, SKIPPED, FAILED, STOPPED))
        self.status_var.set(f"{finished} of {len(self.jobs)} files")

    def _finished(self, jobs: list[Job]) -> None:
        counts = summary(jobs)
        self._refresh_jobs({id(j) for j in jobs})
        text = ", ".join(f"{n} {state}" for state, n in counts.items())
        self.status_var.set("Finished: " + text)
        failed = [j for j in jobs if j.state == FAILED]
        msg = "Finished: " + text
        if failed:
            msg += "\n\nThese didn't work:\n" + "\n".join(f"• {j.label}: {j.note}" for j in failed[:15])
        if self.mode_var.get() == "direct" and self.manager_var.get() == "mo2" and counts.get(DONE):
            msg += "\n\nIn MO2, open the Downloads tab and install the new downloads."
        messagebox.showinfo("SkyrimDownloaded", msg, parent=self.root)

    def stop(self) -> None:
        self.cancel.set()
        self.status_var.set("Stopping…")

    def _close(self) -> None:
        if self.busy and not messagebox.askyesno(
                "Quit?", "Downloads are still going. Stop and quit? (Start again later "
                "to pick up where it left off.)", parent=self.root):
            return
        self.cancel.set()
        self._save_settings()
        self.root.destroy()


def _file_status(opt) -> str:
    bits = []
    if opt.is_primary:
        bits.append("primary")
    if opt.fit.status == "ok" and opt.fit.note:
        bits.append(opt.fit.note)
    elif opt.fit.status == "other":
        bits.append(f"{opt.fit.note} (not your version)")
    elif opt.fit.note:
        bits.append(opt.fit.note)
    return " \u00b7 ".join(bits)


def pick_one(master, title: str, prompt: str, items: list, describe):
    """A small list to choose one item from; returns the item or None."""
    win = tk.Toplevel(master)
    win.title(title)
    win.geometry("720x320")
    win.transient(master)
    win.grab_set()
    ttk.Label(win, text=prompt, wraplength=680).pack(anchor="w", padx=12, pady=(12, 6))
    box = tk.Listbox(win, activestyle="dotbox", relief="flat", highlightthickness=1)
    for item in items:
        box.insert("end", describe(item))
    box.pack(fill="both", expand=True, padx=12)
    box.selection_set(0)
    result = {"item": None}

    def ok(_event=None):
        sel = box.curselection()
        if sel:
            result["item"] = items[sel[0]]
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(fill="x", padx=12, pady=12)
    ttk.Button(btns, text="Use this one", command=ok).pack(side="right")
    ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=6)
    box.bind("<Double-1>", ok)
    box.bind("<Return>", ok)
    if getattr(master, "_theme", None):
        master._theme.paint(win)
    win.wait_window()
    return result["item"]


class ChoiceDialog(tk.Toplevel):
    """One mod at a time: tick the files you want, Back / Skip mod / Next."""

    def __init__(self, master, plans: list[ModPlan], include_old: bool, include_other: bool = False):
        super().__init__(master)
        self.plans = plans
        self.include_old = include_old
        self.include_other = include_other
        self.index = 0
        self.vars: list[tuple[tk.BooleanVar, int]] = []
        self.title("Choose options")
        self.geometry("760x560")
        self.transient(master)
        self.grab_set()

        self.head = tk.StringVar()
        self.sub = tk.StringVar()
        ttk.Label(self, textvariable=self.head, style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, textvariable=self.sub, style="Muted.TLabel").pack(anchor="w", padx=12)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.canvas = tk.Canvas(body, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="◀ Back", command=lambda: self.go(-1)).pack(side="left")
        ttk.Button(btns, text="Open mod page", command=self.open_page).pack(side="left", padx=6)
        self.count = tk.StringVar()
        ttk.Label(btns, textvariable=self.count).pack(side="left", padx=12)
        ttk.Button(btns, text="Done", command=self.finish).pack(side="right")
        ttk.Button(btns, text="Next ▶", command=lambda: self.go(1)).pack(side="right", padx=6)
        ttk.Button(btns, text="Leave this mod out", command=self.skip).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.show()
        if getattr(master, "_theme", None):
            master._theme.paint(self)

    @property
    def plan(self) -> ModPlan:
        return self.plans[self.index]

    def show(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        plan = self.plan
        author = f" by {plan.mod.author}" if plan.mod and plan.mod.author else ""
        self.head.set(plan.title + author)
        self.sub.set(plan.reason + (f"   •   your note: {plan.entry.note}" if plan.entry.note else ""))
        self.count.set(f"Mod {self.index + 1} of {len(self.plans)}")
        self.vars = []
        last_cat = None
        options = visible_options(plan.options, self.include_old, self.include_other)
        hidden = [o for o in for_other_versions(plan.options) if o not in options]
        if hidden and "left out" not in self.sub.get():
            self.sub.set(self.sub.get() + f"   \u2022   {len(hidden)} file(s) for other game versions left out")
        for fid in plan.selected:  # keep a linked old file visible
            opt = plan.option(fid)
            if opt and opt not in options:
                options.append(opt)
        for opt in options:
            if opt.category_label != last_cat:
                last_cat = opt.category_label
                ttk.Label(self.inner, text=f"{last_cat} files", font=("TkDefaultFont", 10, "bold")).pack(
                    anchor="w", pady=(10, 2))
            var = tk.BooleanVar(value=opt.file_id in plan.selected)
            text = f"{opt.name}   v{opt.version}   ({opt.size_text})" if opt.version else f"{opt.name}   ({opt.size_text})"
            if opt.fit.note and opt.fit.status != "unknown":
                text += f"   \u2014 {opt.fit.note}"
            ttk.Checkbutton(self.inner, text=text, variable=var).pack(anchor="w")
            if opt.description:
                desc = opt.description if len(opt.description) < 400 else opt.description[:400] + "…"
                ttk.Label(self.inner, text=desc, wraplength=660, style="Muted.TLabel").pack(anchor="w", padx=24)
            self.vars.append((var, opt.file_id))
        self.canvas.yview_moveto(0)

    def commit(self) -> None:
        self.plan.selected = [fid for var, fid in self.vars if var.get()]
        self.plan.needs_choice = False
        self.plan.reason = "your choice" if self.plan.selected else "nothing ticked - mod left out"

    def go(self, step: int) -> None:
        self.commit()
        new = self.index + step
        if new >= len(self.plans):
            self.finish()
            return
        self.index = max(0, new)
        self.show()

    def skip(self) -> None:
        for var, _ in self.vars:
            var.set(False)
        self.go(1)

    def open_page(self) -> None:
        webbrowser.open(self.plan.entry.page_url + "?tab=files")

    def finish(self) -> None:
        self.commit()
        self.grab_release()
        self.destroy()


def run_gui(settings: Settings) -> int:
    root = tk.Tk()
    App(root, settings)
    root.mainloop()
    return 0
