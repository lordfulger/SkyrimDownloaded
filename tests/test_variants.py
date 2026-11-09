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


class TextureSizeTests(unittest.TestCase):
    def target(self, size):
        from skyrimdl.gameversion import GameTarget
        return GameTarget(texture=size)

    def test_sizes_are_read_from_names(self):
        from skyrimdl.selection import texture_sizes
        sizes = lambda n: sorted(texture_sizes(opt(1, n, 1)))
        self.assertEqual(sizes("Textures 2K"), [2])
        self.assertEqual(sizes("Textures 2K4K"), [2, 4])
        self.assertEqual(sizes("2k_4k mix"), [2, 4])
        self.assertEqual(sizes("Main File 2048"), [2])
        self.assertEqual(sizes("SKSE64 for AE"), [])
        self.assertEqual(sizes("Patch v2.4"), [])

    def test_your_size_is_picked_without_asking(self):
        files = [opt(1, "Textures 1K", 1), opt(2, "Textures 2K", 1, primary=True), opt(3, "Textures 4K", 1)]
        choice = choose(parse_line("1")[0], files, target=self.target("4K"))
        self.assertEqual(choice.selected, [3])
        self.assertFalse(choice.needs_choice)
        self.assertIn("texture size", choice.reason)
        # no preference: as before, you're asked
        self.assertTrue(choose(parse_line("1")[0], files).needs_choice)

    def test_closest_size_and_mixes(self):
        files = [opt(1, "Rocks 1K", 1, primary=True), opt(2, "Rocks 2K4K", 1), opt(3, "Rocks 8K", 1)]
        self.assertEqual(choose(parse_line("1")[0], files, target=self.target("4K")).selected, [2])
        self.assertEqual(choose(parse_line("1")[0], files, target=self.target("2K")).selected, [2])
        files = [opt(1, "Rocks 1K", 1, primary=True), opt(3, "Rocks 8K", 1)]
        self.assertEqual(choose(parse_line("1")[0], files, target=self.target("4K")).selected, [1])

    def test_other_choices_still_asked(self):
        files = [opt(1, "Textures 1K", 1, primary=True), opt(2, "Textures 2K", 1),
                 opt(3, "Optional glow maps", 3)]
        choice = choose(parse_line("1")[0], files, target=self.target("2K"))
        self.assertEqual(choice.selected, [2])
        self.assertTrue(choice.needs_choice)

    def test_list_and_earlier_choices_win(self):
        files = [opt(1, "Textures 1K", 1, primary=True), opt(2, "Textures 2K", 1)]
        self.assertEqual(choose(parse_line("1 | match=1K")[0], files, target=self.target("2K")).selected, [1])
        self.assertEqual(choose(parse_line("1")[0], files, [1], target=self.target("2K")).selected, [1])


class VersionForAnotherModTests(unittest.TestCase):
    def test_dyndolod_version_replaces_standard(self):
        files = [opt(1, "HD Lods Textures SE 1K V9.3 Standard version", 1,
                     "1k texture for all the Lods. 100% compatible with SSELODGen.", True),
                 opt(2, "HD Lods Textures SE 1K V9.3 - DynDOLOD version", 1,
                     "Loose files version if you use DynDOLOD (and only if you use DynDOLOD)."),
                 opt(3, "HD Lods Textures SE V9.0 512 - Performance friendly", 3,
                     "512 texture. 100% compatible with SSELODGen & DynDOLOD.")]
        hd = ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "HD LODs Textures SE"),
                     options=files, selected=[1])
        dyn = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "DynDOLOD 3"),
                      options=[opt(9, "DynDOLOD 3.00 Alpha", 1, primary=True)], selected=[9])
        report = compat.check([hd, dyn])
        patches = [(f.plan.title, f.file_id) for f in report.by_kind(compat.PATCH)]
        self.assertEqual(patches, [("HD LODs Textures SE", 2)])  # "compatible with" isn't a patch
        for plan, fid in compat.patches_to_tick(report):
            compat.tick_patch(plan, fid)
        self.assertEqual(hd.selected, [2])

    def test_texture_sized_patches_tick_one(self):
        files = [opt(1, "Snow 2K", 1, primary=True),
                 opt(2, "Blended Roads Retexture - 1K", 3), opt(3, "Blended Roads Retexture - 2K", 3)]
        snow = ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "Snow Mod"),
                       options=files, selected=[1])
        roads = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "Blended Roads"),
                        options=[opt(9, "Blended Roads", 1, primary=True)], selected=[9])
        report = compat.check([snow, roads])
        self.assertEqual(compat.patches_to_tick(report), [(snow, 3)])  # the size of the main file you picked
        self.assertEqual(compat.patches_to_tick(report, texture="1K"), [(snow, 2)])


class OptionPictureTests(unittest.TestCase):
    def test_pictures_in_the_description_go_with_their_files(self):
        from skyrimdl.pictures import description_images, match_images
        raw = ("Two styles.<br />[b]Version 1[/b] - bigger logs<br />[img]https://x/v1.jpg[/img]<br />"
               "[b]Version 2[/b]<br />[img]https://x/v2.jpg[/img]<br />Slightly desaturated:<br />"
               "[img]https://x/desat.jpg[/img]")
        files = [opt(1, "1k Farmhouse Fences SE Version 2", 1), opt(2, "2k Farmhouse Fences SE Version 1", 1),
                 opt(3, "2k Slightly Desaturated Version 1 Deffuse", 3), opt(4, "Readme", 3)]
        got = match_images(files, description_images(raw), "SD's Farmhouse Fences SE")
        self.assertEqual(got, {1: "https://x/v2.jpg", 2: "https://x/v1.jpg", 3: "https://x/desat.jpg"})
        self.assertEqual(match_images(files, []), {})


class AutoPickTests(unittest.TestCase):
    def rules(self, **kw):
        from skyrimdl.gameversion import GameTarget
        return GameTarget(smart=True, **kw)

    def test_extras_stay_off_and_arent_asked(self):
        from skyrimdl.selection import extra_kind
        files = [opt(1, "Cool Mod", 1, primary=True), opt(2, "Cool Mod - Russian Translation", 3),
                 opt(3, "Cool Mod PT-BR", 3), opt(4, "Readme and Sources", 5)]
        self.assertEqual([extra_kind(f) for f in files], ["", "translation", "translation", "docs"])
        choice = choose(parse_line("1")[0], files, target=self.rules())
        self.assertEqual(choice.selected, [1])
        self.assertFalse(choice.needs_choice)
        self.assertIn("left off", choice.reason)
        # without the rules: asked, as before
        self.assertTrue(choose(parse_line("1")[0], files).needs_choice)

    def test_one_main_and_optionals_is_not_a_real_choice(self):
        files = [opt(1, "Cool Mod", 1, primary=True), opt(2, "Optional glow maps", 3), opt(3, "Extra hats", 3)]
        choice = choose(parse_line("1")[0], files, target=self.rules())
        self.assertEqual((choice.selected, choice.needs_choice), ([1], False))
        self.assertIn("2 optional", choice.reason)
        asked = choose(parse_line("1")[0], files, target=self.rules(only_real_choices=False))
        self.assertTrue(asked.needs_choice)

    def test_several_mains_are_asked_unless_your_words_decide(self):
        files = [opt(1, "Fences Version 1", 1, primary=True), opt(2, "Fences Version 2", 1),
                 opt(3, "Fences Desaturated", 1)]
        self.assertTrue(choose(parse_line("1")[0], files, target=self.rules()).needs_choice)
        choice = choose(parse_line("1")[0], files, target=self.rules(prefer=("Desaturated",)))
        self.assertEqual((choice.selected, choice.needs_choice), ([3], False))
        choice = choose(parse_line("1")[0], files, target=self.rules(avoid=("Version 1", "Desaturated")))
        self.assertEqual((choice.selected, choice.needs_choice), ([2], False))
        # a tie is still asked
        self.assertTrue(choose(parse_line("1")[0], files, target=self.rules(prefer=("Fences",))).needs_choice)

    def test_forms_of_one_file_are_one_choice(self):
        files = [opt(1, "Trees - Loose", 1, primary=True), opt(2, "Trees - BSA", 1), opt(3, "Trees 4K", 3)]
        choice = choose(parse_line("1")[0], files, target=self.rules())
        self.assertEqual((choice.selected, choice.needs_choice), ([2], False))


class PickLikeTests(unittest.TestCase):
    def test_same_words_for_a_similar_mod(self):
        from skyrimdl.selection import pick_like
        a = [opt(1, "Rocks - Snow", 1, primary=True), opt(2, "Rocks - No Snow", 1)]
        b = [opt(11, "Trees - Snow", 1, primary=True), opt(12, "Trees - No Snow", 1), opt(13, "Trees readme", 5)]
        self.assertEqual(pick_like([a[1]], a, "Author Rocks", b, "Author Trees"), [12])
        self.assertEqual(pick_like([a[0]], a, "Author Rocks", b, "Author Trees"), [])  # "snow" fits both: unclear
        c = [opt(21, "Grass 1K", 1, primary=True), opt(22, "Grass 2K", 1)]
        self.assertEqual(pick_like([a[1]], a, "Author Rocks", c, "Author Grass"), [])  # no such words
