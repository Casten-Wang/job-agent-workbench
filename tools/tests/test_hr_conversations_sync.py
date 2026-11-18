#!/usr/bin/env python3
"""Cached conversation reads, the summary, and background sync.

All names, companies and ids are fictional.  No browser is opened and no
platform is contacted: ``list_conversations`` is replaced in every test that
runs the worker.

Contracts locked here:

- ``cached_conversations`` serves the stored rows and never reads a platform;
- ``conversations_summary`` counts unread messages from local storage only;
- one worker per platform runs in parallel across platforms while the same
  platform is never queued twice;
- a platform synced moments ago is skipped instead of read again, and a
  platform whose last sync failed is retried;
- a failed platform keeps its error and fresh timestamp in the summary;
- the HTTP routes exist and pass the platform through.
"""

from __future__ import annotations

import datetime
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import offerpilot_runtime as runtime  # noqa: E402
import server as web_server  # noqa: E402


def _record(platform: str, suffix: str, *, unread: int = 0, source: str = "api") -> dict:
    return {
        "platform": platform,
        "id": (suffix * 32)[:32],
        "company": f"虚构公司{suffix}",
        "title": "产品经理",
        "hr_name": f"示例招聘官{suffix}",
        "hr_title": "招聘",
        "job_id": None,
        "last_message_at": "11-16 10:20",
        "last_message": "你好，方便沟通吗",
        "unread": bool(unread),
        "unread_count": unread,
        "last_direction": "hr",
        "has_reply": True,
        "source": source,
        "messages": [{"sender": "hr", "text": "你好", "time": "11-16 10:20", "mid": "101"}],
        "body_read": True,
        "signature": "sig",
        "fetched_at": "2026-11-16T02:20:00+00:00",
        "stale": False,
        "error": None,
    }


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hr-sync-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.object(runtime, "_hr_store_root", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        with runtime._hr_store_lock:
            runtime._save_hr_store({
                "boss:aaa": _record("boss", "a", unread=2),
                "boss:bbb": _record("boss", "b"),
                "liepin:ccc": _record("liepin", "c", unread=1, source="dom"),
            })
        self._reset_sync_state()
        self.addCleanup(self._reset_sync_state)

    def _reset_sync_state(self) -> None:
        with runtime._sync_state_lock:
            runtime._sync_queue.clear()
            runtime._sync_queued.clear()
            runtime._sync_threads.clear()
            runtime._sync_state.update(
                syncing=False, platform=None, started_at=None,
                finished_at=None, error=None, platforms=[],
            )

    def _mark_listed_in_this_process(self, platform: str) -> None:
        with runtime._conversation_cache_lock:
            runtime._conversation_listed_at_by_platform[platform] = time.monotonic()
        self.addCleanup(runtime._reset_conversation_cache)

    def _wait_idle(self, timeout: float = 3.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not runtime.conversations_summary()["syncing"]:
                return
            time.sleep(0.02)
        self.fail("background sync did not finish")


class CachedListTests(_StoreCase):
    def test_cached_list_serves_the_store_without_reading_a_platform(self):
        with patch.object(runtime, "list_conversations") as live:
            result = runtime.cached_conversations("all")
        live.assert_not_called()
        self.assertTrue(result["available"])
        self.assertEqual(result["count"], 3)
        boss = [row for row in result["conversations"] if row["platform"] == "boss"]
        self.assertEqual(len(boss), 2)
        self.assertEqual(boss[0]["unread_count"] + boss[1]["unread_count"], 2)
        self.assertTrue(all(row["has_body"] for row in result["conversations"]))
        self.assertEqual(
            {row["source"] for row in result["conversations"]}, {"api", "dom"}
        )
        self.assertFalse(result["syncing"])

    def test_a_single_platform_filter_and_51job_refusal(self):
        boss = runtime.cached_conversations("boss")
        self.assertEqual(boss["count"], 2)
        fiftyone = runtime.cached_conversations("51job")
        self.assertFalse(fiftyone["available"])
        self.assertIn("没有站内聊天", fiftyone["error"])


class SummaryTests(_StoreCase):
    def test_summary_counts_from_local_storage_only(self):
        with patch.object(runtime, "list_conversations") as live:
            summary = runtime.conversations_summary()
        live.assert_not_called()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["unread_total"], 3)
        self.assertEqual(summary["by_platform"]["boss"]["count"], 2)
        self.assertEqual(summary["by_platform"]["boss"]["unread"], 2)
        self.assertEqual(summary["by_platform"]["liepin"]["unread"], 1)
        self.assertEqual(summary["by_platform"]["liepin"]["source"], "dom")
        self.assertEqual(summary["by_platform"]["zhilian"]["count"], 0)
        self.assertIsNone(summary["last_synced_at"])

    def test_mixed_sources_stay_json_serializable(self):
        with runtime._hr_store_lock:
            store = runtime._load_hr_store()
            store["boss:ddd"] = _record("boss", "d", source="dom")
            runtime._save_hr_store(store)
        summary = runtime.conversations_summary()
        self.assertIsNone(summary["by_platform"]["boss"]["source"])
        json.dumps(summary, ensure_ascii=False)

    def test_summary_reports_the_last_sync_and_its_error(self):
        with runtime._hr_store_lock:
            runtime._save_sync_meta({
                "boss": {"last_synced_at": "2026-11-17T01:00:00+00:00", "source": "api", "error": None},
                "zhilian": {"last_synced_at": None, "source": None, "error": "读取超时"},
            })
        summary = runtime.conversations_summary()
        self.assertEqual(summary["by_platform"]["boss"]["last_synced_at"], "2026-11-17T01:00:00+00:00")
        self.assertEqual(summary["by_platform"]["zhilian"]["error"], "读取超时")
        self.assertEqual(summary["last_synced_at"], "2026-11-17T01:00:00+00:00")


class SyncQueueTests(_StoreCase):
    def test_the_same_platform_is_not_queued_twice(self):
        release = threading.Event()
        started = []

        def slow(platform):
            started.append(platform)
            release.wait(2)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=slow):
            first = runtime.start_conversations_sync("boss")
            second = runtime.start_conversations_sync("boss")
            self.assertTrue(first["started"])
            self.assertFalse(second["started"])
            release.set()
            self._wait_idle()
        self.assertEqual(started, ["boss"])

    def test_all_queues_the_three_chat_platforms(self):
        release = threading.Event()
        started = []

        def slow(platform):
            started.append(platform)
            release.wait(2)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=slow):
            result = runtime.start_conversations_sync("all")
            self.assertTrue(result["started"])
            self.assertEqual(len(result["queued"]), 3)
            release.set()
            self._wait_idle()
        self.assertEqual(sorted(started), ["boss", "liepin", "zhilian"])

    def test_platforms_are_read_in_parallel(self):
        barrier = threading.Barrier(3, timeout=4)
        failures = []

        def read(platform):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                failures.append(platform)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=read):
            runtime.start_conversations_sync("all")
            self._wait_idle(timeout=8)
        self.assertEqual(failures, [], "each platform waits for the other two, not for a serial queue")

    def test_a_platform_synced_moments_ago_is_skipped(self):
        with runtime._hr_store_lock:
            runtime._save_sync_meta({
                "boss": {"last_synced_at": runtime._hr_now(), "source": "api", "error": None},
            })
        self._mark_listed_in_this_process("boss")
        with patch.object(runtime, "_run_conversations_sync") as read:
            result = runtime.start_conversations_sync("boss")
        self.assertFalse(result["started"])
        self.assertFalse(result["syncing"])
        self.assertEqual(result["skipped"], ["boss"])
        self.assertIn("刚刚同步过", result["reason"])
        read.assert_not_called()

    def test_a_platform_whose_sync_failed_is_retried(self):
        with runtime._hr_store_lock:
            runtime._save_sync_meta({
                "boss": {"last_synced_at": runtime._hr_now(), "source": "api", "error": "上次读取失败"},
            })
        release = threading.Event()
        started = []

        def slow(platform):
            started.append(platform)
            release.wait(2)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=slow):
            result = runtime.start_conversations_sync("boss")
            self.assertTrue(result["started"])
            self.assertNotIn("skipped", result)
            release.set()
            self._wait_idle()
        self.assertEqual(started, ["boss"])

    def test_an_old_sync_is_read_again(self):
        stale = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=runtime.HR_SYNC_MIN_INTERVAL_SECONDS + 1)
        ).isoformat()
        with runtime._hr_store_lock:
            runtime._save_sync_meta({
                "boss": {"last_synced_at": stale, "source": "api", "error": None},
            })
        release = threading.Event()
        started = []

        def slow(platform):
            started.append(platform)
            release.wait(2)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=slow):
            result = runtime.start_conversations_sync("boss")
            self.assertTrue(result["started"])
            release.set()
            self._wait_idle()
        self.assertEqual(started, ["boss"])

    def test_all_skips_only_the_platforms_synced_moments_ago(self):
        with runtime._hr_store_lock:
            runtime._save_sync_meta({
                "boss": {"last_synced_at": runtime._hr_now(), "source": "api", "error": None},
            })
        self._mark_listed_in_this_process("boss")
        release = threading.Event()
        started = []

        def slow(platform):
            started.append(platform)
            release.wait(2)
            return {}

        with patch.object(runtime, "_run_conversations_sync", side_effect=slow):
            result = runtime.start_conversations_sync("all")
            self.assertEqual(result["skipped"], ["boss"])
            self.assertEqual(sorted(result["queued"]), ["liepin", "zhilian"])
            release.set()
            self._wait_idle()
        self.assertEqual(sorted(started), ["liepin", "zhilian"])


class SyncWorkerTests(_StoreCase):
    def test_a_successful_sync_records_freshness_and_marks_the_source(self):
        payload = {
            "ok": True, "available": True, "platform": "boss",
            "conversations": [], "count": 0, "source": "api",
        }
        with patch.object(runtime, "list_conversations", return_value=payload):
            runtime.start_conversations_sync("boss")
            self._wait_idle()
        summary = runtime.conversations_summary()
        self.assertIsNotNone(summary["by_platform"]["boss"]["last_synced_at"])
        self.assertEqual(summary["by_platform"]["boss"]["source"], "api")
        self.assertIsNone(summary["by_platform"]["boss"].get("error"))

    def test_a_failed_sync_keeps_the_error_without_stopping_the_queue(self):
        calls = []

        def read(platform):
            calls.append(platform)
            if platform == "boss":
                raise RuntimeError("接口不可用")
            return {"ok": True, "available": True, "platform": platform, "conversations": [], "count": 0, "source": "dom"}

        with patch.object(runtime, "list_conversations", side_effect=read):
            runtime.start_conversations_sync("all")
            self._wait_idle()
        self.assertEqual(sorted(calls), ["boss", "liepin", "zhilian"])
        summary = runtime.conversations_summary()
        self.assertIn("接口不可用", summary["by_platform"]["boss"]["error"])
        self.assertIsNone(summary["by_platform"]["boss"]["last_synced_at"])
        self.assertIsNotNone(summary["by_platform"]["zhilian"]["last_synced_at"])


class BackendCacheTests(_StoreCase):
    def test_the_list_route_reads_the_cache(self):
        payload = {"ok": True, "available": True, "platform": "boss", "conversations": [], "count": 0, "syncing": False}
        with patch.object(runtime, "cached_conversations", return_value=payload) as cached:
            result = backend.get_offerpilot_conversations("user", "boss")
        cached.assert_called_once_with("boss")
        self.assertTrue(result["ok"])

    def test_sync_validates_the_platform(self):
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_conversations_sync({"platform": "xiaoyuan"})
        with patch.object(runtime, "start_conversations_sync", return_value={"ok": True, "started": True}) as start:
            backend.start_offerpilot_conversations_sync({"platform": "all"})
        start.assert_called_once_with("all")


class HttpRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = web_server.make_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.02)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str, payload: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
            connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_summary_route(self):
        payload = {"ok": True, "total": 0, "unread_total": 0, "by_platform": {}, "last_synced_at": None}
        with patch.object(backend, "get_offerpilot_conversations_summary", return_value=payload) as summary:
            status, body = self.request("GET", "/api/offerpilot/conversations/summary?mode=user")
        self.assertEqual(status, 200)
        self.assertEqual(body, payload)
        summary.assert_called_once_with("user")

    def test_sync_route_returns_202_and_starts_one_sync(self):
        payload = {"ok": True, "started": True, "syncing": True, "platform": "boss"}
        with patch.object(backend, "start_offerpilot_conversations_sync", return_value=payload) as start:
            status, body = self.request("POST", "/api/offerpilot/conversations/sync", {"platform": "boss"})
        self.assertEqual(status, 202)
        self.assertEqual(body, payload)
        start.assert_called_once_with({"platform": "boss"})


if __name__ == "__main__":
    unittest.main()


class RestartIncrementalTests(_StoreCase):
    """A restart clears memory only; the stored bodies and signatures decide what is read."""

    def _listing(self, suffix: str, *, last_message: str, at: str, direction: str = "hr", unread: int = 0) -> dict:
        row = _record("boss", suffix, unread=unread)
        row.update(last_message=last_message, last_message_at=at, last_direction=direction, source="api")
        for key in ("messages", "body_read", "signature", "fetched_at", "stale", "error"):
            row.pop(key, None)
        return row

    def _store_current_bodies(self, rows: list[dict]) -> None:
        with runtime._hr_store_lock:
            store = {}
            for row in rows:
                signature = runtime._hr_signature(row)
                record = _record("boss", row["id"][0], unread=0)
                record.update(
                    id=row["id"], last_message=row["last_message"], last_message_at=row["last_message_at"],
                    signature=signature, body_signature=signature, body_read=True,
                )
                store[runtime._hr_store_key(row)] = record
            runtime._save_hr_store(store)

    def test_an_unchanged_listing_after_a_restart_reads_no_conversation(self):
        rows = [self._listing("a", last_message="你好", at="11-16 10:20"),
                self._listing("b", last_message="方便聊聊吗", at="11-16 11:00")]
        self._store_current_bodies(rows)
        self._reset_sync_state()  # the "restart": in-memory state is gone, files stay
        with patch.object(runtime, "_background_read_possible", return_value=True), \
                patch.object(runtime, "_fetch_thread_body") as fetch:
            runtime._refresh_platform_store(rows, "boss", source="api")
        fetch.assert_not_called()
        kept = runtime._load_hr_store()
        self.assertEqual(len(kept), 2)
        for record in kept.values():
            self.assertTrue(record["messages"])
            self.assertFalse(record.get("stale"))

    def test_only_the_conversation_with_a_new_hr_message_is_read_and_old_messages_survive(self):
        rows = [self._listing("a", last_message="你好", at="11-16 10:20"),
                self._listing("b", last_message="方便聊聊吗", at="11-16 11:00")]
        self._store_current_bodies(rows)
        self._reset_sync_state()
        changed = [rows[0], self._listing("b", last_message="明天下午面试可以吗", at="11-17 09:00", unread=1)]
        new_message = {"sender": "hr", "text": "明天下午面试可以吗", "time": "11-17 09:00", "mid": "102"}
        with patch.object(runtime, "_background_read_possible", return_value=True), \
                patch.object(runtime, "_fetch_thread_body", return_value={"ok": True, "messages": [
                    {"sender": "hr", "text": "你好", "time": "11-16 10:20", "mid": "101"}, new_message,
                ]}) as fetch:
            runtime._refresh_platform_store(changed, "boss", source="api")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0]["id"], changed[1]["id"])
        store = runtime._load_hr_store()
        untouched = store[runtime._hr_store_key(rows[0])]
        self.assertEqual([m["mid"] for m in untouched["messages"]], ["101"])
        merged = store[runtime._hr_store_key(changed[1])]
        self.assertEqual([m["mid"] for m in merged["messages"]], ["101", "102"])

    def test_the_cooldown_survives_a_restart(self):
        runtime._save_sync_meta({"boss": {"last_synced_at": runtime._hr_now(), "source": "api", "error": None}})
        self._reset_sync_state()  # the "restart"
        self.assertTrue(runtime._recently_synced(runtime._load_sync_meta()["boss"]))

    def test_after_a_restart_a_fresh_disk_record_still_reads_once_so_replies_can_be_sent(self):
        # 磁盘上的冷却很新，但本进程内存里没有「最近列表」：发送回复要用它，所以必须读一次。
        runtime._reset_conversation_cache()
        runtime._save_sync_meta({"boss": {"last_synced_at": runtime._hr_now(), "source": "api", "error": None}})
        with patch.object(runtime, "_run_conversations_sync") as read:
            result = runtime.start_conversations_sync("boss")
            self._wait_idle()
        self.assertTrue(result["started"])
        read.assert_called_once_with("boss")
