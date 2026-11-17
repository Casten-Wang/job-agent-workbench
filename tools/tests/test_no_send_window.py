#!/usr/bin/env python3
"""No send/collect time window: every hour of the day is open.

The old implementation enforced ``09:00-16:00`` by default and refused a
reply or a delivery outside it.  These tests pin the replacement contract:

- the window checker is active at any hour, including 03:00, even when a
  legacy ``send_windows`` value is still present in configuration;
- the default and example configuration no longer define a window;
- a background task gets no window deadline;
- the reply gate and ``start_deliver_task`` pass at 03:00.

Nothing is sent and no browser is opened.
"""

from __future__ import annotations

import datetime
import sys
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime  # noqa: E402
from offerpilot import config as offerpilot_config  # noqa: E402
from offerpilot import throttle  # noqa: E402
from offerpilot.web import tasks as offerpilot_tasks  # noqa: E402

LEGACY_WINDOW = ["09:00-16:00"]


class _ThreeAM(datetime.datetime):
    """A clock fixed at 03:00, outside every old send window."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 18, 3, 0, 0)


class SendWindowCheckerTests(unittest.TestCase):
    def test_three_am_is_active_even_with_a_legacy_window(self):
        with patch.object(throttle, "datetime", _ThreeAM):
            checker = throttle.SendWindowChecker(LEGACY_WINDOW)
            self.assertTrue(checker.is_active())
            self.assertFalse(checker.latest_end_time_reached())
            self.assertIsNone(checker.latest_end_datetime())
            self.assertEqual(checker.next_window_info(), "无窗口限制")

    def test_an_empty_window_list_behaves_the_same(self):
        checker = throttle.SendWindowChecker([])
        self.assertTrue(checker.is_active())
        self.assertFalse(checker.latest_end_time_reached())
        self.assertIsNone(checker.latest_end_datetime())
        self.assertEqual(checker.next_window_info(), "无窗口限制")


class ConfigDefaultTests(unittest.TestCase):
    def test_default_config_has_no_send_window(self):
        self.assertEqual(offerpilot_config.DEFAULTS["throttle"]["send_windows"], [])

    def test_example_config_has_no_send_window(self):
        text = (PROJECT_ROOT / "vendor" / "offerpilot" / "config.example.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("send_windows: []", text)
        self.assertNotIn("09:00", text)


class TaskDeadlineTests(unittest.TestCase):
    def test_a_task_started_at_three_am_gets_no_window_deadline(self):
        started = threading.Event()
        release = threading.Event()

        def executor(task, config):
            started.set()
            release.wait(5)

        runner = offerpilot_tasks.WorkbenchTaskRunner(executors={"deliver": executor})
        with patch.object(offerpilot_tasks, "datetime", _ThreeAM), patch.object(
            offerpilot_tasks, "browser_execution", lambda: nullcontext()
        ):
            snapshot = runner.start("deliver", {"throttle": {"send_windows": LEGACY_WINDOW}})
        self.assertTrue(started.wait(5), "the task must start at 03:00")
        self.assertEqual(snapshot["status"], "running")
        self.assertIsNone(snapshot["deadline_at"])
        runner.stop(snapshot["id"], "测试结束")
        release.set()
        runner.wait(5)


class RuntimeGateTests(unittest.TestCase):
    def test_reply_gate_is_open_at_three_am(self):
        with patch.object(throttle, "datetime", _ThreeAM), patch.object(
            offerpilot_runtime, "_stop_requested", return_value=False
        ), patch.object(offerpilot_runtime, "_risk_lock_reason", return_value=None):
            allowed, reason = offerpilot_runtime._reply_gate(
                MagicMock(), {"throttle": {"send_windows": LEGACY_WINDOW}}
            )
        self.assertEqual((allowed, reason), (True, None))

    def test_start_deliver_at_three_am_reaches_the_task_runner(self):
        server = MagicMock()
        server.load_config.return_value = {"throttle": {"send_windows": LEGACY_WINDOW}}
        server.get_db.return_value = MagicMock()
        server.job_mutation_lock = nullcontext()
        server.task_runner.start.return_value = {
            "id": "task-1", "mode": "deliver", "status": "running",
        }
        job = {
            "id": "rt-1",
            "status": "ready",
            "greeting": "您好，方便沟通吗？",
            "greeting_selection": "selected",
        }
        with patch.object(offerpilot_runtime, "load_backend", return_value=server), patch(
            "offerpilot.db.query_jobs", return_value=([job], 1)
        ), patch(
            "offerpilot.db.get_active_platform_safety_lock", return_value=None
        ), patch.object(throttle, "datetime", _ThreeAM):
            result = offerpilot_runtime.start_deliver_task(["rt-1"])
        self.assertEqual(result["requested"], 1)
        server.task_runner.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
