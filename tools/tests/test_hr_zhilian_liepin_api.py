#!/usr/bin/env python3
"""Zhilian / Liepin interface reads with fictional stubs.

No browser and no network: the monitor is replaced with a fake page that
answers the fixed expressions.  Names, companies and ids are invented.

Contracts locked here:

- the Zhilian talk list is mapped into the unified item shape with
  ``source: "api"`` and unread counts;
- a failed talk list falls back to the chat DOM in the same tab;
- Zhilian history comes from the page's NIM SDK; sender follows ``flow``;
  custom cards keep only their fallback text;
- the Liepin contact list is mapped into the same shape (``source: "api"``)
  with no account id, token or opposite id leaving the backend;
- a failed or empty contact list falls back to the drawer DOM in the same tab;
- Liepin history comes from the drawer store; ``direction "0"`` is us;
- both platforms reuse the user's own tab and never close it;
- 智联 / 猎聘 replies go through the user's own page after every send guard
  (see ``ReplySendTests``); nothing is sent without the confirmation phrase;
- every tab the reader opens itself is a background tab.
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

ZHILIAN_ROWS = [
    {
        "sessionid": "s-0001",
        "peerPartnerId": "peer-0001",
        "staffName": "示例招聘官智",
        "companyName": "虚构星河数据有限公司",
        "jobTitle": "数据分析师",
        "unreadCount": 3,
        "text": "方便发一份简历吗",
        "lastSentence": "我：方便发一份简历吗",
        "sendTime": 1763000000000,
    }
]

ZHILIAN_DOM_ROWS = [
    {
        "hr_name": "示例招聘官智",
        "company": "虚构星河数据有限公司",
        "hr_title": "数据分析师",
        "last_message": "方便发一份简历吗",
        "last_message_at": "11-13 08:53",
        "has_unread": True,
    }
]

ZHILIAN_HISTORY = {
    "msgs": [
        {
            "flow": "in", "from": "peer-0001", "to": "me-0001", "time": 1763000000000,
            "type": "text", "text": "你好，方便沟通吗", "idServer": "9001",
        },
        {
            "flow": "out", "from": "me-0001", "to": "peer-0001", "time": 1763000600000,
            "type": "text", "text": "您好，可以", "idServer": "9002",
        },
        {
            "flow": "in", "from": "peer-0001", "to": "me-0001", "time": 1763001200000,
            "type": "custom", "text": "",
            "content": json.dumps({"fallbackText": "[名片] 示例职位", "type": "9"}),
            "idServer": "9003",
        },
    ]
}

LIEPIN_API_ROWS = [
    {
        "name": "示例招聘官猎",
        "company": "虚构远山网络有限公司",
        "title": "产品经理",
        "unReadCnt": 2,
        "oppositeImId": "opposite-0001",
        "userId": "user-0001",
        "imId": "account-0001",
        "messageToken": "token-fixture-value",
        "direction": "1",
        "latestMsgTime": 1763100000000,
        "lastPayload": json.dumps({"bodies": [{"msg": "你好，方便沟通吗", "type": "txt"}]}),
    }
]

LIEPIN_DOM_ROWS = [
    {
        "hr_name": "示例招聘官猎",
        "company": "虚构远山网络有限公司",
        "hr_title": "产品经理",
        "last_message": "你好，方便沟通吗",
        "last_message_at": "11-14 09:00",
        "has_unread": True,
    }
]

LIEPIN_HISTORY = {
    "available": True,
    "rows": [
        {"direction": "1", "msg": "你好，方便沟通吗", "msgTime": 1763100000000, "msgId": "8001"},
        {"direction": "0", "msg": "您好，可以", "msgTime": 1763100600000, "msgId": "8002"},
        {
            "direction": "1", "msg": "",
            "payload": json.dumps({"bodies": [{"msg": "", "type": "img", "url": "https://example.invalid/x.png"}]}),
            "msgTime": 1763101200000, "msgId": "8003",
        },
    ],
}

JOBS = []


class _FakePage:
    JS_ZHILIAN_CHAT_LIST = runtime.JS_ZHILIAN_CHAT_LIST
    JS_LIEPIN_CHAT_LIST = runtime.JS_LIEPIN_CHAT_LIST
    JS_LIEPIN_ENSURE_DRAWER_WWW = runtime.JS_LIEPIN_ENSURE_DRAWER_WWW
    JS_ZHILIAN_OPEN_THREAD = runtime.JS_ZHILIAN_OPEN_THREAD
    JS_LIEPIN_OPEN_THREAD = runtime.JS_LIEPIN_OPEN_THREAD
    JS_ZHILIAN_THREAD = runtime.JS_ZHILIAN_THREAD
    JS_LIEPIN_THREAD = runtime.JS_LIEPIN_THREAD

    def __init__(self) -> None:
        self.zhilian_mode = "api"   # api / error
        self.liepin_store = "api"   # api / missing
        self.liepin_list = "api"    # api / error
        self.liepin_dom_mismatch = False
        self.list_calls = 0
        self.history_calls = 0
        self.scripts: list[str] = []
        self.new_tabs: list[dict] = []
        self.closed: list[str] = []
        self.tabs = [
            {"targetId": "z-tab", "url": "https://i.zhaopin.com/im?refcode=4017"},
            {"targetId": "l-tab", "url": "https://www.liepin.com/zhaopin/"},
        ]

    def get_page_targets(self):
        return list(self.tabs)

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
        return MagicMock(limit=3, consecutive_page_failures=0)

    def _open_conversation_from_chat_list(self, job, config, *, background=True, allow_company_only=True):
        return "thread-tab"

    def _send_message_in_chat(self, target_id, message, config=None):
        raise AssertionError("HR reads must never send")

    def evaluate(self, target_id, script, timeout=None):
        self.scripts.append(script)
        if "getTalkList" in script:
            self.list_calls += 1
            if self.zhilian_mode == "error":
                return json.dumps({"http": 500, "body": None})
            return json.dumps({"http": 200, "body": {"statusCode": 200, "data": ZHILIAN_ROWS}})
        if "getHistoryMsgs" in script:
            self.history_calls += 1
            return json.dumps(ZHILIAN_HISTORY)
        if "const contacts = []" in script:
            self.list_calls += 1
            if self.liepin_list == "error":
                return json.dumps({"available": False, "reason": "会话列表读取失败"})
            return json.dumps({"available": True, "rows": LIEPIN_API_ROWS, "via": "props"})
        if "getChatList" in script:
            self.history_calls += 1
            if self.liepin_store == "missing":
                return json.dumps({"available": False, "reason": "聊天面板未就绪"})
            return json.dumps(LIEPIN_HISTORY)
        if script == self.JS_ZHILIAN_CHAT_LIST:
            return json.dumps({"available": True, "rows": ZHILIAN_DOM_ROWS})
        if script == self.JS_LIEPIN_CHAT_LIST:
            if self.liepin_dom_mismatch:
                return json.dumps({
                    "available": True, "rows": [], "matched": 0,
                    "drawer_found": True, "wrap_count": 2, "fallback_matched": 3,
                })
            return json.dumps({"available": True, "rows": LIEPIN_DOM_ROWS})
        if script == self.JS_LIEPIN_ENSURE_DRAWER_WWW:
            return json.dumps({"available": True, "branch": "expanded"})
        if script in (self.JS_ZHILIAN_OPEN_THREAD, self.JS_LIEPIN_OPEN_THREAD):
            return json.dumps({"available": True})
        if script == self.JS_ZHILIAN_THREAD:
            return json.dumps({"rows": [
                {"sender": "hr", "text": "你好，方便沟通吗"},
                {"sender": "me", "text": "您好，可以"},
            ]})
        if script == self.JS_LIEPIN_THREAD:
            return json.dumps({"rows": [
                {"sender": "hr", "text": "你好，方便沟通吗"},
                {"sender": "me", "text": "您好，可以"},
            ]})
        return json.dumps({"available": True})


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        runtime._zhilian_history_params.clear()
        self.addCleanup(runtime._reset_conversation_cache)
        self.addCleanup(runtime._zhilian_history_params.clear)
        self.temp = tempfile.TemporaryDirectory(prefix="zl-api-test-")
        self.addCleanup(self.temp.cleanup)
        self.page = _FakePage()
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        for patcher in (
            patch.object(runtime, "_hr_store_root", Path(self.temp.name)),
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.page),
            patch.object(runtime, "_runtime_config", return_value={"monitor": {}}),
            patch.object(runtime, "_store_jobs", return_value=JOBS),
            patch.object(runtime, "_stop_requested", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_zhilian_list_maps_the_interface(self):
        result = runtime.list_conversations("zhilian")
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["count"], 1)
        row = result["conversations"][0]
        self.assertEqual(row["hr_name"], "示例招聘官智")
        self.assertEqual(row["company"], "虚构星河数据有限公司")
        self.assertEqual(row["title"], "数据分析师")
        self.assertEqual(row["unread_count"], 3)
        self.assertTrue(row["unread"])
        self.assertEqual(self.page.new_tabs, [], "the user's tab is reused")
        self.assertEqual(self.page.closed, [])
        self.assertIn(row["id"], runtime._zhilian_history_params)

    def test_zhilian_list_failure_falls_back_to_the_dom_in_the_same_tab(self):
        self.page.zhilian_mode = "error"
        result = runtime.list_conversations("zhilian")
        self.assertEqual(result["source"], "dom")
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.page.list_calls, 1, "a failure is not retried")
        self.assertTrue(all(tab["background"] for tab in self.page.new_tabs))
        self.assertNotIn("z-tab", self.page.closed, "the user's own tab is never closed")

    def test_liepin_list_maps_the_interface(self):
        result = runtime.list_conversations("liepin")
        self.assertEqual(result["source"], "api")
        self.assertEqual(result["via"], "props")
        self.assertEqual(result["count"], 1)
        row = result["conversations"][0]
        self.assertEqual(row["hr_name"], "示例招聘官猎")
        self.assertEqual(row["company"], "虚构远山网络有限公司")
        self.assertEqual(row["title"], "产品经理")
        self.assertEqual(row["unread_count"], 2)
        self.assertTrue(row["unread"])
        self.assertEqual(row["last_message"], "你好，方便沟通吗")
        self.assertEqual(row["last_direction"], "hr")
        self.assertTrue(row["has_reply"])
        self.assertEqual(self.page.list_calls, 1)
        self.assertEqual(self.page.new_tabs, [], "the user's drawer tab is reused")
        self.assertEqual(self.page.closed, [], "the user's own tab is never closed")
        params = runtime._liepin_history_params[row["id"]]
        self.assertEqual(params["opposite_im_id"], "opposite-0001")
        exported = json.dumps(result, ensure_ascii=False)
        for secret in ("account-0001", "user-0001", "token-fixture-value", "opposite-0001"):
            self.assertNotIn(secret, exported)

    def test_liepin_list_failure_falls_back_to_the_dom_in_the_same_tab(self):
        self.page.liepin_list = "error"
        result = runtime.list_conversations("liepin")
        self.assertEqual(result["source"], "dom")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["conversations"][0]["hr_name"], "示例招聘官猎")
        self.assertEqual(self.page.list_calls, 1, "a failure is not retried")
        self.assertTrue(all(tab["background"] for tab in self.page.new_tabs))
        self.assertNotIn("l-tab", self.page.closed, "the user's own tab is never closed")

    def test_liepin_dom_reports_a_selector_mismatch(self):
        self.page.liepin_list = "error"
        self.page.liepin_dom_mismatch = True
        result = runtime.list_conversations("liepin")
        self.assertEqual(result["source"], "dom")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["fallback_matched"], 3)
        self.assertTrue(result["selector_mismatch"])
        self.assertTrue(result["drawer_found"])
        self.assertEqual(result["wrap_count"], 2)

    def test_liepin_list_reads_the_page_props_not_a_new_request(self):
        listing_script = runtime._liepin_list_expression()
        self.assertIn("__reactInternalInstance$", listing_script)
        self.assertIn("__reactFiber$", listing_script)
        self.assertIn("props.contact", listing_script)
        self.assertNotIn("fetch(", listing_script, "no request is sent from the reader")
        history_script = runtime._liepin_history_expression({"hr_name": "甲", "company": "乙"})
        self.assertIn("__reactInternalInstance$", history_script)
        self.assertIn("props.getChatList", history_script)
        self.assertIn("reader(''", history_script)

    def test_liepin_history_uses_the_interface_contact_id(self):
        listed = runtime.list_conversations("liepin")
        conversation_id = listed["conversations"][0]["id"]
        thread = runtime.get_thread(conversation_id, "liepin")
        self.assertEqual(thread["source"], "api")
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "hr"])
        history_script = next(script for script in self.page.scripts if "reader(''" in script)
        self.assertIn("opposite-0001", history_script)
        self.assertEqual(self.page.new_tabs, [], "the user's drawer tab is reused")

    def test_zhilian_history_uses_the_nim_sdk(self):
        self._seed_cache("zhilian", "d" * 32)
        runtime._zhilian_history_params["d" * 32] = {"peer_id": "peer-0001"}
        thread = runtime.get_thread("d" * 32, "zhilian")
        self.assertEqual(thread["source"], "api")
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "hr"])
        self.assertEqual(thread["messages"][0]["text"], "你好，方便沟通吗")
        self.assertEqual(thread["messages"][2]["text"], "[名片] 示例职位")
        self.assertEqual([m["mid"] for m in thread["messages"]], ["9001", "9002", "9003"])
        self.assertTrue(thread["reply_allowed"], "the peer id is known, so a confirmed reply may be sent")
        self.assertEqual(self.page.new_tabs, [])

    def _seed_cache(self, platform: str, conversation_id: str) -> None:
        runtime._remember_conversations([{
            "id": conversation_id,
            "platform": platform,
            "company": "虚构示例有限公司",
            "title": "",
            "hr_name": "示例招聘官",
            "hr_title": "",
            "last_message": "",
            "last_message_at": "",
            "unread": False,
        }], platform)

    def test_zhilian_history_without_interface_ids_falls_back_to_the_dom(self):
        self._seed_cache("zhilian", "a" * 32)
        thread = runtime.get_thread("a" * 32, "zhilian")
        self.assertEqual(thread["source"], "dom")
        self.assertTrue(self.page.new_tabs)
        self.assertTrue(all(tab["background"] for tab in self.page.new_tabs))

    def test_liepin_history_uses_the_drawer_store_and_our_side_is_direction_zero(self):
        self._seed_cache("liepin", "c" * 32)
        thread = runtime.get_thread("c" * 32, "liepin")
        self.assertEqual(thread["source"], "api")
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "hr"])
        self.assertEqual(thread["messages"][1]["text"], "您好，可以")
        self.assertIn("x.png", thread["messages"][2]["text"])
        self.assertEqual([m["mid"] for m in thread["messages"]], ["8001", "8002", "8003"])
        self.assertEqual(self.page.new_tabs, [], "the user's drawer tab is reused")
        self.assertEqual(self.page.closed, [])

    def test_liepin_history_falls_back_to_the_dom_when_the_store_is_missing(self):
        self._seed_cache("liepin", "b" * 32)
        self.page.liepin_store = "missing"
        thread = runtime.get_thread("b" * 32, "liepin")
        self.assertEqual(thread["source"], "dom")
        self.assertTrue(self.page.new_tabs)
        self.assertTrue(all(tab["background"] for tab in self.page.new_tabs))


class _SendPage(_FakePage):
    """Fake page that also answers the send expressions."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []
        self.typed: list[str] = []
        self.send_result: dict = {"ok": True, "accepted": True}
        self.open_result: dict = {"ok": True}
        self.type_result: dict = {"ok": True, "cleared": True}

    def evaluate(self, target_id, script, timeout=None):
        if "instance.sendText" in script:
            self.sent.append(script)
            return json.dumps(self.send_result)
        if "hits[0].click()" in script:
            return json.dumps(self.open_result)
        if "readEditor" in script:
            self.typed.append(script)
            return json.dumps(self.type_result)
        return super().evaluate(target_id, script, timeout=timeout)


class ReplySendTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        runtime._zhilian_history_params.clear()
        runtime._liepin_history_params.clear()
        self.addCleanup(runtime._reset_conversation_cache)
        self.addCleanup(runtime._zhilian_history_params.clear)
        self.addCleanup(runtime._liepin_history_params.clear)
        self.temp = tempfile.TemporaryDirectory(prefix="zl-send-test-")
        self.addCleanup(self.temp.cleanup)
        self.page = _SendPage()
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        for patcher in (
            patch.object(runtime, "_hr_store_root", Path(self.temp.name)),
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.page),
            patch.object(runtime, "_runtime_config", return_value={"monitor": {}}),
            patch.object(runtime, "_store_jobs", return_value=JOBS),
            patch.object(runtime, "_stop_requested", return_value=False),
            patch.object(runtime, "_risk_lock_reason", return_value=None),
            patch.object(runtime, "_background_task_running", return_value=False),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _send(self, platform: str, text: str = "您好，方便沟通。"):
        conversation_id = runtime.list_conversations(platform)["conversations"][0]["id"]
        return runtime.send_reply(
            conversation_id, text,
            confirm=runtime.REPLY_CONFIRM_PHRASE, risk_acknowledged=True,
        )

    def test_zhilian_reply_goes_through_the_users_own_tab(self):
        result = self._send("zhilian")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.page.sent), 1)
        self.assertIn("peer-0001", self.page.sent[0])
        self.assertIn("您好，方便沟通。", self.page.sent[0])
        self.assertEqual(self.page.new_tabs, [], "the user's tab is reused")
        self.assertNotIn("z-tab", self.page.closed, "the user's own tab is never closed")

    def test_zhilian_reply_without_platform_confirmation_is_an_error(self):
        self.page.send_result = {"error": "平台 12 秒内没有确认"}
        with self.assertRaises(ValueError) as ctx:
            self._send("zhilian")
        self.assertIn("智联", str(ctx.exception))

    def test_zhilian_reply_needs_the_peer_id_from_the_interface_listing(self):
        self.page.zhilian_mode = "error"  # listing falls back to the DOM: no peer id
        with self.assertRaises(ValueError):
            self._send("zhilian")
        self.assertEqual(self.page.sent, [])

    def test_confirmation_phrase_is_still_required(self):
        conversation_id = runtime.list_conversations("zhilian")["conversations"][0]["id"]
        with self.assertRaises(ValueError):
            runtime.send_reply(conversation_id, "您好", confirm="确认", risk_acknowledged=True)
        with self.assertRaises(ValueError):
            runtime.send_reply(
                conversation_id, "您好", confirm=runtime.REPLY_CONFIRM_PHRASE, risk_acknowledged=False,
            )
        self.assertEqual(self.page.sent, [])

    def test_zhilian_thread_allows_reply_only_when_the_peer_id_is_known(self):
        conversation_id = runtime.list_conversations("zhilian")["conversations"][0]["id"]
        self.assertTrue(runtime.get_thread(conversation_id, "zhilian")["reply_allowed"])
        runtime._zhilian_history_params.clear()
        thread = runtime.get_thread(conversation_id, "zhilian")
        self.assertFalse(thread["reply_allowed"])
        self.assertIn("刷新会话列表", thread["reply_block_reason"])

    def test_liepin_reply_clicks_the_contact_then_types_and_sends(self):
        result = self._send("liepin")
        self.assertTrue(result["ok"])
        self.assertEqual(len(self.page.typed), 1)
        self.assertIn("您好，方便沟通。", self.page.typed[0])
        self.assertEqual(self.page.new_tabs, [], "the user's drawer tab is reused")
        self.assertNotIn("l-tab", self.page.closed)

    def test_liepin_reply_accepts_a_page_history_echo_when_the_editor_kept_the_text(self):
        self.page.type_result = {"ok": True, "cleared": False}
        # LIEPIN_HISTORY already holds our sentence 「您好，可以」.
        self.assertTrue(self._send("liepin", "您好，可以")["ok"])

    def test_liepin_reply_is_unconfirmed_without_echo_or_cleared_editor(self):
        self.page.type_result = {"ok": True, "cleared": False}
        with self.assertRaises(ValueError) as ctx:
            self._send("liepin", "全新的一句话")
        self.assertIn("猎聘", str(ctx.exception))

    def test_liepin_reply_refuses_when_the_contact_is_not_unique(self):
        self.page.open_result = {"ok": False, "reason": "ambiguous"}
        with self.assertRaises(ValueError):
            self._send("liepin")
        self.assertEqual(self.page.typed, [])

    def test_captcha_pages_are_never_used_as_a_chat_tab(self):
        self.page.tabs.insert(0, {
            "targetId": "captcha-tab",
            "url": "https://safe.liepin.com/page/liepin/captchaPage_PC?euuid=fixture",
        })
        self.assertEqual(runtime._find_chat_tab(self.page, "liepin"), "l-tab")

    def test_51job_has_no_reply_path(self):
        entry = {"id": "e" * 32, "platform": "51job", "hr_name": "示例", "company": "虚构"}
        runtime._remember_conversations([{
            **entry, "title": "", "hr_title": "", "last_message": "", "last_message_at": "", "unread": False,
        }], "51job")
        with self.assertRaises(ValueError):
            runtime.send_reply(
                "e" * 32, "您好", confirm=runtime.REPLY_CONFIRM_PHRASE, risk_acknowledged=True,
            )


class LiepinEditorScopeTests(unittest.TestCase):
    """猎聘点开联系人后，输入框与「发送」在独立的聊天窗口里，不在抽屉里（真实页面核对过）。"""

    def test_editor_is_looked_up_in_the_chat_modal_first(self):
        script = runtime._liepin_type_expression("你好", "祝女士")
        self.assertIn(".im-ui-basic-chat-modal", script)
        self.assertLess(script.index("querySelector('.im-ui-basic-chat-modal')"), script.index("querySelector('#im-basic-contact')"))

    def test_chat_window_must_show_the_target_hr_before_typing(self):
        script = runtime._liepin_type_expression("你好", "祝女士")
        self.assertIn('"祝女士"', script)
        self.assertIn("wrong_contact", script)
        self.assertLess(script.index("wrong_contact"), script.index("execCommand"))


if __name__ == "__main__":
    unittest.main()
