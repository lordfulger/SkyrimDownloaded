"""Settings, and saving / restoring the work in progress."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class PersistMixin:
    def _load_settings(self) -> None:
        s = self.settings
        # Fill these in first: logging in below saves settings, which reads them.
        self.version_var.set(gameversion.preset_label(s.game_version))
        self.store_var.set(s.game_store if s.game_store in gameversion.STORES else "Steam")
        self._last_target = self._target_game().describe()
        self.key_var.set(s.get_api_key())
        self.manager_var.set(s.manager if s.manager in ("mo2", "vortex") else "mo2")
        self.mode_var.set(s.mode if s.mode in ("handoff", "direct") else "handoff")
        self.install_var.set(s.install)
        for key, var in self.path_vars.items():
            var.set(getattr(s, key, ""))
        for var in self.path_vars.values():
            var.trace_add("write", lambda *a: self._update_where())
        self._manager_changed()
        if self.list_path and self.list_path.is_file():
            self._read_list(self.list_path)
        if self.key_var.get():
            self.login(quiet=True)
        # Fill in whatever's still blank from a quick look around (registry, usual places).
        self._restore_session()
        self.find_folders(deep=False)
        if not s.game_version:
            self.root.after(300, lambda: self.detect_game(quiet=True))

    def _save_settings(self) -> None:
        s = self.settings
        s.manager = self.manager_var.get()
        s.mode = self.mode_var.get()
        s.install = self.install_var.get()
        for key, var in self.path_vars.items():
            setattr(s, key, var.get().strip())
        s.set_api_key(self.key_var.get())
        s.theme = self.theme_var.get()
        s.game_version = gameversion.version_text(self._target_game().version)
        s.game_store = self.store_var.get()
        s.last_list = str(self.list_path) if self.list_path else ""
        try:
            s.save()
        except OSError:
            pass

    def save_session(self, now: bool = False, wait: bool = False) -> None:
        """Save the work in progress (a moment after each change, and on close)."""
        if self._restoring:
            return
        if self._save_job:
            try:
                self.root.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None
        if not now:
            self._save_job = self.root.after(1200, lambda: self.save_session(now=True))
            return
        reqs = dict(self._req_cache)
        if self.client:
            reqs.update({k: v for k, v in list(self.client._cache.items())
                         if k.startswith("req:") and v is not None})
        try:
            sash = self.panes.sashpos(0)
        except tk.TclError:
            sash = None
        data = session.snapshot(
            list_text=self.list_text.get("1.0", "end-1c"),
            list_path=str(self.list_path or ""), plans=self.plans, report=self.compat,
            requirements=reqs, declined=self.declined,
            ui={"show_other": self.other_var.get(), "show_old": self.old_var.get(),
                "geometry": self.root.geometry(), "sash": sash})
        if wait:
            self._write_session(data)
            return
        # Writing a big session takes a moment: do it off the window's thread, newest wins.
        if getattr(self, "_session_q", None) is None:
            self._session_q = queue.Queue()
            threading.Thread(target=self._session_write_loop, daemon=True, name="session-writer").start()
        self._session_q.put(data)

    def _session_write_loop(self) -> None:
        while True:
            data = self._session_q.get()
            while True:  # skip to the newest copy if several queued up
                try:
                    data = self._session_q.get_nowait()
                except queue.Empty:
                    break
            self._write_session(data)

    def _write_session(self, data) -> None:
        lock = self.__dict__.setdefault("_session_lock", threading.Lock())
        with lock:
            try:
                session.write(self.session_file, data)
            except OSError as err:
                log.warning("Couldn't save the session: %s", err)
                self.events.put(("status", f"Couldn't save your progress: {err}"))

    def save_progress(self) -> None:
        self.save_session(now=True)
        self.status_var.set("Progress saved - it'll all be here next time you open the app.")

    def _list_edited(self, _event=None) -> None:
        if self.list_text.edit_modified():
            self.list_text.edit_modified(False)
            self.save_session()

    def _restore_session(self) -> None:
        restored = session.load(self.session_file)
        if not restored or restored.empty:
            self._restoring = False
            return
        self._restoring = True
        try:
            self.list_text.delete("1.0", "end")
            self.list_text.insert("1.0", restored.list_text)
            self.list_text.edit_modified(False)
            if restored.list_path:
                self.list_path = Path(restored.list_path)
                self.list_label.set(restored.list_path)
            self.plans = restored.plans
            for plan in self.plans:  # work out the version fit again for the current game
                annotate(plan.options, self._target_game())
            self.compat = restored.report
            self._req_cache = {k: v for k, v in restored.requirements.items()}
            self.declined = restored.declined
            ui = restored.ui
            self.other_var.set(bool(ui.get("show_other")))
            self.old_var.set(bool(ui.get("show_old")))
            if ui.get("geometry"):
                try:
                    self.root.geometry(ui["geometry"])
                except tk.TclError:
                    pass
            if ui.get("sash"):
                self.root.after(400, lambda: self.panes.sashpos(0, int(ui["sash"])))
            self._fill_tree()
        finally:
            self._restoring = False
        waiting = sum(1 for p in self.plans if p.needs_choice and not p.error)
        msg = f"Welcome back - restored your work from {restored.when}"
        if self.plans:
            msg += f" ({len(self.plans)} mods" + (f", {waiting} still to choose" if waiting else "") + ")"
        self.status_var.set(msg + ".")

    def start_over(self) -> None:
        if (self.plans or self.list_text.get("1.0", "end-1c").strip()) and not messagebox.askyesno(
                "Start over", "Clear the mod list, the looked-up mods and your choices?\n\n"
                "(A list you saved to a file stays on disk.)", parent=self._parent()):
            return
        self._restoring = True
        try:
            self.plans, self.compat, self.jobs = [], None, []
            self._req_cache, self.declined = {}, set()
            self.list_text.delete("1.0", "end")
            self.list_path = None
            self.list_label.set("(type or paste links below)")
            self._fill_tree()
            self.info.configure(state="normal")
            self.info.delete("1.0", "end")
            self.info.configure(state="disabled")
        finally:
            self._restoring = False
        session.clear(self.session_file)
        self.status_var.set("Started over.")

