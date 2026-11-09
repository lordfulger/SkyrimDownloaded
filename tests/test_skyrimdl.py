import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from skyrimdl import downloader
from skyrimdl.config import Settings, choices_path, load_choices, save_choices
from skyrimdl.engine import (DONE, FAILED, SENT, SKIPPED, Runner, jobs_for, missing_requirements,
                             resolve)
from skyrimdl.links import ListError, Rule, parse_line, parse_list
from skyrimdl.managers import MO2Target, VortexTarget, make_target, nxm_url
from skyrimdl.managers.mo2 import read_instance_ini
from skyrimdl.nexus import AuthError, NexusClient, NotPremiumError
from skyrimdl.selection import FileOption, choose

from tests.fake_nexus import FILES, FREE_KEY, GOOD_KEY, PAYLOADS, FakeNexus

SAMPLE_LIST = """\
# My Skyrim AE list
## Interface
https://www.nexusmods.com/skyrimspecialedition/mods/12604        # SkyUI
https://www.nexusmods.com/skyrimspecialedition/mods/1000 | match=2K
https://www.nexusmods.com/skyrimspecialedition/mods/999
"""


class LinkTests(unittest.TestCase):
    def test_kinds_of_link(self):
        e = parse_line("https://www.nexusmods.com/skyrimspecialedition/mods/266?tab=files&file_id=123")[0]
        self.assertEqual((e.game, e.mod_id, e.file_ids), ("skyrimspecialedition", 266, [123]))
        e = parse_line("nxm://skyrimspecialedition/mods/266/files/55?key=abc&expires=99&user_id=1")[0]
        self.assertEqual((e.mod_id, e.file_ids, e.nxm_key, e.nxm_expires), (266, [55], "abc", 99))
        e = parse_line("  32444  | primary  # Address Library")[0]
        self.assertEqual((e.game, e.mod_id, e.rule.mode, e.note),
                         ("skyrimspecialedition", 32444, "primary", "Address Library"))
        e = parse_line("https://next.nexusmods.com/skyrimspecialedition/mods/17230?tab=description")[0]
        self.assertEqual((e.mod_id, e.file_ids), (17230, []))
        e = parse_line("https://www.nexusmods.com/games/skyrimspecialedition/mods/5)")[0]
        self.assertEqual(e.mod_id, 5)

    def test_pasted_guide_and_merging(self):
        text = ("Install [SKSE](https://www.nexusmods.com/skyrimspecialedition/mods/30379) and "
                "https://www.nexusmods.com/skyrimspecialedition/mods/32444 first.\n"
                "32444 | file=9\n"
                "not a link at all\n"
                "Then 32444 again | file=9\n")
        entries, problems = parse_list(text)
        self.assertEqual([e.mod_id for e in entries], [30379, 32444])
        self.assertEqual(entries[1].rule.file_ids, [9])
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("line 4"))

    def test_rules(self):
        self.assertEqual(Rule.parse("match=2K, match=Performance").match, ["2K", "Performance"])
        r = Rule.parse("ask file=1,2")
        self.assertEqual((r.mode, r.file_ids), ("ask", [1, 2]))
        self.assertEqual(Rule.parse("match=Pretty Textures 2K").match, ["Pretty Textures 2K"])
        r = Rule.parse('match="All in one" primary')
        self.assertEqual((r.match, r.mode), (["All in one"], "primary"))
        self.assertEqual(Rule.parse("").mode, "auto")
        with self.assertRaises(ListError):
            Rule.parse("bogus")
        _, problems = parse_list("https://www.nexusmods.com/skyrimspecialedition/mods/1 | nope\n")
        self.assertTrue(problems and problems[0].startswith("line 1"))

    def test_url_with_hash_in_query_is_not_comment(self):
        e = parse_line("https://www.nexusmods.com/skyrimspecialedition/mods/266?tab=files#x")[0]
        self.assertEqual(e.mod_id, 266)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.files = [FileOption.from_api(f) for f in FILES[1000]]

    def entry(self, line):
        return parse_line(line)[0]

    def test_auto_asks_when_options(self):
        c = choose(self.entry("1000"), self.files)
        self.assertTrue(c.needs_choice)
        self.assertEqual(c.selected, [201])  # primary is pre-ticked

    def test_single_file_needs_no_question(self):
        one = [FileOption.from_api(f) for f in FILES[12604]]
        c = choose(self.entry("12604"), one)
        self.assertEqual((c.selected, c.needs_choice), ([101], False))

    def test_rules_answer_ahead(self):
        self.assertEqual(choose(self.entry("1000 | match=2k"), self.files).selected, [202])
        self.assertEqual(choose(self.entry("1000 | main"), self.files).selected, [201, 202])
        self.assertEqual(choose(self.entry("1000 | all"), self.files).selected, [201, 202, 203])
        c = choose(self.entry("1000 | primary"), self.files)
        self.assertEqual((c.selected, c.needs_choice), ([201], False))
        self.assertEqual(choose(self.entry("1000 | skip"), self.files).selected, [])
        self.assertEqual(choose(self.entry("1000 | file=204"), self.files).selected, [204])

    def test_removed_linked_file_falls_back_and_asks(self):
        c = choose(self.entry("1000 | file=777"), self.files)
        self.assertEqual((c.selected, c.needs_choice), ([201], True))

    def test_remembered_choice(self):
        c = choose(self.entry("1000"), self.files, remembered=[202, 203])
        self.assertEqual((c.selected, c.needs_choice), ([202, 203], False))

    def test_description_html_is_cleaned(self):
        self.assertEqual(self.files[0].description, "1K performance version\nfor low-end PCs")


class ApiAndDownloadTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNexus().__enter__()
        self.addCleanup(self.fake.__exit__)
        self.tmp = Path(tempfile.mkdtemp())
        self.client = NexusClient(GOOD_KEY, base_url=self.fake.base)

    def test_validate_and_headers(self):
        acct = self.client.validate()
        self.assertEqual((acct.name, acct.kind), ("Dovahkiin", "Premium"))
        self.assertEqual(self.client.rate.daily_remaining, 2400)

    def test_bad_key(self):
        with self.assertRaises(AuthError):
            NexusClient("nope", base_url=self.fake.base).validate()

    def test_not_premium(self):
        free = NexusClient(FREE_KEY, base_url=self.fake.base)
        with self.assertRaises(NotPremiumError):
            free.download_links("skyrimspecialedition", 1000, 201)
        # but a link clicked on the site (key + expires) works
        self.assertTrue(free.download_links("skyrimspecialedition", 1000, 201, key="k", expires=5))

    def test_rate_limit_retry(self):
        self.fake.state["fail_429"] = 2
        self.assertEqual(self.client.mod("skyrimspecialedition", 12604).name, "SkyUI")

    def test_resolve_list(self):
        entries, _ = parse_list(SAMPLE_LIST)
        plans = resolve(self.client, entries)
        self.assertEqual([p.title for p in plans], ["SkyUI", "Pretty Textures", "Gone Mod"])
        self.assertEqual(plans[0].selected, [101])
        self.assertEqual(plans[1].selected, [202])
        self.assertIn("not available", plans[2].error)
        missing = resolve(self.client, parse_list("424242")[0])[0]
        self.assertIn("not found", missing.error)

    def test_download_with_resume_after_drop(self):
        self.fake.state["cut_after"] = 100_000
        dest = self.tmp / "out" / "SkyUI.7z"
        urls = self.client.download_links("skyrimspecialedition", 12604, 101)
        seen = []
        with mock.patch.object(downloader, "_sleep", lambda s, c: None):
            downloader.download(urls, dest, partial_dir=self.tmp / "part",
                                expected_size=len(PAYLOADS[101]),
                                progress=lambda d, t: seen.append(d))
        self.assertEqual(dest.read_bytes(), PAYLOADS[101])
        self.assertFalse(list((self.tmp / "part").iterdir()))
        self.assertEqual(seen[-1], len(PAYLOADS[101]))

    def test_cancel(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(downloader.Cancelled):
            downloader.download(["http://127.0.0.1:1/x"], self.tmp / "x", partial_dir=self.tmp, cancel=cancel)

    def test_direct_into_mo2_writes_meta_and_skips_second_time(self):
        inst = self.tmp / "MO2"
        inst.mkdir()
        (inst / "ModOrganizer.ini").write_text(
            "[General]\ngameName=Skyrim Special Edition\n[Settings]\n"
            "download_directory=%BASE_DIR%/dl\n", encoding="utf-8")
        target = MO2Target("skyrimspecialedition", instance=inst)
        self.assertEqual(target.downloads_dir(), inst / "dl")
        entries, _ = parse_list(SAMPLE_LIST)
        plans = resolve(self.client, entries)
        jobs = jobs_for(plans)
        self.client.validate()
        Runner(self.client, target, mode="direct").run(jobs)
        self.assertEqual([j.state for j in jobs], [DONE, DONE], [j.note for j in jobs])
        archive = inst / "dl" / "Pretty Textures 2K-1000-2-0.7z"
        self.assertEqual(archive.read_bytes(), PAYLOADS[202])
        meta = read_instance_ini(archive.with_name(archive.name + ".meta"))
        self.assertEqual(meta["General/gameName"], "SkyrimSE")
        self.assertEqual(meta["General/modID"], "1000")
        self.assertEqual(meta["General/fileID"], "202")
        self.assertEqual(meta["General/modName"], "Pretty Textures")
        self.assertEqual(meta["General/installed"], "false")
        again = jobs_for(plans)
        Runner(self.client, target, mode="direct").run(again)
        self.assertEqual([j.state for j in again], [SKIPPED, SKIPPED])

    def test_direct_download_tries_again(self):
        from skyrimdl import engine
        target = VortexTarget("skyrimspecialedition", downloads=self.tmp / "dl", exe=self.tmp / "Vortex.exe")
        plans = resolve(self.client, parse_list("12604")[0])
        jobs = jobs_for(plans)
        self.fake.state["cdn_fail"] = 3
        old = engine.RETRY_WAIT
        engine.RETRY_WAIT = (0, 0, 0)
        try:
            Runner(self.client, target, mode="direct").run(jobs)
        finally:
            engine.RETRY_WAIT = old
        self.assertEqual(jobs[0].state, DONE, jobs[0].note)

    def test_handoff_sends_nxm_links(self):
        target = VortexTarget("skyrimspecialedition", downloads=self.tmp, exe=self.tmp / "Vortex.exe")
        (self.tmp / "Vortex.exe").write_text("")
        sent = []
        target._launch = lambda args: sent.append(args)
        entries, _ = parse_list(
            "nxm://skyrimspecialedition/mods/1000/files/203?key=K&expires=9\n"
            "https://www.nexusmods.com/skyrimspecialedition/mods/12604\n")
        plans = resolve(self.client, entries)
        jobs = jobs_for(plans)
        self.client.validate()
        Runner(self.client, target, mode="handoff", install=True).run(jobs)
        self.assertEqual([j.state for j in jobs], [SENT, SENT])
        self.assertEqual(sent[0][1:], ["--install",
                                       "nxm://skyrimspecialedition/mods/1000/files/203?key=K&expires=9&user_id=7"])
        self.assertEqual(sent[1][2], "nxm://skyrimspecialedition/mods/12604/files/101")

    def test_requirements(self):
        plans = resolve(self.client, parse_list("12604\n1000\n")[0])
        missing, checked = missing_requirements(self.client, plans)
        self.assertTrue(checked)
        self.assertEqual([(m.requirement.name, m.requirement.external, m.requirement.dlc, m.needed_by)
                          for m in missing],
                         [("SKSE64", False, False, ["Pretty Textures"]),
                          ("Some Outside Tool", True, False, ["Pretty Textures"]),
                          ("Fishing", True, True, ["Pretty Textures"])])
        self.fake.state["graphql_down"] = True
        fresh = NexusClient(GOOD_KEY, base_url=self.fake.base)
        self.assertEqual(missing_requirements(fresh, plans), ([], False))

    def test_size_only_in_kb(self):
        # The v1 API may give only size_kb: don't reject the download over rounding.
        plans = resolve(self.client, parse_list("30379")[0])
        self.assertIsNone(plans[0].options[0].size_bytes)
        target = MO2Target("skyrimspecialedition", downloads=self.tmp / "dl")
        jobs = jobs_for(plans)
        Runner(self.client, target, mode="direct").run(jobs)
        self.assertEqual(jobs[0].state, DONE, jobs[0].note)
        again = jobs_for(plans)
        Runner(self.client, target, mode="direct").run(again)
        self.assertEqual(again[0].state, SKIPPED)

    def test_handoff_failure_reported(self):
        target = MO2Target("skyrimspecialedition", downloads=self.tmp)  # no exe anywhere
        plans = resolve(self.client, parse_list("12604")[0])
        jobs = jobs_for(plans)
        Runner(self.client, target, mode="handoff").run(jobs)
        self.assertEqual(jobs[0].state, FAILED)
        self.assertIn("ModOrganizer.exe", jobs[0].note)


class ManagerAndConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_mo2_ini_bytearray_and_base_dir(self):
        inst = self.tmp / "inst"
        inst.mkdir()
        (inst / "ModOrganizer.ini").write_text(
            "[Settings]\nbase_directory=@ByteArray(D:/Modding/SkyrimAE)\n"
            "download_directory=%BASE_DIR%/downloads\n", encoding="utf-8")
        self.assertEqual(MO2Target("skyrimspecialedition", instance=inst).downloads_dir(),
                         Path("D:/Modding/SkyrimAE/downloads"))
        (inst / "ModOrganizer.ini").write_text("[General]\ngameName=x\n", encoding="utf-8")
        self.assertEqual(MO2Target("skyrimspecialedition", instance=inst).downloads_dir(), inst / "downloads")

    def test_vortex_folder_accepts_root_or_game_folder(self):
        (self.tmp / "skyrimse").mkdir()
        self.assertEqual(VortexTarget("skyrimspecialedition", downloads=self.tmp).downloads_dir(),
                         self.tmp / "skyrimse")
        self.assertEqual(VortexTarget("skyrimspecialedition", downloads=self.tmp / "skyrimse").downloads_dir(),
                         self.tmp / "skyrimse")

    def test_nxm_url(self):
        self.assertEqual(nxm_url("skyrimspecialedition", 1, 2), "nxm://skyrimspecialedition/mods/1/files/2")
        self.assertIn("key=a&expires=3", nxm_url("skyrimspecialedition", 1, 2, key="a", expires=3))

    def test_make_target(self):
        self.assertIsInstance(make_target("vortex", "skyrimspecialedition"), VortexTarget)
        self.assertIsInstance(make_target("MO2", "skyrimspecialedition"), MO2Target)

    def test_settings_roundtrip_and_key(self):
        s = Settings(manager="vortex")
        s.set_api_key("secret-key ")
        s.save(self.tmp)
        raw = (self.tmp / "settings.json").read_text()
        self.assertNotIn("secret-key", raw)
        loaded = Settings.load(self.tmp)
        self.assertEqual((loaded.manager, loaded.get_api_key()), ("vortex", "secret-key"))

    def test_settings_backup_used_if_damaged(self):
        s = Settings(manager="vortex")
        s.set_api_key("abc123")
        s.save(self.tmp)
        s.save(self.tmp)  # the second save keeps the first as the backup
        (self.tmp / "settings.json").write_text("{ half written", encoding="utf-8")
        loaded = Settings.load(self.tmp)
        self.assertEqual(loaded.get_api_key(), "abc123")
        self.assertEqual(loaded.manager, "vortex")
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_theme_setting_roundtrip(self):
        Settings(theme="Dark").save(self.tmp)
        self.assertEqual(Settings.load(self.tmp).theme, "Dark")
        from skyrimdl.theme import resolve
        self.assertEqual(resolve("Dark"), "Dark")
        self.assertEqual(resolve("Light"), "Light")
        self.assertIn(resolve("System"), ("Light", "Dark"))

    def test_choices_file(self):
        fake = FakeNexus().__enter__()
        self.addCleanup(fake.__exit__)
        client = NexusClient(GOOD_KEY, base_url=fake.base)
        lst = self.tmp / "mods.txt"
        lst.write_text("1000\n12604\n")
        plans = resolve(client, parse_list(lst.read_text())[0])
        plans[0].selected = [202, 203]
        save_choices(choices_path(lst), plans)
        data = json.loads(choices_path(lst).read_text())
        self.assertEqual(data["mods"]["skyrimspecialedition/1000"]["files"], [202, 203])
        remembered = load_choices(choices_path(lst))
        again = resolve(client, parse_list(lst.read_text())[0], remembered=remembered)
        self.assertEqual((again[0].selected, again[0].needs_choice), ([202, 203], False))


if __name__ == "__main__":
    unittest.main()


class HandoffPacingTests(unittest.TestCase):
    def test_keeps_a_few_downloads_going(self):
        import threading
        import time as _time
        from skyrimdl import engine
        from skyrimdl.links import ListEntry
        from skyrimdl.managers.base import Target
        from skyrimdl.nexus import ModInfo
        from skyrimdl.selection import FileOption
        tmp = Path(tempfile.mkdtemp())
        peak = [0]

        class FakeManager(Target):
            name = "Fake MO2"
            in_flight = 2

            def downloads_dir(self):
                return tmp

            def exe(self):
                return tmp / "x.exe"

            def handoff_args(self, url, install):
                return [url]

            def _launch(self, args):  # "MO2" starts the download, finishes it a moment later
                fid = args[0].rsplit("/", 1)[-1]
                part = tmp / f"file{fid}.7z.unfinished"
                part.write_text("")
                peak[0] = max(peak[0], len(list(tmp.glob("*.unfinished"))))

                def finish():
                    _time.sleep(0.3)
                    part.rename(tmp / f"file{fid}.7z")
                threading.Thread(target=finish).start()

        opts = [FileOption(i, f"F{i}", f"file{i}.7z", "1", 1, 10) for i in range(1, 7)]
        plan = engine.ModPlan(ListEntry("skyrimspecialedition", 1), ModInfo("skyrimspecialedition", 1, "M"),
                              options=opts, selected=[o.file_id for o in opts])
        jobs = jobs_for([plan])
        client = NexusClient("test-key")
        start = _time.monotonic()
        engine.Runner(client, FakeManager("skyrimspecialedition"), mode="handoff").run(jobs)
        self.assertLessEqual(peak[0], 2)                     # never more than 2 at once
        self.assertLess(_time.monotonic() - start, 15)
        _time.sleep(0.5)
        engine.Runner(client, FakeManager("skyrimspecialedition"), mode="handoff")._arrived(
            [(j, 0) for j in jobs])
        self.assertTrue(all(j.state in (DONE, SENT) for j in jobs))
        self.assertGreaterEqual(sum(j.state == DONE for j in jobs), 4)
