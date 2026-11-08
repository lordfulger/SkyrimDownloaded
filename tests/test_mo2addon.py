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
    m.IPluginTool, m.ReleaseType, m.VersionInfo = IPluginTool, ReleaseType, VersionInfo
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


class AddonTests(unittest.TestCase):
    def setUp(self):
        sys.modules["mobase"] = fake_mobase()
        self.addCleanup(sys.modules.pop, "mobase", None)
        self.plugin = types.ModuleType("SkyrimDownloaded")
        exec(compile(mo2addon.PLUGIN_SOURCE, "SkyrimDownloaded.py", "exec"), self.plugin.__dict__)
        self.tmp = Path(tempfile.mkdtemp())
        self.downloads = self.tmp / "downloads"

    def download_list(self):
        """Download a list into an MO2 instance the way SkyrimDownloaded does (plan + .meta files)."""
        inst = self.tmp / "inst"
        inst.mkdir()
        (inst / "ModOrganizer.ini").write_text("[Settings]\ndownload_directory=%BASE_DIR%/downloads\n")
        target = MO2Target("skyrimspecialedition", instance=inst)
        with FakeNexus() as fake:
            client = NexusClient(GOOD_KEY, base_url=fake.base)
            client.validate()
            plans = resolve(client, parse_list("1000 | file=202,203\n12604\n266\n")[0])
            jobs = jobs_for(plans)
            from skyrimdl.engine import Runner
            Runner(client, target, mode="direct").run(jobs)
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
        self.assertEqual(org.list.order, ["Something else", pt2k, patch, "SkyUI", "USSEP"])
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
