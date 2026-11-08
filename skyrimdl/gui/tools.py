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
        Path(path).write_text(sharing.export_text(self.plans, self._target_game(), title=Path(path).stem),
                              encoding="utf-8")
        messagebox.showinfo("Share", f"Saved {path}.\n\nSend it to anyone with SkyrimDownloaded: opening "
                            "it and pressing Look up mods gives them exactly the same files.", parent=self._parent())

    def check_for_updates(self) -> None:
        if not self.plans:
            messagebox.showinfo("Updates", "Look up the mods in your list first.", parent=self._parent())
            return
        if self.client is None:
            messagebox.showinfo("Updates", "Log in first.", parent=self._parent())
            return
        client, plans, target = self.client, list(self.plans), self._target_game()
        todo = [p for p in plans if p.mod and not p.error and not p.skipped and p.selected]
        if not self._requests_ok(2 * len(todo), f"Checking {len(todo)} mods for updates"):
            return
        self.status_var.set("Checking Nexus for newer files…")
        self.new_operation()

        def work():
            found, errors = updates.check_updates(
                client, plans, target,
                progress=lambda d, t: self.events.put(("status", f"Checked {d} of {t} mods for updates")))
            self.events.put(("updates", (found, errors)))
        self._background(work)

    def _updates_done(self, found, errors) -> None:
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
            for plan in to_review:  # tick the suggested patches; you can untick them
                for fid in report.suggestions().get(id(plan), {}):
                    if fid not in plan.selected:
                        plan.selected.append(fid)
                        plan.reason = "suggested patch ticked - check it"
            self._fill_tree()
            self.walk_choices(to_review, review=True)

