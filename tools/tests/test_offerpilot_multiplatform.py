#!/usr/bin/env python3
"""Read-only multi-platform collection and HR-chat contracts.

Fictional rows only.  Browser helpers are replaced with a fake page object, so
no tab is opened and no message is ever sent.
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

import backend  # noqa: E402
import offerpilot_runtime  # noqa: E402

JOBS = [{
    "id": "j-zhilian-1",
    "company": "虚构智联有限公司",
    "title": "产品经理",
    "hr_name": "示例招聘官",
    "offerpilot_id": "op-zhilian-1",
}]


class _FakeGuard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _FakePlatformMonitor:
    """Records which read-only scripts ran and returns canned rows."""

    MonitorSafetyGuard = _FakeGuard

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.scripts: list[str] = []
        self.closed: list[str] = []
        self.opened = 0
        self.chat_rows = [{
            "company": "虚构智联有限公司",
            "hr_name": "示例招聘官",
            "hr_title": "招聘HR",
            "last_message": "你好，方便沟通吗",
            "last_message_at": "11-16 10:20",
            "has_unread": True,
        }]
        self.thread_rows = [
            {"sender": "hr", "text": "你好，方便沟通吗"},
            {"sender": "me", "text": "您好，方便"},
            {"sender": "unknown", "text": "x" * 800},
        ]

    def get_page_targets(self):
        # No real browser: never borrow the machine's own tabs in tests.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        self.urls.append(url)
        self.opened += 1
        return "tab-platform"

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
        self.closed.append(target_id)

    def evaluate(self, target_id, script):
        self.scripts.append(script)
        if script == offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW:
            return json.dumps({"available": True, "opened": True})
        if script == offerpilot_runtime.JS_ZHILIAN_CHAT_LIST:
            return json.dumps({"available": True, "rows": self.chat_rows}, ensure_ascii=False)
        if script == offerpilot_runtime.JS_LIEPIN_CHAT_LIST:
            return json.dumps({"available": True, "rows": self.chat_rows}, ensure_ascii=False)
        if "target.click()" in script:
            return json.dumps({"available": True}, ensure_ascii=False)
        if script in {offerpilot_runtime.JS_ZHILIAN_THREAD, offerpilot_runtime.JS_LIEPIN_THREAD}:
            return json.dumps({"available": True, "rows": self.thread_rows}, ensure_ascii=False)
        return json.dumps({"available": True})


class PlatformChatTests(unittest.TestCase):
    def setUp(self) -> None:
        offerpilot_runtime._reset_conversation_cache()
        self.addCleanup(offerpilot_runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(offerpilot_runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.fake = _FakePlatformMonitor()
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

    def _list(self, platform):
        return offerpilot_runtime.list_conversations(platform)

    def test_zhilian_list_and_thread_are_read_only_and_carry_platform(self):
        listing = self._list("zhilian")
        self.assertTrue(listing["ok"])
        self.assertTrue(listing["available"])
        self.assertEqual(listing["platform"], "zhilian")
        self.assertEqual(listing["count"], 1)
        row = listing["conversations"][0]
        self.assertRegex(row["id"], r"^[0-9a-f]{32}$")
        self.assertEqual(row["platform"], "zhilian")
        self.assertEqual(row["company"], "虚构智联有限公司")
        self.assertEqual(row["job_id"], "j-zhilian-1")
        self.assertTrue(row["unread"])
        self.assertIn(offerpilot_runtime.PLATFORM_CHAT_URLS["zhilian"], self.fake.urls)

        thread = offerpilot_runtime.get_thread(row["id"], "zhilian")
        self.assertTrue(thread["ok"])
        self.assertEqual(thread["platform"], "zhilian")
        self.assertEqual(thread["conversation_id"], row["id"])
        self.assertEqual([m["sender"] for m in thread["messages"]], ["hr", "me", "system"])
        self.assertEqual(len(thread["messages"][2]["text"]), 500)
        self.assertFalse(thread["reply_allowed"])
        self.assertIn("只读", thread["reply_block_reason"])
        self.assertIn("tab-platform", self.fake.closed)

    def test_liepin_opens_the_drawer_then_reads_contacts(self):
        listing = self._list("liepin")
        self.assertTrue(listing["available"])
        self.assertEqual(listing["platform"], "liepin")
        self.assertEqual(listing["count"], 1)
        self.assertIn(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW, self.fake.scripts)
        self.assertNotIn(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER, self.fake.scripts)
        self.assertIn(offerpilot_runtime.PLATFORM_CHAT_URLS["liepin"], self.fake.urls)
        # The drawer lives on the www job page, not the old home page.
        self.assertEqual(
            offerpilot_runtime.PLATFORM_CHAT_URLS["liepin"],
            "https://www.liepin.com/zhaopin/",
        )

        row = listing["conversations"][0]
        thread = offerpilot_runtime.get_thread(row["id"], "liepin")
        self.assertTrue(thread["available"])
        self.assertEqual(len(thread["messages"]), 3)
        self.assertFalse(thread["reply_allowed"])

    def test_captcha_or_rate_limit_reports_unavailable_instead_of_crashing(self):
        class MonitorRiskDetected(RuntimeError):
            pass

        with patch.object(
            offerpilot_runtime, "_open_platform_tab", side_effect=MonitorRiskDetected("captcha")
        ):
            listing = offerpilot_runtime.list_conversations("zhilian")
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["platform"], "zhilian")
        self.assertIn("验证码", listing["error"])

    def test_51job_reports_unavailable_without_opening_a_tab(self):
        listing = self._list("51job")
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["platform"], "51job")
        self.assertEqual(listing["conversations"], [])
        self.assertEqual(self.fake.opened, 0)
        self.assertEqual(
            listing["error"],
            "前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息",
        )

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            offerpilot_runtime.list_conversations("xiaoyuan")

    def test_contact_details_are_redacted_from_returns(self):
        self.fake.chat_rows[0]["last_message"] = "加微信 abcdef123456 或 13800138000，邮箱 hr@example.com"
        self.fake.thread_rows = [{
            "sender": "hr",
            "text": "电话 13800138000，微信 abcdef123456，邮箱 hr@example.com",
        }]
        listing = self._list("zhilian")
        message = listing["conversations"][0]["last_message"]
        for secret in ("abcdef123456", "13800138000", "hr@example.com"):
            self.assertNotIn(secret, message)
        thread = offerpilot_runtime.get_thread(listing["conversations"][0]["id"], "zhilian")
        text = thread["messages"][0]["text"]
        for secret in ("abcdef123456", "13800138000", "hr@example.com"):
            self.assertNotIn(secret, text)

    def test_thread_rejects_a_mismatched_platform(self):
        listing = self._list("zhilian")
        with self.assertRaises(ValueError):
            offerpilot_runtime.get_thread(listing["conversations"][0]["id"], "liepin")

    def test_reply_is_refused_for_non_boss_platforms(self):
        listing = self._list("zhilian")
        with patch.object(
            offerpilot_runtime, "_stop_requested", return_value=False
        ), patch.object(offerpilot_runtime, "_risk_lock_reason", return_value=None):
            with self.assertRaises(ValueError) as ctx:
                offerpilot_runtime.send_reply(
                    listing["conversations"][0]["id"],
                    "您好，方便沟通。",
                    confirm=offerpilot_runtime.REPLY_CONFIRM_PHRASE,
                    risk_acknowledged=True,
                )
        self.assertIn("BOSS", str(ctx.exception))
        # The listing opened the list tab plus one refresh read per listed
        # conversation; refusing the reply must not open anything further.
        self.assertEqual(self.fake.opened, 2)


class LiepinParserContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from offerpilot.collection.platforms import liepin
        cls.liepin = liepin

    def test_list_parser_covers_the_split_view_card_layout(self):
        script = self.liepin.JS_EXTRACT_LIST
        self.assertIn(".job-card-pc-container", script)
        self.assertIn("data-tlg-ext", script)
        self.assertIn(".search-job-card-name-text", script)
        self.assertIn("https://www.liepin.com/job/", script)
        # The legacy anchor layout stays supported.
        self.assertIn('a[data-nick="job-detail-job-info"]', script)

    def test_detail_parser_reads_the_read_only_split_pane(self):
        self.assertIn("#search-job-detail", self.liepin.JS_EXTRACT_SPLIT_DETAIL)
        self.assertIn("职位描述", self.liepin.JS_EXTRACT_SPLIT_DETAIL)
        self.assertIn("__JOB_ID__", self.liepin.JS_SELECT_CARD)
        self.assertIn("cards[i].click()", self.liepin.JS_SELECT_CARD)
        # Nothing in the split-view path may click apply/chat controls.
        for script in (self.liepin.JS_SELECT_CARD, self.liepin.JS_EXTRACT_SPLIT_DETAIL):
            self.assertNotIn("投简历", script)
            self.assertNotIn("聊一聊", script)


class FullModePlatformGateTests(unittest.TestCase):
    def test_full_mode_still_rejects_platforms_without_deliver(self):
        config = {"collection": {"platforms": {}}}
        for platform in ("zhilian", "51job", "liepin"):
            with self.subTest(platform=platform):
                raw = {
                    "platform_order": [platform],
                    "platforms": {platform: {"keywords": ["产品经理"], "cities": ["上海"], "max_pages": 1}},
                    "auto_score": False,
                    "pace": "cautious",
                }
                with self.assertRaises(ValueError) as ctx:
                    offerpilot_runtime._task_options("full", config, raw)
                self.assertIn("只能单独采集", str(ctx.exception))


class BackendChatDispatchTests(unittest.TestCase):
    def test_backend_passes_platform_through(self):
        with patch.object(
            offerpilot_runtime,
            "cached_conversations",
            return_value={"ok": True, "available": True, "platform": "liepin", "conversations": [], "count": 0},
        ) as listing, patch.object(
            offerpilot_runtime,
            "get_thread",
            return_value={"ok": True, "available": True, "platform": "liepin", "messages": []},
        ) as thread:
            backend.get_offerpilot_conversations("user", "liepin")
            backend.get_offerpilot_conversation("user", "a" * 32, "liepin")
        listing.assert_called_once_with("liepin")
        thread.assert_called_once_with("a" * 32, "liepin")

    def test_mode_is_ignored_and_invalid_platforms_are_rejected(self):
        """``mode`` is a compatibility field; the platform allow-list still applies."""
        listing_payload = {
            "ok": True, "available": True, "platform": "zhilian", "conversations": [], "count": 0,
        }
        with patch.object(offerpilot_runtime, "list_conversations", return_value=listing_payload):
            listing = backend.get_offerpilot_conversations("demo", "zhilian")
        self.assertTrue(listing["available"])
        self.assertEqual(listing["platform"], "zhilian")

        thread_payload = {"ok": True, "available": True, "platform": "51job", "messages": []}
        with patch.object(offerpilot_runtime, "get_thread", return_value=thread_payload):
            thread = backend.get_offerpilot_conversation("demo", "a" * 32, "51job")
        self.assertTrue(thread["available"])
        self.assertEqual(thread["platform"], "51job")

        with self.assertRaises(backend.ApiError):
            backend.get_offerpilot_conversations("user", "xiaoyuan")


class ConversationAggregationTests(unittest.TestCase):
    """Read-only four-platform merge; every fake, no browser is touched."""

    def setUp(self) -> None:
        offerpilot_runtime._reset_conversation_cache()
        self.addCleanup(offerpilot_runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(offerpilot_runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)

    @staticmethod
    def _row(platform: str) -> dict:
        company = f"虚构{platform}公司"
        return {
            "id": offerpilot_runtime._conversation_id(company, "示例招聘官", "招聘HR", platform),
            "platform": platform,
            "company": company,
            "title": "产品经理",
            "hr_name": "示例招聘官",
            "hr_title": "招聘HR",
            "last_message": "你好，方便沟通吗",
            "last_message_at": "11-16 10:20",
            "unread": False,
            "job_id": None,
        }

    def _aggregate_with(self, results):
        def fake_list(platform):
            value = results[platform]
            if isinstance(value, Exception):
                raise value
            return value

        with patch.object(offerpilot_runtime, "list_conversations", side_effect=fake_list):
            return offerpilot_runtime.list_all_conversations()

    def test_one_failing_platform_keeps_the_others(self):
        results = {
            "boss": {"ok": True, "available": True, "conversations": [self._row("boss")], "count": 1},
            "zhilian": {"ok": True, "available": True, "conversations": [self._row("zhilian")], "count": 1},
            "51job": {
                "ok": False,
                "available": False,
                "conversations": [],
                "count": 0,
                "error": "前程无忧网页聊天不可读，联系 hr@example.com",
            },
            "liepin": ValueError("猎聘读取失败"),
        }
        listing = self._aggregate_with(results)
        self.assertTrue(listing["ok"])
        self.assertTrue(listing["available"])
        self.assertEqual(listing["platform"], "all")
        self.assertEqual(listing["count"], 2)
        self.assertEqual({row["platform"] for row in listing["conversations"]}, {"boss", "zhilian"})
        self.assertEqual([p["platform"] for p in listing["platforms"]], ["boss", "zhilian", "51job", "liepin"])
        by_platform = {p["platform"]: p for p in listing["platforms"]}
        self.assertFalse(by_platform["51job"]["available"])
        self.assertFalse(by_platform["liepin"]["available"])
        self.assertEqual(set(listing["errors"]), {"51job", "liepin"})
        self.assertIn("猎聘读取失败", listing["errors"]["liepin"])
        # Contact details never reach the aggregated error text.
        self.assertNotIn("hr@example.com", listing["errors"]["51job"])
        self.assertIn("[联系方式已隐藏]", listing["errors"]["51job"])

    def test_every_row_is_cached_with_its_platform(self):
        results = {
            "boss": {"ok": True, "available": True, "conversations": [self._row("boss")], "count": 1},
            "zhilian": {"ok": True, "available": True, "conversations": [self._row("zhilian")], "count": 1},
            "51job": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
            "liepin": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
        }
        listing = self._aggregate_with(results)
        for row in listing["conversations"]:
            cached = offerpilot_runtime._cached_conversation(row["id"])
            self.assertEqual(cached["platform"], row["platform"])

    def test_all_platforms_failing_reports_each_reason(self):
        listing = self._aggregate_with({p: ValueError(f"{p} 未登录") for p in offerpilot_runtime.CHAT_PLATFORMS})
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["conversations"], [])
        self.assertEqual(set(listing["errors"]), set(offerpilot_runtime.CHAT_PLATFORMS))
        self.assertIn("所有平台都未能读取会话", listing["error"])
        for label in ("BOSS", "智联", "前程无忧", "猎聘"):
            self.assertIn(label, listing["error"])

    def test_thread_resolves_platform_from_the_aggregated_list(self):
        results = {
            "boss": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "未登录"},
            "zhilian": {"ok": True, "available": True, "conversations": [self._row("zhilian")], "count": 1},
            "51job": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
            "liepin": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
        }
        listing = self._aggregate_with(results)
        row = listing["conversations"][0]
        canned = {"ok": True, "available": True, "platform": "zhilian", "conversation_id": row["id"], "messages": []}
        with patch.object(offerpilot_runtime, "_get_zhilian_thread", return_value=canned) as reader:
            thread = offerpilot_runtime.get_thread(row["id"], "all")
        reader.assert_called_once()
        self.assertEqual(thread["platform"], "zhilian")

    def test_thread_platform_mismatch_is_rejected(self):
        results = {
            "boss": {"ok": True, "available": True, "conversations": [self._row("boss")], "count": 1},
            "zhilian": {"ok": True, "available": True, "conversations": [self._row("zhilian")], "count": 1},
            "51job": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
            "liepin": {"ok": False, "available": False, "conversations": [], "count": 0, "error": "不可读"},
        }
        listing = self._aggregate_with(results)
        zhilian_row = next(row for row in listing["conversations"] if row["platform"] == "zhilian")
        with self.assertRaises(ValueError):
            offerpilot_runtime.get_thread(zhilian_row["id"], "boss")

    def test_same_company_on_two_platforms_gets_distinct_ids(self):
        boss_id = offerpilot_runtime._conversation_id("虚构公司", "示例招聘官", "招聘HR", "boss")
        zhilian_id = offerpilot_runtime._conversation_id("虚构公司", "示例招聘官", "招聘HR", "zhilian")
        self.assertNotEqual(boss_id, zhilian_id)
        self.assertRegex(boss_id, r"^[0-9a-f]{32}$")
        self.assertNotIn("虚构", boss_id)


if __name__ == "__main__":
    unittest.main()
