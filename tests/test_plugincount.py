import struct
import tempfile
import unittest
from pathlib import Path

from skyrimdl import plugincount


def plugin(path: Path, flags: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"TES4" + struct.pack("<II", 100, flags) + b"\0" * 100)


class PluginCountTests(unittest.TestCase):
    def test_counts_what_the_game_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            inst = Path(tmp)
            game = inst / "Game"
            (inst / "ModOrganizer.ini").write_text(
                f"[General]\ngamePath=@ByteArray({game.as_posix()})\nselected_profile=@ByteArray(Main)\n",
                encoding="utf-8")
            for m in plugincount.GAME_MASTERS:
                plugin(game / "Data" / m, 1)
            plugin(game / "Data" / "ccBGSSSE001-Fish.esm", 1)
            mods = inst / "mods"
            plugin(mods / "Big Mod" / "BigMod.esp")                      # regular
            plugin(mods / "Flagged" / "Small.esp", plugincount.LIGHT_FLAG)  # ESL-flagged .esp
            plugin(mods / "Light" / "Tiny.esl")                          # .esl
            plugin(mods / "Old Version" / "BigMod.esp", plugincount.LIGHT_FLAG)  # loses to Big Mod
            plugin(mods / "Off Mod" / "Unused.esp")
            prof = inst / "profiles" / "Main"
            prof.mkdir(parents=True)
            # modlist.txt: highest priority first
            (prof / "modlist.txt").write_text("+Big Mod\n+Flagged\n+Light\n+Old Version\n-Off Mod\n", encoding="utf-8")
            (prof / "plugins.txt").write_text(
                "# auto\n*BigMod.esp\n*Small.esp\n*Tiny.esl\nUnused.esp\n*Gone.esp\n", encoding="utf-8")
            (prof / "loadorder.txt").write_text(
                "Skyrim.esm\nUpdate.esm\nDawnguard.esm\nHearthFires.esm\nDragonborn.esm\nccBGSSSE001-Fish.esm\n"
                "BigMod.esp\nSmall.esp\nTiny.esl\nUnused.esp\nGone.esp\n", encoding="utf-8")
            c = plugincount.count(inst, mods, "Main")
        self.assertEqual(sorted(p.name for p in c.regular),
                         sorted(plugincount.GAME_MASTERS + ["ccBGSSSE001-Fish.esm", "BigMod.esp"]))
        self.assertEqual(sorted(p.name for p in c.light), ["Small.esp", "Tiny.esl"])
        self.assertEqual(c.off, 1)
        self.assertEqual(c.missing, ["Gone.esp"])
        self.assertEqual([p.source for p in c.regular if p.name == "BigMod.esp"], ["Big Mod"])
