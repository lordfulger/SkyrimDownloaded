"""The pop-up windows: choose options, updates, compatibility."""

from __future__ import annotations

from .common import *  # noqa: F401,F403


class ChoiceDialog(tk.Toplevel):
    """One mod at a time: tick the files you want. Back / Skip for now / Leave out / Next.

    Mods skipped for now come back at the end, after all the others.
    """

    def __init__(self, master, plans: list[ModPlan], include_old: bool, include_other: bool = False, *,
                 suggestions: dict | None = None, warnings: dict | None = None,
                 title: str = "Choose options", start: int = 0):
        super().__init__(master)
        self.plans = list(plans)
        self.include_old = include_old
        self.include_other = include_other
        self.suggestions = suggestions or {}
        self.warnings = warnings or {}
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
        self.warn = tk.StringVar()
        self.warn_label = ttk.Label(self, textvariable=self.warn, wraplength=760, style="Warn.TLabel")
        self.warn_label.pack(anchor="w", padx=12)

        body = ttk.Frame(self)
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

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="\u25C0 Back", command=lambda: self.go(-1)).pack(side="left")
        ttk.Button(btns, text="Open mod page", command=self.open_page).pack(side="left", padx=6)
        self.count = tk.StringVar()
        ttk.Label(btns, textvariable=self.count).pack(side="left", padx=8)
        ttk.Button(btns, text="Done", command=self.finish).pack(side="right")
        ttk.Button(btns, text="Next \u25B6", style="Accent.TButton", command=lambda: self.go(1)).pack(side="right", padx=6)
        ttk.Button(btns, text="Leave this mod out", command=self.leave_out).pack(side="right")
        ttk.Button(btns, text="Skip for now", command=self.skip_for_now).pack(side="right", padx=6)
        self.bind("<Next>", lambda e: self.canvas.yview_scroll(1, "pages"))
        self.bind("<Prior>", lambda e: self.canvas.yview_scroll(-1, "pages"))
        self.protocol("WM_DELETE_WINDOW", self.finish)
        self.show()

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
        warns = self.warnings.get(id(plan), [])
        self.warn.set("\u26a0 " + "; ".join(warns) if warns else "")
        skipped = f"   \u2022   {len(self.later)} skipped for later" if self.later else ""
        self.count.set(f"Mod {self.index + 1} of {len(self.plans)}{skipped}")
        self.vars = []
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
        for opt in options:
            if opt.category_label != last_cat:
                last_cat = opt.category_label
                ttk.Label(self.inner, text=f"{last_cat} files", font=("TkDefaultFont", 10, "bold")).pack(
                    anchor="w", pady=(10, 2))
            var = tk.BooleanVar(value=opt.file_id in plan.selected)
            text = f"{opt.name}   v{opt.version}   ({opt.size_text})" if opt.version else f"{opt.name}   ({opt.size_text})"
            if opt.fit.note and opt.fit.status != "unknown":
                text += f"   \u2014 {opt.fit.note}"
            ttk.Checkbutton(self.inner, text=text, variable=var).pack(anchor="w")
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

    def _ticked(self) -> list[int]:
        return [fid for var, fid in self.vars if var.get()]

    def commit(self) -> None:
        plan = self.plan
        plan.selected = self._ticked()
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

