"""Step 4: the files list, the Nexus info panel, choosing options."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class PlanMixin:
    def _fill_tree(self) -> None:
        self.save_session()
        self.tree.delete(*self.tree.get_children())
        self._row_option.clear()
        self._row_plan.clear()
        self._job_rows.clear()
        for plan in self.plans:
            tags = ("error",) if plan.error else ("choose",) if plan.needs_choice else ()
            if plan.error:
                status = plan.error
            elif plan.skipped:
                status, tags = "skipped in the list", ("off",)
            elif plan.needs_choice:
                status = "Choose files: " + plan.reason
            else:
                status = plan.reason
            warns = self.compat.warnings().get(id(plan)) if self.compat else None
            if warns and not plan.error:
                status = "\u26a0 " + "; ".join(warns[:2]) + " \u00b7 " + status
            suggested = self.compat.suggestions().get(id(plan), {}) if self.compat else {}
            author = f"  by {plan.mod.author}" if plan.mod and plan.mod.author else ""
            row = self.tree.insert("", "end", text=f"{plan.title}{author}", open=plan.needs_choice,
                                   values=("", "", plan.mod.version if plan.mod else "", "", status),
                                   tags=tags)
            self._row_plan[row] = plan
            for opt in visible_options(plan.options, self.old_var.get(), self.other_var.get()):
                on = opt.file_id in plan.selected
                child = self.tree.insert(row, "end", text=opt.name,
                                         values=(ON if on else OFF, opt.category_label, opt.version,
                                                 opt.size_text, file_status(opt, suggested.get(opt.file_id))),
                                         tags=() if on else ("off",))
                self._row_option[child] = (plan, opt.file_id)
            # Selected files that are hidden (e.g. an old version linked in the list).
            shown = {fid for (_, fid) in (self._row_option[c] for c in self.tree.get_children(row))}
            for fid in plan.selected:
                opt = plan.option(fid)
                if opt and fid not in shown:
                    child = self.tree.insert(row, "end", text=opt.name,
                                             values=(ON, opt.category_label, opt.version, opt.size_text, ""))
                    self._row_option[child] = (plan, fid)
        self._update_plan_summary()

    def _update_plan_summary(self) -> None:
        jobs = jobs_for(self.plans)
        size = sum(j.option.approx_bytes or 0 for j in jobs)
        self.plan_var.set(f"{len(jobs)} files, about {human_size(size)}")

    def _tree_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1":
            self._toggle(row)

    def _tree_double(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row in self._row_option:
            if self.tree.identify_column(event.x) != "#1":  # single click there already toggled
                self._toggle(row)
        elif row:
            self.open_page()

    def _toggle(self, row: str) -> None:
        if self.busy or row not in self._row_option:
            return
        plan, fid = self._row_option[row]
        if fid in plan.selected:
            plan.selected.remove(fid)
        else:
            plan.selected.append(fid)
        on = fid in plan.selected
        self.tree.set(row, "get", ON if on else OFF)
        self.tree.item(row, tags=() if on else ("off",))
        self._mark_chosen(plan)
        self._update_plan_summary()
        self.save_session()

    def _mark_chosen(self, plan: ModPlan) -> None:
        plan.needs_choice = False
        plan.reason = "your choice" if plan.selected else "nothing ticked - mod left out"
        for row, p in self._row_plan.items():
            if p is plan:
                self.tree.item(row, tags=())
                self.tree.set(row, "status", plan.reason)

    def _show_details(self, _event=None) -> None:
        """Show the Nexus page info for the mod (or file) clicked in the list."""
        row = self.tree.focus()
        if row in self._row_option:
            plan, fid = self._row_option[row]
            self._render_info(plan, plan.option(fid))
        elif row in self._row_plan:
            self._render_info(self._row_plan[row], None)

    def _render_info(self, plan: ModPlan, opt) -> None:
        t = self.info
        c = self.theme.colors
        t.configure(state="normal")
        t.delete("1.0", "end")
        for tag in list(self._links):
            t.tag_delete(tag)
        self._links.clear()
        t.tag_configure("title", font=("TkDefaultFont", 13, "bold"), spacing3=2)
        t.tag_configure("h", font=("TkDefaultFont", 10, "bold"), spacing1=8, spacing3=2)
        t.tag_configure("meta", foreground=c["muted"])
        t.tag_configure("warn", foreground=c["error"])
        t.tag_configure("good", foreground=c["done"])
        t.tag_configure("link", foreground=c["accent"], underline=True)

        def put(text: str, *tags: str) -> None:
            t.insert("end", text, tags)

        def link(text: str, url: str) -> None:
            tag = f"link{len(self._links)}"
            self._links[tag] = url
            t.insert("end", text, ("link", tag))
            t.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            t.tag_bind(tag, "<Enter>", lambda e: t.configure(cursor="hand2"))
            t.tag_bind(tag, "<Leave>", lambda e: t.configure(cursor="arrow"))

        mod = plan.mod
        raw = mod.raw if mod else {}
        if opt:
            put(opt.name + "\n", "title")
            bits = [opt.category_label + " file"]
            if opt.version:
                bits.append(f"v{opt.version}")
            bits.append(opt.size_text)
            if opt.uploaded:
                bits.append("uploaded " + time.strftime("%d %b %Y", time.localtime(opt.uploaded)))
            put(" \u00b7 ".join(bits) + "\n", "meta")
            if opt.fit.note and opt.fit.status != "unknown":
                put(("\u2713 " if not opt.fit.hidden else "\u26a0 ") + opt.fit.note + "\n",
                    "warn" if opt.fit.hidden else "good")
            why = (self.compat.suggestions().get(id(plan), {}).get(opt.file_id) if self.compat else None)
            if why:
                put(f"\u2605 Suggested patch: {why}\n", "good")
            put("\n" + (opt.description or "No description for this file.") + "\n")
            put("\nPart of\n", "h")
        put((mod.name if mod else plan.title) + "\n", "h" if opt else "title")
        if mod:
            meta = []
            if mod.author:
                meta.append(f"by {mod.author}")
            if mod.version:
                meta.append(f"version {mod.version}")
            if raw.get("updated_timestamp"):
                meta.append("updated " + time.strftime("%d %b %Y", time.localtime(int(raw["updated_timestamp"]))))
            put(" \u00b7 ".join(meta) + "\n", "meta")
            counts = []
            if raw.get("endorsement_count") is not None:
                counts.append(f"{int(raw['endorsement_count']):,} endorsements")
            if raw.get("mod_downloads") is not None:
                counts.append(f"{int(raw['mod_downloads']):,} downloads")
            if counts:
                put(" \u00b7 ".join(counts) + "\n", "meta")
        link("Open on Nexus \u2197", plan.entry.page_url)
        put("   ")
        link("Files tab \u2197", plan.entry.page_url + "?tab=files")
        put("\n")
        if plan.error:
            put(f"\n\u26a0 {plan.error}\n", "warn")
        if plan.entry.note:
            put(f"\nYour note: {plan.entry.note}\n", "meta")
        if self.compat:
            notes = self.compat.notes_for(plan)
            if notes:
                put("\nLinks with your other mods\n", "h")
                for n in notes[:12]:
                    put(f"\u2022 {n}\n")
        reqs = None
        if mod:
            key = f"req:{plan.entry.game}/{plan.entry.mod_id}"
            reqs = (self.client._cache.get(key) if self.client else None) or self._req_cache.get(key)
        if reqs:
            have = {p.entry.mod_id for p in self.plans}
            put("\nRequirements on Nexus\n", "h")
            for r in reqs:
                mark, tag = ("\u2713 in your list", "good") if r.mod_id in have else (
                    ("not on Nexus", "meta") if r.external else ("not in your list", "warn"))
                put(f"\u2022 {r.name} ")
                put(f"({mark})\n", tag)
        if mod and not opt:
            if mod.summary:
                put("\nSummary\n", "h")
                put(bbcode_to_text(mod.summary) + "\n")
            desc = bbcode_to_text(str(raw.get("description") or ""))
            if desc:
                put("\nDescription\n", "h")
                put(desc + "\n")
        t.configure(state="disabled")
        t.yview_moveto(0)

    def _focused_plan(self) -> ModPlan | None:
        row = self.tree.focus()
        if row in self._row_option:
            return self._row_option[row][0]
        return self._row_plan.get(row)

    def open_page(self) -> None:
        plan = self._focused_plan()
        if plan:
            webbrowser.open(plan.entry.page_url + "?tab=files")

    def walk_choices(self, plans: list | None = None, review: bool = False) -> None:
        """Step through the mods with options, one at a time, like a collection install.

        Opens at the first mod still waiting for a choice (where you left off), with the
        ones before it reachable with Back; mods skipped for now come last. Once every
        mod has been chosen, the mods are checked for links with each other."""
        start = 0
        if plans is None:
            with_options = [p for p in self.plans if not p.error and not p.skipped and
                            (p.needs_choice or len(visible_options(p.options)) > 1)]
            later = [p for p in with_options if p.reason.startswith("skipped for now")]
            plans = [p for p in with_options if p not in later] + later
            waiting = [i for i, p in enumerate(plans) if p.needs_choice]
            start = waiting[0] if waiting else 0
        if not plans:
            if review:
                return
            messagebox.showinfo("SkyrimDownloaded", "No mods with options to choose.", parent=self._parent())
            return
        report = self.compat
        dlg = ChoiceDialog(self.root, plans, self.old_var.get(), self.other_var.get(),
                           suggestions=report.suggestions() if report else {},
                           warnings=report.warnings() if report else {},
                           title="Review linked mods" if review else "Choose options", start=start)
        dlg.wait_window()
        self._fill_tree()
        if review:
            return
        left = [p for p in self.plans if p.needs_choice and not p.error]
        if left:
            self.status_var.set(f"Paused with {len(left)} mod(s) still to choose - "
                                "Choose options\u2026 carries on where you left off.")
        else:
            self.status_var.set("All options chosen. Press Check compatibility to see how your mods "
                                "relate to each other, or Start downloads.")

