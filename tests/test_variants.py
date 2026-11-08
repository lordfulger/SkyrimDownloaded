import unittest

from skyrimdl import compat
from skyrimdl.engine import ModPlan
from skyrimdl.links import ListEntry, parse_line
from skyrimdl.nexus import ModInfo
from skyrimdl.selection import FileOption, choose, prefer_variants


def opt(fid, name, cat, desc="", primary=False, up=0):
    return FileOption(fid, name, name + ".7z", "3.1", cat, 6000, is_primary=primary, uploaded=up, description=desc)


class VariantTests(unittest.TestCase):
    def test_esl_alternative_is_favoured_and_not_doubled(self):
        files = [opt(1, "BCC-SkyUI-v31", 1, "Finally a version with gamepad support.", True),
                 opt(2, "BCC-SkyUI-ESL-v31", 3, "This ESL version is an alternative to the main file, don't use both."),
                 opt(3, "BCC_Config_Example", 3, "The example file")]
        self.assertEqual(choose(parse_line("1")[0], files).selected, [2])
        self.assertEqual(prefer_variants(files, [1, 2, 3]), [2, 3])

    def test_packed_beats_loose(self):
        files = [opt(1, "Pretty Trees - Loose", 1, primary=True), opt(2, "Pretty Trees - BSA", 1),
                 opt(3, "Pretty Trees 2K - Loose files", 1)]
        self.assertEqual(choose(parse_line("1")[0], files).selected, [2])
        self.assertEqual(choose(parse_line("1 | all")[0], files).selected, [2, 3])

    def test_different_files_are_not_variants(self):
        files = [opt(1, "Textures 1K", 1, primary=True), opt(2, "Textures 2K", 1), opt(3, "Patch for X", 3)]
        self.assertEqual(prefer_variants(files, [1, 2, 3]), [1, 2, 3])

    def test_mod_named_after_another_mod_isnt_a_patch_for_it(self):
        bcc = ModPlan(ListEntry("skyrimspecialedition", 1),
                      ModInfo("skyrimspecialedition", 1, "Better Container Controls for SkyUI"),
                      options=[opt(1, "BCC-SkyUI-v31", 1, primary=True), opt(2, "BCC-SkyUI-ESL-v31", 3)],
                      selected=[1])
        skyui = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "SkyUI"),
                        options=[opt(9, "SkyUI_5_2_SE", 1, primary=True)], selected=[9])
        report = compat.check([bcc, skyui])
        self.assertEqual(report.by_kind(compat.PATCH), [])

    def test_auto_patch_skips_a_variant_of_a_ticked_file(self):
        easy = ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "EasyNPC"),
                       options=[opt(1, "Main", 1, primary=True), opt(2, "Pandorable patch", 3),
                                opt(3, "Pandorable patch ESL", 3)], selected=[1, 2])
        pandorable = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "Pandorable"))
        report = compat.Report(findings=[compat.Finding(compat.PATCH, easy, pandorable, "", file_id=3)])
        self.assertEqual(compat.patches_to_tick(report), [])


if __name__ == "__main__":
    unittest.main()
