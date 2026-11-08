"""The Mod Organizer 2 add-on that installs what SkyrimDownloaded downloaded.

MO2 can't be told from outside to install a download, but an MO2 add-on
(a Python plugin) can. SkyrimDownloaded writes an install plan
(``SkyrimDownloaded-install.json``) into the instance's downloads folder; the
add-on - "SkyrimDownloaded: install downloaded mods" under MO2's Tools menu -
installs those downloads in list order (installer / FOMOD windows still
appear as usual), skips mods already installed, then puts the mods in the
list's order in the left pane and switches them on.

The add-on's source is kept here as text so the .exe can copy it into MO2's
``plugins`` folder.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

PLAN_FILE = "SkyrimDownloaded-install.json"
PLUGIN_FILE = "SkyrimDownloaded.py"


def write_plan(downloads: Path, jobs) -> Path:
    """Write the install plan for these download jobs (list order)."""
    from .downloader import safe_file_name
    per_mod: dict[int, int] = {}
    for job in jobs:
        per_mod[id(job.plan)] = per_mod.get(id(job.plan), 0) + 1
    mods = []
    for job in jobs:
        # A mod with several files (e.g. main file + patch) becomes one MO2 mod per file,
        # so installing the second doesn't ask to merge/replace the first.
        name = job.plan.title if per_mod[id(job.plan)] == 1 else f"{job.plan.title} - {job.option.name}"
        mods.append({
            "name": name,
            "mod_id": job.plan.entry.mod_id,
            "file_id": job.option.file_id,
            "file": job.option.name,
            "archive": safe_file_name(job.option.file_name),
        })
    path = downloads / PLAN_FILE
    downloads.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": 1, "mods": mods}, indent=1), encoding="utf-8")
    return path


def plugins_folder(mo2_exe: Path) -> Path:
    return Path(mo2_exe).parent / "plugins"


def install_addon(mo2_exe: Path) -> Path:
    """Copy the add-on into MO2's plugins folder. Returns where it went."""
    folder = plugins_folder(mo2_exe)
    if not folder.is_dir():
        raise FileNotFoundError(f"MO2's plugins folder wasn't found next to {mo2_exe}")
    target = folder / PLUGIN_FILE
    target.write_text(PLUGIN_SOURCE, encoding="utf-8")
    return target


def addon_installed(mo2_exe: Path) -> bool:
    try:
        return (plugins_folder(mo2_exe) / PLUGIN_FILE).read_text(encoding="utf-8") == PLUGIN_SOURCE
    except OSError:
        return False


PLUGIN_SOURCE = r'''"""SkyrimDownloaded installer for Mod Organizer 2.

Tools menu > "SkyrimDownloaded: install downloaded mods" installs the mods
SkyrimDownloaded downloaded for this instance, in the order of your list,
then puts them in that order in the left pane and switches them on.
Installer (FOMOD) windows appear as usual. Mods already installed are skipped.
Made by SkyrimDownloaded - https://github.com/lordfulger/SkyrimDownloaded
"""

import configparser
import json
import os

import mobase

try:
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMessageBox
except ImportError:  # MO2 before 2.5
    try:
        from PyQt5.QtGui import QIcon
        from PyQt5.QtWidgets import QApplication, QMessageBox
    except ImportError:  # outside MO2 (tests)
        QIcon = QApplication = QMessageBox = None

PLAN_FILE = "SkyrimDownloaded-install.json"
TITLE = "SkyrimDownloaded"


def read_plan(downloads):
    with open(os.path.join(downloads, PLAN_FILE), encoding="utf-8") as fh:
        return json.load(fh).get("mods") or []


def meta_index(downloads):
    """{(mod_id, file_id): archive name} from the .meta files MO2 keeps beside downloads."""
    index = {}
    for name in os.listdir(downloads):
        if not name.lower().endswith(".meta"):
            continue
        parser = configparser.RawConfigParser(strict=False)
        try:
            with open(os.path.join(downloads, name), encoding="utf-8", errors="replace") as fh:
                parser.read_file(fh)
            mod_id = int(parser.get("General", "modID"))
            file_id = int(parser.get("General", "fileID"))
        except Exception:
            continue
        archive = name[:-5]
        if os.path.isfile(os.path.join(downloads, archive)):
            index[(mod_id, file_id)] = archive
    return index


def installed_archives(organizer):
    """Download names already installed as mods."""
    done = set()
    mod_list = organizer.modList()
    for name in mod_list.allMods():
        get = getattr(mod_list, "getMod", None)
        mod = get(name) if get else organizer.getMod(name)
        try:
            source = mod.installationFile() if mod else ""
        except Exception:
            source = ""
        if source:
            done.add(os.path.basename(source).lower())
    return done


def make_steps(organizer, downloads, plan):
    """What to do: [(entry, archive or None, already_installed)] in list order."""
    index = meta_index(downloads)
    installed = installed_archives(organizer)
    steps = []
    for entry in plan:
        archive = index.get((int(entry.get("mod_id") or 0), int(entry.get("file_id") or 0)))
        if archive is None and os.path.isfile(os.path.join(downloads, entry.get("archive") or "")):
            archive = entry["archive"]
        steps.append((entry, archive, bool(archive) and archive.lower() in installed))
    return steps


def run(organizer, downloads, steps, ask_continue=lambda message: True, set_order=True):
    """Install the steps, then order and enable the mods. Returns a summary dict."""
    installed, skipped, missing, failed, names = [], [], [], [], []
    mod_list = organizer.modList()
    by_archive = {}
    for name in mod_list.allMods():
        get = getattr(mod_list, "getMod", None)
        mod = get(name) if get else organizer.getMod(name)
        try:
            if mod and mod.installationFile():
                by_archive[os.path.basename(mod.installationFile()).lower()] = name
        except Exception:
            pass
    for entry, archive, already in steps:
        if not archive:
            missing.append(entry.get("file") or entry.get("name"))
            continue
        if already:
            skipped.append(archive)
            names.append(by_archive.get(archive.lower()))
            continue
        mod = organizer.installMod(os.path.join(downloads, archive), entry.get("name") or "")
        if mod is None:
            failed.append(archive)
            if not ask_continue(f"{entry.get('name')} wasn't installed (cancelled or failed). Carry on with the rest?"):
                break
            continue
        installed.append(archive)
        names.append(mod.name())
    names = [n for n in dict.fromkeys(names) if n]
    if set_order and names:
        top = len(mod_list.allMods()) - 1
        for name in names:  # each to the bottom of the left pane, so they end up in list order
            mod_list.setPriority(name, top)
    for name in names:
        try:
            mod_list.setActive(name, True)
        except Exception:
            pass
    try:
        organizer.refresh()
    except Exception:
        pass
    return {"installed": installed, "skipped": skipped, "missing": missing, "failed": failed, "ordered": names}


def _version():
    try:
        return mobase.VersionInfo(1, 0, 0, mobase.ReleaseType.FINAL)
    except Exception:
        return mobase.VersionInfo("1.0.0")


class SkyrimDownloadedInstaller(mobase.IPluginTool):
    def __init__(self):
        super().__init__()
        self._organizer = None
        self._parent = None

    def init(self, organizer):
        self._organizer = organizer
        return True

    def name(self):
        return "SkyrimDownloaded Installer"

    def author(self):
        return "SkyrimDownloaded"

    def description(self):
        return "Installs the mods SkyrimDownloaded downloaded, in your list's order, then orders and enables them."

    def version(self):
        return _version()

    def isActive(self):  # MO2 before 2.4
        return True

    def settings(self):
        return []

    def displayName(self):
        return "SkyrimDownloaded: install downloaded mods"

    def tooltip(self):
        return self.description()

    def icon(self):
        return QIcon() if QIcon else None

    def setParentWidget(self, widget):
        self._parent = widget

    def _ask(self, text):
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No \
            if hasattr(QMessageBox, "StandardButton") else QMessageBox.Yes | QMessageBox.No
        answer = QMessageBox.question(self._parent, TITLE, text, buttons)
        yes = QMessageBox.StandardButton.Yes if hasattr(QMessageBox, "StandardButton") else QMessageBox.Yes
        return answer == yes

    def display(self):
        downloads = self._organizer.downloadsPath()
        try:
            plan = read_plan(downloads)
        except Exception:
            QMessageBox.information(self._parent, TITLE, "Nothing to install yet: download your list with "
                                    "SkyrimDownloaded first (it leaves an install plan in the downloads folder).")
            return
        steps = make_steps(self._organizer, downloads, plan)
        todo = [s for s in steps if s[1] and not s[2]]
        missing = [s for s in steps if not s[1]]
        text = f"{len(todo)} mod(s) to install in your list's order"
        if len(steps) - len(todo) - len(missing):
            text += f", {len(steps) - len(todo) - len(missing)} already installed"
        if missing:
            text += f", {len(missing)} not downloaded yet"
        text += (".\n\nInstaller windows appear as usual. Afterwards the mods are put in your list's order "
                 "at the bottom of the left pane and switched on.\n\nStart?")
        if not todo and not steps:
            return
        if not self._ask(text):
            return
        result = run(self._organizer, downloads, steps, ask_continue=self._ask)
        lines = [f"Installed: {len(result['installed'])}", f"Already installed: {len(result['skipped'])}"]
        if result["failed"]:
            lines.append(f"Not installed: {', '.join(result['failed'][:10])}")
        if result["missing"]:
            lines.append(f"Not downloaded yet: {', '.join(str(m) for m in result['missing'][:10])}")
        lines.append("\nRun LOOT next to sort the plugins.")
        QMessageBox.information(self._parent, TITLE, "\n".join(lines))


def createPlugin():
    return SkyrimDownloadedInstaller()
'''
