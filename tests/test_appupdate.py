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
            fake.state["latest_tag"] = "v1.6.1"
            self.assertIsNone(appupdate.check(url, current="1.6.1"))
            self.assertIsNone(appupdate.check(url, current="1.10.0"))   # compares numbers, not text

    def test_offline_is_quiet(self):
        self.assertIsNone(appupdate.check("http://127.0.0.1:1/nope", timeout=1))


if __name__ == "__main__":
    unittest.main()
