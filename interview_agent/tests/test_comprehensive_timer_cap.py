"""作答窗口上限：人走开、页面放着不管，不能把一整天算进有效作答时长。"""

import unittest
from pathlib import Path

from interview_agent import comprehensive_policy as policy


class TimerCapTests(unittest.TestCase):
    def open_timer(self):
        return policy.open_candidate_window(policy.create_timer_state(30), 1000.0)

    def test_open_window_is_capped_while_ticking(self):
        timer = self.open_timer()
        self.assertEqual(policy.get_active_elapsed_seconds(timer, 1000.0 + 120), 120)
        self.assertEqual(policy.get_active_elapsed_seconds(timer, 1000.0 + 23 * 3600), policy.MAX_WINDOW_SECONDS)
        self.assertEqual(policy.get_remaining_seconds(timer, 1000.0 + 23 * 3600), 30 * 60 - policy.MAX_WINDOW_SECONDS)

    def test_freeze_after_a_long_absence_adds_only_the_cap(self):
        timer = policy.freeze_candidate_window(self.open_timer(), 1000.0 + 23 * 3600, "model_streaming")
        self.assertEqual(timer["active_elapsed_seconds"], policy.MAX_WINDOW_SECONDS)
        self.assertIsNone(timer["window_opened_at"])

    def test_normal_answers_are_counted_exactly(self):
        timer = policy.freeze_candidate_window(self.open_timer(), 1000.0 + 45, "model_streaming")
        timer = policy.open_candidate_window(timer, 2000.0)
        timer = policy.freeze_candidate_window(timer, 2000.0 + 80, "model_streaming")
        self.assertEqual(policy.get_active_elapsed_seconds(timer), 125)


class TimerBadgeTests(unittest.TestCase):
    def test_badge_says_time_is_up_instead_of_zero_remaining(self):
        js = (Path(__file__).resolve().parents[2] / "web/static/comprehensive-interview.js").read_text(encoding="utf-8")
        self.assertIn("时间已到", js)
        self.assertNotIn("还剩 ${formatDuration(remaining)}${frozenText}", js)


if __name__ == "__main__":
    unittest.main()
