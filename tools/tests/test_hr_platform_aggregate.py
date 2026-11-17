#!/usr/bin/env python3
"""Aggregated, read-only HR conversation reads across four platforms.

All rows are fictional and the browser helpers are replaced with fakes.  No
tab is opened, nothing is sent and no conversation text reaches disk.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
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

import backend  # noqa: E402
import offerpilot_runtime as runtime  # noqa: E402


def _row(platform: str, suffix: str) -> dict:
    return {
        "id": hashlib.sha256(f"{platform}:{suffix}".encode("utf-8")).hexdigest()[:32],
        "platform": platform,
        "company": f"虚构{platform}公司",
        "title": "产品经理",
        "hr_name": f"{platform}招聘官",
        "hr_title": "HR",
        "last_message": "你好",
        "last_message_at": "11-16 10:00",
        "unread": False,
        "job_id": None,
    }


def _listing(platform: str, count: int = 1) -> dict:
    rows = [_row(platform, str(index)) for index in range(count)]
    return {
        "ok": True,
        "available": True,
        "platform": platform,
        "conversations": rows,
        "count": len(rows),
    }


class AggregateRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)

    def _aggregate(self, boss, platforms):
        with patch.object(runtime, "_list_boss_conversations", side_effect=boss), patch.object(
            runtime, "_list_platform_conversations", side_effect=platforms
        ):
            return runtime.list_conversations("all")

    def test_all_four_platforms_are_merged_with_platform_fields(self):
        def platform_reader(platform):
            return _listing(platform, 2 if platform == "zhilian" else 1)

        result = self._aggregate(lambda: _listing("boss", 1), platform_reader)
        self.assertTrue(result["ok"])
        self.assertTrue(result["available"])
        self.assertEqual(result["platform"], "all")
        self.assertEqual(result["count"], 5)
        self.assertEqual(
            [row["platform"] for row in result["conversations"]],
            ["boss", "zhilian", "zhilian", "51job", "liepin"],
        )
        self.assertEqual(
            [row["platform"] for row in result["platforms"]],
            ["boss", "zhilian", "51job", "liepin"],
        )
        self.assertTrue(all(row["available"] for row in result["platforms"]))
        self.assertNotIn("errors", result)

    def test_one_platform_failure_keeps_the_other_three(self):
        def platform_reader(platform):
            if platform == "zhilian":
                raise runtime.OfferPilotUnavailable("智联未登录")
            return _listing(platform)

        result = self._aggregate(lambda: _listing("boss"), platform_reader)
        self.assertTrue(result["available"])
        self.assertEqual(result["count"], 3)
        self.assertEqual([row["platform"] for row in result["conversations"]], ["boss", "51job", "liepin"])
        self.assertEqual(result["errors"]["zhilian"], "智联未登录")
        zhilian = next(row for row in result["platforms"] if row["platform"] == "zhilian")
        self.assertFalse(zhilian["available"])
        self.assertEqual(zhilian["count"], 0)
        self.assertEqual(zhilian["error"], "智联未登录")

    def test_all_platforms_failing_reports_unavailable(self):
        def platform_reader(platform):
            raise runtime.OfferPilotUnavailable(f"{platform} 未登录")

        result = self._aggregate(
            lambda: (_ for _ in ()).throw(runtime.OfferPilotUnavailable("BOSS 未登录")),
            platform_reader,
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["available"])
        self.assertEqual(result["conversations"], [])
        self.assertIn("所有平台都未能读取会话", result["error"])
        for label in ("BOSS 直聘", "智联招聘", "前程无忧", "猎聘"):
            self.assertIn(label, result["error"])

    def test_unexpected_reader_error_is_isolated(self):
        def platform_reader(platform):
            if platform == "liepin":
                raise KeyError("broken dom")
            return _listing(platform)

        result = self._aggregate(lambda: _listing("boss"), platform_reader)
        self.assertTrue(result["available"])
        self.assertEqual(result["count"], 3)
        self.assertIn("KeyError", result["errors"]["liepin"])

    def test_aggregate_remembers_every_platform_for_thread_lookup(self):
        result = self._aggregate(
            lambda: _listing("boss"), lambda platform: _listing(platform)
        )
        ids = [row["id"] for row in result["conversations"]]
        self.assertEqual(len(set(ids)), 4)
        for conversation_id in ids:
            entry = runtime._cached_conversation(conversation_id)
            self.assertIn(entry["platform"], runtime.CHAT_PLATFORMS)

    def test_thread_platform_all_resolves_from_the_cached_list(self):
        entry = {**_row("liepin", "x"), "id": "a" * 32}
        with patch.object(runtime, "_cached_conversation", return_value=entry), patch.object(
            runtime, "_get_liepin_thread", return_value={"ok": True}
        ) as thread:
            runtime.get_thread("a" * 32, "all")
        thread.assert_called_once()
        self.assertEqual(thread.call_args.args, (entry,))

    def test_thread_platform_all_still_rejects_a_mismatched_explicit_platform(self):
        entry = {**_row("zhilian", "x"), "id": "b" * 32}
        with patch.object(runtime, "_cached_conversation", return_value=entry):
            with self.assertRaises(ValueError):
                runtime.get_thread("b" * 32, "liepin")


class _FakeGuard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _FakeMonitor:
    MonitorSafetyGuard = _FakeGuard

    def __init__(self) -> None:
        self.scripts: list[str] = []

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        return "tab"

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def _monitor_safety_guard(self, config):
        return _FakeGuard()

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        return None

    def evaluate(self, target_id, script):
        self.scripts.append(script)
        if script == runtime.JS_LIEPIN_ENSURE_DRAWER:
            return json.dumps({"available": True})
        if script == runtime.JS_LIEPIN_CHAT_LIST:
            return json.dumps({
                "available": True,
                "rows": [{
                    "company": "虚构猎聘公司",
                    "hr_name": "示例招聘官",
                    "hr_title": "HR",
                    "last_message": "你好",
                    "last_message_at": "11-16 10:00",
                    "has_unread": True,
                }],
            }, ensure_ascii=False)
        if "target.click()" in script:
            return json.dumps({"available": True})
        if script == runtime.JS_LIEPIN_THREAD:
            return json.dumps({
                "available": True,
                "rows": [{"sender": "hr", "text": "你好"}, {"sender": "me", "text": "您好"}],
            }, ensure_ascii=False)
        return json.dumps({"available": True})


class ThreadMessagePlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)
        server = MagicMock()
        server.CONFIG_PATH = Path("config.yaml")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(runtime, "load_backend", return_value=server),
            patch.object(runtime, "_monitor", return_value=_FakeMonitor()),
            patch.object(runtime, "_runtime_config", return_value=self.config),
            patch.object(runtime, "_store_jobs", return_value=[]),
            patch.object(runtime, "_stop_requested", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_platform_thread_messages_carry_platform_and_can_open_with_all(self):
        listing = runtime.list_conversations("liepin")
        conversation_id = listing["conversations"][0]["id"]
        thread = runtime.get_thread(conversation_id, "all")
        self.assertEqual(thread["platform"], "liepin")
        self.assertTrue(thread["available"])
        self.assertEqual([message["platform"] for message in thread["messages"]], ["liepin", "liepin"])
        self.assertFalse(thread["reply_allowed"])


class BackendAggregateDispatchTests(unittest.TestCase):
    def test_backend_passes_all_to_the_runtime(self):
        payload = {
            "ok": True,
            "available": True,
            "platform": "all",
            "conversations": [_row("boss", "1")],
            "count": 1,
        }
        with patch.object(runtime, "cached_conversations", return_value=payload) as listing:
            result = backend.get_offerpilot_conversations("user", "all")
        listing.assert_called_once_with("all")
        self.assertEqual(result["platform"], "all")

    def test_backend_thread_all_is_passed_through(self):
        payload = {"ok": True, "available": True, "platform": "zhilian", "messages": []}
        with patch.object(runtime, "get_thread", return_value=payload) as thread:
            backend.get_offerpilot_conversation("user", "a" * 32, "all")
        thread.assert_called_once_with("a" * 32, "all")

    def test_mode_is_ignored_for_aggregate_reads(self):
        """``mode`` is a compatibility field; "demo" still reads the local runtime."""
        payload = {"ok": True, "available": True, "platform": "all", "conversations": [], "count": 0}
        with patch.object(runtime, "cached_conversations", return_value=payload) as listing:
            result = backend.get_offerpilot_conversations("demo", "all")
        listing.assert_called_once_with("all")
        self.assertEqual(result["platform"], "all")
        self.assertTrue(result["available"])

    def test_unknown_platform_is_still_rejected(self):
        with self.assertRaises(backend.ApiError):
            backend.get_offerpilot_conversations("user", "xiaoyuan")


if __name__ == "__main__":
    unittest.main()
