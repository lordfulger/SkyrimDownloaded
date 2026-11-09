import tempfile
import time
import unittest
from pathlib import Path

from skyrimdl import listcheck
from skyrimdl.engine import ModPlan
from skyrimdl.links import ListEntry
from skyrimdl.managers.mo2 import read_installed
from skyrimdl.nexus import ModInfo
from skyrimdl.selection import FileOption


def opt(fid, name, cat=1, size=1_000_000, preview="", desc=""):
    return FileOption(fid, name, name + ".7z", "1", cat, size, description=desc,
                      raw={"content_preview_link": preview})


def plan(mod_id, title, options, selected, raw=None):
    return ModPlan(ListEntry("skyrimspecialedition", mod_id, line_no=mod_id),
                   ModInfo("skyrimspecialedition", mod_id, title, raw=raw or {}),
                   options=options, selected=selected)


def f(name):
    return {"type": "file", "name": name}


def d(name, *children):
    return {"type": "directory", "name": name, "children": list(children)}


class PluginTests(unittest.TestCase):
    def test_counts_plugins_from_file_lists(self):
        trees = {
            "a": {"children": [f("Big Mod.esp"), f("Big Mod - Extra.esm"), d("textures", f("x.dds"))]},
            "b": {"children": [f("Small.esl")]},
            "c": {"children": [d("fomod", f("ModuleConfig.xml")), f("Core.esp"),
                               d("Option A", f("A.esp")), d("Option B", f("B.esp"))]},
            "e": {"children": [f("Flagged.esp")]},
        }
        plans = [plan(1, "Big", [opt(1, "Big", preview="a")], [1]),
                 plan(2, "Small", [opt(2, "Small", preview="b")], [2]),
                 plan(3, "Installer", [opt(3, "Installer", preview="c")], [3]),
                 plan(4, "Hidden", [opt(4, "Hidden", preview="")], [4]),
                 plan(5, "Flagged", [opt(5, "Flagged ESL version", preview="e")], [5])]
        count = listcheck.count_plugins(plans, fetch=lambda url: trees.get(url))
        self.assertEqual((count.full, count.light, count.optional, count.unknown_files), (3, 2, 2, 1))
        self.assertEqual(count.total_full, 3 + listcheck.BASE_GAME_PLUGINS)


class ListTests(unittest.TestCase):
    def test_duplicates(self):
        text = "12604\n1000\n# note\nhttps://www.nexusmods.com/skyrimspecialedition/mods/12604?tab=files\n"
        self.assertEqual(listcheck.duplicates(text, "skyrimspecialedition"),
                         [("skyrimspecialedition/12604", [1, 4])])

    def test_replaced_and_old(self):
        now = time.time()
        merged = plan(1, "Old Fix", [], [], raw={
            "description": "This mod has been merged into [url=https://www.nexusmods.com/skyrimspecialedition/mods/17230]"
                           "Engine Fixes[/url], use that instead.", "updated_timestamp": now - 86400})
        old = plan(2, "Ancient", [], [], raw={"description": "Nice mod.", "updated_timestamp": now - 6 * 365 * 86400})
        fresh = plan(3, "Fresh", [], [], raw={"description": "Nice mod.", "updated_timestamp": now})
        got = {r.plan.title: r for r in listcheck.retired([merged, old, fresh], now)}
        self.assertEqual(set(got), {"Old Fix", "Ancient"})
        self.assertIn("merged into", got["Old Fix"].why)
        self.assertEqual(got["Old Fix"].links, ["https://www.nexusmods.com/skyrimspecialedition/mods/17230"])
        self.assertEqual(got["Ancient"].why, "")

    def test_size_by_texture(self):
        files = [opt(1, "Rocks 1K", size=100), opt(2, "Rocks 2K", size=400), opt(3, "Rocks 4K", size=1600)]
        p = plan(1, "Rocks", files, [2])
        sizes = listcheck.size_by_texture([p])
        self.assertEqual((sizes["now"], sizes["1K"], sizes["2K"], sizes["4K"]), (400, 100, 400, 1600))
        self.assertEqual(listcheck.textured_mods([p]), 1)

    def test_space(self):
        p = plan(1, "A", [opt(1, "A", size=10_000)], [1])
        with tempfile.TemporaryDirectory() as tmp:
            spaces = listcheck.space_needed([p], Path(tmp), Path(tmp) / "mods")
        self.assertEqual(len(spaces), 1)  # same drive: one total
        self.assertEqual(spaces[0].need, 10_000 + int(10_000 * listcheck.INSTALL_FACTOR))
        self.assertTrue(spaces[0].enough)

    def test_installed_in_mo2(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = Path(tmp) / "SkyUI"
            m.mkdir()
            (m / "meta.ini").write_text("[General]\nmodid=12604\nversion=5.2SE\n\n[installedFiles]\n"
                                        "1\\modid=12604\n1\\fileid=101\nsize=1\n", encoding="utf-8")
            (Path(tmp) / "Separator_separator").mkdir()
            got = read_installed(Path(tmp))
        self.assertEqual(got["files"], {(12604, 101): "5.2SE"})
        self.assertEqual(got["mods"], {12604: "5.2SE"})
