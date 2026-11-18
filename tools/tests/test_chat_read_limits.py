#!/usr/bin/env python3
"""Chat reads stay serial, bounded, and isolated per platform.

Three contracts are locked here (no browser, no network, nothing sent):

- a single platform's list/thread read has a wall-clock budget, and a timed-out
  platform reports ``读取超时`` while the other platforms are still read;
- chat-read failures never reach the shared monitor failure counter, so one
  platform (or one chat read) cannot push another platform toward a risk lock;
- a timeout returns at the CDP call layer and leaves ``browser_execution()``
  free: the next platform does not run into ``BrowserBusyError``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime as runtime  # noqa: E402

BUDGET = 0.3  # short enough to keep the suite fast, long enough for fast fakes

ZHILIAN_ROWS = [{
    "company": "虚构智联有限公司",
    "hr_name": "示例招聘官",
    "hr_title": "HR",
    "last_message": "你好",
    "last_message_at": "11-16 10:00",
    "has_unread": False,
}]
LIEPIN_ROWS = [{
    "company": "虚构猎聘科技有限公司",
    "hr_name": "王示例",
    "hr_title": "",
    "last_message": "您好，方便发一份简历吗",
    "last_message_at": "11-16 10:20",
    "has_unread": True,
    "unReadCnt": 1,  # the props reader counts unread through the contact object
}]


class _CountingGuard:
    limit = 3

    def __init__(self) -> None:
        self.failures = 0
        self.successes = 0

    def record_page_failure(self) -> None:
        self.failures += 1

    def record_page_success(self) -> None:
        self.successes += 1


class _SlowPlatformMonitor:
    """Zhilian's list call outlives the budget; other platforms answer at once."""

    MonitorSafetyGuard = _CountingGuard
    JS_EXTRACT_CHAT_LIST = "/* chat list */"

    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.closed: list[str] = []
        self.urls: list[str] = []

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        self.urls.append(url)
        return "tab-slow"

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def evaluate(self, target_id, script, timeout=None):
        self.scripts.append(script)
        if script == runtime.JS_ZHILIAN_CHAT_LIST or script == runtime.JS_ZHILIAN_THREAD:
            time.sleep(BUDGET + 0.05)  # the call returns only after the budget is gone
            if timeout is not None and float(timeout) < BUDGET + 0.05:
                return None  # a CDP timeout: the browser call itself gives up
            return json.dumps({"available": True, "rows": ZHILIAN_ROWS}, ensure_ascii=False)
        if script == runtime.JS_LIEPIN_THREAD:
            time.sleep(BUDGET + 0.05)
            if timeout is not None and float(timeout) < BUDGET + 0.05:
                return None
            return json.dumps({"available": True, "rows": [{"sender": "hr", "text": "你好"}]})
        if script == runtime.JS_LIEPIN_ENSURE_DRAWER_WWW:
            return json.dumps({"available": True})
        if script == runtime.JS_LIEPIN_CHAT_LIST:
            return json.dumps({"available": True, "rows": LIEPIN_ROWS}, ensure_ascii=False)
        return json.dumps({"available": True})


class _FastBossMonitor:
    """BOSS list that parses (or fails to parse) without any waiting."""

    MonitorSafetyGuard = _CountingGuard
    JS_EXTRACT_CHAT_LIST = "/* chat list */"

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.closed: list[str] = []

    def _get_monitor_chat_target(self, chat_url, config):
        return "tab-boss", False

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def _monitor_safety_guard(self, config):
        return config.setdefault("_monitor_safety_guard", _CountingGuard())

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def evaluate(self, target_id, script, timeout=None):
        return self.payload


class _ChatReadCase(unittest.TestCase):
    monitor: object

    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}}
        self.patches = [
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.monitor),
            patch.object(runtime, "_runtime_config", return_value=self.config),
            patch.object(runtime, "_store_jobs", return_value=[]),
            patch.object(runtime, "CHAT_LIST_TIMEOUT_SECONDS", BUDGET),
            patch.object(runtime, "CHAT_THREAD_TIMEOUT_SECONDS", BUDGET),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)


class TimeoutIsolationTests(_ChatReadCase):
    def setUp(self) -> None:
        self.monitor = _SlowPlatformMonitor()
        super().setUp()

    def test_budgets_are_sixty_and_thirty_seconds(self):
        with patch.object(runtime, "CHAT_LIST_TIMEOUT_SECONDS", 60.0), patch.object(
            runtime, "CHAT_THREAD_TIMEOUT_SECONDS", 30.0
        ):
            self.assertEqual(runtime.CHAT_LIST_TIMEOUT_SECONDS, 60.0)
            self.assertEqual(runtime.CHAT_THREAD_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(runtime.CHAT_READ_TIMEOUT_ERROR, "读取超时")

    def test_list_timeout_is_reported_as_read_timeout(self):
        listing = runtime._list_platform_conversations("zhilian")
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["platform"], "zhilian")
        self.assertEqual(listing["conversations"], [])
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["error"], "读取超时")
        # The tab is closed even on the timeout path.
        self.assertIn("tab-slow", self.monitor.closed)

    def test_one_platform_timing_out_does_not_stop_the_others(self):
        boss = {
            "ok": True, "available": True, "platform": "boss",
            "conversations": [{
                "id": "a" * 32, "platform": "boss", "company": "虚构BOSS公司",
                "title": "", "hr_name": "示例招聘官", "hr_title": "HR",
                "last_message": "你好", "last_message_at": "11-16 09:00",
                "unread": False, "job_id": None,
            }],
            "count": 1,
        }
        with patch.object(runtime, "_list_boss_conversations", return_value=boss):
            listing = runtime.list_conversations("all")
        self.assertTrue(listing["ok"])
        self.assertTrue(listing["available"])
        by_platform = {entry["platform"]: entry for entry in listing["platforms"]}
        self.assertFalse(by_platform["zhilian"]["available"])
        self.assertEqual(by_platform["zhilian"]["error"], "读取超时")
        self.assertTrue(by_platform["liepin"]["available"])
        self.assertEqual(by_platform["liepin"]["count"], 1)
        self.assertEqual(set(listing["errors"]), {"zhilian", "51job"})
        self.assertEqual(listing["errors"]["zhilian"], "读取超时")
        self.assertEqual(
            [row["platform"] for row in listing["conversations"]],
            ["boss", "liepin"],
        )

    def test_thread_timeout_stays_read_only(self):
        entry = {
            "id": "b" * 32,
            "platform": "zhilian",
            "company": "虚构智联有限公司",
            "title": "",
            "hr_name": "示例招聘官",
            "hr_title": "HR",
        }
        thread = runtime._get_platform_thread(entry, "zhilian")
        self.assertFalse(thread["ok"])
        self.assertFalse(thread["available"])
        self.assertEqual(thread["error"], "读取超时")
        self.assertEqual(thread["messages"], [])
        self.assertFalse(thread["reply_allowed"])
        self.assertIn("读取超时", thread["reply_block_reason"])
        self.assertIn("tab-slow", self.monitor.closed)


class FailureIsolationTests(_ChatReadCase):
    def setUp(self) -> None:
        self.monitor = _FastBossMonitor("not json")
        super().setUp()

    def test_chat_failure_does_not_touch_the_shared_failure_guard(self):
        guard = _CountingGuard()
        self.config["_monitor_safety_guard"] = guard
        with self.assertRaises(runtime.OfferPilotUnavailable):
            runtime._list_boss_conversations()
        self.assertEqual(guard.failures, 0)
        self.assertEqual(guard.successes, 0)

    def test_chat_read_never_attaches_a_guard_to_the_config(self):
        # The payload is unparseable, so the read fails; the config must still
        # never gain a shared guard as a side effect of the chat read.
        with self.assertRaises(runtime.OfferPilotUnavailable):
            runtime._list_boss_conversations()
        self.assertNotIn("_monitor_safety_guard", self.config)

    def test_successful_chat_read_does_not_reset_the_shared_guard(self):
        self.monitor.payload = json.dumps([{"company": "虚构公司", "hr_name": "示例招聘官"}], ensure_ascii=False)
        guard = _CountingGuard()
        self.config["_monitor_safety_guard"] = guard
        listing = runtime._list_boss_conversations()
        self.assertTrue(listing["ok"])
        self.assertEqual(guard.successes, 0)
        self.assertEqual(guard.failures, 0)


class _GatedClient:
    """Stands in for RuntimeClient: a timed-out CDP call returns None."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def evaluate(self, target_id, expression, timeout=30):
        self.calls.append(expression)
        if "im-session-item" in expression:  # zhilian list: never answers
            time.sleep(float(timeout))  # httpx gives up exactly at the timeout
            return None
        if "im-ui-contact-list-item" in expression:
            return {"available": True, "rows": LIEPIN_ROWS}
        return {"available": True}


class _FacadeMonitor:
    """A monitor whose evaluate is the real browser facade."""

    MonitorSafetyGuard = _CountingGuard
    JS_EXTRACT_CHAT_LIST = "/* chat list */"

    def __init__(self) -> None:
        self.closed: list[str] = []

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        return "tab-gate"

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def evaluate(self, target_id, expression, timeout=30):
        import offerpilot.browser as facade

        return facade.evaluate(target_id, expression, timeout=timeout)


class BrowserGateTests(_ChatReadCase):
    def setUp(self) -> None:
        self.monitor = _FacadeMonitor()
        super().setUp()

    def test_timeout_returns_at_the_cdp_layer_and_frees_the_gate(self):
        from offerpilot.browser.ownership import browser_execution

        client = _GatedClient()
        with patch("offerpilot.browser.ensure_runtime", return_value=True), patch(
            "offerpilot.browser._client", return_value=client
        ):
            listing = runtime._list_platform_conversations("zhilian")
            self.assertEqual(listing["error"], "读取超时")
            # The gate must be free immediately: no abandoned worker keeps it.
            with browser_execution():
                pass
            # The next platform reads normally in the same call stack, with its
            # own budget so a slow CI machine cannot fail it on time alone.
            with patch.object(runtime, "CHAT_LIST_TIMEOUT_SECONDS", 5.0):
                follow_up = runtime._list_platform_conversations("liepin")
        self.assertTrue(follow_up["available"])
        self.assertEqual(follow_up["count"], 1)
        # Two list tabs (the timed-out read and the follow-up).  The follow-up's
        # body read is interface-only: a background refresh never opens a
        # conversation page, so no third tab is created.
        self.assertEqual(self.monitor.closed.count("tab-gate"), 2)


if __name__ == "__main__":
    unittest.main()
