import unittest

from skyrimdl import appupdate

from tests.fake_nexus import FakeNexus


class AppUpdateTests(unittest.TestCase):
    def test_newer_release(self):
        with FakeNexus() as fake:
            url = fake.base.replace("/v1", "") + "/repos/x/y/releases/latest"
            fake.state["latest_tag"] = "v2.0.0"
            found = appupdate.check(url, current="1.6.1")
            self.assertEqual((found.version, found.exe_url), ("2.0.0", "https://example.com/v2.0.0.exe"))
            self.assertEqual((found.sha256, found.size), ("ab" * 32, 1234))
            fake.state["latest_tag"] = "v1.6.1"
            self.assertIsNone(appupdate.check(url, current="1.6.1"))
            self.assertIsNone(appupdate.check(url, current="1.10.0"))   # compares numbers, not text

    def test_download_checks_the_checksum(self):
        import hashlib
        import tempfile
        from pathlib import Path
        from tests.fake_nexus import PAYLOADS
        with FakeNexus() as fake:
            data = PAYLOADS[201]
            url = fake.base.replace("/v1", "") + "/cdn/201/SkyrimDownloaded.exe"
            folder = Path(tempfile.mkdtemp())
            good = appupdate.NewVersion("9.9.9", "page", url, hashlib.sha256(data).hexdigest(), len(data))
            path = appupdate.download_update(good, folder)
            self.assertEqual(path.read_bytes(), data)
            bad = appupdate.NewVersion("9.9.9", "page", url, "0" * 64, len(data))
            with self.assertRaises(ValueError):
                appupdate.download_update(bad, folder)
            self.assertFalse((folder / "SkyrimDownloaded.update.exe").exists())

    def test_where_the_update_goes(self):
        import tempfile
        from pathlib import Path
        exe = Path(tempfile.mkdtemp()) / "SkyrimDownloaded.exe"
        self.assertEqual(appupdate.update_target(exe), exe)       # writable folder: in place
        self.assertIsNone(appupdate.running_exe())                # tests run from source
        self.assertIn('copy /Y "%NEW%" "%OLD%"', appupdate.SWAP_SCRIPT)

    def test_programs_start_without_the_exe_s_own_settings(self):
        import os
        from unittest import mock
        fake = {"PATH": "x", "_PYI_APPLICATION_HOME_DIR": "C:/Temp/_MEI1", "_MEIPASS2": "C:/Temp/_MEI1",
                "_PYI_PARENT_PROCESS_LEVEL": "1", "TCL_LIBRARY": "C:/Temp/_MEI1/tcl"}
        with mock.patch.dict(os.environ, fake, clear=True):
            env = appupdate.clean_env()
        self.assertEqual(env, {"PATH": "x", "PYINSTALLER_RESET_ENVIRONMENT": "1"})

    def test_offline_says_why(self):
        with self.assertRaises(appupdate.CheckFailed):
            appupdate.check("http://127.0.0.1:1/nope", timeout=1, fallback=False)

    def test_fallback_reads_the_releases_page(self):
        from unittest import mock
        with FakeNexus() as fake:
            host = fake.base.replace("/v1", "")
            with mock.patch.object(appupdate, "RELEASES_PAGE", host + "/redirect/latest"):
                fake.state["redirect_to"] = "/lordfulger/SkyrimDownloaded/releases/tag/v2.1.0"
                found = appupdate.check("http://127.0.0.1:1/nope", current="1.9.0", timeout=2)
                self.assertEqual(found.version, "2.1.0")
                self.assertTrue(found.exe_url.endswith("/download/v2.1.0/SkyrimDownloaded.exe"))


@unittest.skipUnless(__import__("sys").platform == "win32", "Windows only")
class WindowsSwapTests(unittest.TestCase):
    def test_swap_waits_for_the_app_then_replaces_it(self):
        import subprocess
        import sys
        import tempfile
        import time
        from pathlib import Path
        folder = Path(tempfile.mkdtemp())
        old, new = folder / "SkyrimDownloaded.exe", folder / "SkyrimDownloaded.update.exe"
        old.write_text("old version")
        new.write_text("new version")
        app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])  # stands in for the app
        started = time.monotonic()
        swap = appupdate.start_swap(new, old, app.pid, start_after=False)
        swap.wait(timeout=60)
        app.wait()
        self.assertGreater(time.monotonic() - started, 2.5)   # it waited for the app to close
        self.assertEqual(old.read_text(), "new version")
        self.assertFalse(new.exists())


if __name__ == "__main__":
    unittest.main()
