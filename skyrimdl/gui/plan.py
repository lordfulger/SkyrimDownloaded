"""Step 4: the files list, the Nexus info panel, choosing options."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class PlanMixin:
    def _matches(self, plan: ModPlan, query: str) -> bool:
        if not query:
            return True
        text = " ".join([plan.title, plan.mod.author if plan.mod else "", plan.entry.note,
                         str(plan.entry.mod_id)] + [o.name for o in plan.options]).lower()
        return all(word in text for word in query.lower().split())

    # -- Ctrl+F ------------------------------------------------------------------

    def find(self, event=None):
        """Ctrl+F: jump to the search box (with the text you selected in the list, if any)."""
        try:
            if event is not None and event.widget.winfo_toplevel() is not self.root:
                return None  # a pop-up window handles its own Ctrl+F
        except (AttributeError, tk.TclError):
            pass
        try:
            if self.root.focus_get() is self.list_text and self.list_text.tag_ranges("sel"):
                picked = self.list_text.get("sel.first", "sel.last").strip()
                if picked and "\n" not in picked:
                    self.filter_var.set(picked)
        except tk.TclError:
            pass
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        self.search_entry.icursor("end")
        return "break"

    def _highlight_list(self) -> int:
        """Mark what you searched for in the mod list (section 3). Returns how many found."""
        text = self.list_text
        text.tag_remove("found", "1.0", "end")
        text.tag_remove("found_now", "1.0", "end")
        query = self.filter_var.get().strip()
        if not query:
            return 0
        count, start = 0, "1.0"
        length = tk.IntVar()
        while True:
            at = text.search(query, start, "end", nocase=True, count=length)
            if not at or not length.get():
                break
            end = f"{at}+{length.get()}c"
            text.tag_add("found", at, end)
            count += 1
            start = end
        text.tag_raise("found_now")
        return count

    def find_next(self, event=None, back: bool = False):
        """Enter in the search box: the next match in the list (Shift+Enter: the one before)."""
        query = self.filter_var.get().strip()
        if not query:
            return "break"
        text = self.list_text
        ranges = text.tag_ranges("found")
        if not ranges:
            self._highlight_list()
            ranges = text.tag_ranges("found")
        if ranges:
            now = text.tag_ranges("found_now")
            starts = [str(ranges[i]) for i in range(0, len(ranges), 2)]
            ends = [str(ranges[i]) for i in range(1, len(ranges), 2)]
            i = 0
            if now:
                cur = starts.index(str(now[0])) if str(now[0]) in starts else -1
                i = (cur + (-1 if back else 1)) % len(starts)
            elif back:
                i = len(starts) - 1
            text.tag_remove("found_now", "1.0", "end")
            text.tag_add("found_now", starts[i], ends[i])
            text.mark_set("insert", starts[i])
            text.see(starts[i])
            self.status_var.set(f"\u201c{query}\u201d: {i + 1} of {len(starts)} in the list "
                                "(Enter: next, Shift+Enter: back, Esc: clear)")
        # and the first matching mod in section 4
        rows = list(self._row_plan)
        if rows:
            sel = self.tree.selection()
            if not sel or sel[0] not in rows:
                self.tree.selection_set(rows[0])
                self.tree.see(rows[0])
        return "break"

    def _filter_changed(self) -> None:
        self._highlight_list()
        if getattr(self, "_filter_job", None):
            self.root.after_cancel(self._filter_job)
        self._filter_job = self.root.after(250, self._fill_tree)  # wait for a pause in typing

    def bulk(self, action: str) -> None:
        """Apply one change to every mod shown (all of them, or the ones matching the search)."""
        if action in ("expand", "collapse"):
            for row in self._row_plan:
                self.tree.item(row, open=action == "expand")
            return
        query = self.filter_var.get().strip()
        targets = [p for p in self.plans if not p.error and not p.skipped and self._matches(p, query)]
        suggestions = self.compat.suggestions() if self.compat else {}
        if action == "patches" and not suggestions:
            messagebox.showinfo("Bulk actions", "No suggested patches yet - press Check compatibility first.",
                                parent=self._parent())
            return
        changed = 0
        for plan in targets:
            before = list(plan.selected)
            if action == "patches":
                for fid in suggestions.get(id(plan), {}):
                    if fid not in plan.selected:
                        plan.selected.append(fid)
            elif action == "no-optional":
                plan.selected = [f for f in plan.selected if (o := plan.option(f)) is None or o.category != 3]
            elif action == "version":
                plan.selected = [f for f in plan.selected if (o := plan.option(f)) is None or not o.fit.hidden]
            elif action == "main-only":
                mains = [f for f in plan.selected if (o := plan.option(f)) is not None and o.category == 1]
                plan.selected = mains or plan.selected  # never leave a mod with nothing
            if plan.selected != before:
                changed += 1
                plan.needs_choice = False
                plan.reason = "your choice" if plan.selected else "nothing ticked - mod left out"
        self._fill_tree()
        where = f" (mods matching \u201c{query}\u201d)" if query else ""
        self.status_var.set(f"Changed {changed} mod(s){where}.")

    def _fill_tree(self) -> None:
        self.save_session()
        self._filter_job = None
        self.tree.delete(*self.tree.get_children())
        self._row_option.clear()
        self._row_plan.clear()
        self._job_rows.clear()
        query = self.filter_var.get().strip() if hasattr(self, "filter_var") else ""
        mods_shown = 0
        section = None
        for plan in self.plans:
            if not self._matches(plan, query):
                continue
            mods_shown += 1
            if plan.entry.section and plan.entry.section != section:
                section = plan.entry.section  # the list's "## ..." heading = an MO2 separator
                self.tree.insert("", "end", text=f"\u2500\u2500 {section} \u2500\u2500", tags=("section",))
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
        if hasattr(self, "filter_note"):
            self.filter_note.set(f"showing {mods_shown} of {len(self.plans)} mods" if query else "")
        if query:
            for row in self._row_plan:
                self.tree.item(row, open=True)

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
        suggested = self.compat.suggestions().get(id(plan), {}) if self.compat else {}
        declined = self.__dict__.setdefault("patch_declined", set())
        if fid in plan.selected:
            plan.selected.remove(fid)
            if fid in suggested:
                declined.add(self._patch_key(plan, fid))  # don't tick it again by itself
        else:
            plan.selected.append(fid)
            declined.discard(self._patch_key(plan, fid))
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
        self._info_plan = plan if opt is None else None  # a picture arriving late only goes to its own mod
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
        if mod and mod.picture_url and not opt:
            t.mark_set("picture", "end-1c")
            t.mark_gravity("picture", "left")
            put("\n")
            self._load_picture(plan, mod.picture_url)
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
        rows = self.requirement_rows(plan) if mod else []
        if rows:
            put("\nRequirements on Nexus\n", "h")
            for r in rows:
                put("\u2022 ")
                if r["url"]:
                    link(r["name"], r["url"])
                else:
                    put(r["name"])
                mark, tag = {"listed": ("in your list", "good"), "missing": ("not in your list", "warn"),
                             "dlc": ("DLC / Creation - make sure you have it", "meta"),
                             "outside": ("not on Nexus - get it yourself", "meta")}[r["status"]]
                put(f"  ({mark})", tag)
                if r["status"] == "missing":
                    put("  ")
                    tag_name = f"add{len(self._links)}"
                    self._links[tag_name] = r["url"]
                    t.insert("end", "Add to list", ("link", tag_name))

                    def add(_e, url=r["url"], p=plan):
                        self.add_requirement_to_list(url, p.title)
                        self._render_info(p, opt)
                        self.lookup_if_added()
                    t.tag_bind(tag_name, "<Button-1>", add)
                    t.tag_bind(tag_name, "<Enter>", lambda e: t.configure(cursor="hand2"))
                    t.tag_bind(tag_name, "<Leave>", lambda e: t.configure(cursor="arrow"))
                put("\n")
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

    def _load_picture(self, plan: ModPlan, url: str) -> None:
        """Fetch the mod's picture in the background and put it at the top of the panel."""
        cache = self.__dict__.setdefault("_pictures", {})
        self._info_plan = plan
        if url in cache:
            self._show_picture(plan, url, cache[url])
            return

        def work():
            self.events.put(("picture", (plan, url, pictures.fetch(url))))
        threading.Thread(target=work, daemon=True).start()

    def _show_picture(self, plan: ModPlan, url: str, data) -> None:
        cache = self.__dict__.setdefault("_pictures", {})
        cache[url] = data
        if getattr(self, "_info_plan", None) is not plan or not data:
            return  # the panel moved on to another mod, or there's no picture
        width = max(120, self.info.winfo_width() - 30)
        photo = pictures.to_photo(data, width)
        if photo is None:
            return
        self._info_photo = photo  # keep a reference, or Tk drops the image
        t = self.info
        try:
            t.configure(state="normal")
            t.image_create("picture", image=photo)
            t.configure(state="disabled")
        except tk.TclError:
            pass

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
                           title="Review linked mods" if review else "Choose options", start=start,
                           requirement_rows=self.requirement_rows,
                           add_requirement=self.add_requirement_to_list)
        dlg.wait_window()
        if report:  # suggested patches unticked in the window stay unticked
            declined = self.__dict__.setdefault("patch_declined", set())
            for plan in plans:
                for fid in report.suggestions().get(id(plan), {}):
                    (declined.discard if fid in plan.selected else declined.add)(self._patch_key(plan, fid))
        self._fill_tree()
        if self.lookup_if_added():  # requirements were added from the window: look them up
            return
        if review:
            return
        left = [p for p in self.plans if p.needs_choice and not p.error]
        if left:
            self.status_var.set(f"Paused with {len(left)} mod(s) still to choose - "
                                "Choose options\u2026 carries on where you left off.")
        else:
            self.status_var.set("All options chosen. Press Check compatibility to see how your mods "
                                "relate to each other, or Start downloads.")

