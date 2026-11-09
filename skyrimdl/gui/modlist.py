"""Step 3: the mod list, looking mods up, missing requirements."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, RequirementsDialog, UpdatesDialog


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
        self.new_operation()

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
        self.new_operation()
        self._background(work)

    def _check_requirements(self) -> None:
        client, plans = self.client, list(self.plans)

        if self.cancel.is_set():  # Stop was pressed during the lookup: skip the checks
            return

        def work():
            missing, checked = missing_requirements(client, plans)
            if self.cancel.is_set():
                return
            # Also look for patch files for other mods in the list (no pop-up: they're just ticked).
            report = compat.check(plans, client)
            self.events.put(("requirements", (missing, checked, report)))
        self._background(work)

    def _patch_key(self, plan, fid) -> str:
        return f"{plan.entry.key}:{fid}"

    def auto_tick_patches(self, report) -> int:
        """Tick patch files meant for other mods in the list (e.g. EasyNPC's files for
        Pandorable / Interesting NPCs when those are in the list too), unless you unticked them."""
        declined = self.__dict__.setdefault("patch_declined", set())
        ticked = 0
        for plan, fid in compat.patches_to_tick(
                report, skip=lambda p, f: self._patch_key(p, f) in declined,
                texture=self._target_game().texture):
            compat.tick_patch(plan, fid)  # a "DynDOLOD version" main file replaces the plain one
            ticked += 1
            if "patches" not in plan.reason:
                plan.reason = (plan.reason + " + " if plan.reason else "") + "patches for mods in your list"
        return ticked

    # -- requirements: what each mod needs, and adding what's missing ------------

    def requirement_rows(self, plan: ModPlan) -> list[dict]:
        """A mod's requirements on Nexus, each with a link and whether it's in the list."""
        key = f"req:{plan.entry.game}/{plan.entry.mod_id}"
        reqs = (self.client._cache.get(key) if self.client else None) or self._req_cache.get(key) or []
        if not reqs:
            # Looked up on an earlier run: it's in the saved answers on this PC (no request).
            try:
                from ..nexus import Requirement
                from ..nexuscache import shared
                saved = shared().get(key)
                reqs = [Requirement(**r) for r in saved] if saved else []
            except Exception:
                reqs = []
        listed = self._listed_mods()
        rows = []
        for r in reqs:
            url = r.url or (f"https://www.nexusmods.com/{plan.entry.game}/mods/{r.mod_id}" if r.mod_id else "")
            if r.dlc:
                status = "dlc"
            elif r.external or not r.mod_id:
                status = "outside"
            else:
                status = "listed" if (plan.entry.game, r.mod_id) in listed else "missing"
            rows.append({"name": r.name, "url": url, "notes": r.notes, "status": status,
                         "needed_by": plan.title})
        return rows

    def _listed_mods(self) -> set:
        """(game, mod id) of every mod in the list, including ones added but not looked up yet."""
        entries, _ = parse_list(self.list_text.get("1.0", "end-1c"), self.settings.game)
        return {(e.game, e.mod_id) for e in entries} | {(p.entry.game, p.entry.mod_id) for p in self.plans}

    def add_requirement_to_list(self, url: str, needed_by: str) -> bool:
        """Add a required mod to the list (looked up once the current window closes)."""
        entries, _ = parse_list(url, self.settings.game)
        if not entries or (entries[0].game, entries[0].mod_id) in self._listed_mods():
            return False
        body = self.list_text.get("1.0", "end-1c").rstrip("\n")
        if "# Added requirements" not in body:
            body += "\n\n# Added requirements"
        body += f"\n{url}    # required by {needed_by[:80]}"
        self.list_text.delete("1.0", "end")
        self.list_text.insert("1.0", body + "\n")
        if self.list_path and getattr(self, "_list_was_saved", False):
            try:
                self.list_path.write_text(self.list_text.get("1.0", "end-1c"), encoding="utf-8")
            except OSError:
                pass
        self.declined.add(url)
        self._pending_lookup = True
        self.status_var.set(f"Added {url.rsplit('/', 1)[-1]} to the list - it's looked up next.")
        log.info("Added requirement %s (needed by %s)", url, needed_by)
        return True

    def lookup_if_added(self) -> bool:
        """Look the list up again if requirements were added (cheap: the rest is saved)."""
        if getattr(self, "_pending_lookup", False):
            self._pending_lookup = False
            self.root.after(50, self.lookup)
            return True
        return False

    def _requirements_done(self, missing, checked, report=None) -> None:
        ticked = 0
        if report is not None:
            self.compat = report
            ticked = self.auto_tick_patches(report)
            self._fill_tree()
            if ticked:
                log.info("Ticked %d patch files for mods in the list", ticked)
        waiting = sum(1 for p in self.plans if p.needs_choice and not p.error)
        self.status_var.set(f"{len(self.plans)} mods looked up"
                            + (f", {waiting} have options to choose" if waiting else "")
                            + ("" if checked else " (couldn't check requirements)")
                            + (f" \u00b7 ticked {ticked} patch file(s) for mods in your list (\u2605)" if ticked else ""))
        new = [m for m in missing if m.link not in self.declined]
        if new:
            dlg = RequirementsDialog(self.root, new)
            dlg.wait_window()
            self.declined.update(m.link for m in new)  # don't ask about these again
            for m in dlg.chosen:
                self.add_requirement_to_list(m.link, ", ".join(m.needed_by))
            if self.lookup_if_added():
                return
        if waiting:
            self.root.after(50, self.walk_choices)


