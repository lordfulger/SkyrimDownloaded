"""Step 3: the mod list, looking mods up, missing requirements."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class ListMixin:
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
        warning = sharing.version_warning(sharing.list_meta(self.list_text.get("1.0", "end-1c")),
                                          self._target_game())
        if warning:
            messagebox.showinfo("Shared list", warning, parent=self.root)
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

