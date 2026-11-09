"""One test per bug found in the November review, so none of them comes back."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from skyrimdl import compat, crashlog, listcheck, sharing, updates
from skyrimdl.config import Settings
from skyrimdl.engine import ModPlan
from skyrimdl.gameversion import GameTarget, parse_version
from skyrimdl.links import ListEntry, parse_line, parse_list
from skyrimdl.managers.mo2 import nexus_domain
from skyrimdl.nexus import ModInfo, NexusClient, NexusError
from skyrimdl.selection import FileOption, choose
from tests.fake_nexus import GOOD_KEY, FakeNexus

SE = "https://www.nexusmods.com/skyrimspecialedition/mods/"


def opt(fid, name, cat=1, primary=False, version="1"):
    return FileOption(fid, name, name + ".7z", version, cat, 1000, is_primary=primary)


class ReviewFixTests(unittest.TestCase):
    def test_same_file_update_keeps_the_pick(self):
        o = opt(10, "Mod")
        plan = ModPlan(ListEntry("skyrimspecialedition", 1), options=[o], selected=[10])
        updates.apply([updates.Update(plan, o, o, "same file, updated")])
        self.assertEqual(plan.selected, [10])

    def test_settings_still_save_when_the_file_is_damaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "settings.json").write_text("{ half", encoding="utf-8")
            s = Settings(manager="vortex")
            s.save(folder)
            self.assertEqual(Settings.load(folder).manager, "vortex")
            self.assertEqual(list(folder.glob("*.tmp")), [])

    def test_list_lines(self):
        entries, problems = parse_list(
            f"| SkyUI | {SE}12604 | Required |\n"          # a row pasted from a table
            f"SkyUI | {SE}266\n"
            f"## {SE}999\n"                                # a link commented out, not a heading
            f"{SE}1 {SE}2 | file=5\n{SE}1 | file=6\n"      # rules aren't shared between links
            "www.nexusmods.com/skyrimspecialedition/mods/1000\n")  # no https://
        self.assertEqual(problems, [])
        got = {e.mod_id: (e.rule.file_ids, e.section) for e in entries}
        self.assertEqual(got, {12604: ([], ""), 266: ([], ""), 1: ([5, 6], ""), 2: ([5], ""), 1000: ([], "")})
        _, problems = parse_list(f"{SE}1\n{SE}2\n{SE}3\n2024\n")
        self.assertTrue(any("just a number" in p for p in problems))

    def test_a_mods_own_version_isnt_a_game_version(self):
        target = GameTarget(parse_version("1.6.1170"))
        files = [opt(1, "Immersive Thing v1.5.12", primary=True), opt(2, "USSEP Patch", 3)]
        self.assertEqual(choose(parse_line("1")[0], files, target=target).selected, [1])
        files = [opt(1, "Engine Fixes for 1.5.97", primary=True), opt(2, "Extras", 3)]
        c = choose(parse_line("1")[0], files, target=target)
        self.assertEqual((c.selected, c.needs_choice), ([], True))   # not just the extras

    def test_earlier_pick_for_another_version_is_asked_again(self):
        target = GameTarget(parse_version("1.6.1170"))
        files = [opt(1, "Thing for 1.5.97", primary=True), opt(2, "Thing A for 1.6.1170"),
                 opt(3, "Thing B for 1.6.1170")]
        c = choose(parse_line("1")[0], files, [1], target=target)
        self.assertTrue(c.needs_choice)
        # Only one file fits now: that one is taken.
        c = choose(parse_line("1")[0], files[:2], [1], target=target)
        self.assertEqual((c.selected, c.needs_choice), ([2], False))
        self.assertEqual(choose(parse_line("1")[0], files, [], target=target).reason, "left out by you")

    def test_out_of_requests_fails_at_once(self):
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            client.rate.daily_remaining = client.rate.hourly_remaining = 0
            client._out_until = time.time() + 60
            start = time.monotonic()
            with self.assertRaises(NexusError):
                client.mod("skyrimspecialedition", 12604)
            self.assertLess(time.monotonic() - start, 1)

    def test_shared_list_round_trip_is_stable(self):
        mod = ModInfo("skyrimspecialedition", 12604, "SkyUI")
        a = ModPlan(ListEntry("skyrimspecialedition", 12604, note="my fave", section="UI"), mod,
                    options=[opt(101, "SkyUI_5_2_SE")], selected=[101])
        b = ModPlan(ListEntry("skyrimspecialedition", 1000), ModInfo("skyrimspecialedition", 1000, "Pretty"),
                    options=[opt(201, "1K")], selected=[201])
        text = sharing.export_text([a, b], None)
        entries, _ = parse_list(text)
        self.assertEqual([e.section for e in entries], ["UI", "Other mods"])
        a.entry.note = entries[0].note
        self.assertEqual(sharing.export_text([a, b], None), text)

    def test_mo2_game_names(self):
        self.assertEqual(nexus_domain("Skyrim", "skyrimspecialedition"), "skyrim")
        self.assertEqual(nexus_domain('"SkyrimSE"', "x"), "skyrimspecialedition")
        self.assertEqual(nexus_domain("", "skyrimspecialedition"), "skyrimspecialedition")

    def test_plugins_counted_once(self):
        tree = {"children": [{"type": "file", "name": "Mod.esp"}]}
        plans = [ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "A"),
                         options=[FileOption(1, "Main", "a.7z", "1", 1, 1, raw={"content_preview_link": "x"}),
                                  FileOption(2, "Hotfix", "b.7z", "1", 2, 1, raw={"content_preview_link": "x"})],
                         selected=[1, 2])]
        self.assertEqual(listcheck.count_plugins(plans, fetch=lambda url: tree).full, 1)

    def test_crash_log_names(self):
        crash = crashlog.parse("FrameworkName: NetScriptFramework\nPossible relevant objects (1)\n{\n"
                               "  [ 2]  Actor(File: `Skyrim.esm <- Cool Armor.esp`)\n"
                               "  [ 3]  NPC(File: \"Pandorable's NPCs.esp\")\n}\n")
        self.assertEqual([n.name for n in crash.named], ["Cool Armor.esp", "Pandorable's NPCs.esp"])

    def test_compat_check_matches_the_same_with_the_word_index(self):
        a = ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "Frost Giants",
                    raw={"description": "Requires Ancient Lanterns. Not compatible with Big Snow Overhaul."}),
                    options=[opt(1, "Frost Giants", primary=True)], selected=[1])
        b = ModPlan(ListEntry("skyrimspecialedition", 2), ModInfo("skyrimspecialedition", 2, "Ancient Lanterns"),
                    options=[opt(2, "Main", primary=True)], selected=[2])
        c = ModPlan(ListEntry("skyrimspecialedition", 3), ModInfo("skyrimspecialedition", 3, "Big Snow Overhaul"),
                    options=[opt(3, "Main", primary=True)], selected=[3])
        kinds = {(f.kind, f.other.title) for f in compat.check([a, b, c]).findings}
        self.assertIn((compat.NEEDS, "Ancient Lanterns"), kinds)
        self.assertIn((compat.CONFLICT, "Big Snow Overhaul"), kinds)


class AddonFixTests(unittest.TestCase):
    def test_unfinished_downloads_dont_count(self):
        ns = {}
        from skyrimdl import mo2addon
        src = mo2addon.PLUGIN_SOURCE
        start = src.index("def meta_index(downloads):")
        end = src.index("\ndef ", start + 10)
        exec("import os, configparser\n" + src[start:end], ns)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name, extra in (("a.7z", ""), ("b.7z.unfinished", ""), ("c.7z", "paused=true\n")):
                (d / name).write_text("x")
                (d / (name + ".meta")).write_text(f"[General]\nmodID=1\nfileID={ord(name[0])}\n{extra}")
            self.assertEqual(ns["meta_index"](str(d)), {(1, ord("a")): "a.7z"})


if __name__ == "__main__":
    unittest.main()
