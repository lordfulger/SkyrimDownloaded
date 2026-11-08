import tempfile
import unittest
from pathlib import Path

from skyrimdl import compat, session
from skyrimdl.engine import resolve
from skyrimdl.links import parse_list
from skyrimdl.nexus import NexusClient

from tests.fake_nexus import GOOD_KEY, FakeNexus


class SessionTests(unittest.TestCase):
    def test_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "session.json"
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            text = "12604  # SkyUI\n1000 | match=2K\n266\n17230\n999\n"
            plans = resolve(client, parse_list(text)[0])
            report = compat.check(plans, client)
            reqs = {k: v for k, v in client._cache.items() if k.startswith("req:")}
        plans[1].selected = [202, 203]
        plans[1].reason = "your choice"
        plans[3].needs_choice, plans[3].reason = True, "skipped for now - come back to it"
        session.save(path, list_text=text + "unsaved edit\n", list_path="C:/lists/mods.txt",
                     plans=plans, report=report, requirements=reqs, declined={"https://x"},
                     ui={"show_other": True, "sash": 200})

        back = session.load(path)
        self.assertEqual(back.list_text, text + "unsaved edit\n")
        self.assertEqual(back.list_path, "C:/lists/mods.txt")
        self.assertEqual([p.title for p in back.plans], [p.title for p in plans])
        self.assertEqual(back.plans[1].selected, [202, 203])
        self.assertEqual(back.plans[1].entry.rule.match, ["2K"])
        self.assertEqual(back.plans[0].entry.note, "SkyUI")
        self.assertTrue(back.plans[3].needs_choice)
        self.assertEqual(back.plans[4].error, plans[4].error)
        self.assertEqual(back.plans[1].mod.raw["endorsement_count"], 1234)
        self.assertEqual([o.file_id for o in back.plans[1].options], [o.file_id for o in plans[1].options])
        self.assertEqual({(f.kind, f.plan.title, f.other.title) for f in back.report.findings},
                         {(f.kind, f.plan.title, f.other.title) for f in report.findings})
        # Findings point at the restored plans themselves.
        self.assertTrue(all(f.plan in back.plans for f in back.report.findings))
        self.assertIn("req:skyrimspecialedition/1000", back.requirements)
        self.assertEqual(back.requirements["req:skyrimspecialedition/1000"][1].name, "SKSE64")
        self.assertEqual(back.declined, {"https://x"})
        self.assertEqual(back.ui["sash"], 200)
        self.assertFalse(back.empty)

    def test_missing_or_broken_file(self):
        folder = Path(tempfile.mkdtemp())
        self.assertIsNone(session.load(folder / "nope.json"))
        (folder / "bad.json").write_text("{not json")
        self.assertIsNone(session.load(folder / "bad.json"))
        (folder / "old.json").write_text('{"format": 999}')
        self.assertIsNone(session.load(folder / "old.json"))
        session.clear(folder / "nope.json")  # no error


if __name__ == "__main__":
    unittest.main()
