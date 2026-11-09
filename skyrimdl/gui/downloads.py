"""Downloading / sending files to the mod manager."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class DownloadMixin:
    def start(self) -> None:
        if not self.plans:
            messagebox.showinfo("SkyrimDownloaded", "Look up the mods in your list first.", parent=self._parent())
            return
        waiting = [p for p in self.plans if p.needs_choice and not p.error]
        if waiting and not messagebox.askyesno(
                "Options not chosen",
                f"{len(waiting)} mods have options you haven't looked at "
                "(highlighted). Use the ticked files for them?", parent=self._parent()):
            self.walk_choices()
            return
        try:
            target = self._target()
        except ManagerError as err:
            messagebox.showerror("SkyrimDownloaded", str(err), parent=self._parent())
            return
        mode = self.mode_var.get()
        issues = target.problems(mode)
        if issues:
            messagebox.showerror("SkyrimDownloaded", "\n\n".join(issues), parent=self._parent())
            return
        if mode == "direct" and self.client and self.client._account and not self.client._account.is_premium:
            messagebox.showerror("SkyrimDownloaded", "Downloading here needs a Premium account. "
                                 "Choose 'Mod manager downloads' instead.", parent=self._parent())
            return
        mo2_auto = target.name == "Mod Organizer 2" and self.install_var.get()
        if mo2_auto and not self._mo2_addon_ready(target):
            return
        if mode == "handoff":
            if target.name == "Vortex":
                how = " and installs it (you'll see installer options there)." if self.install_var.get() else "."
            elif mo2_auto:
                how = (". Once they've all arrived, the SkyrimDownloaded add-on in MO2 installs them in your "
                       "list's order, puts them under the list's separators and switches them on. Mods with "
                       "installer options show their options window as they install.")
            else:
                how = "."
            if not messagebox.askokcancel(
                    "Ready?", f"Open {target.name} on your Skyrim setup now, then press OK.\n\n"
                    f"Each file is sent to {target.name} in your list's order, which downloads it with your "
                    f"Nexus login{how}\n\nA few download at a time: the next is sent as soon as one finishes, "
                    "and each shows as done here when it arrives.", parent=self._parent()):
                return
        self._save_settings()
        if self._list_is_saved():
            try:
                save_choices(choices_path(self.list_path), self.plans)
            except OSError:
                pass
        self.jobs = jobs_for(self.plans)
        if not self.jobs:
            messagebox.showinfo("SkyrimDownloaded", "No files ticked.", parent=self._parent())
            return
        # Already installed in MO2 (the same file)? Don't get it again.
        installed = self._installed_in_mo2(target)
        have = [j for j in self.jobs if (j.plan.entry.mod_id, j.option.file_id) in installed.get("files", {})]
        if have and messagebox.askyesno(
                "Already installed",
                f"{len(have)} of the {len(self.jobs)} files are already installed in MO2 (the same file "
                "from Nexus).\n\nSkip them?", parent=self._parent()):
            self.jobs = [j for j in self.jobs if j not in have]
            if not self.jobs:
                messagebox.showinfo("SkyrimDownloaded", "Everything ticked is already installed.",
                                    parent=self._parent())
                return
        # Room on the drives?
        short = [sp for sp in self._space_for(target, self.jobs) if not sp.enough]
        if short and not messagebox.askyesno(
                "Not enough disk space",
                "\n".join(f"{sp.folder}: needs about {human_size(sp.need)}, {human_size(sp.free)} free"
                          for sp in short) + "\n\nStart anyway?", icon="warning", parent=self._parent()):
            return
        self._map_job_rows()
        for row, plan in self._row_plan.items():  # show each file's progress
            self.tree.item(row, open=bool(plan.selected) and not plan.error)
        total = sum(j.option.approx_bytes or 0 for j in self.jobs) or 1
        self.progress.configure(maximum=total, value=0)
        self.new_operation()
        runner = Runner(self.client, target, mode=mode, install=self.install_var.get(),
                        parallel=self.settings.parallel,
                        on_event=lambda job: self.events.put(("job", job)), cancel=self.cancel,
                        category_separators=target.name == "Mod Organizer 2" and self.category_var.get())
        jobs = self.jobs

        def work():
            runner.run(jobs)
            self.events.put(("finished", jobs))
        self._background(work)

    def _installed_in_mo2(self, target) -> dict:
        if target.name != "Mod Organizer 2":
            return {}
        try:
            return target.installed()
        except Exception:
            log.exception("reading MO2's installed mods")
            return {}

    def _space_for(self, target, jobs, install: bool | None = None) -> list:
        """Disk space for these downloads (and for installing them, with MO2)."""
        from .. import listcheck
        try:
            downloads = target.downloads_dir()
        except ManagerError:
            downloads = None
        install = self.install_var.get() if install is None else install
        mods = target.mods_dir() if hasattr(target, "mods_dir") and install else None
        picked = {id(j.option) for j in jobs}

        class _Plan:  # just the files of these jobs
            def __init__(self, opts):
                self._opts, self.error, self.skipped = opts, None, False

            def selected_options(self):
                return self._opts
        return listcheck.space_needed([_Plan([j.option for j in jobs])], downloads, mods,
                                      already=lambda o: id(o) not in picked or bool(target.existing(o)))

    def _map_job_rows(self) -> None:
        self._job_rows.clear()
        for row, (plan, fid) in self._row_option.items():
            for job in self.jobs:
                if job.plan is plan and job.option.file_id == fid:
                    self._job_rows[id(job)] = row

    def _mo2_addon_ready(self, target) -> bool:
        """Installing in MO2 needs the SkyrimDownloaded add-on: offer to add it."""
        try:
            exe = target.exe()
        except ManagerError:
            messagebox.showerror("Install in MO2", "Point the tool at ModOrganizer.exe in step 2 first.",
                                 parent=self._parent())
            return False
        if mo2addon.addon_installed(exe):
            return True
        if not messagebox.askyesno(
                "Install in MO2", "Installing in MO2 is done by the SkyrimDownloaded add-on, which isn't in "
                "MO2 yet. Add it now?\n\n(MO2 has to be restarted once after adding it.)", parent=self._parent()):
            return False
        try:
            mo2addon.install_addon(exe)
        except OSError as err:
            messagebox.showerror("Install in MO2", f"Couldn't add it: {err}", parent=self._parent())
            return False
        self._manager_changed()
        messagebox.showinfo("Install in MO2", "Added. Restart Mod Organizer 2 now (close and open it), "
                            "then press Start downloads again.", parent=self._parent())
        return False

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
                if job.speed:
                    text += f" \u00b7 {human_size(job.speed)}/s \u00b7 {human_time(job.seconds_left)} left"
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
        status = f"{finished} of {len(self.jobs)} files"
        speed = sum(j.speed for j in self.jobs if j.state == WORKING)
        if speed:
            left = sum(max(0, (j.total_bytes or 0) - j.done_bytes) for j in self.jobs
                       if j.state in (WORKING, QUEUED))
            status += f" \u00b7 {human_size(speed)}/s \u00b7 about {human_time(left / speed)} left"
        self.status_var.set(status)

    def _finished(self, jobs: list[Job]) -> None:
        counts = summary(jobs)
        self._refresh_jobs({id(j) for j in jobs})
        text = ", ".join(f"{n} {state}" for state, n in counts.items())
        self.status_var.set("Finished: " + text)
        failed = [j for j in jobs if j.state == FAILED]
        msg = "Finished: " + text
        if failed:
            msg += "\n\nThese didn't work:\n" + "\n".join(f"• {j.label}: {j.note}" for j in failed[:15])
        if self.manager_var.get() == "mo2" and self.install_var.get() and (counts.get(DONE) or counts.get(SENT)):
            msg += ("\n\nMO2 installs them by itself once they've all downloaded, in your list's order "
                    "with its separators. Keep MO2 open.")
        elif self.manager_var.get() == "mo2" and (counts.get(DONE) or counts.get(SENT)):
            msg += ("\n\nTo install them all in your list's order: in MO2, Tools (puzzle piece) > "
                    "\"SkyrimDownloaded: install downloaded mods\"" + ("" if self.addon_btn.cget("text").endswith("\u2713")
                    else " - add it first with \"Add installer to MO2\" in step 2") + ". Or install them one by "
                    "one from MO2's Downloads tab.")
        if failed:
            if messagebox.askyesno("SkyrimDownloaded", msg + f"\n\nTry the {len(failed)} that didn't work again?",
                                   parent=self._parent()):
                self.retry_failed(failed)
            return
        messagebox.showinfo("SkyrimDownloaded", msg, parent=self._parent())

    def retry_failed(self, failed) -> None:
        """Send / download just the files that didn't work (finished ones are skipped anyway)."""
        try:
            target = self._target()
        except ManagerError as err:
            messagebox.showerror("SkyrimDownloaded", str(err), parent=self._parent())
            return
        for job in failed:
            job.state, job.note, job.done_bytes = QUEUED, "trying again", 0
        self.new_operation()
        runner = Runner(self.client, target, mode=self.mode_var.get(), install=self.install_var.get(),
                        parallel=self.settings.parallel,
                        on_event=lambda job: self.events.put(("job", job)), cancel=self.cancel,
                        category_separators=target.name == "Mod Organizer 2" and self.category_var.get())

        def work():
            runner.run(failed)
            self.events.put(("finished", self.jobs))
        self._background(work)

    def stop(self) -> None:
        self.stop_all()
        self.status_var.set("Stopping…")

