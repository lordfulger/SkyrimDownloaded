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

    def test_portable_and_installer_files(self):
        with FakeNexus() as fake:
            url = fake.base.replace("/v1", "") + "/repos/x/y/releases/latest"
            found = appupdate.check(url, current="1.0.0")
        self.assertTrue(found.exe_url.endswith("v9.9.9.exe"))          # the single .exe, not the installer
        self.assertEqual((found.sha256, found.size), ("ab" * 32, 1234))
        self.assertTrue(found.setup_url.endswith("-setup.exe"))
        self.assertEqual((found.setup_sha256, found.setup_size), ("cd" * 32, 5678))
        self.assertFalse(appupdate.is_installed())                     # running from source

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
            self.assertFalse(path.exists())  # the bad one replaced and then removed it
            self.assertFalse((folder / ".skyrimdl-partial").exists())
            # No checksum to check: only a real program is accepted.
            unknown = appupdate.NewVersion("9.9.10", "page", url, "", None)
            with self.assertRaises(ValueError):
                appupdate.download_update(unknown, folder)

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
        folder = Path(tempfile.mkdtemp(prefix="with space "))  # user names with spaces
        old, new = folder / "SkyrimDownloaded.exe", folder / "SkyrimDownloaded.update.exe"
        spaced_temp = folder / "Temp Dir"
        spaced_temp.mkdir()
        self.addCleanup(setattr, tempfile, "tempdir", tempfile.tempdir)
        tempfile.tempdir = str(spaced_temp)
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


    def test_install_runs_the_installer_after_the_app_closes(self):
        import subprocess
        import sys
        import tempfile
        import time
        from pathlib import Path
        from unittest import mock
        folder = Path(tempfile.mkdtemp(prefix="with space "))
        marker = folder / "ran.txt"
        setup = folder / "fake setup.cmd"  # stands in for SkyrimDownloadedSetup.exe
        setup.write_text(f'@echo %* > "{marker}"\r\n', encoding="ascii")
        app_exe = folder / "reopened.cmd"   # stands in for the installed app
        reopened = folder / "reopened.txt"
        app_exe.write_text(f'@echo yes > "{reopened}"\r\n', encoding="ascii")
        app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
        with mock.patch.object(appupdate, "running_exe", return_value=app_exe):
            proc = appupdate.start_install(setup, app.pid, silent=True)
        proc.wait(timeout=60)
        app.wait()
        for _ in range(20):
            if reopened.exists():
                break
            time.sleep(0.5)
        self.assertIn("/VERYSILENT", marker.read_text())
        self.assertTrue(reopened.exists())


if __name__ == "__main__":
    unittest.main()
