"""The Discover panel on the side: suggestions for your list, and browsing Nexus."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .. import discover


def _date(stamp: str) -> str:
    return stamp[:10] if stamp else ""


def _count(n: int) -> str:
    return f"{n / 1_000_000:.1f}M" if n >= 1_000_000 else f"{n / 1000:.1f}k" if n >= 10_000 else str(n)


class DiscoverMixin:
    # -- building it ----------------------------------------------------------------

    def build_discover(self, parent) -> None:
        self.discover_frame = frame = ttk.LabelFrame(parent, text="Discover mods")
        self._found_rows: dict[str, discover.Found] = {}
        self._suggest_rows: dict[str, discover.Found] = {}
        self._browse_offset = 0
        self._browse_total = 0

        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=(4, 0))
        ttk.Button(top, text="✕", width=3, command=self.toggle_discover).pack(side="right")
        self.discover_note = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.discover_note, style="Muted.TLabel", wraplength=330).pack(side="left")

        self.discover_info = tk.StringVar()
        ttk.Label(frame, textvariable=self.discover_info, wraplength=360, justify="left").pack(
            side="bottom", fill="x", padx=8, pady=(0, 6))
        tabs = ttk.Notebook(frame)
        tabs.pack(fill="both", expand=True, padx=6, pady=4)
        self.discover_tabs = tabs

        # Suggested for your list
        sug = ttk.Frame(tabs)
        tabs.add(sug, text="For your list")
        row = ttk.Frame(sug)
        row.pack(fill="x", pady=4)
        self.suggest_btn = ttk.Button(row, text="Find suggestions", command=self.find_suggestions)
        self.suggest_btn.pack(side="left")
        self.auto_add_var = tk.BooleanVar(value=bool(self.settings.auto_add_patches))
        ttk.Checkbutton(row, text="Add patches by themselves", variable=self.auto_add_var,
                        command=self._discover_settings).pack(side="left", padx=6)
        ttk.Label(sug, text="Patches tie two or more of your mods together; add-ons are made for one. Only "
                            "mods whose requirements are all in your list are shown.", style="Muted.TLabel",
                  wraplength=330).pack(anchor="w")
        self.suggest_tree = self._discover_tree(sug, (("for", "For", 110), ("end", "♥", 52)))
        btns = ttk.Frame(sug)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add to list", style="Accent.TButton",
                   command=lambda: self._add_selected(self.suggest_tree, self._suggest_rows)).pack(side="left")
        ttk.Button(btns, text="Add all patches", command=self._add_all_patches).pack(side="left", padx=4)
        ttk.Button(btns, text="Open page",
                   command=lambda: self._open_selected(self.suggest_tree, self._suggest_rows)).pack(side="left")
        ttk.Button(btns, text="Hide", command=lambda: self._hide_suggestion(self.suggest_tree, self._suggest_rows)
                   ).pack(side="left", padx=4)

        # Goes well with your list (from collections)
        gw = ttk.Frame(tabs)
        tabs.add(gw, text="Goes well with")
        row = ttk.Frame(gw)
        row.pack(fill="x", pady=4)
        self.goes_btn = ttk.Button(row, text="Find mods that go well", command=self.find_goes_well)
        self.goes_btn.pack(side="left")
        ttk.Label(gw, text="From Nexus Collections that use many of your mods: the other mods those "
                           "collections have in common. Higher up = in more collections like your list.",
                  style="Muted.TLabel", wraplength=330).pack(anchor="w")
        self._goes_rows: dict[str, discover.Found] = {}
        self.goes_tree = self._discover_tree(gw, (("in", "In", 52), ("end", "\u2665", 52)))
        btns = ttk.Frame(gw)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add to list", style="Accent.TButton",
                   command=lambda: self._add_selected(self.goes_tree, self._goes_rows)).pack(side="left")
        ttk.Button(btns, text="Open page",
                   command=lambda: self._open_selected(self.goes_tree, self._goes_rows)).pack(side="left", padx=4)
        ttk.Button(btns, text="Hide", command=lambda: self._hide_suggestion(self.goes_tree, self._goes_rows)
                   ).pack(side="left")

        # Browse Nexus
        br = ttk.Frame(tabs)
        tabs.add(br, text="Browse Nexus")
        r1 = ttk.Frame(br)
        r1.pack(fill="x", pady=(4, 2))
        self.show_var = tk.StringVar(value="Most endorsed")
        self.period_var = tk.StringVar(value="Last month")
        for var, values, width in ((self.show_var, list(discover.SHOW), 16), (self.period_var, list(discover.PERIODS), 13)):
            box = ttk.Combobox(r1, textvariable=var, values=values, state="readonly", width=width)
            box.pack(side="left", padx=(0, 4))
            box.bind("<<ComboboxSelected>>", lambda e: self.browse_nexus())
        r2 = ttk.Frame(br)
        r2.pack(fill="x", pady=2)
        self.browse_search = tk.StringVar()
        entry = ttk.Entry(r2, textvariable=self.browse_search, width=22)
        entry.pack(side="left")
        entry.bind("<Return>", lambda e: self.browse_nexus())
        ttk.Button(r2, text="Search", command=self.browse_nexus).pack(side="left", padx=4)
        self.adult_var = tk.BooleanVar(value=bool(self.settings.show_adult))
        ttk.Checkbutton(r2, text="Adult", variable=self.adult_var,
                        command=lambda: (self._discover_settings(), self.browse_nexus())).pack(side="left")
        self.browse_tree = self._discover_tree(br, (("end", "♥", 52), ("dl", "Downloads", 72),
                                                    ("upd", "Updated", 80)))
        btns = ttk.Frame(br)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Add to list", style="Accent.TButton",
                   command=lambda: self._add_selected(self.browse_tree, self._found_rows)).pack(side="left")
        ttk.Button(btns, text="Open page",
                   command=lambda: self._open_selected(self.browse_tree, self._found_rows)).pack(side="left", padx=4)
        self.more_btn = ttk.Button(btns, text="More", command=lambda: self.browse_nexus(more=True))
        self.more_btn.pack(side="left")

        tabs.bind("<<NotebookTabChanged>>", lambda e: self._tab_changed())

    def _discover_tree(self, parent, cols):
        box = ttk.Frame(parent)
        box.pack(fill="both", expand=True)
        tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="tree headings", selectmode="extended",
                            height=5)  # grows to fill; small so the buttons below always fit
        tree.heading("#0", text="Mod")
        tree.column("#0", width=170, minwidth=120, stretch=True)
        for key, title, width in cols:
            tree.heading(key, text=title)
            tree.column(key, width=width, minwidth=40, stretch=key == "for",
                        anchor="e" if key in ("end", "dl") else "w")
        sb = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        AutoScroll(tree)
        tree.bind("<<TreeviewSelect>>", lambda e, t=tree: self._discover_selected(t))
        tree.bind("<Double-1>", lambda e, t=tree: self._open_selected(t, self._rows_of(t)))
        return tree

    def toggle_discover(self) -> None:
        shown = str(self.discover_frame) in self.hsplit.panes()
        if shown:
            self.hsplit.forget(self.discover_frame)
        else:
            self.hsplit.add(self.discover_frame, weight=1)
            self.root.after(50, self._place_discover)
            if not self.browse_tree.get_children() and self.client is not None:
                self.browse_nexus()
        self.settings.discover_open = not shown
        self._save_settings()

    def _place_discover(self) -> None:
        try:
            width = self.hsplit.winfo_width()
            if width > 900:
                self.hsplit.sashpos(0, width - 420)
        except tk.TclError:
            pass

    def _discover_settings(self) -> None:
        self.settings.auto_add_patches = self.auto_add_var.get()
        self.settings.show_adult = self.adult_var.get()
        self._save_settings()

    def _tab_changed(self) -> None:
        self.discover_info.set("")

    # -- browsing ----------------------------------------------------------------------

    def browse_nexus(self, more: bool = False) -> None:
        if self.client is None:
            self.discover_note.set("Log in first.")
            return
        offset = self._browse_offset if more else 0
        show, period = self.show_var.get(), self.period_var.get()
        search, adult = self.browse_search.get(), self.adult_var.get()
        client, game = self.client, self.settings.game
        self.discover_note.set("Asking Nexus…")

        def work():
            try:
                found, total = discover.browse(client, game, show, period, search, adult, offset=offset)
            except NexusError as err:
                self.events.put(("discover-browse", (None, str(err), more)))
                return
            self.events.put(("discover-browse", ((found, total, offset), "", more)))
        threading.Thread(target=work, daemon=True).start()

    def _browse_done(self, result, error, more) -> None:
        if result is None:
            self.discover_note.set(f"Couldn't get mods from Nexus: {error}")
            return
        found, total, offset = result
        if not more:
            self.browse_tree.delete(*self.browse_tree.get_children())
            self._found_rows.clear()
        listed = {mid for _, mid in self._listed_mods()}
        for f in found:
            mark = "✓ " if f.mod_id in listed else ""
            row = self.browse_tree.insert("", "end", text=mark + f.name,
                                          values=(_count(f.endorsements), _count(f.downloads), _date(f.updated)))
            self._found_rows[row] = f
        self._browse_offset = offset + len(found)
        self._browse_total = total
        shown = len(self._found_rows)
        self.discover_note.set(f"{shown} of {total} mods · {self.show_var.get().lower()}, "
                               f"{self.period_var.get().lower()}. ✓ = in your list.")
        self.more_btn.configure(state="normal" if shown < total else "disabled")

    # -- suggestions ----------------------------------------------------------------------

    def find_suggestions(self) -> None:
        if self.busy_with_list("looking for suggestions"):
            return
        if self.client is None:
            self.discover_note.set("Log in first.")
            return
        if not self.plans:
            self.discover_note.set("Look up the mods in your list first.")
            return
        plans, client = list(self.plans), self.client
        hidden = frozenset(int(x) for x in self.settings.hidden_suggestions or [])
        adult = self.adult_var.get()
        cancel = self.new_operation()
        self.suggest_btn.configure(state="disabled")
        self.discover_note.set("Looking for patches and add-ons for your mods…")

        def work():
            found = None
            try:
                found = discover.suggest(
                    client, plans, nexuscache.shared(), adult=adult, hidden=hidden, cancel=cancel,
                    on_progress=lambda d, t: d % 20 == 0 and self.events.put(
                        ("status", f"Suggestions: checked {d} of {t} mods")))
                nexuscache.shared().flush()
            except NexusError as err:  # stopped, or Nexus didn't answer
                log.warning("Suggestions: %s", err)
            finally:
                self.events.put(("discover-suggest", found))
        self._background(work)

    def _suggest_done(self, found) -> None:
        self.suggest_btn.configure(state="normal")
        if found is None:
            self.discover_note.set("Stopped, or Nexus didn't answer - press Find suggestions to try again.")
            return
        tree = self.suggest_tree
        tree.delete(*tree.get_children())
        self._suggest_rows.clear()
        patches = [f for f in found if f.kind == "patch"]
        addons = [f for f in found if f.kind != "patch"]
        for title, group in ((f"Patches between your mods ({len(patches)})", patches),
                             (f"Add-ons for your mods ({len(addons)})", addons)):
            if not group:
                continue
            head = tree.insert("", "end", text=title, open=True, tags=("section",))
            for f in group:
                row = tree.insert(head, "end", text=f.name, values=(", ".join(f.ties), _count(f.endorsements)))
                self._suggest_rows[row] = f
        self.discover_note.set(f"{len(patches)} patches and {len(addons)} add-ons for the mods in your list."
                               if found else "No suggestions: nothing on Nexus lists only mods you have.")
        self.status_var.set(self.discover_note.get())
        if patches and self.auto_add_var.get():
            n = self._add_found(patches, "# Suggested patches")
            if n:
                self.discover_note.set(self.discover_note.get() + f" Added {n} patch(es) to your list.")

    # -- goes well with your list -------------------------------------------------------

    def find_goes_well(self) -> None:
        if self.busy_with_list("looking for mods that go well"):
            return
        if self.client is None:
            self.discover_note.set("Log in first.")
            return
        if not self.plans:
            self.discover_note.set("Look up the mods in your list first.")
            return
        plans, client = list(self.plans), self.client
        hidden = frozenset(int(x) for x in self.settings.hidden_suggestions or [])
        adult = self.adult_var.get()
        cancel = self.new_operation()
        self.goes_btn.configure(state="disabled")
        self.discover_note.set("Looking through Nexus Collections that use your mods\u2026")

        def work():
            found = None
            try:
                found = discover.goes_well(
                    client, plans, nexuscache.shared(), adult=adult, hidden=hidden, cancel=cancel,
                    on_progress=lambda d, t: self.events.put(
                        ("status", f"Goes well with: read collections for {d} of {t} of your mods")))
                nexuscache.shared().flush()
            except NexusError as err:
                log.warning("Goes well with: %s", err)
            finally:
                self.events.put(("discover-goes", found))
        self._background(work)

    def _goes_done(self, found) -> None:
        self.goes_btn.configure(state="normal")
        if found is None:
            self.discover_note.set("Stopped, or Nexus didn't answer - press Find mods that go well to try again.")
            return
        tree = self.goes_tree
        tree.delete(*tree.get_children())
        self._goes_rows.clear()
        for f in found:
            text = f.name + ("  (needs more)" if f.needs else "")
            row = tree.insert("", "end", text=text, values=(len(f.seen_in), _count(f.endorsements)))
            self._goes_rows[row] = f
        self.discover_note.set(f"{len(found)} mods that collections like your list also use."
                               if found else "Nothing found: no collections share enough mods with your list.")
        self.status_var.set(self.discover_note.get())

    # -- shared --------------------------------------------------------------------------

    def _selected_found(self, tree, rows) -> list:
        return [rows[r] for r in tree.selection() if r in rows]

    def _rows_of(self, tree) -> dict:
        if tree is self.suggest_tree:
            return self._suggest_rows
        if tree is getattr(self, "goes_tree", None):
            return self._goes_rows
        return self._found_rows

    def _discover_selected(self, tree) -> None:
        rows = self._rows_of(tree)
        picked = self._selected_found(tree, rows)
        if not picked:
            self.discover_info.set("")
            return
        f = picked[0]
        bits = [f"{f.name} by {f.author}" if f.author else f.name,
                f"{f.category} · v{f.version} · ♥ {f.endorsements:,} · "
                f"{f.downloads:,} downloads · updated {_date(f.updated)}"]
        if f.ties:
            bits.append(("Patch for: " if f.kind == "patch" else "Add-on for: ") + ", ".join(f.ties))
        if f.seen_in:
            more = f" and {len(f.seen_in) - 3} more" if len(f.seen_in) > 3 else ""
            bits.append(f"In {len(f.seen_in)} collections like your list: " + ", ".join(f.seen_in[:3]) + more)
        if f.needs:
            bits.append("Needs (not in your list): " + ", ".join(f.needs[:4]))
        if f.summary:
            bits.append(f.summary[:300])
        self.discover_info.set("\n".join(bits))

    def _open_selected(self, tree, rows) -> None:
        for f in self._selected_found(tree, rows)[:5]:
            webbrowser.open(f.url)

    def _add_selected(self, tree, rows) -> None:
        picked = self._selected_found(tree, rows)
        if not picked:
            self.discover_note.set("Pick a mod first (Ctrl+click for several).")
            return
        self._add_found(picked, "# Added from Discover")

    def _add_all_patches(self) -> None:
        patches = [f for f in self._suggest_rows.values() if f.kind == "patch"]
        if patches:
            self._add_found(patches, "# Suggested patches")

    def _add_found(self, found: list, header: str) -> int:
        items = [(f.url, (f"patch for {' + '.join(f.ties)}" if f.kind == "patch" else
                          f"add-on for {f.ties[0]}" if f.ties else f.name)[:120]) for f in found]
        n = self.add_to_list(items, header)
        for tree, rows in ((self.suggest_tree, self._suggest_rows), (self.browse_tree, self._found_rows),
                           (self.goes_tree, self._goes_rows)):
            for row, f in rows.items():
                if f in found and tree.exists(row) and not tree.item(row, "text").startswith("✓"):
                    tree.item(row, text="✓ " + tree.item(row, "text"))
        if n:
            self._lookup_soon()
        else:
            self.discover_note.set("Already in your list.")
        return n

    def _lookup_soon(self) -> None:
        """Look the list up a few seconds after the last add (so several adds go together)."""
        if getattr(self, "_discover_lookup_job", None):
            self.root.after_cancel(self._discover_lookup_job)

        def go():
            self._discover_lookup_job = None
            if self.busy:
                self._discover_lookup_job = self.root.after(3000, go)
            else:
                self.lookup()
        self._discover_lookup_job = self.root.after(4000, go)

    def _hide_suggestion(self, tree, rows) -> None:
        picked = self._selected_found(tree, rows)
        hidden = list(self.settings.hidden_suggestions or [])
        for row in list(tree.selection()):
            f = rows.pop(row, None)
            if f:
                hidden.append(f.mod_id)
                tree.delete(row)
        self.settings.hidden_suggestions = hidden
        self._save_settings()
        if picked:
            self.discover_note.set(f"Hid {len(picked)} suggestion(s); they won't be suggested again.")
