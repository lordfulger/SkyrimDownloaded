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
        self._remember_account(key, acct)
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
        self.settings.account = {}
        self.settings.rate = {}
        self.nexus_btn.configure(text="Log in with Nexus")
        self.account_var.set("Logged out")
        self._save_settings()

    def _login_ok(self, key, acct) -> None:
        self._remember_account(key, acct)
        self.account_var.set(f"Logged in as {acct.name} ({acct.kind})")
        self._save_settings()  # keep the login now, not only when the app closes
        log.info("Logged in as %s", acct.name)

    def _login_retry(self, why: str) -> None:
        self.account_var.set("Couldn't reach Nexus to log in - trying again in a minute "
                             "(your key is kept)")
        if not getattr(self, "_login_retry_job", None):
            def again():
                self._login_retry_job = None
                if self.client is None and self.key_var.get().strip():
                    self.login(quiet=True)
            self._login_retry_job = self.root.after(60_000, again)

    def _theme_changed(self) -> None:
        self.theme.apply(self.theme_var.get())
        self.settings.theme = self.theme_var.get()
        self._save_settings()

    def _remember_account(self, key: str, acct) -> None:
        from dataclasses import asdict
        self.settings.account = dict(asdict(acct), key=self.settings.key_fingerprint(key))

    def _login_from_saved(self, key: str) -> bool:
        """Log in from the last login, without asking Nexus (no request used).
        The key is still checked by Nexus with the first real request."""
        from ..nexus import Account
        saved = dict(self.settings.account or {})
        if not saved or saved.pop("key", None) != self.settings.key_fingerprint(key):
            return False
        try:
            acct = Account(**saved)
        except TypeError:
            return False
        client = NexusClient(key, disk_cache=nexuscache.shared())
        client._account = acct
        rate = self.settings.rate or {}
        if rate and time.strftime("%Y-%m-%d", time.gmtime(rate.get("time", 0))) == time.strftime("%Y-%m-%d", time.gmtime()):
            client.rate.daily_remaining = rate.get("daily")
            client.rate.hourly_remaining = rate.get("hourly")
        self.client = client
        self.account_var.set(f"Logged in as {acct.name} ({acct.kind})")
        return True

    def login(self, quiet: bool = False) -> None:
        key = self.key_var.get().strip()
        if not key:
            if not quiet:
                messagebox.showinfo("SkyrimDownloaded",
                                    "Paste your personal API key from Nexus Mods first.\n\n"
                                    "It's at the bottom of " + API_KEY_PAGE, parent=self._parent())
            return
        if quiet and self._login_from_saved(key):
            return  # no request to Nexus just for opening the app

        def work():
            try:
                client = NexusClient(key, disk_cache=nexuscache.shared())
                acct = client.validate()
            except AuthError as err:
                log.warning("Login refused: %s", err)
                self.events.put(("account", f"Login failed: {err}"))
                return
            except NexusError as err:
                # Nexus didn't answer (no internet, Nexus down, too many requests): the key may
                # be fine, so keep it and try again in a minute.
                log.warning("Couldn't reach Nexus to log in: %s", err)
                self.events.put(("login-retry", str(err)))
                return
            self.client = client
            self.events.put(("login-ok", (key, acct)))
            if not acct.is_premium and not quiet:
                self.events.put(("error", "This account isn't Premium. Nexus only gives "
                                          "download links to tools for Premium accounts."))
        self.account_var.set("Checking…")
        threading.Thread(target=work, daemon=True).start()
        self._save_settings()

