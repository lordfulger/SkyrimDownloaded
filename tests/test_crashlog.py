import tempfile
import unittest
from pathlib import Path

from skyrimdl import crashlog
from skyrimdl.engine import ModPlan
from skyrimdl.links import ListEntry
from skyrimdl.nexus import ModInfo

LOG = (Path(__file__).parent / "data" / "crash-logger.log").read_text(encoding="utf-8")
NSF = """Unhandled native exception occurred at 0x7FF6 (SkyrimSE.exe+12) on thread 1!
FrameworkName: NetScriptFramework
Probable callstack
{
  [0]   0x7FF6 (SkyrimSE.exe+12)
  [1]   0x7FFA (hdtSMP64.dll+1A2B3)
}
Possible relevant objects (1)
{
  [   2]  Actor(Name: "Lydia", FormId: 000A2C94, File: "Skyrim.esm <- Pretty Followers.esp")
}
Modules
{
  hdtSMP64.dll
  SomethingElse.dll
}
"""


def plan(mod_id, title):
    return ModPlan(ListEntry("skyrimspecialedition", mod_id), ModInfo("skyrimspecialedition", mod_id, title))


class CrashLogTests(unittest.TestCase):
    def test_crash_logger(self):
        crash = crashlog.parse(LOG)
        self.assertEqual(crash.kind, "Crash Logger")
        self.assertIn("EXCEPTION_ACCESS_VIOLATION", crash.exception)
        got = [(n.name, n.kind, n.count, n.in_stack) for n in crash.named]
        self.assertEqual(got, [("po3_PapyrusExtender.dll", "dll", 3, True), ("BadMod Plugin.dll", "dll", 1, True),
                               ("Interesting NPCs.esp", "plugin", 3, False), ("USSEP.esp", "plugin", 1, False)])
        # not: the game, Windows, base game plugins, or the full lists at the end (EngineFixes.dll)

    def test_net_script_framework(self):
        crash = crashlog.parse(NSF)
        self.assertEqual(crash.kind, ".NET Script Framework")
        self.assertEqual([n.name for n in crash.named], ["hdtSMP64.dll", "Pretty Followers.esp"])

    def test_matched_to_mods(self):
        crash = crashlog.parse(LOG)
        plans = [plan(22854, "powerofthree's Papyrus Extender"), plan(29194, "Interesting NPCs - SE"),
                 plan(266, "Unofficial Skyrim Special Edition Patch")]
        with tempfile.TemporaryDirectory() as tmp:
            mods = Path(tmp)
            (mods / "Papyrus Extender" / "SKSE" / "Plugins").mkdir(parents=True)
            (mods / "Papyrus Extender" / "SKSE" / "Plugins" / "po3_PapyrusExtender.dll").write_text("")
            (mods / "Papyrus Extender" / "meta.ini").write_text("[General]\nmodid=22854\n")
            (mods / "Bad Mod").mkdir()
            (mods / "Bad Mod" / "BadMod Plugin.dll").write_text("")
            files = crashlog.index_mo2(mods)
            ids = crashlog.mo2_mod_ids(mods, files.values())
        crashlog.match(crash, plans, files, ids)
        got = {n.name: (n.mod, bool(n.url)) for n in crash.named}
        self.assertEqual(got["po3_PapyrusExtender.dll"], ("powerofthree's Papyrus Extender", True))
        self.assertEqual(got["BadMod Plugin.dll"], ("Bad Mod", False))       # in MO2, not in the list
        self.assertEqual(got["Interesting NPCs.esp"], ("Interesting NPCs - SE", True))  # by name
        self.assertEqual(got["USSEP.esp"], ("Unofficial Skyrim Special Edition Patch", True))  # initials
