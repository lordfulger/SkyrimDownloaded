"""Step 2: the mod manager, its folders, and your Skyrim version."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class ManagerMixin:
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
                    "the main menu.", parent=self._parent())
            return
        game = with_version[0]
        if not quiet and len({(g.version, g.store) for g in with_version}) > 1:
            game = pick_one(self.root, "Which Skyrim?", "More than one Skyrim install was found:",
                            with_version, lambda g: g.describe()) or game
        self.version_var.set(gameversion.preset_label(gameversion.version_text(game.version)))
        self.store_var.set(game.store)
        self._version_changed()
        self.game_note_var.set(f"Detected from {game.exe} (via {game.found_by})")

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
                messagebox.showinfo("Found", "Filled in:\n\n" + "\n".join(filled) + more, parent=self._parent())
            else:
                messagebox.showinfo(
                    "Nothing found",
                    "Couldn't find Mod Organizer 2 or Vortex on this PC.\n\n"
                    "Use Browse to pick the folders yourself: for MO2, the folder with "
                    "ModOrganizer.ini in it.", parent=self._parent())

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

    def _target(self):
        paths = {k: v.get().strip() for k, v in self.path_vars.items()}
        return make_target(self.manager_var.get(), self.settings.game, **paths)

