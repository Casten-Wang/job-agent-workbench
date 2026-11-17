#!/usr/bin/env python3
"""HR conversation store: incremental refresh, redaction, stale fallback.

Contracts locked here (fictional rows; no browser, no network, nothing sent):

- an unchanged listing signature with a stored body does not open the page;
- a changed conversation is opened once and its new messages are merged
  without duplicating what was already stored;
- a single-platform refresh replaces only that platform's stored records;
- a failed read keeps the stored messages and marks them stale;
- the file lives under ``web/data`` and is written atomically;
- phone, email and WeChat never reach the file;
- the send gate still requires a fresh in-memory listing.
"""

from __future__ import annotations

import json
import os
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

import offerpilot_runtime as runtime  # noqa: E402

FAKE_PHONE = "1" + "3" * 10  # fabricated 11-digit number, not anyone's
CONTACT_TEXT = f"我的电话 {FAKE_PHONE}，邮箱 demo.person@example.com，微信 demo_wechat01"
ROW = {
    "company": "虚构存储科技有限公司",
    "hr_name": "示例招聘官",
    "hr_title": "招聘HR",
    "last_message": "你好，方便沟通吗",
    "last_message_at": "11-16 10:20",
    "has_unread": True,
}


class _Guard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _StoreMonitor:
    """Serves one BOSS list and per-conversation bodies; counts every open."""

    MonitorSafetyGuard = _Guard
    JS_EXTRACT_CHAT_LIST = "js:boss-list"
    JS_EXTRACT_CONVERSATION = "js:boss-thread"

    def __init__(self) -> None:
        self.list_rows = [dict(ROW)]
        self.threads: dict[str, list[dict]] = {}
        self.fail_open: set[str] = set()
        self.opened: list[str] = []
        self.current_hr = ""
        self.closed: list[str] = []

    def _get_monitor_chat_target(self, url, config):
        return "tab-list", False

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        return "tab-list"

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def _monitor_safety_guard(self, config):
        return _Guard()

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def _open_conversation_from_chat_list(self, job, config, *, background=True):
        hr = job.get("hr_name") or ""
        self.opened.append(hr)
        if hr in self.fail_open:
            return None
        self.current_hr = hr
        return "tab-thread"

    def evaluate(self, target_id, script, timeout=None):
        if script == self.JS_EXTRACT_CHAT_LIST:
            return json.dumps(self.list_rows, ensure_ascii=False)
        if script == self.JS_EXTRACT_CONVERSATION:
            return json.dumps(self.threads.get(self.current_hr, []), ensure_ascii=False)
        return json.dumps({"available": True})

    def _send_message_in_chat(self, target_id, message, config=None):
        raise AssertionError("the store refresh must never send a message")


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self.temp = tempfile.TemporaryDirectory(prefix="hr-store-test-")
        self.addCleanup(self.temp.cleanup)
        self.store_root = Path(self.temp.name)
        self.monitor = _StoreMonitor()
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(runtime, "_hr_store_root", self.store_root),
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.monitor),
            patch.object(runtime, "_runtime_config", return_value=self.config),
            patch.object(runtime, "_store_jobs", return_value=[]),
            patch.object(runtime, "_stop_requested", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _store(self) -> dict:
        return json.loads((self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8"))["conversations"]

    def _key_for(self, hr: str) -> str:
        return next(key for key, value in self._store().items() if value["hr_name"] == hr)


class UnchangedSignatureTests(_StoreCase):
    def test_unchanged_signature_with_a_body_does_not_reopen_the_page(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好，方便沟通吗"}]
        runtime.list_conversations("boss")
        self.assertEqual(self.monitor.opened, ["示例招聘官"])

        runtime.list_conversations("boss")  # same signature, body already stored
        self.assertEqual(self.monitor.opened, ["示例招聘官"], "no second page open")

    def test_changed_signature_opens_the_page_once_and_merges(self):
        self.monitor.threads["示例招聘官"] = [
            {"sender": "hr", "text": "你好，方便沟通吗"},
            {"sender": "me", "text": "您好，方便"},
        ]
        runtime.list_conversations("boss")
        self.monitor.list_rows = [dict(ROW, last_message_at="11-16 11:00", last_message="好的，周四可以")]
        self.monitor.threads["示例招聘官"] = [
            {"sender": "hr", "text": "你好，方便沟通吗"},
            {"sender": "me", "text": "您好，方便"},
            {"sender": "hr", "text": "好的，周四可以"},
        ]
        runtime.list_conversations("boss")
        self.assertEqual(self.monitor.opened, ["示例招聘官", "示例招聘官"])
        messages = self._store()[self._key_for("示例招聘官")]["messages"]
        self.assertEqual(
            [(m["sender"], m["text"]) for m in messages],
            [("hr", "你好，方便沟通吗"), ("me", "您好，方便"), ("hr", "好的，周四可以")],
            "old messages kept, the repeated ones not duplicated",
        )

    def test_identical_sentences_sent_twice_are_both_kept_and_not_duplicated_later(self):
        # The BOSS reader does not expose a per-message time, so repeats are
        # told apart by how many times the same (sender, text) was read.
        self.monitor.threads["示例招聘官"] = [
            {"sender": "me", "text": "好的"},
            {"sender": "me", "text": "好的"},
        ]
        runtime.list_conversations("boss")
        self.assertEqual(len(self._store()[self._key_for("示例招聘官")]["messages"]), 2)

        self.monitor.list_rows = [dict(ROW, last_message_at="11-16 14:00", last_message="好的")]
        self.monitor.threads["示例招聘官"] = [
            {"sender": "me", "text": "好的"},
            {"sender": "me", "text": "好的"},
            {"sender": "hr", "text": "收到"},
        ]
        runtime.list_conversations("boss")
        messages = self._store()[self._key_for("示例招聘官")]["messages"]
        self.assertEqual([(m["sender"], m["text"]) for m in messages],
                         [("me", "好的"), ("me", "好的"), ("hr", "收到")])


class PerPlatformReplacementTests(_StoreCase):
    def test_single_platform_refresh_keeps_other_platforms_records(self):
        zhilian = {"id": "z" * 32, "platform": "zhilian", "company": "虚构智联", "hr_name": "虚构招聘官乙"}
        runtime._remember_conversations([zhilian], "zhilian")
        seed = {
            "platform": "zhilian", "id": "z" * 32, "company": "虚构智联", "title": "",
            "hr_name": "虚构招聘官乙", "hr_title": "", "job_id": None,
            "last_message_at": "11-15", "last_message": "在吗", "unread": False,
        }
        seeded = runtime._hr_store_record(seed, messages=[{"sender": "hr", "text": "在吗", "time": ""}],
                                          signature="sig", fetched_at="2026-11-15T00:00:00+00:00")
        runtime._save_hr_store({"zhilian:" + "z" * 32: seeded})

        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好，方便沟通吗"}]
        runtime.list_conversations("boss")

        store = self._store()
        self.assertIn("zhilian:" + "z" * 32, store, "zhilian record survives a boss-only refresh")
        self.assertEqual(store["zhilian:" + "z" * 32]["messages"][0]["text"], "在吗")
        self.assertFalse(store["zhilian:" + "z" * 32]["stale"])

    def test_boss_refresh_replaces_its_own_stale_records(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "旧消息"}]
        runtime.list_conversations("boss")
        self.monitor.list_rows = []  # the conversation left the list
        runtime.list_conversations("boss")
        self.assertEqual(
            [value for value in self._store().values() if value["platform"] == "boss"],
            [],
            "a successful listing drops that platform's records that are no longer listed",
        )


class StaleOnFailureTests(_StoreCase):
    def test_failed_open_keeps_old_messages_and_marks_stale(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好，方便沟通吗"}]
        listing = runtime.list_conversations("boss")
        conversation_id = listing["conversations"][0]["id"]

        self.monitor.list_rows = [dict(ROW, last_message_at="11-16 12:00", last_message="新消息")]
        self.monitor.fail_open.add("示例招聘官")
        runtime.list_conversations("boss")

        record = self._store()[self._key_for("示例招聘官")]
        self.assertTrue(record["stale"])
        self.assertTrue(record["error"])
        self.assertEqual(record["messages"][0]["text"], "你好，方便沟通吗")
        self.assertTrue(conversation_id)

    def test_failed_list_keeps_the_platform_records_and_marks_them_stale(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好，方便沟通吗"}]
        runtime.list_conversations("boss")
        with patch.object(runtime, "_list_boss_conversations_within", side_effect=ValueError("列表解析失败")):
            with self.assertRaises(ValueError):
                runtime.list_conversations("boss")
        record = self._store()[self._key_for("示例招聘官")]
        self.assertTrue(record["stale"])
        self.assertEqual(record["messages"][0]["text"], "你好，方便沟通吗")

    def test_stale_body_is_returned_flagged_and_never_reported_as_fresh(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好，方便沟通吗"}]
        listing = runtime.list_conversations("boss")
        conversation_id = listing["conversations"][0]["id"]
        self.monitor.fail_open.add("示例招聘官")
        self.monitor.list_rows = [dict(ROW, last_message_at="11-16 12:00", last_message="新消息")]
        runtime.list_conversations("boss")

        thread = runtime.get_thread(conversation_id, "boss")
        self.assertTrue(thread["stale"])
        self.assertEqual(thread["messages"][0]["text"], "你好，方便沟通吗")
        self.assertFalse(thread["reply_allowed"] and thread["stale"])


class FileLayoutTests(_StoreCase):
    def test_store_path_is_under_the_mode_directory(self):
        path = runtime._hr_store_path("user")
        self.assertEqual(path.name, "conversations.json")
        self.assertEqual(path.parent.name, "hr")

    def test_default_store_path_is_web_data_user(self):
        with patch.object(runtime, "_hr_store_root", None):
            path = runtime._hr_store_path("user")
        self.assertEqual(path, WEB_DIR / "data" / "user" / "hr" / "conversations.json")

    def test_write_is_atomic_via_os_replace(self):
        calls = []
        real_replace = os.replace

        def spy(src, dst):
            calls.append((Path(src).parent, Path(dst)))
            return real_replace(src, dst)

        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好"}]
        with patch.object(runtime.os, "replace", side_effect=spy):
            runtime.list_conversations("boss")
        self.assertTrue(calls)
        temp_dir, target = calls[-1]
        self.assertEqual(target, self.store_root / "hr" / "conversations.json")
        self.assertEqual(temp_dir, target.parent)
        self.assertFalse(list(target.parent.glob(".conversations-*")), "no temp file left behind")

    def test_failed_replace_leaves_the_previous_store_intact(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "第一版"}]
        runtime.list_conversations("boss")
        before = (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")

        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "第二版"}]
        self.monitor.list_rows = [dict(ROW, last_message_at="11-16 13:00", last_message="改了")]
        with patch.object(runtime.os, "replace", side_effect=OSError("disk full")):
            runtime.list_conversations("boss")  # refresh swallows the write failure
        after = (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)
        self.assertEqual(list(self.store_root.joinpath("hr").glob(".conversations-*")), [])


class RedactionTests(_StoreCase):
    def test_contacts_never_reach_the_file(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": CONTACT_TEXT}]
        self.monitor.list_rows = [dict(ROW, last_message=CONTACT_TEXT)]
        runtime.list_conversations("boss")
        raw = (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")
        self.assertNotIn(FAKE_PHONE, raw)
        self.assertNotIn("demo.person@example.com", raw)
        self.assertNotIn("demo_wechat01", raw)
        self.assertIn("[联系方式已隐藏]", raw)

    def test_contacts_in_the_error_text_are_redacted(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好"}]
        runtime.list_conversations("boss")
        runtime._mark_platform_stale("boss", f"联系 demo.person@example.com {CONTACT_TEXT}")
        raw = (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")
        self.assertNotIn("demo.person@example.com", raw)
        self.assertNotIn(FAKE_PHONE, raw)


class SendGateTests(_StoreCase):
    def test_a_stored_body_never_makes_a_conversation_sendable(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好"}]
        runtime.list_conversations("boss")
        conversation_id = self._store()[self._key_for("示例招聘官")]["id"]
        runtime._reset_conversation_cache()  # the in-memory listing is gone
        with self.assertRaises(ValueError) as ctx:
            runtime.send_reply(
                conversation_id, "您好",
                confirm=runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=True,
            )
        self.assertIn("会话列表", str(ctx.exception))

    def test_stored_thread_read_reports_reply_enabled_without_a_time_window(self):
        self.monitor.threads["示例招聘官"] = [{"sender": "hr", "text": "你好"}]
        listing = runtime.list_conversations("boss")
        thread = runtime.get_thread(listing["conversations"][0]["id"], "boss")
        self.assertTrue(thread["reply_allowed"])
        self.assertIsNone(thread["reply_block_reason"])


if __name__ == "__main__":
    unittest.main()
