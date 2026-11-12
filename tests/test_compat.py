import unittest

from skyrimdl import compat
from skyrimdl.engine import resolve
from skyrimdl.links import parse_list
from skyrimdl.nexus import NexusClient
from skyrimdl.text import bbcode_to_text, nexus_mod_ids

from tests.fake_nexus import GOOD_KEY, FakeNexus


class TextTests(unittest.TestCase):
    def test_bbcode(self):
        src = ("[b]Hi[/b]<br />[url=https://www.nexusmods.com/skyrimspecialedition/mods/266]USSEP[/url] "
               "[img]x.png[/img][list][*]one[*]two[/list] &amp; [size=3]done[/size]")
        self.assertEqual(bbcode_to_text(src), "Hi\nUSSEP\n\n\u2022 one\n\u2022 two\n& done")
        self.assertIn("USSEP (https://www.nexusmods.com/skyrimspecialedition/mods/266)",
                      bbcode_to_text(src, keep_links=True))
        self.assertEqual(nexus_mod_ids(src, "skyrimspecialedition"), {266})
        self.assertEqual(nexus_mod_ids(src, "skyrim"), set())

    def test_aliases(self):
        names = [a for a, _ in compat.aliases("Unofficial Skyrim Special Edition Patch")]
        self.assertIn("USSEP", names)
        self.assertIn("Immersive Armors", [a for a, _ in compat.aliases("Immersive Armors - SE")])
        self.assertEqual(compat.aliases("Lux"), [])           # too short to match safely
        self.assertEqual(compat.aliases("Patch"), [])          # too generic


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNexus().__enter__()
        self.addCleanup(self.fake.__exit__)
        self.client = NexusClient(GOOD_KEY, base_url=self.fake.base)
        text = "12604\n1000\n266\n17230\n"
        self.plans = resolve(self.client, parse_list(text)[0])
        self.by_name = {p.title: p for p in self.plans}

    def test_findings(self):
        report = compat.check(self.plans, self.client)
        self.assertTrue(report.requirements_checked)
        kinds = {(f.kind, f.plan.title, f.other.title) for f in report.findings}
        self.assertIn((compat.NEEDS, "Pretty Textures", "SkyUI"), kinds)
        self.assertIn((compat.PATCH, "Pretty Textures", "Unofficial Skyrim Special Edition Patch"), kinds)
        self.assertIn((compat.CONFLICT, "Pretty Textures", "SSE Engine Fixes"), kinds)
        # The page also says it needs SkyUI: not reported twice.
        needs = [f for f in report.findings if f.kind == compat.NEEDS and f.other.title == "SkyUI"]
        self.assertEqual(len(needs), 1)
        patch = report.by_kind(compat.PATCH)[0]
        self.assertEqual(patch.file_id, 203)
        pt, ef = self.by_name["Pretty Textures"], self.by_name["SSE Engine Fixes"]
        self.assertEqual(report.plans_to_review(), [pt, ef])
        self.assertEqual(report.suggestions(), {id(pt): {203: "for Unofficial Skyrim Special Edition Patch, "
                                                               "which is in your list"}})
        self.assertIn("may conflict with SSE Engine Fixes", report.warnings()[id(pt)])

        self.assertTrue(report.notes_for(ef))

    def test_warnings_carry_links(self):
        report = compat.check(self.plans, self.client)
        pt = self.by_name["Pretty Textures"]
        needs = [w for w in report.warnings()[id(pt)] if w.before == "requires" and w.name == "SkyUI"]
        self.assertEqual(len(needs), 1)
        self.assertEqual(needs[0].url, "https://www.nexusmods.com/skyrimspecialedition/mods/12604")
        self.assertEqual(needs[0], "requires SkyUI (in your list)")
        dlc = [w for w in report.warnings()[id(pt)] if w.name == "Fishing"]
        self.assertEqual(dlc[0].url, "")

    def test_descriptions_are_plain_text(self):
        from skyrimdl.selection import _plain
        self.assertEqual(_plain("Needs [url=https://x.y/1]Font Overhaul[/url]<br>[b]Fast[/b]"),
                         "Needs Font Overhaul\nFast")
    def test_mods_not_in_list_are_ignored(self):
        plans = [p for p in self.plans if p.title in ("Pretty Textures", "SkyUI")]
        report = compat.check(plans, self.client)
        self.assertEqual({f.kind for f in report.findings}, {compat.NEEDS, compat.DLC})

    def test_without_requirements(self):
        report = compat.check(self.plans, None)
        self.assertFalse(report.requirements_checked)
        # Still finds the need from the page text, and the patch and the conflict.
        kinds = {f.kind for f in report.findings}
        self.assertTrue({compat.NEEDS, compat.PATCH, compat.CONFLICT} <= kinds)


class PatchPickTests(unittest.TestCase):
    def setUp(self):
        from skyrimdl.engine import ModPlan
        from skyrimdl.links import ListEntry
        from skyrimdl.nexus import ModInfo
        from skyrimdl.selection import FileOption

        def opt(fid, name, cat=3, up=0):
            return FileOption(fid, name, name.replace(" ", "_") + ".7z", "1", cat, 1000, uploaded=up)
        self.easy = ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "EasyNPC"),
                            options=[opt(10, "Main", 1), opt(11, "Pandorable patch v1.0", up=1),
                                     opt(12, "Pandorable patch v1.2", up=2), opt(13, "Pandorable patch beta", up=3),
                                     opt(14, "Interesting NPCs patch", 2, up=1)], selected=[10])
        self.pandorable = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "Pandorable"))
        self.inpc = ModPlan(ListEntry("skyrimspecialedition", 3), ModInfo("skyrimspecialedition", 3, "Interesting NPCs"))
        self.report = compat.Report(findings=[
            compat.Finding(compat.PATCH, self.easy, self.pandorable, "", file_id=f) for f in (11, 12, 13)] + [
            compat.Finding(compat.PATCH, self.easy, self.inpc, "", file_id=14)])

    def test_newest_patch_only_no_beta_no_updates(self):
        picks = compat.patches_to_tick(self.report)
        self.assertEqual([(p.title, f) for p, f in picks], [("EasyNPC", 12)])

    def test_your_own_pick_and_unticked_ones_are_respected(self):
        self.easy.selected.append(11)   # you picked v1.0 yourself
        self.assertEqual(compat.patches_to_tick(self.report), [])
        self.easy.selected.remove(11)
        self.assertEqual(compat.patches_to_tick(self.report, skip=lambda p, f: f == 12), [(self.easy, 11)])


if __name__ == "__main__":
    unittest.main()
