"""Step 3: the mod list, looking mods up, missing requirements."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class ListMixin:
    def _read_list(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as err:
            messagebox.showerror("SkyrimDownloaded", f"Can't read {path}:\n{err}", parent=self._parent())
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

    def import_collection(self) -> None:
        """Start (or add to) the list from a Nexus Collection's link."""
        if self.client is None:
            messagebox.showinfo("Collection", "Log in first.", parent=self._parent())
            return
        from tkinter import simpledialog
        link = simpledialog.askstring(
            "Start from a Nexus Collection",
            "Paste the collection's link (from its page on Nexus Mods):", parent=self._parent())
        if not link:
            return
        parsed = collections.parse_link(link)
        if not parsed:
            messagebox.showerror("Collection", "That doesn't look like a link to a Nexus Collection "
                                 "(\u2026nexusmods.com/games/skyrimspecialedition/collections/abc123).",
                                 parent=self._parent())
            return
        game, slug, revision = parsed
        client = self.client
        self.status_var.set("Getting the collection from Nexus\u2026")

        def work():
            data = client.collection(slug, game, revision)
            self.events.put(("collection", (data, game)))
        self._background(work)

    def _collection_loaded(self, data, game) -> None:
        text, count = collections.to_list(data, game)
        name = (data.get("collection") or {}).get("name") or "the collection"
        current = self.list_text.get("1.0", "end-1c").strip()
        if current:
            answer = messagebox.askyesnocancel(
                "Collection", f"{name} has {count} mods.\n\nYes: add them to your current list\n"
                "No: replace your list with them", parent=self._parent())
            if answer is None:
                return
            if answer:
                text = current + "\n\n" + text
        self.list_text.delete("1.0", "end")
        self.list_text.insert("1.0", text)
        self.list_path = None
        self.list_label.set(f"(from the collection {name})")
        self.status_var.set(f"Added {count} mods from {name}. Change the list if you like, then Look up mods.")
        log.info("Imported collection %s (%d mods)", name, count)

    def lookup(self) -> None:
        if self.client is None:
            messagebox.showinfo("SkyrimDownloaded", "Log in with your API key first.", parent=self._parent())
            return
        entries, problems = parse_list(self.list_text.get("1.0", "end-1c"), self.settings.game)
        if problems:
            messagebox.showwarning("Problems in the list", "\n".join(problems[:20]), parent=self._parent())
        if not entries:
            messagebox.showinfo("SkyrimDownloaded", "No Nexus links or mod numbers in the list.", parent=self._parent())
            return
        warning = sharing.version_warning(sharing.list_meta(self.list_text.get("1.0", "end-1c")),
                                          self._target_game())
        if warning:
            messagebox.showinfo("Shared list", warning, parent=self._parent())
        others = sorted({e.game for e in entries if e.game != self.settings.game})
        if others and not messagebox.askyesno(
                "Other games", "Some links are for other games (" + ", ".join(others)
                + "). Your mod manager may refuse them. Carry on?", parent=self._parent()):
            return
        self._list_was_saved = self._list_is_saved()
        store = choices_path(self.list_path) if self._list_was_saved else None
        remembered = {} if self.fresh_var.get() else load_choices(store)
        if not self.fresh_var.get():  # keep what was ticked in this window
            remembered.update({p.entry.key: list(p.selected) for p in self.plans
                               if p.selected and not p.needs_choice and not p.error
                               and p.reason in ("your choice", "your earlier choice")})
        client = self.client
        client.refresh = self.refresh_var.get()
        needed = client.estimate_lookup([(e.game, e.mod_id) for e in entries if e.rule.mode != "skip"])
        if not self._requests_ok(needed, f"Looking up {len(entries)} mods"):
            client.refresh = False
            return
        self._save_settings()
        target = self._target_game()
        made, saved = client.requests_made, client.requests_saved

        def work():
            try:
                plans = resolve(client, entries, remembered=remembered, target=target,
                                on_progress=lambda d, t, p: self.events.put(("lookup-progress", (d, t))))
            finally:
                client.refresh = False
            self._lookup_cost = (client.requests_made - made, client.requests_saved - saved)
            self.events.put(("plans", plans))
        self.refresh_var.set(False)
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
        external = [m for m in missing if m.requirement.external and not m.requirement.dlc
                    and m.link not in self.declined]
        dlc = [m for m in missing if m.requirement.dlc and m.link not in self.declined]
        if dlc:
            self.declined.update(m.link for m in dlc)
            external = external + dlc
        if addable or external:
            lines = []
            if addable:
                lines.append("These mods need others that aren't in your list:\n")
                lines += [f"\u2022 {m.requirement.name}  (needed by {', '.join(m.needed_by)})"
                          + (f"\n     {m.requirement.notes}" if m.requirement.notes else "")
                          for m in addable[:25]]
            outside = [m for m in external if not m.requirement.dlc]
            if outside:
                lines.append("\nNot on Nexus, get these yourself:")
                lines += [f"\u2022 {m.requirement.name}: {m.link}" for m in outside[:10]]
            content = [m for m in external if m.requirement.dlc]
            if content:
                lines.append("\nGame content these mods need (DLC / Creations) - make sure you have it:")
                lines += [f"\u2022 {m.requirement.name}  (for {', '.join(m.needed_by)})"
                          + (f" - {m.requirement.notes}" if m.requirement.notes else "") for m in content[:10]]
            self.declined.update(m.link for m in external)
            if addable:
                lines.append("\nAdd the missing Nexus mods to the list?")
                add = messagebox.askyesno("Missing requirements", "\n".join(lines), parent=self._parent())
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
                messagebox.showinfo("Requirements", "\n".join(lines), parent=self._parent())
        if waiting:
            self.root.after(50, self.walk_choices)

