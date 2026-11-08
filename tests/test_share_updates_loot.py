import tempfile
import unittest
from pathlib import Path

from skyrimdl import loot, sharing, updates
from skyrimdl.engine import resolve
from skyrimdl.gameversion import GameTarget
from skyrimdl.links import parse_list
from skyrimdl.managers.base import ManagerError
from skyrimdl.nexus import NexusClient

from tests.fake_nexus import GOOD_KEY, FakeNexus

AE = GameTarget.from_settings("1.6.1170", "Steam")
SE = GameTarget.from_settings("1.5.97", "Steam")


class ShareTests(unittest.TestCase):
    def test_export_and_reimport_gives_the_same_files(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            plans = resolve(client, parse_list("12604  # the menu\n1000\n17230\n266\n999\n")[0], target=AE)
            plans[1].selected = [202, 203]          # Pretty Textures: 2K + patch
            plans[3].entry.rule.mode = "skip"       # USSEP left out
            text = sharing.export_text(plans, AE, title="My AE list")
            self.assertIn("#! game-version: 1.6.1170", text)
            self.assertIn("mods/1000 | file=202,203   # Pretty Textures: Pretty Textures 2K, USSEP Patch/ for real",
                          text.replace(", for real", "/ for real"))
            self.assertIn("mods/266 | skip", text)
            self.assertIn("# https://www.nexusmods.com/skyrimspecialedition/mods/999", text)
            # Someone else opens it: same files, no questions asked.
            entries, problems = parse_list(text)
            self.assertEqual(problems, [])
            again = resolve(client, entries, target=AE)
            by_title = {p.title: p for p in again}
            self.assertEqual(by_title["Pretty Textures"].selected, [202, 203])
            self.assertFalse(by_title["Pretty Textures"].needs_choice)
            self.assertEqual(by_title["SSE Engine Fixes"].selected, [402])
            ussep = next(p for p in again if p.entry.mod_id == 266)
            self.assertTrue(ussep.skipped)
            self.assertIn("left out", ussep.title)
            self.assertNotIn("Gone Mod", by_title)
            # On a different game version the pinned AE file is flagged.
            on_se = {p.title: p for p in resolve(client, entries, target=SE)}
            self.assertTrue(on_se["SSE Engine Fixes"].needs_choice)
            self.assertIn("another game version", on_se["SSE Engine Fixes"].reason)

    def test_version_warning(self):
        meta = sharing.list_meta("# x\n#! game-version: 1.6.1170\n#! store: Steam\nhttps://...\n")
        self.assertEqual(meta, {"game-version": "1.6.1170", "store": "Steam"})
        self.assertIsNone(sharing.version_warning(meta, AE))
        self.assertIsNone(sharing.version_warning(meta, GameTarget.from_settings("1.6.1179", "Steam")))
        self.assertIn("1.6.1170", sharing.version_warning(meta, SE))
        self.assertIn("GOG", sharing.version_warning(meta, GameTarget.from_settings("1.6.1179", "GOG")))
        self.assertIsNotNone(sharing.version_warning(meta, GameTarget()))
        self.assertIsNone(sharing.version_warning({}, AE))


class UpdateTests(unittest.TestCase):
    def test_newer_file_and_removed_file(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            plans = resolve(client, parse_list("1000 | file=202,203\n12604\n")[0], target=AE)
            found, errors = updates.check_updates(client, plans, AE)
            self.assertEqual((found, errors), ([], []))
            fake.state["new_upload"] = True
            found, errors = updates.check_updates(client, plans, AE)
            self.assertEqual(errors, [])
            by_old = {u.old.file_id: u for u in found}
            self.assertEqual(by_old[202].new.file_id, 205)
            self.assertEqual(by_old[202].note, "newer file uploaded")
            self.assertIn("removed from Nexus", by_old[203].note)
            self.assertIsNone(by_old[203].new)   # no other optional file to offer instead
            self.assertIn("v2.0 \u2192 Pretty Textures 2K v2.1", by_old[202].label)
            # The mod's file list now shows what's on Nexus.
            self.assertIn(205, [o.file_id for o in plans[0].options])
            n = updates.apply([by_old[202]])
            self.assertEqual(n, 1)
            self.assertEqual(plans[0].selected, [205, 203])

    def test_follows_a_chain_of_updates(self):
        chain = [{"old_file_id": 1, "new_file_id": 2}, {"old_file_id": 2, "new_file_id": 3},
                 {"old_file_id": 3, "new_file_id": 1}]  # a loop must not hang
        self.assertEqual(updates._latest(1, chain[:2]), 3)
        self.assertIn(updates._latest(1, chain), (1, 2, 3))


class LootTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.inst = self.tmp / "Nolvus"
        self.inst.mkdir()
        self.exe = self.inst / "ModOrganizer.exe"
        self.exe.write_text("")

    def ini(self, executables: str) -> None:
        (self.inst / "ModOrganizer.ini").write_text(
            "[General]\ngameName=Skyrim Special Edition\n[customExecutables]\nsize=2\n" + executables,
            encoding="utf-8")

    def test_configured_loot_runs_by_name_through_mo2(self):
        self.ini("1\\title=SKSE\n1\\binary=D:/Skyrim/skse64_loader.exe\n"
                 "2\\title=LOOT\n2\\binary=D:/Tools/LOOT/LOOT.exe\n")
        self.assertEqual(loot.mo2_executables(self.inst),
                         [("SKSE", "D:/Skyrim/skse64_loader.exe"), ("LOOT", "D:/Tools/LOOT/LOOT.exe")])
        cmd = loot.command("mo2", "skyrimspecialedition", mo2_exe=self.exe, instance_dir=self.inst)
        self.assertEqual(cmd, [str(self.exe), "run", "-e", "LOOT"])
        cmd = loot.command("mo2", "skyrimspecialedition", mo2_exe=self.exe, instance_dir=self.inst,
                           instance_name="Skyrim AE", portable=False)
        self.assertEqual(cmd[:3], [str(self.exe), "-i", "Skyrim AE"])

    def test_unconfigured_loot_runs_by_path_through_mo2(self):
        self.ini("1\\title=SKSE\n1\\binary=D:/Skyrim/skse64_loader.exe\n")
        tools = self.inst / "tools" / "LOOT"
        tools.mkdir(parents=True)
        (tools / "LOOT.exe").write_text("")
        cmd = loot.command("mo2", "skyrimspecialedition", mo2_exe=self.exe, instance_dir=self.inst)
        self.assertEqual(cmd, [str(self.exe), "run", str(tools / "LOOT.exe")])

    def test_needs_mo2_exe(self):
        with self.assertRaises(ManagerError):
            loot.command("mo2", "skyrimspecialedition", mo2_exe=None, instance_dir=self.inst)


if __name__ == "__main__":
    unittest.main()
