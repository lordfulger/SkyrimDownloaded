"""The pop-up windows: choose options, updates, compatibility."""

from __future__ import annotations

from .common import *  # noqa: F401,F403


class ChoiceDialog(tk.Toplevel):
    """One mod at a time: tick the files you want. Back / Skip for now / Leave out / Next.

    Mods skipped for now come back at the end, after all the others.
    """

    def __init__(self, master, plans: list[ModPlan], include_old: bool, include_other: bool = False, *,
                 suggestions: dict | None = None, warnings: dict | None = None,
                 title: str = "Choose options", start: int = 0,
                 requirement_rows=None, add_requirement=None, texture: str = ""):
        super().__init__(master)
        self.texture = texture
        self.plans = list(plans)
        self.include_old = include_old
        self.include_other = include_other
        self.suggestions = suggestions or {}
        self.warnings = warnings or {}
        self.requirement_rows = requirement_rows or (lambda plan: [])
        self.add_requirement = add_requirement
        self.like: dict = {}  # id(plan): {"files": [...], "from": title} - your pick for a similar mod
        # skipped for now (including skips from an earlier visit)
        self.later: list[ModPlan] = [p for p in self.plans if p.reason.startswith("skipped for now")]
        self.index = min(max(0, start), len(self.plans) - 1)
        self.resumed = start > 0
        self.vars: list[tuple[tk.BooleanVar, int]] = []
        self.title(title)
        self.geometry("800x600")
        self.minsize(560, 380)
        self.transient(master)
        self.grab_set()

        self.head = tk.StringVar()
        self.sub = tk.StringVar()
        ttk.Label(self, textvariable=self.head, style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, textvariable=self.sub, style="Muted.TLabel", wraplength=760).pack(anchor="w", padx=12)
        ttk.Label(self, text="Keys: 1-9 tick / untick a file \u00b7 Enter = Next \u00b7 Backspace = Back \u00b7 "
                             "S = Skip for now \u00b7 Ctrl+F = find a file", style="Muted.TLabel").pack(anchor="w", padx=12)
        # Warnings like "needs X" - X is a link to its Nexus page.
        self.warn_box = ttk.Frame(self)
        self.warn_box.pack(anchor="w", fill="x", padx=12)

        # Ctrl+F: find a file in this mod's list
        self.find_bar = ttk.Frame(self)
        ttk.Label(self.find_bar, text="Find a file:").pack(side="left")
        self.find_var = tk.StringVar()
        self.find_entry = ttk.Entry(self.find_bar, textvariable=self.find_var, width=34)
        self.find_entry.pack(side="left", padx=6)
        self.find_note = tk.StringVar()
        ttk.Label(self.find_bar, textvariable=self.find_note, style="Muted.TLabel").pack(side="left")
        ttk.Button(self.find_bar, text="\u2715", width=3, command=self.close_find).pack(side="right")
        self.find_var.trace_add("write", lambda *a: self.find_file(0))
        self.find_entry.bind("<Return>", lambda e: self.find_file(1) or "break")
        self.find_entry.bind("<Shift-Return>", lambda e: self.find_file(-1) or "break")
        self.find_entry.bind("<Escape>", lambda e: self.close_find() or "break")
        self._find_at = -1
        self._file_rows: list[tuple[object, str]] = []
        self._photos: list = []
        self._pic_token = object()

        body = ttk.Frame(self)
        self._body = body
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.canvas = tk.Canvas(body, highlightthickness=0, yscrollincrement=18)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.autoscroll = AutoScroll(self.canvas)
        wheel_scroll(self.canvas, self.inner)

        btns = ttk.Frame(self)  # moving around
        btns.pack(fill="x", padx=12, pady=(0, 4))
        ttk.Button(btns, text="\u25C0 Back", command=lambda: self.go(-1)).pack(side="left")
        ttk.Button(btns, text="Open mod page", command=self.open_page).pack(side="left", padx=6)
        ttk.Button(btns, text="Pictures", command=self.open_pictures).pack(side="left")
        self.count = tk.StringVar()
        ttk.Label(btns, textvariable=self.count).pack(side="left", padx=8)
        # Go back (or ahead) to a mod by its number or name
        ttk.Label(btns, text="Go to mod:").pack(side="left", padx=(8, 4))
        self.goto_var = tk.StringVar()
        goto = ttk.Entry(btns, textvariable=self.goto_var, width=8)
        goto.pack(side="left")
        goto.bind("<Return>", lambda e: self.go_to(self.goto_var.get()) or "break")
        ttk.Button(btns, text="Go", width=4, command=lambda: self.go_to(self.goto_var.get())).pack(side="left", padx=(2, 0))
        acts = ttk.Frame(self)  # deciding
        acts.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(acts, text="Done", command=self.finish).pack(side="right")
        ttk.Button(acts, text="Next \u25B6", style="Accent.TButton", command=lambda: self.go(1)).pack(side="right", padx=6)
        ttk.Button(acts, text="Leave this mod out", command=self.leave_out).pack(side="right")
        ttk.Button(acts, text="Skip for now", command=self.skip_for_now).pack(side="right", padx=6)
        self.accept_btn = ttk.Button(acts, text="Accept the rest (use what's ticked)", command=self.accept_rest)
        self.accept_btn.pack(side="left")
        self.bind("<Key>", self._key)
        self.bind("<Control-f>", self.open_find)
        self.bind("<Control-F>", self.open_find)
        self.bind("<Next>", lambda e: self.canvas.yview_scroll(1, "pages"))
        self.bind("<Prior>", lambda e: self.canvas.yview_scroll(-1, "pages"))
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.show()
        self.after(100, self.focus_force)  # so the number keys work straight away

    @property
    def plan(self) -> ModPlan:
        return self.plans[self.index]

    def show(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        plan = self.plan
        author = f" by {plan.mod.author}" if plan.mod and plan.mod.author else ""
        self.head.set(plan.title + author)
        sub = plan.reason
        if self.resumed:
            sub = "Picking up where you left off. " + sub
            self.resumed = False
        if plan in self.later:
            sub = "You skipped this one earlier - choose now, or Done to leave it for later."
        self.sub.set(sub + (f"   \u2022   your note: {plan.entry.note}" if plan.entry.note else ""))
        self._show_warnings(self.warnings.get(id(plan), []))
        skipped = f"   \u2022   {len(self.later)} skipped for later" if self.later else ""
        self.count.set(f"Mod {self.index + 1} of {len(self.plans)}{skipped}")
        self.vars = []
        self._photos = []
        self._file_rows = []
        self._find_at = -1
        last_cat = None
        options = visible_options(plan.options, self.include_old, self.include_other)
        hidden = [o for o in for_other_versions(plan.options) if o not in options]
        if hidden and "left out" not in self.sub.get():
            self.sub.set(self.sub.get() + f"   \u2022   {len(hidden)} file(s) for other game versions left out")
        for fid in plan.selected:  # keep a linked old file visible
            opt = plan.option(fid)
            if opt and opt not in options:
                options.append(opt)
        suggested = self.suggestions.get(id(plan), {})
        self._show_needs(plan)
        # Pictures from the mod's description, shown under the file they're about.
        raw_desc = str(((plan.mod.raw or {}) if plan.mod else {}).get("description") or "")
        pics = pictures.match_images(options, pictures.description_images(raw_desc),
                                     plan.mod.name if plan.mod else "")
        self._pic_token = object()
        for opt in options:
            if opt.category_label != last_cat:
                last_cat = opt.category_label
                ttk.Label(self.inner, text=f"{last_cat} files", font=("TkDefaultFont", 10, "bold")).pack(
                    anchor="w", pady=(10, 2))
            var = tk.BooleanVar(value=opt.file_id in plan.selected)
            text = f"{opt.name}   v{opt.version}   ({opt.size_text})" if opt.version else f"{opt.name}   ({opt.size_text})"
            if opt.fit.note and opt.fit.status != "unknown":
                text += f"   \u2014 {opt.fit.note}"
            if self.texture and texture_sizes(opt) and len(options) > 1:
                want = float(self.texture.rstrip("Kk"))
                if texture_sizes(opt) == {want}:
                    text += "   \u2605 your texture size"
                elif want in texture_sizes(opt):
                    text += "   \u2014 has your texture size"
            n = len(self.vars) + 1
            if n <= 9:
                text = f"{n}  " + text  # press the number to tick / untick
            box = ttk.Checkbutton(self.inner, text=text, variable=var)
            box.pack(anchor="w")
            self._file_rows.append((box, f"{text} {opt.file_name} {opt.description}".lower()))
            if opt.file_id in pics:
                spot = ttk.Label(self.inner, text="(loading picture\u2026)", style="Muted.TLabel", cursor="hand2")
                spot.pack(anchor="w", padx=24, pady=2)
                spot.bind("<Button-1>", lambda e, u=pics[opt.file_id]: webbrowser.open(u))
                self._load_picture(spot, pics[opt.file_id])
            if opt.file_id in self.like.get(id(plan), {}).get("files", []):
                ttk.Label(self.inner, text=f"\u2605 Same pick as for {self.like[id(plan)]['from']}",
                          style="Good.TLabel").pack(anchor="w", padx=24)
            if opt.file_id in suggested:
                ttk.Label(self.inner, text=f"\u2605 Suggested patch: {suggested[opt.file_id]}",
                          style="Good.TLabel").pack(anchor="w", padx=24)
            if opt.description:
                desc = opt.description if len(opt.description) < 500 else opt.description[:500] + "\u2026"
                ttk.Label(self.inner, text=desc, wraplength=700, style="Muted.TLabel").pack(anchor="w", padx=24)
            self.vars.append((var, opt.file_id))
        self.canvas.yview_moveto(0)
        # Wheel and middle-click scrolling anywhere over the list of files (new widgets only).
        wheel_scroll(self.canvas, *self.inner.winfo_children(), include_target=False)
        for w in self.inner.winfo_children():
            self.autoscroll.attach(w)
        if getattr(self.master, "_theme", None):
            self.master._theme.paint(self)
        if self.find_bar.winfo_ismapped() and self.find_var.get().strip():
            self.after_idle(lambda: self.find_file(0))

    # -- pictures --------------------------------------------------------------

    def _load_picture(self, spot, url: str) -> None:
        """Download in the background; shown when ready (if this mod is still on screen)."""
        token = self._pic_token
        box: dict = {}

        def work():
            box["data"] = pictures.fetch(url)
        threading.Thread(target=work, daemon=True).start()

        def check():
            if token is not self._pic_token or not spot.winfo_exists():
                return  # moved on to another mod
            if "data" not in box:
                self.after(200, check)
                return
            photo = pictures.to_photo(box["data"], 220, 124)
            if photo is None:
                spot.configure(text="(picture couldn't be shown - click to open it)")
                return
            self._photos.append(photo)  # Tk needs a reference kept
            spot.configure(image=photo, text="")
        self.after(200, check)

    def open_pictures(self) -> None:
        """The mod's image gallery on Nexus (it can't be read by programs, so in the browser)."""
        webbrowser.open(self.plan.entry.page_url + "?tab=images")

    # -- Ctrl+F --------------------------------------------------------------

    def open_find(self, event=None):
        if not self.find_bar.winfo_ismapped():
            self.find_bar.pack(fill="x", padx=12, pady=(6, 0), before=self._body)
        self.find_entry.focus_set()
        self.find_entry.select_range(0, "end")
        return "break"

    def close_find(self) -> None:
        self.find_var.set("")
        self.find_bar.pack_forget()
        self.focus_set()

    def find_file(self, step: int) -> None:
        """Scroll to a file matching what you typed. step 0: the first one, 1: next, -1: back."""
        words = self.find_var.get().lower().split()
        hits = [w for w, text in self._file_rows if words and all(x in text for x in words)]
        for w, _ in self._file_rows:
            try:
                w.state(["!focus"])
            except tk.TclError:
                pass
        if not words:
            self.find_note.set("")
            return
        if not hits:
            self.find_note.set("not found")
            return
        self._find_at = 0 if step == 0 or self._find_at < 0 else (self._find_at + step) % len(hits)
        self._find_at = min(self._find_at, len(hits) - 1)
        w = hits[self._find_at]
        self.find_note.set(f"{self._find_at + 1} of {len(hits)}   (Enter: next)")
        self.update_idletasks()
        total = max(1, self.inner.winfo_height())
        self.canvas.yview_moveto(max(0.0, (w.winfo_y() - 40) / total))
        w.state(["focus"])  # draws the focus outline round it, without taking the typing focus

    def _show_warnings(self, warns) -> None:
        for child in self.warn_box.winfo_children():
            child.destroy()
        for w in warns:
            line = ttk.Frame(self.warn_box)
            line.pack(anchor="w", fill="x")
            before = getattr(w, "before", None)
            if before is None:  # plain text
                ttk.Label(line, text="\u26a0 " + str(w), style="Warn.TLabel", wraplength=760).pack(side="left")
                continue
            ttk.Label(line, text="\u26a0 " + before, style="Warn.TLabel").pack(side="left")
            if w.url:
                link_label(line, w.name, w.url).pack(side="left", padx=(4, 0))
            else:
                ttk.Label(line, text=w.name, style="Warn.TLabel").pack(side="left", padx=(4, 0))
            if before == "needs" and w.url:
                self._needed_mod_status(line, w)
            elif w.after:
                ttk.Label(line, text=w.after, style="Warn.TLabel").pack(side="left")

    def _needed_mod_status(self, line, w) -> None:
        """After "needs X": whether X will be downloaded, with a button to fix it if not."""
        other = w.other

        def button(text, action):
            btn = ttk.Button(line, text=text)

            def press():
                done = action()
                btn.configure(text=done or "Done \u2713", state="disabled")
            btn.configure(command=press)
            btn.pack(side="left", padx=8)

        if other is None:
            ttk.Label(line, text="  not in your list", style="Warn.TLabel").pack(side="left")
            if self.add_requirement:
                button("Add to list", lambda: "Added \u2713" if self.add_requirement(w.url, self.plan.title)
                       else "Already in your list")
        elif other.skipped:
            ttk.Label(line, text="  in your list, but marked skip there", style="Warn.TLabel").pack(side="left")
        elif other.error or not other.selected:
            ttk.Label(line, text="  in your list, but left out", style="Warn.TLabel").pack(side="left")
            if not other.error and primary_file(other.options):
                button("Include it", lambda: self._include(other))
        else:
            ttk.Label(line, text="  \u2713 in your list", style="Good.TLabel").pack(side="left")

    def _include(self, other) -> str:
        """Get a needed mod after all: its main file, or what you pick when you get to it."""
        main = primary_file(other.options)
        other.selected = [main.file_id] if main else []
        other.reason = f"included - {self.plan.title} needs it"
        if other in self.later:
            self.later.remove(other)
        return "Included \u2713"

    def _show_needs(self, plan) -> None:
        """What this mod needs, with a link to each mod and Add to list for missing ones."""
        rows = self.requirement_rows(plan)
        if not rows:
            return
        ttk.Label(self.inner, text="Needs", font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(4, 2))
        for r in rows:
            line = ttk.Frame(self.inner)
            line.pack(anchor="w", fill="x", padx=(8, 0), pady=1)
            if r["status"] == "listed":
                ttk.Label(line, text="\u2713", style="Good.TLabel").pack(side="left")
                link_label(line, r["name"], r["url"]).pack(side="left", padx=4)
                ttk.Label(line, text="in your list", style="Muted.TLabel").pack(side="left")
            elif r["status"] == "missing":
                ttk.Label(line, text="\u2717", style="Warn.TLabel").pack(side="left")
                link_label(line, r["name"], r["url"]).pack(side="left", padx=4)
                ttk.Label(line, text="not in your list", style="Warn.TLabel").pack(side="left")
                if self.add_requirement:
                    btn = ttk.Button(line, text="Add to list")

                    def add(b=btn, row=r):
                        added = self.add_requirement(row["url"], plan.title)
                        b.configure(text="Added \u2713" if added else "Already in your list", state="disabled")
                    btn.configure(command=add)
                    btn.pack(side="left", padx=8)
            elif r["status"] == "dlc":
                ttk.Label(line, text="\u25c6").pack(side="left")
                ttk.Label(line, text=f"{r['name']} (DLC / Creation - make sure you have it)").pack(side="left", padx=4)
            else:
                ttk.Label(line, text="\u2192").pack(side="left")
                if r["url"]:
                    link_label(line, r["name"], r["url"]).pack(side="left", padx=4)
                else:
                    ttk.Label(line, text=r["name"]).pack(side="left", padx=4)
                ttk.Label(line, text="not on Nexus - get it yourself", style="Muted.TLabel").pack(side="left")
            if r.get("notes"):
                ttk.Label(self.inner, text=r["notes"], style="Muted.TLabel", wraplength=680).pack(anchor="w", padx=34)

    def _ticked(self) -> list[int]:
        return [fid for var, fid in self.vars if var.get()]

    def commit(self) -> None:
        plan = self.plan
        plan.selected = self._ticked()
        self._spread_pick(plan)
        plan.needs_choice = False
        plan.reason = "your choice" if plan.selected else "nothing ticked - mod left out"
        if plan in self.later:
            self.later.remove(plan)

    def go(self, step: int) -> None:
        # Next chooses what's ticked; Back only keeps changes you made.
        if step > 0 or set(self._ticked()) != set(self.plan.selected):
            self.commit()
        new = self.index + step
        if new >= len(self.plans):
            self.finish()
            return
        self.index = max(0, new)
        self.show()

    # -- faster choosing ---------------------------------------------------------

    def _key(self, event):
        """1-9 tick / untick a file, Enter = Next, Backspace = Back, S = Skip for now."""
        if isinstance(self.focus_get(), (ttk.Entry, tk.Entry)):
            return None  # typing in Find / Go to
        if event.char and event.char in "123456789":
            i = int(event.char) - 1
            if i < len(self.vars):
                self.vars[i][0].set(not self.vars[i][0].get())
            return "break"
        if event.keysym in ("Return", "KP_Enter"):
            self.go(1)
            return "break"
        if event.keysym == "BackSpace":
            self.go(-1)
            return "break"
        if event.keysym.lower() == "s" and not event.state & 0x4:
            self.skip_for_now()
            return "break"
        return None

    def _spread_pick(self, plan) -> None:
        """You picked e.g. "No Snow" for one mod: pre-tick the same for that author's other
        mods still waiting (they're still shown to you, marked \u2605)."""
        author = (plan.mod.author if plan.mod else "") or ""
        chosen = plan.selected_options()
        if not author or not chosen:
            return
        for other in self.plans:
            if other is plan or not other.needs_choice or not other.mod or other.mod.author != author:
                continue
            pick = pick_like(chosen, plan.options, plan.title, other.options, other.title)
            if pick:
                other.selected = pick
                other.reason = f"same pick as for {plan.title} - check it"
                self.like[id(other)] = {"files": pick, "from": plan.title}

    def accept_rest(self) -> None:
        """Take what's ticked for every mod still waiting (from here on, and the skipped ones),
        leaving only mods with nothing ticked."""
        waiting = [p for p in self.plans[self.index:] + self.later if p.needs_choice]
        waiting = list({id(p): p for p in waiting}.values())
        if set(self._ticked()) != set(self.plan.selected):
            self.plan.selected = self._ticked()
        ok = [p for p in waiting if p.selected]
        if not ok:
            self.sub.set("Nothing to accept: the mods left have nothing ticked.")
            return
        if not messagebox.askyesno(
                "Accept the rest", f"Use the ticked files for the {len(ok)} mod(s) still waiting?\n\n"
                "(They're the main file, your texture size, your word preferences, patches for mods in "
                "your list, or your pick for a similar mod. You can still change any of them in the list.)"
                + (f"\n\n{len(waiting) - len(ok)} with nothing ticked stay waiting." if len(waiting) > len(ok) else ""),
                parent=self):
            return
        for p in ok:
            p.needs_choice = False
            if not p.reason.startswith("accepted"):
                p.reason = "accepted the ticked files"
            if p in self.later:
                self.later.remove(p)
        self.autoscroll.stop()
        self.grab_release()
        self.destroy()

    def go_to(self, where: str) -> None:
        """Jump to mod number N (as counted in this window), or the first mod whose name has
        the text you typed. The mod on screen keeps any change you made to it."""
        where = (where or "").strip()
        if not where:
            return
        if where.isdigit():
            new = int(where) - 1
            if not 0 <= new < len(self.plans):
                self.sub.set(f"There's no mod {where} - pick 1 to {len(self.plans)}.")
                return
        else:
            hits = [i for i, p in enumerate(self.plans) if where.lower() in p.title.lower()]
            if not hits:
                self.sub.set(f"No mod here has \u201c{where}\u201d in its name.")
                return
            after = [i for i in hits if i > self.index]  # pressing Go again finds the next one
            new = after[0] if after else hits[0]
        if set(self._ticked()) != set(self.plan.selected):
            self.commit()
        self.index = new
        self.goto_var.set("")
        self.show()

    def skip_for_now(self) -> None:
        """Put this mod off: it comes back after all the others."""
        plan = self.plan
        plan.needs_choice = True
        plan.reason = "skipped for now - come back to it"
        if plan not in self.later:
            self.later.append(plan)
        if self.index == len(self.plans) - 1:
            self.sub.set("This is the last mod in the list. Choose its files, leave it out, or press "
                         "Done to come back to it later (it stays highlighted).")
            self.count.set(f"Mod {self.index + 1} of {len(self.plans)}   \u2022   {len(self.later)} skipped for later")
            return
        self.plans.pop(self.index)
        self.plans.append(plan)
        self.show()

    def leave_out(self) -> None:
        for var, _ in self.vars:
            var.set(False)
        self.go(1)

    def open_page(self) -> None:
        webbrowser.open(self.plan.entry.page_url + "?tab=files")

    def finish(self) -> None:
        """Done = stop here for now. The mod on screen only counts as chosen if you
        changed its ticks; otherwise it waits for next time, where this carries on."""
        plan = self.plan
        if set(self._ticked()) != set(plan.selected):
            self.commit()
        self.autoscroll.stop()
        self.grab_release()
        self.destroy()


class RequirementsDialog(tk.Toplevel):
    """Mods your list needs but doesn't have: a link to each, tick the ones to add."""

    def __init__(self, master, missing: list):
        super().__init__(master)
        self.chosen: list = []
        self.title("Missing requirements")
        self.geometry("820x500")
        self.transient(master)
        self.grab_set()
        addable = [m for m in missing if not m.requirement.external and not m.requirement.dlc]
        outside = [m for m in missing if m.requirement.external and not m.requirement.dlc]
        dlc = [m for m in missing if m.requirement.dlc]
        head = (f"{len(addable)} mod(s) your list needs but doesn't have" if addable
                else "Your mods need these too")
        ttk.Label(self, text=head, style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text="Click a name to open its Nexus page. Ticked mods are added to your list and "
                             "looked up.", style="Muted.TLabel").pack(anchor="w", padx=12)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        canvas = tk.Canvas(body, highlightthickness=0, yscrollincrement=18)
        sb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.vars = []

        def section(title):
            ttk.Label(inner, text=title, font=("TkDefaultFont", 10, "bold")).pack(anchor="w", pady=(8, 2))

        def row(m, ticked: bool | None):
            line = ttk.Frame(inner)
            line.pack(anchor="w", fill="x", pady=1)
            if ticked is not None:
                var = tk.BooleanVar(value=ticked)
                ttk.Checkbutton(line, variable=var).pack(side="left")
                self.vars.append((var, m))
            else:
                ttk.Label(line, text="\u25c6" if m.requirement.dlc else "\u2192").pack(side="left", padx=(4, 0))
            if m.link and not m.link.startswith("dlc:"):
                link_label(line, m.requirement.name, m.link).pack(side="left", padx=4)
            else:
                ttk.Label(line, text=m.requirement.name).pack(side="left", padx=4)
            ttk.Label(line, text=f"needed by {', '.join(m.needed_by)[:90]}", style="Muted.TLabel").pack(side="left")
            if m.requirement.notes:
                ttk.Label(inner, text=m.requirement.notes, style="Muted.TLabel", wraplength=740).pack(anchor="w", padx=30)

        if addable:
            section("On Nexus - tick to add to your list")
            for m in addable:
                row(m, True)
        if outside:
            section("Not on Nexus - get these yourself")
            for m in outside:
                row(m, None)
        if dlc:
            section("Game content (DLC / Creations) - make sure you have it")
            for m in dlc:
                row(m, None)
        wheel_scroll(canvas, inner)
        AutoScroll(canvas, also=tuple(inner.winfo_children()))
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Not now" if addable else "OK", command=self.destroy).pack(side="right")
        if addable:
            ttk.Button(btns, text="Add ticked to list \u25b6", style="Accent.TButton",
                       command=self._add).pack(side="right", padx=6)
        if getattr(master, "_theme", None):
            master._theme.paint(self)

    def _add(self) -> None:
        self.chosen = [m for var, m in self.vars if var.get()]
        self.destroy()


class UpdatesDialog(tk.Toplevel):
    """Newer files found: tick which ones to switch to."""

    def __init__(self, master, found: list):
        super().__init__(master)
        self.chosen: list = []
        self.title("Updates")
        self.geometry("820x480")
        self.transient(master)
        self.grab_set()
        newer = sum(1 for u in found if u.new is not None)
        gone = len(found) - newer
        head = ", ".join(x for x in (f"{newer} newer file(s) on Nexus" if newer else "",
                                     f"{gone} of your files removed" if gone else "") if x)
        ttk.Label(self, text=head, style="Title.TLabel").pack(
            anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text="Tick the ones to switch to; Start downloads then gets them. Files with no "
                             "replacement are listed so you can check the mod's page.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", padx=12)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        canvas = tk.Canvas(body, highlightthickness=0, yscrollincrement=18)
        sb = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.vars = []
        for u in found:
            if u.new is not None:
                var = tk.BooleanVar(value=True)
                ttk.Checkbutton(inner, text=u.label, variable=var).pack(anchor="w", pady=1)
                self.vars.append((var, u))
            else:
                ttk.Label(inner, text="⚠ " + u.label, style="Warn.TLabel").pack(anchor="w", pady=1)
        wheel_scroll(canvas, inner)
        AutoScroll(canvas, also=tuple(inner.winfo_children()))
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        if self.vars:
            ttk.Button(btns, text="Use the newer files", style="Accent.TButton",
                       command=self._use).pack(side="right", padx=6)
        if getattr(master, "_theme", None):
            master._theme.paint(self)

    def _use(self) -> None:
        self.chosen = [u for var, u in self.vars if var.get()]
        self.destroy()


class CompatDialog(tk.Toplevel):
    """What the compatibility check found, with a button to go over those mods again."""

    def __init__(self, master, report: "compat.Report"):
        super().__init__(master)
        self.choice = "close"
        self.title("Compatibility")
        self.geometry("820x560")
        self.transient(master)
        self.grab_set()
        n = len(report.findings)
        review = report.plans_to_review()
        ttk.Label(self, text=f"{n} link(s) found between the mods in your list",
                  style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text="From each mod's requirements, its files and its Nexus page. Page text is read "
                             "automatically, so treat \"possible\" items as things to check.",
                  style="Muted.TLabel", wraplength=780).pack(anchor="w", padx=12)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        text = tk.Text(body, wrap="word", relief="flat", highlightthickness=1, padx=10, pady=8,
                       font="TkDefaultFont")
        text._details = True
        sb = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        AutoScroll(text)
        theme = getattr(master, "_theme", None)
        c = theme.colors if theme else {"muted": "#555", "error": "#b00020", "done": "#1b7a1b"}
        text.tag_configure("h", font=("TkDefaultFont", 11, "bold"), spacing1=10, spacing3=4)
        text.tag_configure("meta", foreground=c["muted"])
        text.tag_configure("warn", foreground=c["error"])
        text.tag_configure("good", foreground=c["done"])
        icons = {compat.CONFLICT: ("\u26a0 ", "warn"), compat.PATCH: ("\u2605 ", "good"),
                 compat.NEEDS: ("\u2192 ", ""), compat.DLC: ("\u25c6 ", ""), compat.WORKS_WITH: ("\u2713 ", "good"),
                 compat.MENTIONS: ("\u2022 ", "meta")}
        for kind in (compat.CONFLICT, compat.PATCH, compat.NEEDS, compat.DLC, compat.WORKS_WITH, compat.MENTIONS):
            items = report.by_kind(kind)
            if not items:
                continue
            text.insert("end", f"{compat.HEADINGS[kind]} ({len(items)})\n", "h")
            icon, tag = icons[kind]
            for f in items:
                text.insert("end", icon + f.text, tag)
                if kind == compat.PATCH:
                    ticked = f.file_id in f.plan.selected
                    text.insert("end", "  (ticked)" if ticked else "  (not ticked yet)", "meta")
                text.insert("end", "\n")
                if f.evidence and kind not in (compat.NEEDS, compat.DLC):
                    text.insert("end", f"      \u201c{f.evidence[:160]}\u201d\n", "meta")
        if not report.requirements_checked:
            text.insert("end", "\n(Couldn't ask Nexus for requirements this time.)\n", "meta")
        text.configure(state="disabled")

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        if review:
            ttk.Button(btns, text=f"Review these {len(review)} mods \u25B6", style="Accent.TButton",
                       command=self._review).pack(side="right", padx=6)
            ttk.Label(btns, text="Suggested patches get ticked; you can untick them.",
                      style="Muted.TLabel").pack(side="left")
        if theme:
            theme.paint(self)

    def _review(self) -> None:
        self.choice = "review"
        self.destroy()



class ListCheckDialog(tk.Toplevel):
    """Check list: plugin count, disk space, already installed, duplicates, replaced or
    abandoned mods, and the download size for each texture size."""

    def __init__(self, master, result: dict, plans: list, texture: str = ""):
        from .. import listcheck
        super().__init__(master)
        self.title("Check list")
        self.geometry("860x620")
        self.transient(master)
        ttk.Label(self, text="Your list, checked", style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text="Before downloading: what could go wrong once it's all installed.",
                  style="Muted.TLabel").pack(anchor="w", padx=12)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        text = tk.Text(body, wrap="word", relief="flat", highlightthickness=1, padx=10, pady=8,
                       font="TkDefaultFont")
        text._details = True
        sb = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        AutoScroll(text)
        theme = getattr(master, "_theme", None)
        c = theme.colors if theme else {"muted": "#555", "error": "#b00020", "done": "#1b7a1b", "accent": "#2a6ad8"}
        text.tag_configure("h", font=("TkDefaultFont", 11, "bold"), spacing1=12, spacing3=4)
        text.tag_configure("meta", foreground=c["muted"])
        text.tag_configure("warn", foreground=c["error"])
        text.tag_configure("good", foreground=c["done"])
        self._links = 0

        def put(s, *tags):
            text.insert("end", s, tags)

        def link(label, url):
            self._links += 1
            tag = f"link{self._links}"
            text.tag_configure(tag, foreground=c.get("accent", "#2a6ad8"), underline=True)
            text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            text.tag_bind(tag, "<Enter>", lambda e: text.configure(cursor="hand2"))
            text.tag_bind(tag, "<Leave>", lambda e: text.configure(cursor=""))
            text.insert("end", label, (tag,))

        # 1. Plugins
        p = result["plugins"]
        put("Plugins\n", "h")
        tag = "warn" if p.total_full > listcheck.PLUGIN_LIMIT - 10 else "good"
        put(f"About {p.total_full} regular plugins (.esp / .esm, counting the 5 from the game) - Skyrim's limit "
            f"is {listcheck.PLUGIN_LIMIT}.\n", tag)
        put(f"{p.light} light plugins (.esl or ESL-flagged) - these don't count towards the limit.\n")
        if p.optional:
            put(f"Up to {p.optional} more come from installer options, depending on what you pick there.\n", "meta")
        if p.unknown_files:
            put(f"{p.unknown_files} file(s) don't show their contents on Nexus, so they're not counted.\n", "meta")
        if p.total_full > listcheck.PLUGIN_LIMIT - 10:
            put("Too close to the limit: look for ESL versions of the mods below, or merge plugins.\n", "warn")
        heavy = sorted(((plan, opt, [x for x in pl if not x.light and not x.optional]) for plan, opt, pl in p.by_mod),
                       key=lambda t: -len(t[2]))
        heavy = [t for t in heavy if t[2]][:15]
        if heavy:
            put("Most regular plugins:\n", "meta")
            for plan, opt, pl in heavy:
                put("  ")
                link(plan.title, plan.entry.page_url)
                put(f"  {len(pl)}: " + ", ".join(x.name for x in pl[:6]) + ("…" if len(pl) > 6 else "") + "\n",
                    "meta")
        put("ESL-flagged .esp files can't be told apart from the file list, so the count goes by the file "
            "names and descriptions (\"ESL\", \"ESPFE\").\n", "meta")

        # 2. Disk space
        put("Disk space\n", "h")
        if not result["space"]:
            put("Set up your mod manager in step 2 to check the drives.\n", "meta")
        for sp in result["space"]:
            free = human_size(sp.free) if sp.free is not None else "?"
            put(f"{sp.folder}: needs about {human_size(sp.need)}, {free} free\n", "good" if sp.enough else "warn")
        put(f"Installed mods take about {listcheck.INSTALL_FACTOR:g}x their download size (a guess: archives "
            "are compressed). Files already in the downloads folder aren't counted.\n", "meta")

        # 3. Already installed
        installed = result.get("installed") or {}
        if installed.get("mods"):
            have = [pl for pl in plans if pl.entry.mod_id in installed["mods"]]
            same = [pl for pl in have if pl.selected and all((pl.entry.mod_id, f) in installed["files"]
                                                            for f in pl.selected)]
            put("Already in MO2\n", "h")
            put(f"{len(have)} of your mods are installed in MO2; for {len(same)} of them the files you picked "
                "are the ones installed. Start downloads offers to skip those.\n")

        # 4. Duplicates
        dups = result["duplicates"]
        put("In the list twice\n", "h")
        if not dups:
            put("None.\n", "good")
        titles = {p.entry.key: p for p in plans}
        for key, lines in dups:
            put("\u2022 ")
            p = titles.get(key)
            game, _, mod_id = key.partition("/")
            link(p.title if p else key, f"https://www.nexusmods.com/{game}/mods/{mod_id}")
            put(f"  lines {', '.join(map(str, lines))} (only got once)\n", "meta")

        # 5. Replaced / abandoned
        put("Replaced, merged or not updated in years\n", "h")
        retired = result["retired"]
        if not retired:
            put("None found.\n", "good")
        for r in sorted(retired, key=lambda r: (not r.why, r.updated)):
            put("⚠ " if r.why else "• ", "warn" if r.why else "meta")
            link(r.plan.title, r.plan.entry.page_url)
            if r.updated:
                put("  last updated " + time.strftime("%b %Y", time.localtime(r.updated)), "meta")
            put("\n")
            if r.why:
                put(f"      “{r.why[:220]}”\n", "meta")
            for u in r.links[:3]:
                put("      → ")
                link(u, u)
                put("\n")

        # 6. Sizes
        sizes = result["sizes"]
        put("Download size\n", "h")
        put(f"As picked now: {human_size(sizes['now'])}\n")
        if result["textured"]:
            put(f"{result['textured']} mods come in several texture sizes. With every one of them at:\n", "meta")
            for size in TEXTURE_SIZES:
                mark = "   ← your setting" if size == texture else ""
                put(f"   {size}: {human_size(sizes[size])}{mark}\n")
        text.configure(state="disabled")
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        if getattr(master, "_theme", None):
            master._theme.paint(self)


class AutoPickDialog(tk.Toplevel):
    """How files are picked without asking you."""

    def __init__(self, master, settings):
        super().__init__(master)
        self.settings = settings
        self.changed = False
        self.title("Auto-pick")
        self.geometry("640x430")
        self.transient(master)
        self.grab_set()
        pad = {"padx": 14, "anchor": "w"}
        ttk.Label(self, text="Pick files by myself when I can", style="Title.TLabel").pack(pady=(12, 0), **pad)
        ttk.Label(self, text="Mods these rules decide aren't asked about in Choose options (you can still "
                             "change them there, or in the list). Mods you picked by hand aren't changed.",
                  style="Muted.TLabel", wraplength=600).pack(**pad)
        self.on = tk.BooleanVar(value=settings.auto_pick)
        self.extras = tk.BooleanVar(value=settings.skip_extras)
        self.real = tk.BooleanVar(value=settings.only_real_choices)
        self.prefer = tk.StringVar(value=settings.prefer_words)
        self.avoid = tk.StringVar(value=settings.avoid_words)
        ttk.Checkbutton(self, text="Use these rules", variable=self.on).pack(pady=(10, 4), **pad)
        ttk.Checkbutton(self, text="Leave extras unticked: translations (Russian, Chinese, PT-BR…), readmes, "
                                   "source files, old / beta / test files", variable=self.extras).pack(**pad)
        ttk.Checkbutton(self, text="Only ask when there's a real choice: one main file plus optional files = "
                                   "take the main file, leave the optional ones off", variable=self.real).pack(**pad)
        ttk.Label(self, text="Words to go for, separated by commas (e.g. ESL, BSA, Desaturated, Performance):"
                  ).pack(pady=(12, 0), **pad)
        ttk.Entry(self, textvariable=self.prefer).pack(fill="x", padx=14)
        ttk.Label(self, text="Words to stay away from (e.g. Loose, Lite, No Snow):").pack(pady=(8, 0), **pad)
        ttk.Entry(self, textvariable=self.avoid).pack(fill="x", padx=14)
        ttk.Label(self, text="When a mod has several different main files, the one whose name has the most of "
                             "your words (and none to avoid) is picked. A tie is asked about.",
                  style="Muted.TLabel", wraplength=600).pack(pady=(4, 0), **pad)
        ttk.Label(self, text="Patches for mods in your list are still ticked, and your texture size still "
                             "applies.", style="Muted.TLabel", wraplength=600).pack(**pad)
        btns = ttk.Frame(self)
        btns.pack(fill="x", side="bottom", padx=14, pady=12)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Save and re-pick", style="Accent.TButton", command=self.save).pack(side="right", padx=6)
        if getattr(master, "_theme", None):
            master._theme.paint(self)

    def save(self) -> None:
        s = self.settings
        new = (self.on.get(), self.extras.get(), self.real.get(), self.prefer.get().strip(), self.avoid.get().strip())
        old = (s.auto_pick, s.skip_extras, s.only_real_choices, s.prefer_words, s.avoid_words)
        if new != old:
            s.auto_pick, s.skip_extras, s.only_real_choices, s.prefer_words, s.avoid_words = new
            self.changed = True
        self.destroy()


class CrashDialog(tk.Toplevel):
    """What a crash log names, matched to the mods they come from."""

    def __init__(self, master, crash, path):
        super().__init__(master)
        self.title("Crash log")
        self.geometry("860x600")
        self.transient(master)
        ttk.Label(self, text=path.name, style="Title.TLabel").pack(anchor="w", padx=12, pady=(12, 0))
        ttk.Label(self, text=f"{crash.kind} log" + (f" \u00b7 {crash.game}" if crash.game else ""),
                  style="Muted.TLabel").pack(anchor="w", padx=12)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=12, pady=8)
        text = tk.Text(body, wrap="word", relief="flat", highlightthickness=1, padx=10, pady=8, font="TkDefaultFont")
        text._details = True
        sb = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        AutoScroll(text)
        theme = getattr(master, "_theme", None)
        c = theme.colors if theme else {"muted": "#555", "error": "#b00020", "done": "#1b7a1b", "accent": "#2a6ad8"}
        text.tag_configure("h", font=("TkDefaultFont", 11, "bold"), spacing1=12, spacing3=4)
        text.tag_configure("meta", foreground=c["muted"])
        text.tag_configure("warn", foreground=c["error"])
        links = [0]

        def link(label, url):
            links[0] += 1
            tag = f"link{links[0]}"
            text.tag_configure(tag, foreground=c.get("accent", "#2a6ad8"), underline=True)
            text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
            text.insert("end", label, (tag,))

        if crash.exception:
            text.insert("end", crash.exception[:200] + "\n", "warn")
        stack = [n for n in crash.named if n.in_stack]
        objects = [n for n in crash.named if not n.in_stack]
        for title, group, why in (
                ("In the code that crashed (call stack)", stack,
                 "The first one here is the most likely cause - especially if it's a mod's DLL."),
                ("Plugins and DLLs of the things involved", objects,
                 "Objects the game was handling when it crashed, and the plugins that add or change them. "
                 "Often a clue, not proof.")):
            text.insert("end", title + "\n", "h")
            text.insert("end", why + "\n", "meta")
            if not group:
                text.insert("end", "None named.\n", "meta")
            for i, n in enumerate(group):
                text.insert("end", ("\u2192 " if i == 0 and group is stack else "\u2022 ") + n.name)
                text.insert("end", f"  ({n.count}x)" if n.count > 1 else "", "meta")
                text.insert("end", "   from ")
                if n.url:
                    link(n.mod, n.url)
                elif n.mod:
                    text.insert("end", n.mod + " (in MO2, not in your list)")
                else:
                    text.insert("end", "a mod not found in your list or MO2", "meta")
                text.insert("end", "\n")
        if not crash.named:
            text.insert("end", "\nNo mod files are named before the lists of loaded modules and plugins. "
                               "The crash may be in the game itself or a driver.\n", "meta")
        text.insert("end", "\nNext: check the mods above (their pages' Posts and Bugs tabs often know "
                           "the crash), update them, or switch them off in MO2 to test.\n", "meta")
        text.configure(state="disabled")
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="Open the log", command=lambda: _open_file(path)).pack(side="right", padx=6)
        if getattr(master, "_theme", None):
            master._theme.paint(self)


def _open_file(path) -> None:
    import os
    import subprocess
    import sys
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass
