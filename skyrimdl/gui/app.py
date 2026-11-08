"""The main window. Its parts live in the mixin modules next to this one."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .account import AccountMixin
from .manager_panel import ManagerMixin
from .persist import PersistMixin
from .modlist import ListMixin
from .plan import PlanMixin
from .tools import ToolsMixin
from .downloads import DownloadMixin


class App(AccountMixin, ManagerMixin, PersistMixin, ListMixin, PlanMixin, ToolsMixin, DownloadMixin):
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
        height = max(640, min(940, root.winfo_screenheight() - 90))
        root.geometry(f"1100x{height}")
        root.minsize(820, 600)
        self.theme = theme_mod.Theme(root, settings.theme)
        root._theme = self.theme  # dialogs pick it up from their parent
        self.session_file = session.session_path()
        self._save_job = None
        self._req_cache: dict = {}     # requirements restored from the last session
        self._restoring = True         # no saving until the last session is back
        self._watching_clipboard = False
        self._clip_seen: set[str] = set()
        self._build()
        self.theme.apply()
        self._load_settings()
        root.after(100, self._pump)
        root.protocol("WM_DELETE_WINDOW", self._close)

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

        # Sections 3 and 4 share the space; drag the bar between them to resize.
        panes = ttk.PanedWindow(outer, orient="vertical")
        panes.pack(fill="both", expand=True, **pad)
        self.panes = panes
        # Give the mod list about a third of the space to start with.
        self.root.after(250, lambda: panes.winfo_height() > 50 and panes.sashpos(
            0, max(150, int(panes.winfo_height() * 0.33))))

        # List
        lst = ttk.LabelFrame(panes, text="3. Mod list (Nexus links, nxm:// links or mod numbers, one per line)")
        bar = ttk.Frame(lst)
        bar.pack(fill="x", padx=6, pady=4)
        ttk.Button(bar, text="Open list\u2026", command=self.open_list).pack(side="left")
        ttk.Button(bar, text="Save list\u2026", command=self.save_list).pack(side="left", padx=4)
        ttk.Button(bar, text="Save progress", command=self.save_progress).pack(side="left")
        ttk.Button(bar, text="Start over", command=self.start_over).pack(side="left", padx=4)
        ttk.Button(bar, text="Share\u2026", command=self.share_list).pack(side="left")
        self.list_label = tk.StringVar(value="(type or paste links below)")
        ttk.Label(bar, textvariable=self.list_label).pack(side="left", padx=8)
        self.lookup_btn = ttk.Button(bar, text="Look up mods \u25B6", command=self.lookup)
        self.lookup_btn.pack(side="right")
        self.fresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Forget last choices", variable=self.fresh_var).pack(side="right", padx=8)
        box = ttk.Frame(lst)
        box.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.list_text = tk.Text(box, height=5, wrap="none", undo=True, relief="flat",
                                 highlightthickness=1)
        ys = ttk.Scrollbar(box, orient="vertical", command=self.list_text.yview)
        xs = ttk.Scrollbar(box, orient="horizontal", command=self.list_text.xview)
        self.list_text.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.list_text.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        AutoScroll(self.list_text)
        self.list_text.bind("<<Modified>>", self._list_edited)
        panes.add(lst, weight=1)

        # Plan
        plan = ttk.LabelFrame(panes, text="4. Files to get (click the box or double-click a file to tick/untick "
                                          "it; click a mod to see its Nexus page)")
        panes.add(plan, weight=3)
        tools = ttk.Frame(plan)
        tools.pack(fill="x", padx=6, pady=4)
        ttk.Button(tools, text="Choose options\u2026", command=self.walk_choices).pack(side="left")
        self.compat_btn = ttk.Button(tools, text="Check compatibility",
                                     command=lambda: self.check_compatibility(auto=False))
        self.compat_btn.pack(side="left", padx=4)
        self.updates_btn = ttk.Button(tools, text="Check for updates", command=self.check_for_updates)
        self.updates_btn.pack(side="left")
        ttk.Button(tools, text="Open mod page", command=self.open_page).pack(side="left", padx=4)
        self.old_var = tk.BooleanVar(value=False)
        self.other_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="Other game versions", variable=self.other_var,
                        command=self._fill_tree).pack(side="left", padx=(10, 4))
        ttk.Checkbutton(tools, text="Old versions", variable=self.old_var,
                        command=self._fill_tree).pack(side="left", padx=4)
        self.plan_var = tk.StringVar()
        ttk.Label(tools, textvariable=self.plan_var).pack(side="right")

        split = ttk.PanedWindow(plan, orient="horizontal")
        split.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        cols = ("get", "type", "version", "size", "status")
        frame = ttk.Frame(split)
        self.tree = ttk.Treeview(frame, columns=cols, show="tree headings", selectmode="browse")
        for col, text, width in (("#0", "Mod / file", 300), ("get", "Get", 40), ("type", "Type", 70),
                                 ("version", "Version", 70), ("size", "Size", 70),
                                 ("status", "Status", 220)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, minwidth=36, stretch=col in ("#0", "status"),
                             anchor="center" if col == "get" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<ButtonRelease-1>", self._tree_click)
        self.tree.bind("<space>", lambda e: self._toggle(self.tree.focus()))
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        self.tree.bind("<Double-1>", self._tree_double)
        AutoScroll(self.tree)
        split.add(frame, weight=3)

        # Nexus page info for the mod clicked in the list.
        info = ttk.Frame(split)
        self.info = tk.Text(info, wrap="word", state="disabled", relief="flat", highlightthickness=1,
                            width=42, padx=10, pady=8, cursor="arrow", font="TkDefaultFont")
        self.info._details = True
        info_sb = ttk.Scrollbar(info, orient="vertical", command=self.info.yview)
        self.info.configure(yscrollcommand=info_sb.set)
        self.info.pack(side="left", fill="both", expand=True)
        info_sb.pack(side="right", fill="y")
        AutoScroll(self.info)
        split.add(info, weight=2)
        self._links: dict[str, str] = {}
        self.compat: compat.Report | None = None

        # Go
        go = ttk.Frame(outer)
        # Packed first at the bottom, so it never gets squeezed off a small window.
        go.pack(side="bottom", fill="x", before=outer.winfo_children()[0], **pad)
        self.progress = ttk.Progressbar(go, mode="determinate", length=280)
        self.progress.pack(side="left")
        self.stop_btn = ttk.Button(go, text="Stop", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right")
        self.start_btn = ttk.Button(go, text="Start downloads ▶", command=self.start)
        self.start_btn.pack(side="right", padx=4)
        ttk.Button(go, text="Sort with LOOT", command=self.run_loot).pack(side="right", padx=(0, 8))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(go, textvariable=self.status_var).pack(side="left", fill="x", expand=True, padx=8)

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
        self.compat_btn.configure(state=state)
        self.updates_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _pump(self) -> None:
        try:
            self._pump_once()
        except tk.TclError:
            return  # the window has been closed
        self.root.after(150, self._pump)

    def _pump_once(self) -> None:
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
                    self.compat = None
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
                elif kind == "updates":
                    self._updates_done(*payload)
                elif kind == "compat":
                    self._compat_done(*payload)
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

    def _close(self) -> None:
        if self.busy and not messagebox.askyesno(
                "Quit?", "Downloads are still going. Stop and quit? (Start again later "
                "to pick up where it left off.)", parent=self.root):
            return
        self.cancel.set()
        self._save_settings()
        self.save_session(now=True)
        self.root.destroy()


def run_gui(settings: Settings) -> int:
    root = tk.Tk()
    App(root, settings)
    root.mainloop()
    return 0

