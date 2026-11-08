import unittest

from skyrimdl import collections
from skyrimdl.engine import resolve
from skyrimdl.links import parse_list
from skyrimdl.nexus import NexusClient, NexusError

from tests.fake_nexus import GOOD_KEY, FakeNexus


class CollectionTests(unittest.TestCase):
    def test_parse_link(self):
        self.assertEqual(collections.parse_link("https://www.nexusmods.com/games/skyrimspecialedition/collections/abc123"),
                         ("skyrimspecialedition", "abc123", None))
        self.assertEqual(collections.parse_link("https://next.nexusmods.com/skyrimspecialedition/collections/qwe456/revisions/12"),
                         ("skyrimspecialedition", "qwe456", 12))
        self.assertEqual(collections.parse_link("abc123"), ("skyrimspecialedition", "abc123", None))
        self.assertIsNone(collections.parse_link("https://www.nexusmods.com/skyrimspecialedition/mods/266"))

    def test_collection_becomes_a_pinned_list(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            data = client.collection("abc123", "skyrimspecialedition")
            text, count = collections.to_list(data, "skyrimspecialedition")
            self.assertEqual(count, 3)
            self.assertIn("# Pretty Skyrim / Lite (revision 7)", text)
            self.assertIn("mods/1000 | file=202,203   # Pretty Textures: Pretty Textures 2K, USSEP Patch, for real", text)
            self.assertIn("mods/266 | file=501 ask", text)
            self.assertIn("SKSE64 (1) : https://skse.silverlock.org".replace(" :", ":"), text)
            entries, problems = parse_list(text)
            self.assertEqual(problems, [])
            plans = {p.entry.mod_id: p for p in resolve(client, entries)}
            self.assertEqual(plans[1000].selected, [202, 203])
            self.assertFalse(plans[1000].needs_choice)
            self.assertTrue(plans[266].needs_choice)      # optional in the collection: asked
            with self.assertRaises(NexusError):
                client.collection("nope99", "skyrimspecialedition")


if __name__ == "__main__":
    unittest.main()
