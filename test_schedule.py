"""Unit tests for the schedule helpers — stdlib unittest, no dependencies.

Run: python3 -m unittest discover -p "test_*.py"
"""
import unittest

from watcher import cron_schedule


class CronScheduleTests(unittest.TestCase):
    def test_sub_hour_uses_step(self):
        self.assertEqual(cron_schedule(15), "*/15 * * * *")
        self.assertEqual(cron_schedule(30), "*/30 * * * *")
        self.assertEqual(cron_schedule(45), "*/45 * * * *")

    def test_whole_hours_use_hour_field(self):
        # the bug this guards: minutes>=60 must NOT become */1 (every minute)
        self.assertEqual(cron_schedule(60), "0 */1 * * *")
        self.assertEqual(cron_schedule(120), "0 */2 * * *")
        self.assertEqual(cron_schedule(180), "0 */3 * * *")

    def test_non_whole_over_hour_falls_back_to_hourly(self):
        # cron's */N can't express N>=60 without minute drift -> hourly
        self.assertEqual(cron_schedule(90), "0 * * * *")
        self.assertEqual(cron_schedule(100), "0 * * * *")

    def test_zero_and_negative_floor_to_one_minute(self):
        self.assertEqual(cron_schedule(0), "*/1 * * * *")
        self.assertEqual(cron_schedule(-5), "*/1 * * * *")


if __name__ == "__main__":
    unittest.main()
