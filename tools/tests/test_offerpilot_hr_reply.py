#!/usr/bin/env python3
"""Tests for the scoring date anchor and the read-only HR conversation flow.

All conversations and jobs are fictional.  No browser is opened and nothing is
sent: the monitor module is replaced with a fake page object.
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
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(TOOLS_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import offerpilot_runtime  # noqa: E402
import server as web_server  # noqa: E402
from offerpilot import throttle  # noqa: E402
from offerpilot.ai import scorer  # noqa: E402


class _ThreeAM(datetime.datetime):
    """A clock fixed at 03:00, once outside every old send window."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 18, 3, 0, 0)


class ScoreDateTests(unittest.TestCase):
    def test_prompt_contains_the_scoring_day(self):
        job = {
            "title": "产品经理",
            "company": "示例云图科技有限公司",
            "city": "上海",
            "salary": "15-25K",
            "experience": "1-3年",
            "education": "本科",
            "recruitment_type": "experienced",
            "jd": "负责产品需求与上线。",
        }
        with patch.object(scorer, "_current_date", return_value="2026-11-16"):
            prompt = scorer._build_scoring_prompt(job, "虚构简历正文", {})
        self.assertIn("今天日期：2026-11-16", prompt)
        self.assertIn("计算“至今”年限时以此为准", prompt)
        self.assertRegex(scorer._current_date(), r"^\d{4}-\d{2}-\d{2}$")


class _FakeGuard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _FakeMonitor:
    """Fake page object: returns canned lists and records every send call."""

    JS_EXTRACT_CHAT_LIST = "js:chat-list"
    JS_EXTRACT_CONVERSATION = "js:conversation"
    MonitorSafetyGuard = _FakeGuard

    def __init__(self, chat_rows=None, thread_rows=None) -> None:
        self.chat_rows = chat_rows or []
        self.thread_rows = thread_rows or []
        self.guard = _FakeGuard()
        self.sent: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.opened: list[dict] = []
        self.send_result = True

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _get_monitor_chat_target(self, url, config):
        return "tab-list", False

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def evaluate(self, target_id, script):
        rows = self.thread_rows if script == self.JS_EXTRACT_CONVERSATION else self.chat_rows
        return json.dumps(rows, ensure_ascii=False)

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def stop_requested(self, config):
        return False

    def _monitor_safety_guard(self, config):
        return self.guard

    def _open_conversation_from_chat_list(self, job, config, *, background=True):
        self.opened.append({"job": dict(job), "background": background})
        return "tab-thread"

    def _send_message_in_chat(self, target_id, message, config=None):
        self.sent.append((target_id, message))
        return self.send_result


CHAT_ROWS = [
    {
        "hr_name": "示例招聘官",
        "company": "上海邦中",
        "hr_title": "招聘HR",
        "last_message": "你好，方便沟通吗",
        "last_message_at": "11-16 10:20",
        "has_unread": True,
        "last_direction": "hr",
        "has_reply": True,
    },
    {
        "hr_name": "示例招聘官",
        "company": "闪魂",
        "hr_title": "HRBP",
        "last_message": "感谢投递",
        "last_message_at": "11-15 18:00",
        "has_unread": False,
        "last_direction": "me",
        "has_reply": False,
    },
]

JOBS = [
    {
        "id": "j-1",
        "company": "上海邦中",
        "title": "产品经理",
        "hr_name": "示例招聘官",
        "offerpilot_id": "op-1",
    },
]


class ConversationRuntimeTests(unittest.TestCase):
    def setUp(self):
        offerpilot_runtime._reset_conversation_cache()
        self.addCleanup(offerpilot_runtime._reset_conversation_cache)
        self._store_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._store_temp.cleanup)
        patcher = patch.object(offerpilot_runtime, "_hr_store_root", Path(self._store_temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = _FakeMonitor(CHAT_ROWS, [
            {"sender": "hr", "text": "你好，方便沟通吗"},
            {"sender": "me", "text": "您好，方便"},
            {"sender": "unknown", "text": "x" * 800},
        ])
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(offerpilot_runtime, "load_backend", return_value=self.server),
            patch.object(offerpilot_runtime, "_monitor", return_value=self.fake),
            patch.object(offerpilot_runtime, "_runtime_config", return_value=self.config),
            patch.object(offerpilot_runtime, "_store_jobs", return_value=JOBS),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _green_gate(self):
        runtime = offerpilot_runtime
        return (
            patch.object(runtime, "_stop_requested", return_value=False),
            patch.object(runtime, "_risk_lock_reason", return_value=None),
        )

    def _prime(self):
        for patcher in self._green_gate():
            patcher.start()
            self.addCleanup(patcher.stop)
        result = offerpilot_runtime.list_conversations()
        self.assertEqual(result["count"], 2)
        return result

    def test_list_returns_hashed_ids_and_matched_job(self):
        result = self._prime()
        first, second = result["conversations"]
        self.assertRegex(first["id"], r"^[0-9a-f]{32}$")
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotIn("示例招聘官", first["id"])
        self.assertEqual(first["job_id"], "j-1")
        self.assertEqual(first["title"], "产品经理")
        self.assertIsNone(second["job_id"])
        self.assertTrue(first["unread"])
        self.assertEqual(first["last_message_at"], "11-16 10:20")
        self.assertIn("tab-list", self.fake.closed)

    def test_thread_truncates_messages_and_maps_senders(self):
        result = self._prime()
        thread = offerpilot_runtime.get_thread(result["conversations"][0]["id"])
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "system"])
        self.assertEqual(len(thread["messages"][2]["text"]), 500)
        self.assertTrue(thread["reply_allowed"])
        self.assertIsNone(thread["reply_block_reason"])
        # The listing refresh read only the unread conversation; the one whose
        # last message is ours is lazy, and serving the cached body must not
        # open either of them a second time.
        self.assertEqual([item["job"]["company"] for item in self.fake.opened], ["上海邦中"])
        self.assertTrue(all(item["background"] is True for item in self.fake.opened))

        offerpilot_runtime.get_thread(result["conversations"][1]["id"])
        self.assertEqual(
            [item["job"]["company"] for item in self.fake.opened], ["上海邦中", "闪魂"]
        )

    def test_send_reply_sends_exactly_one_message(self):
        result = self._prime()
        sent = offerpilot_runtime.send_reply(
            result["conversations"][0]["id"],
            "  您好，我可以周四下午沟通。  ",
            confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
            risk_acknowledged=True,
        )
        self.assertEqual(sent["company"], "上海邦中")
        self.assertEqual(self.fake.sent, [("tab-thread", "您好，我可以周四下午沟通。")])
        # Sending must not steal the user's screen focus: the conversation tab
        # used to send the reply is opened in the background like every read.
        self.assertTrue(all(item["background"] is True for item in self.fake.opened))

    def test_empty_and_overlong_text_are_rejected(self):
        result = self._prime()
        cid = result["conversations"][0]["id"]
        for text in ("   ", "字" * 1001):
            with self.assertRaises(ValueError):
                offerpilot_runtime.send_reply(
                    cid, text,
                    confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                    risk_acknowledged=True,
                )
        self.assertEqual(self.fake.sent, [])

    def test_wrong_confirm_phrase_is_rejected(self):
        result = self._prime()
        with self.assertRaises(ValueError) as ctx:
            offerpilot_runtime.send_reply(
                result["conversations"][0]["id"], "您好",
                confirm="确认发送", risk_acknowledged=True,
            )
        self.assertIn("确认短语", str(ctx.exception))
        self.assertEqual(self.fake.sent, [])

    def test_missing_risk_acknowledgement_is_rejected(self):
        result = self._prime()
        with self.assertRaises(ValueError):
            offerpilot_runtime.send_reply(
                result["conversations"][0]["id"], "您好",
                confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=False,
            )
        self.assertEqual(self.fake.sent, [])

    def test_reply_is_sent_at_three_am(self):
        # The old implementation refused 03:00; sending is now allowed all day.
        result = self._prime()
        with patch.object(throttle, "datetime", _ThreeAM):
            self.assertTrue(throttle.SendWindowChecker(["09:00-16:00"]).is_active())
            sent = offerpilot_runtime.send_reply(
                result["conversations"][0]["id"], "您好，现在方便沟通吗？",
                confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=True,
            )
        self.assertEqual(sent["company"], "上海邦中")
        self.assertEqual(len(self.fake.sent), 1)

    def test_reply_gate_ignores_a_legacy_send_window_at_three_am(self):
        with patch.object(throttle, "datetime", _ThreeAM), patch.object(
            offerpilot_runtime, "_stop_requested", return_value=False
        ), patch.object(offerpilot_runtime, "_risk_lock_reason", return_value=None):
            allowed, reason = offerpilot_runtime._reply_gate(self.server, self.config)
        self.assertEqual((allowed, reason), (True, None))

    def test_stop_request_is_rejected(self):
        result = self._prime()
        with patch.object(offerpilot_runtime, "_stop_requested", return_value=True):
            with self.assertRaises(ValueError) as ctx:
                offerpilot_runtime.send_reply(
                    result["conversations"][0]["id"], "您好",
                    confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                    risk_acknowledged=True,
                )
        self.assertIn("停止", str(ctx.exception))
        self.assertEqual(self.fake.sent, [])

    def test_risk_lock_is_rejected(self):
        result = self._prime()
        with patch.object(offerpilot_runtime, "_risk_lock_reason", return_value="平台风险锁未解除，请稍后再试"):
            with self.assertRaises(ValueError) as ctx:
                offerpilot_runtime.send_reply(
                    result["conversations"][0]["id"], "您好",
                    confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                    risk_acknowledged=True,
                )
        self.assertIn("风险锁", str(ctx.exception))
        self.assertEqual(self.fake.sent, [])

    def test_id_outside_recent_list_is_rejected(self):
        self._prime()
        with self.assertRaises(ValueError) as ctx:
            offerpilot_runtime.send_reply(
                "0" * 32, "您好",
                confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=True,
            )
        self.assertIn("会话列表", str(ctx.exception))
        self.assertEqual(self.fake.sent, [])

    def test_expired_list_is_rejected(self):
        result = self._prime()
        with offerpilot_runtime._conversation_cache_lock:
            offerpilot_runtime._conversation_listed_at -= offerpilot_runtime.CONVERSATIONS_TTL_SECONDS + 1
            for name in list(offerpilot_runtime._conversation_listed_at_by_platform):
                offerpilot_runtime._conversation_listed_at_by_platform[name] -= (
                    offerpilot_runtime.CONVERSATIONS_TTL_SECONDS + 1
                )
        with self.assertRaises(ValueError):
            offerpilot_runtime.send_reply(
                result["conversations"][0]["id"], "您好",
                confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=True,
            )
        self.assertEqual(self.fake.sent, [])

    def test_failed_send_is_reported(self):
        result = self._prime()
        self.fake.send_result = False
        with self.assertRaises(ValueError) as ctx:
            offerpilot_runtime.send_reply(
                result["conversations"][0]["id"], "您好",
                confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                risk_acknowledged=True,
            )
        self.assertIn("未被平台确认", str(ctx.exception))


class ReplyActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(backend, "WEB_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = backend.Store("user")
        self.store.set_jobs([])
        self.store.set_queue([])
        self.store.set_deliveries([])
        store_patcher = patch.object(backend, "get_store", return_value=self.store)
        store_patcher.start()
        self.addCleanup(store_patcher.stop)

    def test_mode_is_a_compatibility_field(self):
        """``mode`` is ignored: the reply path uses the single local runtime."""
        with patch.object(
            backend.offerpilot_runtime,
            "send_reply",
            return_value={"conversation_id": "a" * 32, "company": "虚构公司"},
        ) as send:
            result = backend.send_offerpilot_reply({
                "mode": "demo",
                "id": "a" * 32,
                "text": "您好",
                "confirm": offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                "risk_acknowledged": True,
            })
        self.assertTrue(result["ok"])
        send.assert_called_once()

    def test_invalid_and_missing_ids_are_rejected(self):
        for cid in ("", "not-a-hash", "z" * 32):
            with self.assertRaises(backend.ApiError):
                backend.send_offerpilot_reply({
                    "mode": "user",
                    "id": cid,
                    "text": "您好",
                    "confirm": offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                    "risk_acknowledged": True,
                })

    def test_success_logs_action_and_company_only(self):
        with patch.object(offerpilot_runtime, "send_reply", return_value={
            "ok": True, "conversation_id": "a" * 32, "company": "上海邦中", "chars": 2,
        }) as send:
            result = backend.send_offerpilot_reply({
                "mode": "user",
                "id": "a" * 32,
                "text": "您好，这是我的回复正文",
                "confirm": offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                "risk_acknowledged": True,
            })
        self.assertTrue(result["ok"])
        send.assert_called_once()
        rows = [row for row in self.store.activity(50) if row.get("action") == "发送 HR 回复"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detail"], "上海邦中")
        self.assertNotIn("回复正文", json.dumps(rows, ensure_ascii=False))

    def test_action_is_registered(self):
        self.assertIs(backend.ACTIONS["offerpilot-reply"], backend.send_offerpilot_reply)

    def test_mode_is_a_compatibility_field_for_reads(self):
        """``mode`` is ignored: reads always go to the single local runtime."""
        listing_payload = {"ok": True, "available": True, "conversations": [], "count": 0}
        thread_payload = {"ok": True, "available": True, "messages": []}
        with patch.object(
            offerpilot_runtime, "cached_conversations", return_value=listing_payload
        ) as listing, patch.object(
            offerpilot_runtime, "get_thread", return_value=thread_payload
        ) as thread:
            listing_result = backend.get_offerpilot_conversations("demo")
            thread_result = backend.get_offerpilot_conversation("demo", "a" * 32)
        self.assertTrue(listing_result["available"])
        self.assertTrue(thread_result["available"])
        listing.assert_called_once_with("boss")
        thread.assert_called_once_with("a" * 32, "boss")


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
        else:
            raise RuntimeError("临时 HTTP 服务未能在 5 秒内启动")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str, payload: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {}
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_conversations_route_is_wired(self):
        payload = {"ok": True, "available": False, "conversations": [], "count": 0}
        # "demo" is a compatibility value: the route still forwards it, and the
        # backend maps every value to the single local dataset.
        with patch.object(backend, "get_offerpilot_conversations", return_value=payload) as listing:
            status, raw = self.request("GET", "/api/offerpilot/conversations?mode=demo")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), payload)
        listing.assert_called_once_with("demo", "boss")

    def test_conversation_route_passes_id_and_rejects_bad_ids(self):
        payload = {"ok": True, "available": False, "messages": []}
        with patch.object(backend, "get_offerpilot_conversation", return_value=payload) as thread:
            status, raw = self.request("GET", f"/api/offerpilot/conversation?mode=user&id={'a' * 32}")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw), payload)
        thread.assert_called_once_with("user", "a" * 32, "boss")

        status, raw = self.request("GET", "/api/offerpilot/conversation?mode=user&id=bad")
        self.assertEqual(status, 400)
        self.assertIn("会话 id", json.loads(raw)["error"])

    def test_conversation_routes_pass_the_platform_query(self):
        payload = {"ok": True, "available": False, "conversations": [], "count": 0}
        with patch.object(backend, "get_offerpilot_conversations", return_value=payload) as listing:
            status, _ = self.request("GET", "/api/offerpilot/conversations?mode=demo&platform=liepin")
        self.assertEqual(status, 200)
        listing.assert_called_once_with("demo", "liepin")

        thread_payload = {"ok": True, "available": False, "messages": []}
        with patch.object(backend, "get_offerpilot_conversation", return_value=thread_payload) as thread:
            status, _ = self.request(
                "GET", f"/api/offerpilot/conversation?mode=user&platform=zhilian&id={'a' * 32}"
            )
        self.assertEqual(status, 200)
        thread.assert_called_once_with("user", "a" * 32, "zhilian")

        status, raw = self.request("GET", "/api/offerpilot/conversations?mode=demo&platform=xiaoyuan")
        self.assertEqual(status, 400)
        self.assertIn("平台", json.loads(raw)["error"])

    def test_reply_action_is_reachable_and_mode_is_ignored(self):
        with patch.object(
            backend.offerpilot_runtime,
            "send_reply",
            return_value={"conversation_id": "a" * 32, "company": "虚构公司"},
        ):
            status, raw = self.request("POST", "/api/action", {
                "action": "offerpilot-reply",
                "mode": "demo",
                "id": "a" * 32,
                "text": "您好",
                "confirm": offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                "risk_acknowledged": True,
            })
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(raw)["ok"])


if __name__ == "__main__":
    unittest.main()
