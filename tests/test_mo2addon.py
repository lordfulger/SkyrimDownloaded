import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from skyrimdl import mo2addon
from skyrimdl.engine import jobs_for, resolve
from skyrimdl.links import parse_list
from skyrimdl.managers.mo2 import MO2Target, write_meta
from skyrimdl.nexus import NexusClient

from tests.fake_nexus import GOOD_KEY, FakeNexus


def fake_mobase():
    m = types.ModuleType("mobase")

    class IPluginTool:
        def __init__(self):
            pass

    class ReleaseType:
        FINAL = 3

    class VersionInfo:
        def __init__(self, *a):
            self.parts = a
    class GuessedString(str):
        pass

    class PluginSetting:
        def __init__(self, *a):
            self.args = a
    m.IPluginTool, m.ReleaseType, m.VersionInfo = IPluginTool, ReleaseType, VersionInfo
    m.GuessedString, m.PluginSetting = GuessedString, PluginSetting
    return m


class FakeMod:
    def __init__(self, name, archive):
        self._name, self._archive = name, archive

    def name(self):
        return self._name

    def installationFile(self):
        return self._archive


class FakeModList:
    def __init__(self, mods):
        self.order = [m.name() for m in mods]
        self.mods = {m.name(): m for m in mods}
        self.active = set()

    def allMods(self):
        return list(self.order)

    def getMod(self, name):
        return self.mods.get(name)

    def setPriority(self, name, priority):
        self.order.remove(name)
        self.order.insert(min(priority, len(self.order)), name)
        return True

    def setActive(self, name, active):
        (self.active.add if active else self.active.discard)(name)


class FakeOrganizer:
    def __init__(self, downloads, mods=(), cancel=()):
        self.downloads = downloads
        self.list = FakeModList(list(mods))
        self.cancel = set(cancel)
        self.installed = []
        self.settings = {}

    def modList(self):
        return self.list

    def downloadsPath(self):
        return str(self.downloads)

    def installMod(self, path, name):
        archive = Path(path).name
        self.installed.append(archive)
        if archive in self.cancel:
            return None
        mod = FakeMod(name or archive, str(path))
        self.list.mods[mod.name()] = mod
        self.list.order.append(mod.name())
        return mod

    def refresh(self):
        pass

    def createMod(self, name):
        mod = FakeMod(str(name), "")
        self.list.mods[mod.name()] = mod
        self.list.order.append(mod.name())
        return mod

    def modsPath(self):
        return str(self.downloads.parent / "mods")

    def pluginSetting(self, plugin, key):
        return self.settings.get(key, True)

    def onUserInterfaceInitialized(self, callback):
        self.ui_callback = callback


LIST = "## 01 - TEXTURES\n1000 | file=202,203\n## 02 - INTERFACE\n12604\n266\n"


class AddonTests(unittest.TestCase):
    def setUp(self):
        sys.modules["mobase"] = fake_mobase()
        self.addCleanup(sys.modules.pop, "mobase", None)
        self.plugin = types.ModuleType("SkyrimDownloaded")
        exec(compile(mo2addon.PLUGIN_SOURCE, "SkyrimDownloaded.py", "exec"), self.plugin.__dict__)
        self.tmp = Path(tempfile.mkdtemp())
        self.downloads = self.tmp / "downloads"

    def download_list(self, auto=False):
        """Download a list into an MO2 instance the way SkyrimDownloaded does (plan + .meta files)."""
        inst = self.tmp / "inst"
        inst.mkdir()
        (inst / "ModOrganizer.ini").write_text("[Settings]\ndownload_directory=%BASE_DIR%/downloads\n")
        target = MO2Target("skyrimspecialedition", instance=inst)
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            client.validate()
            plans = resolve(client, parse_list(LIST)[0])
            jobs = jobs_for(plans)
            from skyrimdl.engine import Runner
            Runner(client, target, mode="direct", install=auto).run(jobs)
        self.downloads = inst / "downloads"
        return jobs

    def test_plan_and_install_in_list_order(self):
        jobs = self.download_list()
        plan = json.loads((self.downloads / mo2addon.PLAN_FILE).read_text())["mods"]
        self.assertEqual([(m["mod_id"], m["file_id"]) for m in plan], [(1000, 202), (1000, 203), (12604, 101), (266, 501)])
        # USSEP is already installed as a mod in MO2.
        ussep = FakeMod("USSEP", str(self.downloads / "USSEP-266-4-3-2.7z"))
        other = FakeMod("Something else", "elsewhere.7z")
        org = FakeOrganizer(self.downloads, [other, ussep])
        steps = self.plugin.make_steps(org, str(self.downloads), self.plugin.read_plan(str(self.downloads)))
        self.assertEqual([(s[1], s[2]) for s in steps],
                         [("Pretty Textures 2K-1000-2-0.7z", False), ("Patch-1000-1-1.zip", False),
                          ("SkyUI_5_2_SE-12604-5-2SE.7z", False), ("USSEP-266-4-3-2.7z", True)])
        result = self.plugin.run(org, str(self.downloads), steps)
        self.assertEqual(org.installed, ["Pretty Textures 2K-1000-2-0.7z", "Patch-1000-1-1.zip",
                                         "SkyUI_5_2_SE-12604-5-2SE.7z"])
        self.assertEqual(result["skipped"], ["USSEP-266-4-3-2.7z"])
        # Left pane: the list's mods at the bottom, in list order; all switched on.
        pt2k, patch = "Pretty Textures - Pretty Textures 2K", "Pretty Textures - USSEP Patch, for real"
        # Separators from the list's "## ..." headings, each followed by its mods.
        self.assertEqual(org.list.order, ["Something else", "01 - TEXTURES_separator", pt2k, patch,
                                          "02 - INTERFACE_separator", "SkyUI", "USSEP"])
        self.assertEqual(org.list.active, {pt2k, patch, "SkyUI", "USSEP"})
        self.assertEqual(len(jobs), 4)

    def test_cancelled_install_asks_and_missing_downloads_are_reported(self):
        self.download_list()
        (self.downloads / "SkyUI_5_2_SE-12604-5-2SE.7z").unlink()
        org = FakeOrganizer(self.downloads, cancel={"Pretty Textures 2K-1000-2-0.7z"})
        steps = self.plugin.make_steps(org, str(self.downloads), self.plugin.read_plan(str(self.downloads)))
        asked = []
        result = self.plugin.run(org, str(self.downloads), steps, ask_continue=lambda m: asked.append(m) or True)
        self.assertEqual(result["failed"], ["Pretty Textures 2K-1000-2-0.7z"])
        self.assertEqual(len(asked), 1)
        self.assertEqual(result["missing"], ["SkyUI_5_2_SE"])
        self.assertIn("USSEP-266-4-3-2.7z", result["installed"])

    def test_automatic_mode(self):
        self.download_list(auto=True)
        plan = json.loads((self.downloads / mo2addon.PLAN_FILE).read_text())
        self.assertTrue(plan["auto_install"])
        self.assertEqual(plan["mods"][0]["separator"], "01 - TEXTURES")
        org = FakeOrganizer(self.downloads)
        p = self.plugin.createPlugin()
        p.init(org)
        reports = []
        p._report = reports.append
        # One download hasn't arrived yet: wait, then ask after a long quiet spell.
        skyui = self.downloads / "SkyUI_5_2_SE-12604-5-2SE.7z"
        skyui.rename(skyui.with_suffix(".unfinished"))
        self.assertIsNone(p.check_auto(now=1000))
        self.assertIsNone(p.check_auto(now=1100))
        self.assertEqual(p.check_auto(now=1000 + 11 * 60), "ask")
        # It arrives: install everything, once.
        skyui.with_suffix(".unfinished").rename(skyui)
        self.assertEqual(p.check_auto(now=2000), "install")
        p._install(str(self.downloads), self.plugin.read_plan_file(str(self.downloads)))
        self.assertEqual(len(reports[0]["installed"]), 4)
        self.assertIsNone(p.check_auto(now=2100))          # done: not again
        # Switched off in MO2's settings: does nothing.
        org.settings["auto_install"] = False
        self.download_list_again = None
        self.assertIsNone(p.check_auto(now=3000))

    def test_plugin_metadata_and_install_into_mo2(self):
        p = self.plugin.createPlugin()
        self.assertEqual(p.displayName(), "SkyrimDownloaded: install downloaded mods")
        self.assertTrue(p.init(object()))
        mo2 = self.tmp / "MO2"
        (mo2 / "plugins").mkdir(parents=True)
        (mo2 / "ModOrganizer.exe").write_text("")
        self.assertFalse(mo2addon.addon_installed(mo2 / "ModOrganizer.exe"))
        where = mo2addon.install_addon(mo2 / "ModOrganizer.exe")
        self.assertEqual(where, mo2 / "plugins" / "SkyrimDownloaded.py")
        self.assertTrue(mo2addon.addon_installed(mo2 / "ModOrganizer.exe"))


if __name__ == "__main__":
    unittest.main()


class CategorySeparatorTests(unittest.TestCase):
    def test_mods_without_a_heading_go_under_their_category(self):
        import json
        import tempfile
        from pathlib import Path
        from skyrimdl.engine import Runner, jobs_for, resolve
        from skyrimdl.links import parse_list
        from skyrimdl.managers.mo2 import MO2Target
        from skyrimdl.nexus import NexusClient
        from tests.fake_nexus import FakeNexus, GOOD_KEY
        with FakeNexus() as fake, tempfile.TemporaryDirectory() as tmp:
            inst = Path(tmp)
            (inst / "ModOrganizer.ini").write_text("[General]\ngameName=Skyrim Special Edition\n", encoding="utf-8")
            (inst / "ModOrganizer.exe").write_text("")
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            plans = resolve(client, parse_list("12604\n1000 | file=201\n## My UI\n266\n17230 | file=402\n")[0])
            target = MO2Target("skyrimspecialedition", instance=inst)
            target._launch = lambda args: None
            Runner(client, target, mode="handoff", category_separators=True).run(jobs_for(plans))
            mods = json.loads((inst / "downloads" / "SkyrimDownloaded-install.json").read_text())["mods"]
        got = [(m["name"], m["separator"]) for m in mods]
        self.assertEqual(got, [("SkyUI", "User Interface"), ("Pretty Textures", "Environmental"),
                               ("Unofficial Skyrim Special Edition Patch", "My UI"),
                               ("SSE Engine Fixes", "My UI")])
