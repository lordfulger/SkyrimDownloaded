import unittest

from skyrimdl.engine import Job
from skyrimdl.selection import FileOption, human_time


class SpeedTests(unittest.TestCase):
    def test_speed_and_time_left(self):
        opt = FileOption(file_id=1, name="x", file_name="x.7z", version="1", category=1, size_bytes=100_000_000)
        job = Job(plan=None, option=opt, total_bytes=100_000_000)
        job.track(0, now=0.0)
        job.done_bytes = 10_000_000
        job.track(10_000_000, now=1.0)            # 10 MB/s
        self.assertAlmostEqual(job.speed, 10_000_000)
        self.assertAlmostEqual(job.seconds_left, 9.0)
        job.done_bytes = 30_000_000
        job.track(30_000_000, now=2.0)            # 20 MB/s now, smoothed
        self.assertAlmostEqual(job.speed, 13_000_000)
        job.track(30_100_000, now=2.1)            # too soon to count
        self.assertAlmostEqual(job.speed, 13_000_000)

    def test_human_time(self):
        self.assertEqual([human_time(x) for x in (5, 59, 61, 3599, 3725, None)],
                         ["5 s", "59 s", "1 min", "59 min", "1 h 2 min", "?"])


if __name__ == "__main__":
    unittest.main()
