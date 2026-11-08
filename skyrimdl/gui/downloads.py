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
        if mode == "handoff" and not messagebox.askokcancel(
                "Ready?", f"Open {target.name} on your Skyrim setup now, then press OK.\n\n"
                f"Each file is sent to {target.name}, which downloads it with your Nexus login"
                + (" and installs it (you'll see installer options there)."
                   if target.name == "Vortex" and self.install_var.get() else "."),
                parent=self._parent()):
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
        messagebox.showinfo("SkyrimDownloaded", msg, parent=self._parent())

    def stop(self) -> None:
        self.cancel.set()
        self.status_var.set("Stopping…")

