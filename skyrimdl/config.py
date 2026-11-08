"""Settings and your API key, kept between runs.

On Windows the API key is encrypted with your Windows login (DPAPI), so another
user on the PC, or someone who copies the settings file, can't read it.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


def config_dir() -> Path:
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "SkyrimDownloaded"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "skyrimdownloaded"


CONFIG_FILE = "settings.json"


@dataclass
class Settings:
    manager: str = "mo2"            # "mo2" or "vortex"
    mode: str = "handoff"           # "handoff" (manager downloads) or "direct" (this tool downloads)
    install: bool = True            # Vortex: install after download
    game: str = "skyrimspecialedition"
    parallel: int = 3               # downloads at once in direct mode
    mo2_instance: str = ""
    mo2_exe: str = ""
    mo2_downloads: str = ""
    vortex_downloads: str = ""
    vortex_exe: str = ""
    last_list: str = ""
    theme: str = "System"           # "System", "Light" or "Dark"
    game_version: str = ""          # e.g. "1.6.1170"; blank = don't filter by version
    game_store: str = "Steam"       # "Steam", "GOG" or "Game Pass"
    check_app_updates: bool = True  # look for a newer SkyrimDownloaded once a day
    # The last login, so opening the app doesn't need to ask Nexus again (saves a request).
    account: dict = field(default_factory=dict)
    # Requests left at the last answer from Nexus: {"daily", "hourly", "time"}.
    rate: dict = field(default_factory=dict)
    last_update_check: float = 0.0
    api_key_protected: str = field(default="", repr=False)

    # -- the API key -------------------------------------------------------

    def key_fingerprint(self, key: str | None = None) -> str:
        import hashlib
        key = self.get_api_key() if key is None else key
        return hashlib.sha256(key.strip().encode()).hexdigest()[:16] if key.strip() else ""

    def get_api_key(self) -> str:
        env = os.environ.get("NEXUS_API_KEY")
        if env:
            return env.strip()
        if not self.api_key_protected:
            return ""
        try:
            return _unprotect(self.api_key_protected)
        except Exception:
            return ""

    def set_api_key(self, key: str) -> None:
        self.api_key_protected = _protect(key.strip()) if key.strip() else ""

    def game_target(self):
        from .gameversion import GameTarget
        return GameTarget.from_settings(self.game_version, self.game_store)

    def target_paths(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in
                ("mo2_instance", "mo2_exe", "mo2_downloads", "vortex_downloads", "vortex_exe")}

    # -- load / save -------------------------------------------------------

    @classmethod
    def load(cls, folder: Path | None = None) -> "Settings":
        path = (folder or config_dir()) / CONFIG_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, folder: Path | None = None) -> Path:
        folder = folder or config_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CONFIG_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        return path


# -- protecting the key ------------------------------------------------------

def _protect(text: str) -> str:
    raw = text.encode("utf-8")
    if sys.platform == "win32":
        return "dpapi:" + base64.b64encode(_dpapi(raw, encrypt=True)).decode("ascii")
    return "plain:" + base64.b64encode(raw).decode("ascii")


def _unprotect(stored: str) -> str:
    kind, _, payload = stored.partition(":")
    raw = base64.b64decode(payload)
    if kind == "dpapi":
        return _dpapi(raw, encrypt=False).decode("utf-8")
    return raw.decode("utf-8")


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out))  # UI_FORBIDDEN
    if not ok:
        raise OSError("Windows couldn't " + ("encrypt" if encrypt else "decrypt") + " the API key")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


# -- remembered choices --------------------------------------------------------

def choices_path(list_path: Path) -> Path:
    return list_path.with_name(list_path.name + ".choices.json")


def load_choices(path: Path | None) -> dict[str, list[int]]:
    if not path:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    mods = data.get("mods", {}) if isinstance(data, dict) else {}
    out = {}
    for key, value in mods.items():
        ids = value.get("files") if isinstance(value, dict) else value
        if isinstance(ids, list):
            out[key] = [int(i) for i in ids if str(i).isdigit()]
    return out


def save_choices(path: Path, plans) -> None:
    """Remember what was picked for each mod (merged with what was saved before)."""
    try:
        old = json.loads(path.read_text(encoding="utf-8")).get("mods", {})
    except (OSError, ValueError, AttributeError):
        old = {}
    mods = dict(old) if isinstance(old, dict) else {}
    for plan in plans:
        if plan.error or plan.skipped or not plan.selected:
            continue
        mods[plan.entry.key] = {
            "mod": plan.title,
            "files": list(plan.selected),
            "names": [o.name for o in plan.selected_options()],
        }
    path.write_text(json.dumps({"version": 1, "mods": mods}, indent=2), encoding="utf-8")
