"""Logging in to Nexus and the theme."""

from __future__ import annotations

from .common import *  # noqa: F401,F403
from .dialogs import ChoiceDialog, CompatDialog, UpdatesDialog


class AccountMixin:
    def nexus_login(self) -> None:
        """Open Nexus's key page and log in as soon as the key is copied."""
        if self._watching_clipboard:
            self._stop_clipboard_watch("Not logged in")
            return
        webbrowser.open(API_KEY_PAGE)
        self._watching_clipboard = True
        self._clip_seen = set()
        self.nexus_btn.configure(text="Cancel")
        self.account_var.set("In your browser: log in to Nexus if asked, then click Copy next to "
                             "your Personal API Key (or select it and press Ctrl+C)\u2026")
        self.root.after(CLIPBOARD_WAIT_MS, lambda: self._watching_clipboard and
                        self._stop_clipboard_watch("Gave up waiting for the key - try again"))
        self._poll_clipboard()

    def _poll_clipboard(self) -> None:
        if not self._watching_clipboard:
            return
        try:
            text = self.root.clipboard_get().strip()
        except tk.TclError:
            text = ""
        if text and text not in self._clip_seen and _KEY_SHAPE.match(text):
            self._clip_seen.add(text)
            self._try_clipboard_key(text)
        self.root.after(700, self._poll_clipboard)

    def _try_clipboard_key(self, key: str) -> None:
        def work():
            try:
                client = NexusClient(key, disk_cache=nexuscache.shared())
                acct = client.validate()
            except NexusError:
                return  # not a key (or not this one): keep waiting
            self.events.put(("clipboard-login", (key, client, acct)))
        threading.Thread(target=work, daemon=True).start()

    def _clipboard_login_done(self, key, client, acct) -> None:
        if not self._watching_clipboard:
            return
        self._stop_clipboard_watch(f"Logged in as {acct.name} ({acct.kind})")
        self.client = client
        self.key_var.set(key)
        self._save_settings()
        try:  # don't leave the key sitting on the clipboard
            self.root.clipboard_clear()
        except tk.TclError:
            pass
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if not acct.is_premium:
            messagebox.showwarning("SkyrimDownloaded", "This account isn't Premium. Nexus only gives "
                                   "download links to tools for Premium accounts.", parent=self._parent())

    def _stop_clipboard_watch(self, message: str) -> None:
        self._watching_clipboard = False
        self.nexus_btn.configure(text="Log in with Nexus")
        self.account_var.set(message)

    def logout(self) -> None:
        self._watching_clipboard = False
        self.client = None
        self.key_var.set("")
        self.settings.set_api_key("")
        self.nexus_btn.configure(text="Log in with Nexus")
        self.account_var.set("Logged out")
        self._save_settings()

    def _theme_changed(self) -> None:
        self.theme.apply(self.theme_var.get())
        self.settings.theme = self.theme_var.get()
        self._save_settings()

    def login(self, quiet: bool = False) -> None:
        key = self.key_var.get().strip()
        if not key:
            if not quiet:
                messagebox.showinfo("SkyrimDownloaded",
                                    "Paste your personal API key from Nexus Mods first.\n\n"
                                    "It's at the bottom of " + API_KEY_PAGE, parent=self._parent())
            return

        def work():
            try:
                client = NexusClient(key, disk_cache=nexuscache.shared())
                acct = client.validate()
            except NexusError as err:
                self.events.put(("account", f"Login failed: {err}"))
                return
            self.client = client
            self.events.put(("account", f"Logged in as {acct.name} ({acct.kind})"))
            if not acct.is_premium and not quiet:
                self.events.put(("error", "This account isn't Premium. Nexus only gives "
                                          "download links to tools for Premium accounts."))
        self.account_var.set("Checking…")
        threading.Thread(target=work, daemon=True).start()
        self._save_settings()

