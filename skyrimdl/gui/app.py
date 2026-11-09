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
from .discover_panel import DiscoverMixin


class App(AccountMixin, ManagerMixin, PersistMixin, ListMixin, PlanMixin, ToolsMixin, DownloadMixin,
          DiscoverMixin):
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
        root.geometry(f"1100x{height}")  # the size when not maximized
        self.maximize()
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
        if self.settings.discover_open:  # it was open last time
            self.settings.discover_open = False
            self.root.after(600, self.toggle_discover)
        root.report_callback_exception = self._callback_error
        self._set_window_icon()
        # Tk must only ever be touched from this thread. Python's cycle collector can run on
        # any thread and would then delete Tk variables/images of closed dialogs from a
        # background thread - which crashes or freezes Tk. So collect here, on a timer.
        gc.disable()
        self._gc_ticks = 0
        root.after(4000, self.check_app_update)
        root.after(9000, self.daily_mod_check)
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
        self.requests_var = tk.StringVar(value="")
        ttk.Label(top_row, textvariable=self.requests_var, style="Muted.TLabel").pack(side="left", padx=6)
        self.theme_var = tk.StringVar(value=self.settings.theme if self.settings.theme in theme_mod.MODES
                                      else "System")
        help_btn = ttk.Menubutton(top_row, text="Help \u25be")
        help_menu = tk.Menu(help_btn, tearoff=False)
        help_menu.add_command(label="Read a Skyrim crash log\u2026", command=self.read_crash_log)
        self.daily_var = tk.BooleanVar(value=bool(self.settings.check_mod_updates))
        help_menu.add_checkbutton(label="Check my mods for new files once a day (1 request)",
                                  variable=self.daily_var, command=self._daily_toggled)
        help_menu.add_separator()
        help_menu.add_command(label="Copy debug info", command=self.copy_debug_info)
        help_menu.add_command(label="Open log folder", command=self.open_log_folder)
        help_menu.add_command(label="Check for a new version / update", command=lambda: self.check_app_update(force=True))
        help_menu.add_separator()
        help_menu.add_command(label="Read the guide (README)",
                              command=lambda: webbrowser.open("https://github.com/lordfulger/SkyrimDownloaded#readme"))
        help_btn["menu"] = help_menu
        help_btn.pack(side="right", padx=(8, 0))
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
        self.install_check = ttk.Checkbutton(top, text="Install after download",
                                             variable=self.install_var)
        self.install_check.pack(side="left", padx=12)
        self.category_var = tk.BooleanVar(value=False)
        self.category_check = ttk.Checkbutton(top, text="Separators by Nexus category",
                                              variable=self.category_var, command=self._save_settings)
        self.category_check.pack(side="left")

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
        self.addon_btn = ttk.Button(found, text="Add installer to MO2", command=self.add_mo2_addon)
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
        ttk.Label(game, text="Textures:").pack(side="left", padx=(12, 0))
        self.texture_var = tk.StringVar(value=NO_TEXTURE_PREF)
        texture_box = ttk.Combobox(game, textvariable=self.texture_var, state="readonly", width=14,
                                   values=[NO_TEXTURE_PREF] + TEXTURE_SIZES)
        texture_box.pack(side="left", padx=6)
        texture_box.bind("<<ComboboxSelected>>", lambda e: self._version_changed())
        self.game_note_var = tk.StringVar(value="Files for other versions are left out.")
        ttk.Label(game, textvariable=self.game_note_var, style="Muted.TLabel").pack(side="left", padx=8)

        # Sections 3 and 4 share the space; drag the bar between them to resize.
        # ...and the Discover panel can open on their right.
        self.hsplit = ttk.PanedWindow(outer, orient="horizontal")
        self.hsplit.pack(fill="both", expand=True, **pad)
        panes = ttk.PanedWindow(self.hsplit, orient="vertical")
        self.hsplit.add(panes, weight=3)
        self.panes = panes
        self.build_discover(self.hsplit)
        # The mod list gets a share of the space (a third to start with), set once the window
        # has its real size, and never less than a few lines.
        self.sash_fraction = 0.33
        self._sash_ready = False
        panes.bind("<Configure>", lambda e: self._place_sash(), add="+")
        panes.bind("<ButtonRelease-1>", lambda e: self._sash_moved(), add="+")

        # List
        lst = ttk.LabelFrame(panes, text="3. Mod list (Nexus links, nxm:// links or mod numbers, one per line)")
        bar = ttk.Frame(lst)
        bar.pack(fill="x", padx=6, pady=4)
        list_btn = ttk.Menubutton(bar, text="List \u25be")
        list_menu = tk.Menu(list_btn, tearoff=False)
        list_menu.add_command(label="Open list\u2026", command=self.open_list)
        list_menu.add_command(label="Save list\u2026", command=self.save_list)
        list_menu.add_command(label="Start from a Nexus Collection\u2026", command=self.import_collection)
        list_menu.add_command(label="Build from my MO2 setup\u2026", command=self.build_from_mo2)
        list_menu.add_command(label="Share (with your choices)\u2026", command=self.share_list)
        list_menu.add_separator()
        list_menu.add_command(label="Start over", command=self.start_over)
        list_btn["menu"] = list_menu
        list_btn.pack(side="left")
        ttk.Button(bar, text="Save progress", command=self.save_progress).pack(side="left", padx=4)
        self.list_label = tk.StringVar(value="(type or paste links below)")
        list_label = ttk.Label(bar, textvariable=self.list_label, style="Muted.TLabel")
        self.lookup_btn = ttk.Button(bar, text="Look up mods \u25B6", command=self.lookup)
        self.lookup_btn.pack(side="right")
        self.fresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Forget last choices", variable=self.fresh_var).pack(side="right", padx=8)
        self.refresh_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Refresh from Nexus", variable=self.refresh_var).pack(side="right")
        list_label.pack(side="left", padx=8, fill="x", expand=True)  # last: gets the space that's left
        # Find in the list
        lfind = ttk.Frame(lst)
        lfind.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(lfind, text="Find:").pack(side="left")
        self.list_find_var = tk.StringVar()
        self.list_find_entry = ttk.Entry(lfind, textvariable=self.list_find_var, width=34)
        self.list_find_entry.pack(side="left", padx=6)
        ttk.Button(lfind, text="\u25B2", width=3,
                   command=lambda: self.list_find_next(back=True)).pack(side="left")
        ttk.Button(lfind, text="\u25BC", width=3,
                   command=lambda: self.list_find_next()).pack(side="left", padx=(2, 0))
        ttk.Button(lfind, text="\u2715", width=3,
                   command=lambda: self.list_find_var.set("")).pack(side="left", padx=(2, 0))
        self.list_find_note = tk.StringVar()
        ttk.Label(lfind, textvariable=self.list_find_note, style="Muted.TLabel").pack(side="left", padx=6)
        ttk.Label(lfind, text="Enter: next   Shift+Enter: back   Esc: clear",
                  style="Muted.TLabel").pack(side="right")
        self.list_find_var.trace_add("write", lambda *a: self.list_find_changed())
        self.list_find_entry.bind("<Return>", lambda e: self.list_find_next())
        self.list_find_entry.bind("<Shift-Return>", lambda e: self.list_find_next(back=True))
        self.list_find_entry.bind("<Escape>", lambda e: (self.list_find_var.set(""), self.list_text.focus_set()))
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
        ttk.Button(tools, text="Auto-pick\u2026", command=self.auto_pick_settings).pack(side="left", padx=4)
        ttk.Button(tools, text="Discover \u25b8", command=self.toggle_discover).pack(side="right", padx=4)
        self.listcheck_btn = ttk.Button(tools, text="Check list", command=self.check_list)
        self.listcheck_btn.pack(side="left", padx=4)
        ttk.Button(tools, text="Open mod page", command=self.open_page).pack(side="left", padx=4)
        self.old_var = tk.BooleanVar(value=False)
        self.other_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(tools, text="Other game versions", variable=self.other_var,
                        command=self._fill_tree).pack(side="left", padx=(10, 4))
        ttk.Checkbutton(tools, text="Old versions", variable=self.old_var,
                        command=self._fill_tree).pack(side="left", padx=4)
        self.plan_var = tk.StringVar()
        ttk.Label(tools, textvariable=self.plan_var).pack(side="right")

        find = ttk.Frame(plan)
        find.pack(fill="x", padx=6, pady=(0, 4))
        ttk.Label(find, text="Search:").pack(side="left")
        self.filter_var = tk.StringVar()
        search = ttk.Entry(find, textvariable=self.filter_var, width=34)
        search.pack(side="left", padx=6)
        self.search_entry = search
        search.bind("<Return>", self.find_first_mod)
        search.bind("<Escape>", lambda e: self.filter_var.set(""))
        # Ctrl+F: the Find box of section 3 when you're in the list, otherwise this Search box
        for seq in ("<Control-f>", "<Control-F>"):
            self.root.bind_all(seq, self.find)
            self.list_text.bind(seq, self.find)  # before the text box's own Ctrl+F
            self.list_find_entry.bind(seq, self.find)
        self.filter_var.trace_add("write", lambda *a: self._filter_changed())
        ttk.Button(find, text="\u2715", width=3, command=lambda: self.filter_var.set("")).pack(side="left")
        bulk_btn = ttk.Menubutton(find, text="Bulk actions \u25be")
        bulk = tk.Menu(bulk_btn, tearoff=False)
        bulk.add_command(label="Tick all suggested patches", command=lambda: self.bulk("patches"))
        bulk.add_command(label="Leave out every optional file", command=lambda: self.bulk("no-optional"))
        bulk.add_command(label="Untick files for other game versions", command=lambda: self.bulk("version"))
        bulk.add_command(label="Keep only the main files", command=lambda: self.bulk("main-only"))
        bulk.add_command(label="Use my texture size (also for mods I picked by hand)",
                         command=lambda: self.bulk("texture"))
        bulk.add_separator()
        bulk.add_command(label="Track every mod on Nexus (get told about updates)",
                         command=lambda: self.nexus_bulk("track"))
        bulk.add_command(label="Endorse every mod (thank the authors)", command=lambda: self.nexus_bulk("endorse"))
        bulk.add_separator()
        bulk.add_command(label="Expand all", command=lambda: self.bulk("expand"))
        bulk.add_command(label="Collapse all", command=lambda: self.bulk("collapse"))
        bulk_btn["menu"] = bulk
        bulk_btn.pack(side="left", padx=8)
        self.filter_note = tk.StringVar()
        ttk.Label(find, textvariable=self.filter_note, style="Muted.TLabel").pack(side="left", padx=6)

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
        self.tree.bind("<Button-3>", self._tree_menu)  # right-click: Choose options from here
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
        self.update_btn = ttk.Button(go, text="", style="Accent.TButton")  # shown when there's a new version
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

    def new_operation(self) -> threading.Event:
        """A fresh Stop signal for the work about to start (Nexus requests follow it too)."""
        self.cancel = threading.Event()
        if self.client is not None:
            self.client.cancel = self.cancel
        return self.cancel

    def _set_busy(self, busy: bool) -> None:
        self._busy_count = max(0, getattr(self, "_busy_count", 0) + (1 if busy else -1))
        busy = self._busy_count > 0
        if not busy and self.cancel.is_set():
            self.status_var.set("Stopped. Start again to carry on where it left off.")
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.lookup_btn.configure(state=state)
        self.find_btn.configure(state=state)
        self.compat_btn.configure(state=state)
        self.updates_btn.configure(state=state)
        self.listcheck_btn.configure(state=state)
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if busy else "disabled")

    def _pump(self) -> None:
        """Hand results from background work to the window, every 150 ms.

        It always keeps going: an error while handling one result is logged and
        the rest carry on (a stopped pump would leave the window looking frozen)."""
        try:
            self._pump_once()
        except Exception:
            log.exception("while updating the window")
        self._gc_ticks = getattr(self, "_gc_ticks", 0) + 1
        if self._gc_ticks % 15 == 0:  # about every 2 seconds, on the main thread
            gc.collect(2 if self._gc_ticks % 150 == 0 else 0)
        try:
            self.root.after(150, self._pump)
        except tk.TclError:
            pass  # the window has been closed

    def check_app_update(self, force: bool = False) -> None:
        """Once a day, ask GitHub whether there's a newer SkyrimDownloaded."""
        s = self.settings
        if not force and (not s.check_app_updates or time.time() - s.last_update_check < 20 * 3600):
            return
        s.last_update_check = time.time()

        def work():
            try:
                found = appupdate.check()
            except appupdate.CheckFailed as err:
                log.warning("Update check failed: %s", err)
                if force:
                    self.events.put(("error", f"Couldn't check for a new version: {err}\n\nCheck your "
                                              "internet connection, or whether a firewall or antivirus blocks "
                                              "SkyrimDownloaded from reaching github.com. The latest version is "
                                              "always on " + appupdate.RELEASES_PAGE))
                return
            self.events.put(("app-update", (found, force)))
        threading.Thread(target=work, daemon=True).start()

    def _app_update_found(self, found, force: bool) -> None:
        if found is None:
            if force:
                messagebox.showinfo("SkyrimDownloaded", f"You have the latest version ({__version__}).",
                                    parent=self._parent())
            return
        log.info("New version available: %s", found.version)
        self.update_btn.configure(text=f"\u2b06 Update to {found.version}",
                                  command=lambda: self.update_app(found))
        self.update_btn.pack(side="right", padx=(0, 8))
        if force:
            self.update_app(found)

    def update_app(self, found) -> None:
        """Download the new version, then close, swap it in and reopen."""
        exe = appupdate.running_exe()
        if exe is None or not found.exe_url or sys.platform != "win32":
            if messagebox.askyesno("Update", f"Version {found.version} is out (you have {__version__}). "
                                   "Open the download page?", parent=self._parent()):
                webbrowser.open(found.page)
            return
        if self.busy:
            messagebox.showinfo("Update", "Wait for the current downloads or lookups to finish first.",
                                parent=self._parent())
            return
        target = appupdate.update_target(exe)
        where = "" if target == exe else (
            f"\n\nThe folder it's in can't be written to, so the new version goes to {target.parent} "
            "and starts from there.")
        if not messagebox.askyesno(
                "Update", f"Update to version {found.version}?\n\nIt downloads, then SkyrimDownloaded "
                f"closes and reopens on the new version. Your work is saved and comes back.{where}",
                parent=self._parent()):
            return
        self.update_btn.configure(state="disabled")

        def progress(done, total):
            if total:
                self.events.put(("status", f"Downloading version {found.version}: "
                                           f"{100 * done // max(total, 1)}%"))

        def work():
            path = appupdate.download_update(found, target.parent, progress=progress)
            self.events.put(("update-ready", (path, target)))
        self._background(work)

    def _update_ready(self, path, target) -> None:
        log.info("Update downloaded to %s; swapping into %s", path, target)
        self._save_settings()
        self.save_session(now=True, wait=True)
        try:
            appupdate.start_swap(path, target, os.getpid())
        except OSError as err:
            messagebox.showerror("Update", f"Couldn't start the update: {err}", parent=self._parent())
            self.update_btn.configure(state="normal")
            return
        self.cancel.set()
        self.root.destroy()

    def add_mo2_addon(self) -> None:
        """Put the SkyrimDownloaded add-on in MO2's plugins folder."""
        try:
            exe = self._target().exe()
            where = mo2addon.install_addon(exe)
        except (ManagerError, OSError) as err:
            messagebox.showerror("MO2 add-on", f"Couldn't add it: {err}\n\nPoint the tool at ModOrganizer.exe "
                                 "in step 2 first.", parent=self._parent())
            return
        log.info("Installed the MO2 add-on to %s", where)
        self._manager_changed()
        messagebox.showinfo(
            "MO2 add-on", f"Added to {where}.\n\nRestart Mod Organizer 2. After your downloads finish, open "
            "MO2's Tools menu (the puzzle-piece button) > \"SkyrimDownloaded: install downloaded mods\". It "
            "installs everything in your list's order, then orders and switches the mods on.",
            parent=self._parent())

    def copy_debug_info(self) -> None:
        """Version, system, setup and the end of the log, ready to paste into a problem report."""
        target = self._target_game()
        extra = {
            "Mod manager": f"{self.manager_var.get()} ({self.mode_var.get()})",
            "Your Skyrim": target.describe(),
            "Mods looked up": str(len(self.plans)),
            "Saved Nexus data": f"{len(nexuscache.shared())} entries",
            "Nexus requests": self.client.rate.describe() if self.client else "not logged in",
        }
        text = logs.debug_info(extra)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Debug info copied - paste it into your message.")

    def open_log_folder(self) -> None:
        folder = logs.log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(folder))  # noqa: S606
        else:
            webbrowser.open(folder.as_uri())

    LIST_MIN = 160  # pixels: the mod list never gets squeezed below this

    def _place_sash(self) -> None:
        """Put the divider between the mod list and the files at its share of the height."""
        try:
            height = self.panes.winfo_height()
            if height < 300:
                return  # not laid out yet
            want = max(self.LIST_MIN, int(height * self.sash_fraction))
            want = min(want, height - 200)  # leave the files list room too
            if not self._sash_ready or abs(self.panes.sashpos(0) - want) > 2:
                self.panes.sashpos(0, want)
                self._sash_ready = True
        except tk.TclError:
            pass

    def _sash_moved(self) -> None:
        """Remember where you dragged the divider (as a share of the height)."""
        try:
            height = self.panes.winfo_height()
            pos = self.panes.sashpos(0)
            if height >= 300:
                self.sash_fraction = min(0.8, max(self.LIST_MIN / height, pos / height))
                self._place_sash()
                self.save_session()
        except tk.TclError:
            pass

    def _asset(self, name: str):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
        path = base / "assets" / name
        return path if path.is_file() else None

    def _logo_image(self, size: int):
        """The logo as a Tk image of about ``size`` pixels (None if there's no logo)."""
        small = self._asset("logo_small.png") if size <= 64 else None
        icon = self._asset("icon.png")
        logo = self._asset("logo.png")
        try:
            if small:
                return tk.PhotoImage(file=str(small))
            source = icon or logo
            if source is None:
                return None
            try:  # Pillow (bundled in the .exe) scales it nicely
                from PIL import Image, ImageTk
                img = Image.open(source).convert("RGBA")
                side = min(img.size)
                left, top = (img.width - side) // 2, (img.height - side) // 2
                img = img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
                return ImageTk.PhotoImage(img)
            except ImportError:
                photo = tk.PhotoImage(file=str(source))
                factor = max(1, photo.width() // size)
                return photo.subsample(factor) if factor > 1 else photo
        except (tk.TclError, OSError):
            return None

    def _set_window_icon(self) -> None:
        """The logo in the title bar and on the taskbar (also set before the window shows)."""
        if getattr(self.root, "_app_icon", None) is None:
            set_app_icon(self.root)

    def maximize(self) -> None:
        """Fill the screen (the window's maximize button)."""
        self._want_max = True
        try:
            if sys.platform == "win32":
                self.root.state("zoomed")
            else:
                self.root.attributes("-zoomed", True)
        except tk.TclError:
            pass

    def is_maximized(self) -> bool:
        try:
            if sys.platform == "win32":
                return self.root.state() == "zoomed"
            return bool(self.root.attributes("-zoomed"))
        except tk.TclError:
            return False

    def _parent(self):
        """The window a message should sit on: an open dialog if there is one."""
        try:
            grab = self.root.grab_current()
            if grab is not None and grab.winfo_exists():
                return grab
        except (tk.TclError, KeyError):
            pass
        return self.root

    def _safe(self, fn, *args) -> None:
        try:
            fn(*args)
        except Exception:
            log.exception("in %s", getattr(fn, "__name__", fn))
            self._oops()

    def _oops(self) -> None:
        try:
            self.status_var.set("Something went wrong - it's in the log (Help \u25be > Copy debug info).")
        except tk.TclError:
            pass

    def _callback_error(self, exc, value, tb) -> None:
        """Errors in button clicks etc.: log them instead of losing them."""
        log.error("Error in the window", exc_info=(exc, value, tb))
        self._oops()

    def _show_requests_left(self) -> None:
        c = self.client
        if c is None:
            self.requests_var.set("")
            return
        r = c.rate
        if r.daily_remaining is None and r.hourly_remaining is None:
            text = ""
        elif r.daily_remaining == 0:
            text = f"Nexus requests: daily allowance used up - {r.hourly_remaining} left this hour"
        else:
            text = f"Nexus requests left: {r.daily_remaining:,} today"
        if c.requests_saved:
            text += f" \u00b7 {c.requests_saved:,} saved by reusing earlier lookups"
        self.requests_var.set(text)

    def _requests_ok(self, needed: int, what: str) -> bool:
        """Warn before something would use more API requests than are left."""
        r = self.client.rate if self.client else None
        if not r or r.daily_remaining is None or needed <= 0:
            return True
        left = r.daily_remaining if r.daily_remaining > 0 else (r.hourly_remaining or 0)
        if needed <= left:
            return True
        return messagebox.askyesno(
            "Nexus requests", f"{what} needs about {needed:,} Nexus requests, and you have {left:,} left "
            f"{'today' if r.daily_remaining else 'this hour'}.\n\nOnce the daily allowance is used up, "
            "Nexus allows only about 100 an hour, so this would slow right down. Mods you've looked "
            "up before cost nothing.\n\nGo ahead anyway?", parent=self._parent())

    def _pump_once(self) -> None:
        try:
            self._show_requests_left()
        except Exception:
            log.exception("showing requests left")
        dirty_jobs = set()
        for _ in range(500):  # don't hog the window if a lot arrives at once
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "job":
                dirty_jobs.add(id(payload))
                continue
            try:
                self._handle_event(kind, payload)
            except Exception:
                log.exception("handling %s", kind)
                self._oops()
        if dirty_jobs:
            try:
                self._refresh_jobs(dirty_jobs)
            except Exception:
                log.exception("refreshing download progress")

    def _later(self, fn, *args) -> None:
        """Run something that may open a dialog outside the pump, so the pump keeps going."""
        self.root.after(0, lambda: self._safe(fn, *args))

    def _handle_event(self, kind: str, payload) -> None:
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
            made, saved = getattr(self, "_lookup_cost", (0, 0))
            cost = f" ({made} Nexus requests, {saved} saved by reusing earlier lookups)" if made or saved else ""
            log.info("Looked up %d mods%s", len(self.plans), cost)
            self.status_var.set(f"{len(self.plans)} mods looked up{cost}"
                                + (f", {waiting} have options to choose" if waiting else "")
                                + ". Checking requirements\u2026")
            self._check_requirements()
        elif kind == "picture":
            self._show_picture(*payload)
        elif kind == "where":
            self.where_var.set(payload)
        elif kind == "idle":
            self._set_busy(False)
        elif kind == "info":
            self._later(lambda: messagebox.showinfo("SkyrimDownloaded", payload, parent=self._parent()))
        elif kind == "error":
            log.error("Background error: %s", payload)
            self._later(lambda: messagebox.showerror("SkyrimDownloaded", payload, parent=self._parent()))
        else:
            handler = {
                "clipboard-login": self._clipboard_login_done, "login-ok": self._login_ok,
                "listcheck": self._listcheck_done,
                "discover-browse": self._browse_done, "discover-suggest": self._suggest_done,
                "discover-goes": self._goes_done, "mod-updates": self._daily_done,
                "login-retry": self._login_retry, "updates": self._updates_done,
                "compat": self._compat_done, "games": self._games_found, "found": self._apply_found,
                "requirements": self._requirements_done, "finished": self._finished,
                "app-update": self._app_update_found, "update-ready": self._update_ready, "collection": self._collection_loaded,
            }.get(kind)
            if handler is None:
                log.warning("Unknown event %s", kind)
            else:
                self._later(handler, *payload) if isinstance(payload, tuple) else self._later(handler, payload)

    def _close(self) -> None:
        if self.busy and not messagebox.askyesno(
                "Quit?", "Downloads are still going. Stop and quit? (Start again later "
                "to pick up where it left off.)", parent=self._parent()):
            return
        self.cancel.set()
        self._save_settings()
        self.save_session(now=True, wait=True)
        self.root.destroy()


def asset_path(name: str):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    path = base / "assets" / name
    return path if path.is_file() else None


def set_app_icon(root) -> None:
    """The logo for the title bar, the taskbar and every window the app opens.

    On Windows the .ico (all sizes) is the default icon for every window; the .png is set
    too (and is what other systems use). Without either, Tk's feather shows."""
    if sys.platform == "win32":
        try:  # its own taskbar button and icon, not Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lordfulger.SkyrimDownloaded")
        except Exception:
            pass
        ico = asset_path("icon.ico")
        if ico:
            try:
                root.iconbitmap(default=str(ico))
            except tk.TclError:
                pass
    png = asset_path("icon.png") or asset_path("logo.png")
    if png:
        try:
            if png.name == "logo.png":
                try:  # running from source: crop the logo to its emblem with Pillow
                    from PIL import Image, ImageTk
                    img = Image.open(png).convert("RGBA")
                    side = min(img.size)
                    left, top = (img.width - side) // 2, (img.height - side) // 2
                    photo = ImageTk.PhotoImage(img.crop((left, top, left + side, top + side)).resize((256, 256)))
                except ImportError:
                    photo = tk.PhotoImage(file=str(png))
            else:
                photo = tk.PhotoImage(file=str(png))
            root._app_icon = photo  # keep a reference
            root.iconphoto(True, photo)
        except (tk.TclError, OSError):
            pass


def run_gui(settings: Settings) -> int:
    logs.setup()
    root = tk.Tk()
    root.withdraw()          # stay hidden until the logo is set and the window is built
    set_app_icon(root)
    app = App(root, settings)
    root.deiconify()
    if getattr(app, "_want_max", True):
        app.maximize()  # showing a hidden window can drop the maximized state
    root.mainloop()
    return 0

