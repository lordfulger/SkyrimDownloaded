"""Share, check for updates, LOOT, compatibility."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class ToolsMixin:
    def share_list(self) -> None:
        """Save the list with every choice locked in, for someone else to use."""
        if not self.plans:
            messagebox.showinfo("Share", "Look up the mods in your list first, so your choices can be "
                                "saved with it.", parent=self._parent())
            return
        left = [p for p in self.plans if p.needs_choice and not p.error]
        if left and not messagebox.askyesno(
                "Share", f"{len(left)} mod(s) still have options you haven't chosen; their ticked files "
                "will be used. Share anyway?", parent=self._parent()):
            return
        base = self.list_path.stem if self.list_path else "my-mods"
        path = filedialog.asksaveasfilename(title="Share list", defaultextension=".txt",
                                            initialfile=f"{base}-shared.txt",
                                            filetypes=[("Text files", "*.txt")])
        if not path:
            return
        try:
            Path(path).write_text(sharing.export_text(self.plans, self._target_game(), title=Path(path).stem),
                                  encoding="utf-8")
        except OSError as err:
            messagebox.showerror("Share", f"Couldn't save it there: {err}", parent=self._parent())
            return
        messagebox.showinfo("Share", f"Saved {path}.\n\nSend it to anyone with SkyrimDownloaded: opening "
                            "it and pressing Look up mods gives them exactly the same files.", parent=self._parent())

    # -- Check list: plugins, disk space, duplicates, replaced mods, sizes ----------

    def check_list(self) -> None:
        if not self.plans:
            messagebox.showinfo("Check list", "Look up the mods in your list first.", parent=self._parent())
            return
        from .. import listcheck
        plans = list(self.plans)
        try:
            target = self._target()
        except ManagerError:
            target = None
        self.status_var.set("Checking your list\u2026")
        cancel = self.new_operation()
        cache = nexuscache.shared()
        list_text = self.list_text.get("1.0", "end-1c")
        install = self.install_var.get()  # read here: Tk only on this thread

        def work():
            plugins = listcheck.count_plugins(
                plans, fetch=lambda url: listcheck.fetch_preview(url, cache), cancel=cancel,
                on_progress=lambda d, t: d % 10 == 0 and self.events.put(
                    ("status", f"Reading the file lists of the picked files: {d} of {t}")))
            installed = self._installed_in_mo2(target) if target else {}
            result = {
                "plugins": plugins,
                "duplicates": listcheck.duplicates(list_text, self.settings.game),
                "retired": listcheck.retired(plans),
                "sizes": listcheck.size_by_texture(plans),
                "textured": listcheck.textured_mods(plans),
                "installed": installed,
                "space": self._space_for(target, jobs_for(plans), install) if target else [],
            }
            cache.flush()
            self.events.put(("listcheck", result))
        self._background(work)

    def _listcheck_done(self, result) -> None:
        from .dialogs import ListCheckDialog
        p = result["plugins"]
        self.status_var.set(f"List checked: about {p.total_full} regular plugins (limit 254), "
                            f"{p.light} light (ESL).")
        ListCheckDialog(self.root, result, self.plans, texture=self._target_game().texture)

    def nexus_bulk(self, action: str) -> None:
        """Track or endorse every mod shown (all of them, or the ones matching the search)."""
        if self.busy_with_list("tracking or endorsing"):
            return
        if self.client is None:
            messagebox.showinfo("Nexus", "Log in first.", parent=self._parent())
            return
        query = self.filter_var.get().strip()
        mods = [p for p in self.plans if p.mod and not p.error and not p.skipped and self._matches(p, query)]
        mods = list({(p.entry.game, p.entry.mod_id): p for p in mods}.values())
        if not mods:
            messagebox.showinfo("Nexus", "Look up the mods in your list first.", parent=self._parent())
            return
        what = ("track" if action == "track" else "endorse")
        did = "Tracked" if action == "track" else "Endorsed"
        if not messagebox.askyesno(
                "Nexus", f"{what.capitalize()} {len(mods)} mod(s) on Nexus with your account?\n\nThis uses one "
                "request per mod." + (" Only endorse mods you've actually used - Nexus may refuse ones you "
                                      "haven't downloaded." if action == "endorse" else ""),
                parent=self._parent()):
            return
        if not self._requests_ok(len(mods), f"{what.capitalize()} {len(mods)} mods"):
            return
        client = self.client
        self.new_operation()

        def work():
            done, failed = 0, []
            for i, p in enumerate(mods, 1):
                try:
                    if action == "track":
                        client.track(p.entry.game, p.entry.mod_id)
                    else:
                        client.endorse(p.entry.game, p.entry.mod_id, p.mod.version)
                    done += 1
                except NexusError as err:
                    if isinstance(err, (AuthError,)) or "stopped" in str(err):
                        failed.append(f"{p.title}: {err}")
                        break
                    failed.append(f"{p.title}: {err}")
                self.events.put(("status", f"{did} {i} of {len(mods)}"))
            msg = f"{did} {done} of {len(mods)} mods on Nexus."
            if failed:
                msg += "\n\nDidn't work:\n" + "\n".join(failed[:12])
            self.events.put(("status", msg.split("\n")[0]))
            self.events.put(("info", msg))
        self._background(work)

    # -- crash logs ----------------------------------------------------------------------

    def read_crash_log(self) -> None:
        """Pick a crash log (the newest is offered first) and show which mods it names."""
        from .. import crashlog
        extra = []  # .NET Script Framework writes its logs into the game's Data folder (MO2: overwrite)
        try:
            inst = make_target("mo2", self.settings.game,
                               **{k: v.get().strip() for k, v in self.path_vars.items()}).instance_dir
            if inst:
                extra.append(inst / "overwrite" / "NetScriptFramework" / "Crash")
        except ManagerError:
            pass
        newest = crashlog.newest_logs(1, extra)
        folders = crashlog.log_folders(extra)
        path = filedialog.askopenfilename(
            title="Pick a crash log (Crash Logger: crash-....log; .NET Script Framework: Crash_....txt)",
            initialdir=str(newest[0].parent if newest else folders[0] if folders else Path.home()),
            initialfile=newest[0].name if newest else "",
            filetypes=[("Crash logs", "*.log *.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as err:
            messagebox.showerror("Crash log", f"Couldn't read it: {err}", parent=self._parent())
            return
        crash = crashlog.parse(text)
        mo2_files, mo2_ids = {}, {}
        try:
            target = make_target("mo2", self.settings.game,
                                 **{k: v.get().strip() for k, v in self.path_vars.items()})
            mods_dir = target.mods_dir()
        except ManagerError:
            mods_dir = None
        if mods_dir and mods_dir.is_dir():
            mo2_files = crashlog.index_mo2(mods_dir)
            mo2_ids = crashlog.mo2_mod_ids(mods_dir, [mo2_files[n.name.lower()] for n in crash.named
                                                      if n.name.lower() in mo2_files])
        crashlog.match(crash, self.plans, mo2_files, mo2_ids,
                       crashlog.preview_index(self.plans, nexuscache.shared()))
        from .dialogs import CrashDialog
        CrashDialog(self.root, crash, Path(path))

    def check_for_updates(self) -> None:
        if not self.plans:
            messagebox.showinfo("Updates", "Look up the mods in your list first.", parent=self._parent())
            return
        if self.client is None:
            messagebox.showinfo("Updates", "Log in first.", parent=self._parent())
            return
        client, plans, target = self.client, list(self.plans), self._target_game()
        todo = [p for p in plans if p.mod and not p.error and not p.skipped and p.selected]
        newer = [p for p in todo if p.newer_files]
        if newer and len(newer) < len(todo):
            answer = messagebox.askyesnocancel(
                "Updates", f"{len(newer)} mods in your list have new files on Nexus (marked \u2b06).\n\n"
                f"Yes: check just those (about {2 * len(newer)} requests)\n"
                f"No: check all {len(todo)} mods (about {2 * len(todo)} requests)", parent=self._parent())
            if answer is None:
                return
            if answer:
                plans = todo = newer
        if not self._requests_ok(2 * len(todo), f"Checking {len(todo)} mods for updates"):
            return
        self.status_var.set("Checking Nexus for newer files…")
        self._checked_for_updates = list(todo)
        self.new_operation()

        def work():
            found, errors = updates.check_updates(
                client, plans, target,
                progress=lambda d, t: self.events.put(("status", f"Checked {d} of {t} mods for updates")))
            self.events.put(("updates", (found, errors)))
        self._background(work)

    # -- once a day: which mods have new files (one request) -------------------------------

    def daily_mod_check(self, force: bool = False) -> None:
        s = self.settings
        for p in self.plans:  # marks from today's check, kept across restarts
            p.newer_files = p.newer_files or p.entry.mod_id in set(s.newer_mod_ids or [])
        if not force and (not s.check_mod_updates or time.time() - s.last_mod_update_check < 20 * 3600):
            if any(p.newer_files for p in self.plans):
                self._fill_tree()
            return
        if self.client is None or not self.plans or self.busy:
            if not force:
                self.root.after(10 * 60 * 1000, self.daily_mod_check)  # try again in 10 minutes
            return
        days = (time.time() - s.last_mod_update_check) / 86400
        period = "1d" if days <= 1.2 else "1w" if days <= 7 else "1m"
        client, plans, game = self.client, list(self.plans), self.settings.game

        def work():
            try:
                updated = client.updated_mods(game, period)
            except NexusError as err:
                log.warning("Daily update check: %s", err)
                return
            self.events.put(("mod-updates", (updates.newer_on_nexus(plans, updated), period)))
        threading.Thread(target=work, daemon=True).start()

    def _daily_done(self, newer, period) -> None:
        s = self.settings
        s.last_mod_update_check = time.time()
        s.newer_mod_ids = sorted({p.entry.mod_id for p in self.plans if p.newer_files})
        self._save_settings()
        if newer:
            self._fill_tree()
            self.status_var.set(f"{len(newer)} mods in your list have new files on Nexus (marked \u2b06) - "
                                "press Check for updates to see them.")
        log.info("Daily update check (%s): %d mods with new files", period, len(newer))

    def _daily_toggled(self) -> None:
        self.settings.check_mod_updates = self.daily_var.get()
        self._save_settings()
        if self.settings.check_mod_updates:
            self.daily_mod_check()

    def _updates_done(self, found, errors) -> None:
        for p in getattr(self, "_checked_for_updates", []):
            p.newer_files = False
        self.settings.newer_mod_ids = sorted({p.entry.mod_id for p in self.plans if p.newer_files})
        self._fill_tree()
        if not found:
            msg = "Everything you picked is up to date."
            if errors:
                msg += "\n\nCouldn't check:\n" + "\n".join(errors[:10])
            self.status_var.set("No updates.")
            messagebox.showinfo("Updates", msg, parent=self._parent())
            return
        self.status_var.set(f"{len(found)} update(s) found.")
        dlg = UpdatesDialog(self.root, found)
        dlg.wait_window()
        if dlg.chosen:
            n = updates.apply(dlg.chosen)
            self._fill_tree()
            self.status_var.set(f"Switched {n} file(s) to the newer version - Start downloads to get them.")

    def run_loot(self) -> None:
        manager = self.manager_var.get()
        try:
            target = self._target()
            if manager == "mo2":
                inst = target.instance_dir
                args = loot.command("mo2", self.settings.game, mo2_exe=target.exe(), instance_dir=inst,
                                    instance_name=inst.name if inst else None, portable=target.is_portable)
            else:
                args = loot.command("vortex", self.settings.game)
        except ManagerError as err:
            messagebox.showinfo("LOOT", str(err), parent=self._parent())
            return
        try:
            import subprocess
            subprocess.Popen(args, close_fds=True, env=appupdate.clean_env())
        except OSError as err:
            messagebox.showerror("LOOT", f"Couldn't start LOOT: {err}", parent=self._parent())
            return
        how = "through Mod Organizer 2" if manager == "mo2" else "on its own"
        self.status_var.set(f"Opened LOOT {how}: press Sort Plugins, then Apply.")

    def check_compatibility(self, auto: bool) -> None:
        if not self.plans:
            if not auto:
                messagebox.showinfo("SkyrimDownloaded", "Look up the mods in your list first.", parent=self._parent())
            return
        client, plans = self.client, list(self.plans)
        self.status_var.set("Checking how your mods relate to each other\u2026")
        self.new_operation()

        def work():
            self.events.put(("compat", (compat.check(plans, client), auto)))
        self._background(work)

    def _compat_done(self, report: "compat.Report", auto: bool) -> None:
        self.compat = report
        self._fill_tree()
        self._show_details()
        n = len(report.findings)
        self.status_var.set(f"Compatibility: {n} link(s) between your mods" if n
                            else "Compatibility: no links found between your mods")
        if not report.findings:
            if not auto:
                messagebox.showinfo("Compatibility", "None of the mods in your list mention each other: "
                                    "no requirements, patches or conflicts between them were found.",
                                    parent=self._parent())
            return
        review = CompatDialog(self.root, report)
        review.wait_window()
        if review.choice == "review":
            to_review = report.plans_to_review()
            # tick the suggested patches (one per mod, one size); you can untick them
            for plan, fid in compat.patches_to_tick(report, texture=self._target_game().texture):
                if plan in to_review and fid not in plan.selected:
                    compat.tick_patch(plan, fid)
                    plan.reason = "suggested patch ticked - check it"
            self._fill_tree()
            self.walk_choices(to_review, review=True)

