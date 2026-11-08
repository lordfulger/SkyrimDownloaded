import tempfile
import unittest
from pathlib import Path

from skyrimdl.gameversion import (GameTarget, family, find_games, fit, mo2_game_path,
                                  parse_version, read_hints, store_of)
from skyrimdl.links import parse_line
from skyrimdl.nexus import NexusClient
from skyrimdl.engine import resolve, rechoose
from skyrimdl.selection import FileOption, choose, visible_options

from tests.fake_nexus import FILES, GOOD_KEY, FakeNexus

SE = GameTarget.from_settings("1.5.97", "Steam")
AE640 = GameTarget.from_settings("1.6.640", "Steam")
AE = GameTarget.from_settings("1.6.1170", "Steam")
GOG = GameTarget.from_settings("1.6.1179", "GOG")


def status(name, target, description=""):
    return fit(name, "", description, target).status


class HintTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(family((1, 5, 97)), "SE")
        self.assertEqual(family((1, 6, 353)), "AE-early")
        self.assertEqual(family((1, 6, 640)), "AE-640")
        self.assertEqual(family((1, 6, 659)), "AE-640")
        self.assertEqual(family((1, 6, 1130)), "AE-1130")
        self.assertEqual(family((1, 6, 1179)), "AE-1130")
        self.assertEqual(family((1, 4, 15)), "VR")
        self.assertEqual(parse_version("AE 1.6.1170 latest"), (1, 6, 1170))

    def test_exact_versions_by_family(self):
        self.assertEqual(status("Engine Fixes for 1.5.97", SE), "ok")
        self.assertEqual(status("Engine Fixes for 1.5.97", AE), "other")
        self.assertEqual(status("SKSE plugin 1.6.1130", AE), "ok")   # 1130 build works on 1170
        self.assertEqual(status("SKSE plugin 1.6.1130", AE640), "other")
        self.assertEqual(status("for AE 1170", AE), "ok")

    def test_ranges_and_words(self):
        self.assertEqual(status("Main - 1.6.1130+", AE), "ok")
        self.assertEqual(status("Main - 1.6.1130+", AE640), "other")
        self.assertEqual(status("Main - 1.6.640 and older", SE), "ok")
        self.assertEqual(status("Main - 1.6.640 and older", AE), "other")
        self.assertEqual(status("1.6.317 - 1.6.353", AE640), "other")
        self.assertEqual(status("Pre-AE version", SE), "ok")
        self.assertEqual(status("Pre-AE version", AE), "other")
        self.assertEqual(status("AE version", AE640), "ok")
        self.assertEqual(status("AE version", SE), "other")
        self.assertEqual(status("SE/AE", SE), "ok")
        self.assertEqual(status("SE AE version", AE), "ok")

    def test_vr_and_stores(self):
        self.assertEqual(status("Tweaks VR", AE), "other")
        self.assertEqual(status("Tweaks VR", GameTarget.from_settings("1.4.15", "Steam")), "ok")
        self.assertEqual(status("Main (GOG)", AE), "other")
        self.assertEqual(status("Main (GOG)", GOG), "ok")
        self.assertEqual(status("Main 1.6.1170 Steam", GOG), "other")
        self.assertEqual(status("Main for Game Pass", AE), "other")

    def test_no_false_alarms(self):
        for name in ("SkyUI_5_2_SE", "Main", "Textures 2K", "USSEP 4.3.2", "Update v1.6.2", "VRAM saver"):
            self.assertEqual(status(name, AE), "unknown", name)
        # Descriptions only hint; they never hide a file.
        self.assertEqual(status("Main", SE, "Works on 1.6.1170"), "unknown")
        self.assertEqual(status("Main", SE, "For 1.5.97 users"), "ok")
        self.assertEqual(status("Engine Fixes for 1.5.97", GameTarget()), "unknown")
        self.assertTrue(read_hints("Engine Fixes VR").vr)

    def test_newer_than_yours_is_hidden(self):
        t1130 = GameTarget.from_settings("1.6.1130", "Steam")
        self.assertEqual(fit("Main for 1.6.1179", "", "", t1130).status, "other")
        self.assertIn("newer than yours", fit("Main for 1.6.1179", "", "", t1130).note)
        self.assertEqual(status("Main for 1.6.1130", AE), "ok")      # older build, same group
        self.assertEqual(status("Main 1.6.659", AE640), "other")       # 659 is newer than 640
        self.assertEqual(status("Main", SE, "Requires 1.6.1170"), "other")
        self.assertEqual(status("Main", t1130, "Built for AE 1.6.1179 only"), "other")
        self.assertEqual(status("Main", AE, "Requires 1.6.1130 or later"), "ok")
        self.assertEqual(status("Main", SE, "Works on 1.6.1170"), "unknown")  # not specific

    def test_file_name_with_underscores(self):
        self.assertEqual(fit("Main", "Display_Tweaks_1_6_1170-34705-0-5-16.7z", "", AE).status, "ok")
        self.assertEqual(fit("Main", "Display_Tweaks_1_5_97-34705-0-5-16.7z", "", AE).status, "other")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.files = [FileOption.from_api(f) for f in FILES[17230]]

    def test_version_split_needs_no_question(self):
        for target, expected in ((SE, 401), (AE, 402)):
            c = choose(parse_line("17230")[0], self.files, target=target)
            self.assertEqual(c.selected, [expected])
            self.assertTrue(c.needs_choice)  # main file + the optional part 2 are still a choice
            self.assertIn("left out", c.reason)
            names = [f.name for f in visible_options(self.files)]
            self.assertNotIn("Engine Fixes VR", names)
            self.assertIn("Engine Fixes VR", [f.name for f in visible_options(self.files, include_other=True)])

    def test_only_file_for_your_version(self):
        mains = [f for f in self.files if f.category == 1]
        c = choose(parse_line("17230")[0], mains, target=SE)
        self.assertEqual((c.selected, c.needs_choice), ([401], False))
        self.assertIn("only file for your game version", c.reason)
        # Without a version every main file is offered and the primary is ticked.
        c = choose(parse_line("17230")[0], mains, target=None)
        self.assertEqual((c.selected, c.needs_choice), ([402], True))

    def test_rules_skip_other_versions(self):
        c = choose(parse_line("17230 | all")[0], self.files, target=SE)
        self.assertEqual(c.selected, [401, 404])
        c = choose(parse_line("17230 | primary")[0], self.files, target=SE)
        self.assertEqual(c.selected, [401])

    def test_everything_for_another_version_still_shown(self):
        vr_only = [f for f in self.files if f.file_id == 403]
        c = choose(parse_line("17230")[0], vr_only, target=AE)
        self.assertEqual((c.selected, c.needs_choice), ([403], True))
        self.assertIn("no file seems to be for", c.reason)
        self.assertEqual(len(visible_options(vr_only)), 1)


class ResolveTests(unittest.TestCase):
    def test_resolve_and_rechoose(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            plan = resolve(client, parse_line("17230 | primary"), target=AE)[0]
            self.assertEqual(plan.selected, [402])
            rechoose(plan, None, SE)
            self.assertEqual(plan.selected, [401])


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def game(self, name, *extra):
        folder = self.tmp / name
        folder.mkdir()
        (folder / "SkyrimSE.exe").write_text("")
        for f in extra:
            (folder / f).write_text("")
        return folder

    def test_store_of(self):
        self.assertEqual(store_of(self.game("steam", "steam_api64.dll")), "Steam")
        self.assertEqual(store_of(self.game("gog", "goggame-1711230643.info")), "GOG")
        self.assertEqual(store_of(self.game("xbox", "MicrosoftGame.config")), "Game Pass")

    def test_find_games_uses_mo2_game_path(self):
        folder = self.game("Skyrim Special Edition", "steam_api64.dll")
        inst = self.tmp / "inst"
        inst.mkdir()
        (inst / "ModOrganizer.ini").write_text(
            "[General]\ngameName=Skyrim Special Edition\n"
            "gamePath=@ByteArray(" + str(folder).replace("\\", "\\\\") + ")\n", encoding="utf-8")
        self.assertEqual(Path(mo2_game_path(inst)), folder)
        games = find_games(mo2_game_path(inst), read_version=lambda exe: (1, 6, 1170))
        self.assertEqual(len(games), 1)
        self.assertEqual((games[0].version, games[0].store, games[0].found_by),
                         ((1, 6, 1170), "Steam", "MO2 instance"))



@unittest.skipUnless(__import__("os").name == "nt", "Windows only")
class WindowsExeVersionTests(unittest.TestCase):
    def test_reads_a_real_exe_version(self):
        import sys
        from skyrimdl.gameversion import exe_version
        v = exe_version(Path(sys.executable))
        self.assertIsNotNone(v)
        self.assertEqual(v[0], sys.version_info.major)


if __name__ == "__main__":
    unittest.main()
