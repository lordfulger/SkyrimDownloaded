import unittest

from skyrimdl import discover
from skyrimdl.engine import resolve
from skyrimdl.links import parse_list
from skyrimdl.nexus import NexusClient
from tests.fake_nexus import FakeNexus, GOOD_KEY


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNexus().__enter__()
        self.addCleanup(self.fake.__exit__)
        self.client = NexusClient(GOOD_KEY, base_url=self.fake.base)

    def test_requirements_use_the_current_api(self):
        reqs = self.client.requirements("skyrimspecialedition", 1000)
        self.assertEqual({r.name for r in reqs}, {"SkyUI", "SKSE64", "Some Outside Tool", "Fishing"})
        self.assertTrue(any("mod(modId" in str(r) or r.startswith("POST") for r in self.fake.state["requests"]))

    def test_suggestions_are_patches_and_addons_for_your_mods(self):
        plans = resolve(self.client, parse_list("12604\n266\n")[0])
        found = discover.suggest(self.client, plans)
        got = [(f.name, f.kind, f.ties) for f in found]
        self.assertEqual(got, [
            ("SkyUI - USSEP Patch", "patch", ["SkyUI", "Unofficial Skyrim Special Edition Patch"]),
            ("Cool SkyUI Addon", "add-on", ["SkyUI"]),
        ])  # not: one needing a mod you don't have, a translation, an adult mod
        self.assertEqual([f.needs for f in found], [[], []])
        adult = discover.suggest(self.client, plans, adult=True)
        self.assertIn("Spicy USSEP Addon", [f.name for f in adult])
        hidden = discover.suggest(self.client, plans, hidden={5002})
        self.assertNotIn("Cool SkyUI Addon", [f.name for f in hidden])

    def test_browse(self):
        found, total = discover.browse(self.client, "skyrimspecialedition", "Recently updated", "Last week",
                                       search="skyui", now=1_000_000)
        self.assertEqual(total, 7)  # adult mods left out
        self.assertEqual(found[0].name, "SkyUI - USSEP Patch")
        sent = self.fake.state["browse"][-1]
        self.assertEqual(sent["s"], [{"updatedAt": {"direction": "DESC"}}])
        self.assertIn({"updatedAt": [{"value": str(1_000_000 - 7 * 86400), "op": "GTE"}]}, sent["f"])
        self.assertIn({"nameStemmed": [{"value": "skyui", "op": "MATCHES"}]}, sent["f"])
        _, all_total = discover.browse(self.client, "skyrimspecialedition", "Most endorsed", "All time", adult=True)
        self.assertEqual(all_total, 8)

    def test_goes_well_with_your_list(self):
        plans = resolve(self.client, parse_list("12604\n266\n1000\n17230\n")[0])
        found = discover.goes_well(self.client, plans)
        self.assertEqual([f.name for f in found], ["Goes Well Mod"])  # in 2 collections like yours
        self.assertEqual(found[0].seen_in, ["Lite Setup", "Pretty Setup"])
        self.assertEqual(found[0].needs, ["x"])  # its requirement isn't in your list
        self.assertEqual(discover.goes_well(self.client, plans, hidden={6001}), [])
