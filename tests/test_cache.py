import tempfile
import time
import unittest
from pathlib import Path

from skyrimdl import compat
from skyrimdl.engine import resolve
from skyrimdl.links import parse_list
from skyrimdl.nexus import NexusClient
from skyrimdl.nexuscache import DiskCache

from tests.fake_nexus import GOOD_KEY, FakeNexus

LIST = "12604\n1000\n17230\n"


class DiskCacheTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "nexus-cache.json"

    def test_second_lookup_uses_no_requests(self):
        with FakeNexus() as fake:
            first = NexusClient(GOOD_KEY, base_url=fake.base, disk_cache=DiskCache(self.path))
            plans = resolve(first, parse_list(LIST)[0])
            compat.check(plans, first)
            first.disk_cache.flush()
            self.assertEqual(first.requests_made, 6)       # page + Files tab for 3 mods

            # A new run (new client, cache read back from disk).
            count_before = len(fake.state["requests"])
            second = NexusClient(GOOD_KEY, base_url=fake.base, disk_cache=DiskCache(self.path))
            self.assertTrue(second.is_saved("skyrimspecialedition", 1000))
            self.assertEqual(second.estimate_lookup([("skyrimspecialedition", 1000),
                                                     ("skyrimspecialedition", 266)]), 2)
            again = resolve(second, parse_list(LIST)[0])
            report = compat.check(again, second)
            self.assertEqual(second.requests_made, 0)
            self.assertEqual(second.requests_saved, 6)
            self.assertEqual(len(fake.state["requests"]), count_before)  # nothing sent, not even GraphQL
            self.assertEqual([p.title for p in again], [p.title for p in plans])
            self.assertTrue(report.by_kind(compat.NEEDS))

            # "Refresh from Nexus" asks again (and saves the new answers).
            fresh = NexusClient(GOOD_KEY, base_url=fake.base, disk_cache=DiskCache(self.path), refresh=True)
            resolve(fresh, parse_list(LIST)[0])
            self.assertEqual(fresh.requests_made, 6)

    def test_old_entries_expire(self):
        cache = DiskCache(self.path, max_age_days=1)
        cache.put("/x", {"a": 1})
        self.assertEqual(cache.get("/x"), {"a": 1})
        cache._entries["/x"]["t"] = time.time() - 2 * 86400
        self.assertIsNone(cache.get("/x"))
        self.assertFalse(cache.has("/x"))

    def test_broken_cache_file_is_ignored(self):
        self.path.write_text("{nope")
        self.assertEqual(len(DiskCache(self.path)), 0)


class DlcTests(unittest.TestCase):
    def test_dlc_requirements(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            reqs = client.requirements("skyrimspecialedition", 1000)
            dlc = [r for r in reqs if r.dlc]
            self.assertEqual([(r.name, r.notes) for r in dlc], [("Fishing", "for the fishing rods")])
            plans = resolve(client, parse_list("1000\n12604\n")[0])
            report = compat.check(plans, client)
            found = report.by_kind(compat.DLC)
            self.assertEqual(len(found), 1)
            self.assertIn("requires Fishing", found[0].text)
            self.assertIn("requires Fishing", report.warnings()[id(plans[0])])

    def test_still_works_if_nexus_rejects_the_dlc_part(self):
        with FakeNexus() as fake:
            fake.state["dlc_unsupported"] = True
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            reqs = client.requirements("skyrimspecialedition", 1000)
            self.assertEqual({r.name for r in reqs}, {"SkyUI", "SKSE64", "Some Outside Tool"})


if __name__ == "__main__":
    unittest.main()
