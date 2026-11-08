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

    def test_mods_not_in_list_are_ignored(self):
        plans = [p for p in self.plans if p.title in ("Pretty Textures", "SkyUI")]
        report = compat.check(plans, self.client)
        self.assertEqual({f.kind for f in report.findings}, {compat.NEEDS})

    def test_without_requirements(self):
        report = compat.check(self.plans, None)
        self.assertFalse(report.requirements_checked)
        # Still finds the need from the page text, and the patch and the conflict.
        kinds = {f.kind for f in report.findings}
        self.assertTrue({compat.NEEDS, compat.PATCH, compat.CONFLICT} <= kinds)


if __name__ == "__main__":
    unittest.main()
