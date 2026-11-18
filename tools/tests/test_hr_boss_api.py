#!/usr/bin/env python3
"""BOSS HR reads through the page's same-origin interface.

All companies, people and ids here are fictional.  No browser is opened and
nothing is sent: the monitor is replaced with a fake page that answers the
fixed fetch expressions and the DOM fallback.

Contracts locked here:

- the list is mapped from ``zpData.result`` into the existing item shape and
  carries ``source: "api"``;
- a conversation whose listing signature did not change is not requested
  again, and an empty conversation is remembered as read;
- history messages are attributed by ``from.uid``; card bodies are system;
- an interface failure falls back to the DOM, never to a foreground tab;
- the conversation ids used by the interface never reach the API response;
- a login/risk answer stops the read without retrying.
"""

from __future__ import annotations

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

import offerpilot_runtime as runtime  # noqa: E402

FAKE_PHONE = "1" + "3" * 10
CONTACT_TEXT = f"我的电话 {FAKE_PHONE}，邮箱 demo.person@example.com，微信 demo_wechat01"

BOSS_UID = 900001
MY_UID = 111111

API_ROWS = [
    {
        "name": "示例招聘官甲",
        "brandName": "虚构云帆科技有限公司",
        "title": "产品经理",
        "encryptBossId": "enc-boss-0001",
        "uid": BOSS_UID,
        "securityId": "sec-0001",
        "unreadMsgCount": 2,
        "lastMsg": "你好，方便沟通吗",
        "lastMessageInfo": {
            "msgId": 101, "showText": "你好，方便沟通吗",
            "fromId": BOSS_UID, "toId": MY_UID, "status": 1, "msgTime": 1763000000000,
        },
        "lastTime": "刚刚",
        "lastTS": 1763000000000,
        "filtered": False,
        "isFiltered": False,
    },
    {
        "name": "示例招聘官乙",
        "brandName": "虚构青禾网络有限公司",
        "title": "数据分析师",
        "encryptBossId": "enc-boss-0002",
        "uid": 900002,
        "securityId": "sec-0002",
        "unreadMsgCount": 0,
        "lastMsg": CONTACT_TEXT,
        "lastMessageInfo": {
            "msgId": 201, "showText": CONTACT_TEXT,
            "fromId": MY_UID, "toId": 900002, "status": 2, "msgTime": 1762990000000,
        },
        "lastTime": "昨天",
        "lastTS": 1762990000000,
        "filtered": False,
        "isFiltered": False,
    },
]

HISTORY_ROWS = [
    {
        "mid": 101, "time": 1763000000000,
        "from": {"uid": BOSS_UID, "name": "示例招聘官甲"},
        "to": {"uid": MY_UID},
        "bodyType": 1, "body": {"type": 1, "text": "你好，方便沟通吗"},
    },
    {
        "mid": 102, "time": 1763000100000,
        "from": {"uid": MY_UID},
        "to": {"uid": BOSS_UID},
        "bodyType": 1, "body": {"type": 1, "text": "您好，方便"},
    },
    {
        "mid": 103, "time": 1763000200000,
        "from": {"uid": BOSS_UID},
        "to": {"uid": MY_UID},
        "bodyType": 8, "body": {"type": 8, "headTitle": "附件简历已发送"},
    },
]

DOM_ROWS = [
    {
        "hr_name": "示例招聘官甲",
        "company": "虚构云帆科技有限公司",
        "hr_title": "产品经理",
        "last_message": "你好，方便沟通吗",
        "last_message_at": "11-16 10:20",
        "has_unread": True,
        "last_direction": "hr",
        "has_reply": True,
    }
]

JOBS = [
    {
        "id": "job-1",
        "company": "虚构云帆科技有限公司",
        "title": "产品经理",
        "hr_name": "示例招聘官甲",
    }
]


class _Risk(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class _Guard:
    limit = 3
    consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        pass

    def record_page_success(self) -> None:
        pass


class _FakePage:
    """Answers the two fixed fetch expressions, the DOM list and the DOM chat."""

    JS_EXTRACT_CHAT_LIST = "js:chat-list"
    JS_EXTRACT_CONVERSATION = "js:conversation"
    MonitorRiskDetected = _Risk
    MonitorSafetyGuard = _Guard

    def __init__(self) -> None:
        self.api_rows = [dict(row) for row in API_ROWS]
        self.history_rows = [dict(row) for row in HISTORY_ROWS]
        self.dom_rows = [dict(row) for row in DOM_ROWS]
        self.dom_thread_rows = [
            {"sender": "hr", "text": "你好，方便沟通吗"},
            {"sender": "me", "text": "您好，方便"},
        ]
        self.user_tab = True
        self.list_mode = "api"        # api / error / risk
        self.history_mode = "api"     # api / error
        self.list_calls = 0
        self.history_calls = 0
        self.dom_list_calls = 0
        self.new_tabs: list[dict] = []
        self.closed: list[str] = []
        self.opened: list[dict] = []

    def get_page_targets(self) -> list[dict]:
        if not self.user_tab:
            return []
        return [{"targetId": "user-tab", "url": "https://www.zhipin.com/web/geek/chat"}]

    def _open_monitor_tab(self, url, config, *, background=True):
        self.new_tabs.append({"url": url, "background": background})
        return "new-tab"

    def get_page_info(self, target_id):
        return {"ready": "complete"}

    def _wait_or_stop(self, config, seconds):
        return False

    def _inspect_monitor_page(self, target_id, config):
        return None

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def stop_requested(self, config):
        return False

    def _monitor_safety_guard(self, config):
        return _Guard()

    def _open_conversation_from_chat_list(self, job, config, *, background=True, allow_company_only=True):
        self.opened.append({"job": dict(job), "background": background})
        return "thread-tab"

    def _send_message_in_chat(self, target_id, message, config=None):
        raise AssertionError("HR reads must never send")

    def evaluate(self, target_id, script, timeout=None):
        if script == self.JS_EXTRACT_CHAT_LIST:
            self.dom_list_calls += 1
            return json.dumps(self.dom_rows, ensure_ascii=False)
        if script == self.JS_EXTRACT_CONVERSATION:
            return json.dumps(self.dom_thread_rows, ensure_ascii=False)
        if "getGeekFriendList.json" in script:
            self.list_calls += 1
            if self.list_mode == "risk":
                return json.dumps({"http": 200, "body": {"code": 37, "message": "请完成验证"}})
            if self.list_mode == "error":
                return json.dumps({"http": 500, "body": None})
            return json.dumps({"http": 200, "body": {"code": 0, "zpData": {"result": self.api_rows}}})
        if "historyMsg" in script:
            self.history_calls += 1
            if self.history_mode == "error":
                return json.dumps({"http": 500, "body": None})
            return json.dumps({"http": 200, "body": {
                "code": 0,
                "zpData": {"hasMore": False, "messages": self.history_rows, "minMsgId": 0},
            }})
        return json.dumps({"available": True})


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        runtime._boss_history_params.clear()
        self.addCleanup(runtime._reset_conversation_cache)
        self.addCleanup(runtime._boss_history_params.clear)
        self.temp = tempfile.TemporaryDirectory(prefix="boss-api-test-")
        self.addCleanup(self.temp.cleanup)
        self.store_root = Path(self.temp.name)
        self.page = _FakePage()
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(runtime, "_hr_store_root", self.store_root),
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.page),
            patch.object(runtime, "_runtime_config", return_value=self.config),
            patch.object(runtime, "_store_jobs", return_value=JOBS),
            patch.object(runtime, "_stop_requested", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _store(self) -> dict:
        path = self.store_root / "hr" / "conversations.json"
        return json.loads(path.read_text(encoding="utf-8"))["conversations"]

    def _list(self) -> dict:
        return runtime.list_conversations("boss")

    def _record_for(self, hr_name: str) -> dict:
        return next(
            record for record in self._store().values()
            if record.get("hr_name") == hr_name
        )


class ListMappingTests(_Case):
    def test_list_maps_the_interface_and_reports_its_source(self):
        result = self._list()
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["count"], 2)
        first, second = result["conversations"]
        self.assertEqual(first["hr_name"], "示例招聘官甲")
        self.assertEqual(first["company"], "虚构云帆科技有限公司")
        self.assertEqual(first["title"], "产品经理")
        self.assertTrue(first["unread"])
        self.assertEqual(first["last_direction"], "hr")
        self.assertTrue(first["has_reply"])
        self.assertEqual(first["job_id"], "job-1")
        self.assertEqual(second["last_direction"], "me")
        self.assertFalse(second["has_reply"])

    def test_interface_ids_never_reach_the_response(self):
        raw = json.dumps(self._list(), ensure_ascii=False)
        self.assertNotIn("enc-boss-0001", raw)
        self.assertNotIn("sec-0001", raw)
        self.assertNotIn("_boss_params", raw)

    def test_contacts_in_the_list_are_redacted(self):
        result = self._list()
        second = result["conversations"][1]["last_message"]
        self.assertNotIn(FAKE_PHONE, second)
        self.assertNotIn("demo.person@example.com", second)
        self.assertNotIn("demo_wechat01", second)
        self.assertIn("[联系方式已隐藏]", second)

    def test_the_users_tab_is_reused_and_never_closed(self):
        self._list()
        self.assertEqual(self.page.new_tabs, [], "an existing chat tab is reused")
        self.assertEqual(self.page.closed, [])

    def test_without_a_chat_tab_a_background_one_is_opened_and_closed(self):
        self.page.user_tab = False
        self._list()
        self.assertEqual(len(self.page.new_tabs), 1)
        self.assertTrue(self.page.new_tabs[0]["background"])
        self.assertEqual(self.page.closed, ["new-tab"])


class HistoryMappingTests(_Case):
    def test_senders_follow_from_uid_and_cards_stay_system(self):
        result = self._list()
        thread = runtime.get_thread(result["conversations"][0]["id"], "boss")
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "system"])
        self.assertEqual(thread["messages"][2]["text"], "附件简历已发送")
        # The unified message shape carries the platform's own id for dedupe;
        # interface request parameters stay internal.
        self.assertEqual([m["mid"] for m in thread["messages"]], ["101", "102", "103"])
        raw = json.dumps(thread, ensure_ascii=False)
        self.assertNotIn("enc-boss-0001", raw)
        self.assertNotIn("sec-0001", raw)

    def test_changed_signature_prompts_only_that_conversation(self):
        self._list()
        # Cold start reads only the conversation with something new from HR;
        # the one whose last message is ours is left for the user to open.
        self.assertEqual(self.page.history_calls, 1)
        self._list()  # unchanged signatures: nothing is requested again
        self.assertEqual(self.page.history_calls, 1)

        self.page.api_rows[0] = dict(
            self.page.api_rows[0],
            lastMsg="好的，周四可以",
            lastTS=1763001000000,
            lastMessageInfo=dict(
                self.page.api_rows[0]["lastMessageInfo"],
                showText="好的，周四可以",
                fromId=BOSS_UID,
                msgTime=1763001000000,
            ),
        )
        self._list()
        self.assertEqual(self.page.history_calls, 2, "only the changed conversation is read")

    def test_an_empty_conversation_is_marked_read_and_not_requested_again(self):
        self.page.history_rows = []
        self._list()
        self.assertEqual(self.page.history_calls, 1)
        record = self._record_for("示例招聘官甲")
        self.assertTrue(record["body_read"])
        self.assertEqual(record["messages"], [])
        lazy = self._record_for("示例招聘官乙")
        self.assertFalse(lazy["body_read"], "last message ours: lazy until opened")

        self._list()
        self.assertEqual(self.page.history_calls, 1, "an empty read is still a read")

        result = runtime.get_thread(record["id"], "boss")
        self.assertEqual(result["messages"], [])
        self.assertEqual(self.page.history_calls, 1)

    def test_a_conversation_whose_last_message_is_ours_is_read_only_when_opened(self):
        self._list()
        lazy = self._record_for("示例招聘官乙")
        self.assertFalse(lazy["body_read"])
        self.assertEqual(self.page.history_calls, 1)

        thread = runtime.get_thread(lazy["id"], "boss")
        self.assertEqual(self.page.history_calls, 2, "opening reads that one conversation")
        self.assertTrue(thread["messages"])
        self.assertTrue(self._record_for("示例招聘官乙")["body_read"])

    def test_a_reply_sent_on_the_platform_marks_stale_without_a_background_read(self):
        self._list()
        lazy = self._record_for("示例招聘官乙")
        runtime.get_thread(lazy["id"], "boss")  # the user opens it once: a body is stored
        self.assertEqual(self.page.history_calls, 2)

        self.page.api_rows[1] = dict(
            self.page.api_rows[1],
            lastMsg="好的，明天见",
            lastTS=1763002000000,
            lastMessageInfo=dict(
                self.page.api_rows[1]["lastMessageInfo"],
                showText="好的，明天见",
                fromId=MY_UID,
                msgTime=1763002000000,
            ),
        )
        self._list()
        self.assertEqual(self.page.history_calls, 2, "our own latest message is not read in the background")
        record = self._record_for("示例招聘官乙")
        self.assertTrue(record["stale"], "the stored body is behind the listing")

        runtime.get_thread(record["id"], "boss")
        self.assertEqual(self.page.history_calls, 3, "opening refreshes that conversation once")
        self.assertFalse(self._record_for("示例招聘官乙")["stale"])

    def test_the_listing_is_written_before_the_body_is_read(self):
        seen: dict = {}
        real = runtime._fetch_thread_body

        def spy(row, platform, **kwargs):
            path = self.store_root / "hr" / "conversations.json"
            store = json.loads(path.read_text(encoding="utf-8"))["conversations"]
            seen["record"] = next(
                value for value in store.values()
                if value.get("hr_name") == row.get("hr_name")
            )
            return real(row, platform, **kwargs)

        with patch.object(runtime, "_fetch_thread_body", side_effect=spy):
            self._list()
        self.assertEqual(seen["record"]["last_message"], "你好，方便沟通吗")
        self.assertFalse(seen["record"]["body_read"], "the listing is saved before any body")
        self.assertEqual(seen["record"]["messages"], [])

    def test_stored_messages_merge_by_max_mid_without_repeating(self):
        self._list()
        self.page.api_rows[0] = dict(
            self.page.api_rows[0],
            lastMsg="附件简历已发送",
            lastTS=1763000200000,
            lastMessageInfo=dict(
                self.page.api_rows[0]["lastMessageInfo"],
                showText="附件简历已发送",
                fromId=BOSS_UID,
                msgTime=1763000200000,
            ),
        )
        self.page.history_rows = list(HISTORY_ROWS) + [
            {
                "mid": 104, "time": 1763000300000,
                "from": {"uid": 900001}, "to": {"uid": MY_UID},
                "bodyType": 1, "body": {"type": 1, "text": "周四下午可以吗"},
            },
        ]
        self._list()
        record = self._store()[next(
            key for key, value in self._store().items()
            if value["company"] == "虚构云帆科技有限公司"
        )]
        texts = [message["text"] for message in record["messages"]]
        self.assertEqual(texts.count("你好，方便沟通吗"), 1)
        self.assertEqual(texts[-1], "周四下午可以吗")


class FallbackTests(_Case):
    def test_interface_error_falls_back_to_the_dom_list(self):
        self.page.list_mode = "error"
        self.page.history_mode = "error"
        result = self._list()
        self.assertEqual(result["source"], "dom")
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.page.list_calls, 1, "a failure is not retried")
        self.assertEqual(self.page.dom_list_calls, 1)
        # 后台列表刷新不读正文：DOM 兜底只列会话，正文等用户打开时再读。
        self.assertFalse(self.page.opened)

    def test_risk_answer_stops_without_retry_or_dom_fallback(self):
        self.page.list_mode = "risk"
        with self.assertRaises(_Risk) as ctx:
            self._list()
        self.assertEqual(ctx.exception.kind, "captcha")
        self.assertEqual(self.page.list_calls, 1)
        self.assertEqual(self.page.dom_list_calls, 0)


if __name__ == "__main__":
    unittest.main()
