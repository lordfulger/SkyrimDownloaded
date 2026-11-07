import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skyrimdl import finder
from skyrimdl.managers.vortex import default_downloads


def touch(path: Path, text: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


SKYRIM_INI = "[General]\ngameName=Skyrim Special Edition\n[Settings]\ndownload_directory=%BASE_DIR%/downloads\n"


class FinderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.drive = self.tmp / "D"
        self.local = self.tmp / "LocalAppData"
        self.roaming = self.tmp / "AppData"
        env = {"LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming),
               "ProgramFiles": str(self.tmp / "PF"), "ProgramW6432": str(self.tmp / "PF")}
        for patcher in (mock.patch.dict(os.environ, env),
                        # don't walk the real drives or read the real registry
                        mock.patch.object(finder, "fixed_drives", lambda: []),
                        mock.patch.object(finder, "_registry_values", lambda: []),
                        mock.patch.object(finder.Path, "home", lambda: self.tmp / "home")):
            patcher.start()
            self.addCleanup(patcher.stop)

        # A Wabbajack-style portable MO2 for Skyrim AE.
        self.portable = self.drive / "Wabbajack" / "Nolvus"
        touch(self.portable / "ModOrganizer.exe")
        touch(self.portable / "ModOrganizer.ini", SKYRIM_INI)
        # A normal MO2 install (no ini beside it) used by global instances.
        self.mo2_exe = touch(self.drive / "Tools" / "MO2" / "ModOrganizer.exe")
        touch(self.local / "ModOrganizer" / "Skyrim AE" / "ModOrganizer.ini", SKYRIM_INI)
        touch(self.local / "ModOrganizer" / "Fallout 4" / "ModOrganizer.ini",
              "[General]\ngameName=Fallout 4\n")
        # Inside a mods folder: must not be searched.
        touch(self.portable / "mods" / "SomeMod" / "ModOrganizer.exe")
        # Vortex's tagged downloads folder.
        self.vortex_dl = self.drive / "VortexDownloads"
        touch(self.vortex_dl / finder.VORTEX_DOWNLOADS_TAG, "{}")

    def test_deep_search(self):
        found = finder.find(deep=True, extra_roots=[self.drive], budget=10)
        by_dir = {m.instance_dir: m for m in found.mo2}
        self.assertEqual(set(by_dir), {self.portable,
                                       self.local / "ModOrganizer" / "Skyrim AE",
                                       self.local / "ModOrganizer" / "Fallout 4"})
        self.assertTrue(by_dir[self.portable].portable)
        self.assertEqual(by_dir[self.portable].exe, self.portable / "ModOrganizer.exe")
        self.assertEqual(by_dir[self.portable].downloads, self.portable / "downloads")
        # Global instances borrow the stand-alone MO2 install's exe.
        self.assertEqual(by_dir[self.local / "ModOrganizer" / "Skyrim AE"].exe, self.mo2_exe)
        self.assertNotIn(self.portable / "mods" / "SomeMod" / "ModOrganizer.exe", found.mo2_exes)
        # Two Skyrim setups: the user has to pick; Skyrim ones are listed first.
        self.assertIsNone(found.best_mo2())
        self.assertFalse(found.sorted_mo2()[-1].is_skyrim_se)
        self.assertEqual(found.vortex.downloads_root, self.vortex_dl)
        self.assertEqual(found.vortex.game_downloads("skyrimspecialedition"), self.vortex_dl / "skyrimse")

    def test_quick_search_finds_global_instances_only(self):
        found = finder.find(deep=False)
        self.assertEqual({m.name for m in found.mo2}, {"Skyrim AE", "Fallout 4"})
        self.assertEqual(found.best_mo2().name, "Skyrim AE")

    def test_vortex_settings_database(self):
        moved = self.drive / "Moved Downloads"
        moved.mkdir(parents=True)
        db = self.roaming / "Vortex" / "state.v2"
        db.mkdir(parents=True)
        old = b'\x01\x00settings###downloads###path\x10"C:\\\\Old"'
        new = (b'\x01\x00settings###downloads###path\x22'
               + ('"' + str(moved).replace("\\", "\\\\") + '"').encode())
        (db / "000005.log").write_bytes(b"junk" + old + b"more" + new + b"end")
        self.assertEqual(finder.vortex_saved_downloads_root(), moved)
        self.assertEqual(default_downloads("skyrimspecialedition"), moved / "skyrimse")
        found = finder.find(deep=False)
        self.assertEqual(found.vortex.downloads_root, moved)

    def test_time_budget(self):
        hits, timed_out = finder.walk_for_targets([self.drive], budget=0)
        self.assertTrue(timed_out)

    def test_exe_from_command(self):
        self.assertEqual(finder._exe_from_command('"C:\\MO2\\nxmhandler.exe" "%1"'),
                         Path("C:\\MO2\\nxmhandler.exe"))
        self.assertEqual(finder._exe_from_command("C:\\Program Files\\Vortex\\Vortex.exe,0"),
                         Path("C:\\Program Files\\Vortex\\Vortex.exe"))


if __name__ == "__main__":
    unittest.main()
