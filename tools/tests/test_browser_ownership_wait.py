#!/usr/bin/env python3
"""浏览器所有权锁：短调用可以排队等待，长工作流占用时仍然报忙。

背景：HR 会话同步按平台并行启动，每个线程的第一步都是 ``_ready()``。
非阻塞抢锁会让后到的平台直接报「浏览器正由其他后台任务使用」，导致智联/猎聘读不到。
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot.browser import ownership  # noqa: E402


class OwnershipWaitTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ownership, "get_runtime_url", return_value="http://test.invalid/ownership-wait")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _hold(self, seconds):
        started = threading.Event()

        def run():
            with ownership.browser_execution():
                started.set()
                time.sleep(seconds)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(started.wait(2))
        return thread

    def test_without_wait_a_busy_browser_fails_at_once(self):
        thread = self._hold(0.4)
        with self.assertRaises(ownership.BrowserBusyError):
            with ownership.browser_execution():
                pass
        thread.join()

    def test_with_wait_a_short_holder_is_queued_behind(self):
        thread = self._hold(0.3)
        with ownership.browser_execution(wait=3):
            pass
        thread.join()

    def test_with_wait_a_long_holder_still_ends_in_busy(self):
        thread = self._hold(1.2)
        with self.assertRaises(ownership.BrowserBusyError):
            with ownership.browser_execution(wait=0.3):
                pass
        thread.join()


if __name__ == "__main__":
    unittest.main()
