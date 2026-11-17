#!/usr/bin/env python3
"""Conversation cache scope and Liepin list diagnostics.

Regression contract (no browser, no network, nothing sent):

- reading one platform's list replaces only that platform's cached entries;
  conversations from the other platforms stay resolvable for their own TTL;
- the ``platform=all`` aggregate still replaces the whole cache, so a platform
  missing from a later aggregate is dropped;
- 51job reports the fixed WeChat-QR wording with ``available: false`` and no
  page is opened;
- a Liepin list result says which drawer branch ran and how many row nodes the
  selector matched, so ``count=0`` can be told apart from a selector miss.
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

BOSS_ROWS = [{
    "company": "虚构BOSS科技有限公司",
    "hr_name": "示例招聘官",
    "hr_title": "招聘HR",
    "last_message": "你好，方便沟通吗",
    "last_message_at": "11-16 10:20",
    "has_unread": False,
}]
ZHILIAN_ROWS = [{
    "company": "虚构智联有限公司",
    "hr_name": "虚构招聘官乙",
    "hr_title": "HR",
    "last_message": "方便发一份简历吗",
    "last_message_at": "11-16 10:10",
    "has_unread": True,
}]
LIEPIN_ROWS = [{
    "company": "虚构猎聘科技有限公司",
    "hr_name": "王示例",
    "hr_title": "",
    "last_message": "您好，方便沟通吗",
    "last_message_at": "11-16 10:00",
    "has_unread": False,
}]
SIXTY_ONE = "前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息"


class _FakeGuard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _FakeChatMonitor:
    """Serves canned list/thread payloads; records every tab and script."""

    MonitorSafetyGuard = _FakeGuard
    JS_EXTRACT_CHAT_LIST = "js:boss-chat-list"

    def __init__(self, *, chat_rows, liepin_branch="clicked_entry", liepin_matched=None,
                 liepin_rows=None) -> None:
        self.chat_rows = chat_rows
        self.zhilian_down = False
        self.liepin_branch = liepin_branch
        self.liepin_matched = liepin_matched
        self.liepin_rows = liepin_rows
        self.urls: list[str] = []
        self.scripts: list[str] = []
        self.closed: list[str] = []

    def _get_monitor_chat_target(self, chat_url, config):
        return "tab-boss", False

    def _open_monitor_tab(self, url, config, *, background=True):
        self.urls.append(url)
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
        if script == self.JS_EXTRACT_CHAT_LIST:
            return json.dumps(self.chat_rows, ensure_ascii=False)
        if script == runtime.JS_ZHILIAN_CHAT_LIST:
            if self.zhilian_down:
                return json.dumps({"available": False, "reason": "未登录"})
            return json.dumps({"available": True, "rows": self.chat_rows}, ensure_ascii=False)
        if script == runtime.JS_LIEPIN_ENSURE_DRAWER_WWW:
            if self.liepin_branch is None:
                return json.dumps({"available": False, "reason": "未找到猎聘「我的沟通」入口"})
            return json.dumps(
                {"available": True, "opened": True, "branch": self.liepin_branch},
                ensure_ascii=False,
            )
        if script == runtime.JS_LIEPIN_CHAT_LIST:
            rows = self.liepin_rows if self.liepin_rows is not None else self.chat_rows
            matched = self.liepin_matched if self.liepin_matched is not None else len(rows)
            return json.dumps({"available": True, "rows": rows, "matched": matched}, ensure_ascii=False)
        if script in {runtime.JS_ZHILIAN_OPEN_THREAD, runtime.JS_LIEPIN_OPEN_THREAD}:
            return json.dumps({"available": True})
        if script in {runtime.JS_ZHILIAN_THREAD, runtime.JS_LIEPIN_THREAD}:
            return json.dumps({"available": True, "rows": [{"sender": "hr", "text": "你好"}]})
        return json.dumps({"available": True})


class _ChatReadCase(unittest.TestCase):
    chat_rows = ZHILIAN_ROWS

    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)
        self.fake = _FakeChatMonitor(chat_rows=self.chat_rows)
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_monitor", return_value=self.fake),
            patch.object(runtime, "_runtime_config", return_value=self.config),
            patch.object(runtime, "_store_jobs", return_value=[]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class ConversationCacheScopeTests(_ChatReadCase):
    """A single-platform list must not evict the other platforms' rows."""

    def _ids(self, listing):
        return {row["platform"]: row["id"] for row in listing["conversations"]}

    def test_boss_list_after_aggregate_keeps_zhilian_conversations(self):
        aggregate = runtime.list_conversations("all")
        self.assertTrue(aggregate["ok"], aggregate)
        ids = self._ids(aggregate)
        self.assertIn("boss", ids)
        self.assertIn("zhilian", ids)

        boss_only = runtime.list_conversations("boss")
        self.assertTrue(boss_only["ok"])
        self.assertEqual({row["platform"] for row in boss_only["conversations"]}, {"boss"})
        self.assertEqual(self._ids(boss_only)["boss"], ids["boss"])

        # The Zhilian row must still resolve in the cache, as its own platform.
        cached = runtime._cached_conversation(ids["zhilian"])
        self.assertEqual(cached["platform"], "zhilian")
        self.assertEqual(cached["company"], ZHILIAN_ROWS[0]["company"])

    def test_zhilian_thread_still_opens_after_a_boss_only_read(self):
        aggregate = runtime.list_conversations("all")
        zhilian_id = self._ids(aggregate)["zhilian"]
        runtime.list_conversations("boss")

        thread = runtime.get_thread(zhilian_id, "all")
        self.assertTrue(thread["ok"])
        self.assertEqual(thread["platform"], "zhilian")
        self.assertEqual(thread["conversation_id"], zhilian_id)
        self.assertEqual(
            thread["messages"],
            [{"sender": "hr", "text": "你好", "time": "", "platform": "zhilian"}],
        )
        # The aggregate already read and stored this body, so opening it again
        # serves the stored copy and does not touch the platform.
        self.assertTrue(thread["ok"])

    def test_single_platform_read_replaces_only_its_own_stale_rows(self):
        runtime.list_conversations("all")
        first = self._ids(runtime.list_conversations("all"))

        # BOSS now shows a different HR; the old BOSS row must be gone while the
        # Zhilian row from the previous read is untouched.
        self.fake.chat_rows = [dict(BOSS_ROWS[0], hr_name="另一位示例")]
        second_boss = runtime.list_conversations("boss")
        new_boss_id = self._ids(second_boss)["boss"]
        self.assertNotEqual(new_boss_id, first["boss"])
        with self.assertRaises(ValueError):
            runtime._cached_conversation(first["boss"])
        self.assertEqual(runtime._cached_conversation(first["zhilian"])["platform"], "zhilian")

    def test_single_platform_read_does_not_extend_another_platform_ttl(self):
        runtime.list_conversations("all")
        zhilian_id = self._ids(runtime.list_conversations("all"))["zhilian"]

        stale = dict(runtime._conversation_listed_at_by_platform)
        stale["zhilian"] = stale["zhilian"] - runtime.CONVERSATIONS_TTL_SECONDS - 1
        with patch.object(runtime, "_conversation_listed_at_by_platform", stale):
            runtime.list_conversations("boss")
            with self.assertRaises(ValueError):
                runtime._cached_conversation(zhilian_id)

    def test_aggregate_still_replaces_the_whole_cache(self):
        runtime.list_conversations("all")
        zhilian_id = self._ids(runtime.list_conversations("all"))["zhilian"]

        # The next aggregate cannot read Zhilian: its old rows are dropped, as
        # the aggregate path still replaces the whole cache.
        self.fake.zhilian_down = True
        aggregate = runtime.list_conversations("all")
        self.assertNotIn("zhilian", self._ids(aggregate))
        self.assertIn("zhilian", aggregate.get("errors", {}))
        with self.assertRaises(ValueError):
            runtime._cached_conversation(zhilian_id)


class Chat51JobWordingTests(_ChatReadCase):
    def test_51job_list_reports_wechat_wording_without_opening_a_page(self):
        listing = runtime.list_conversations("51job")
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["platform"], "51job")
        self.assertEqual(listing["conversations"], [])
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["error"], SIXTY_ONE)
        self.assertEqual(self.fake.urls, [])
        self.assertEqual(self.fake.scripts, [])
        self.assertEqual(self.fake.closed, [])

    def test_51job_thread_reports_wechat_wording(self):
        entry = {
            "id": runtime._conversation_id("虚构前程无忧有限公司", "示例招聘官", "HR", "51job"),
            "platform": "51job",
            "company": "虚构前程无忧有限公司",
            "title": "产品经理",
            "hr_name": "示例招聘官",
        }
        runtime._remember_conversations([entry], "51job")
        thread = runtime.get_thread(entry["id"], "51job")
        self.assertFalse(thread["available"])
        self.assertFalse(thread["reply_allowed"])
        self.assertTrue(thread["reply_block_reason"].startswith(SIXTY_ONE))
        self.assertEqual(self.fake.urls, [])


class LiepinListDiagnosticsTests(_ChatReadCase):
    """The list result must say which drawer branch ran and what the selector saw."""

    def test_expanded_drawer_reports_branch_and_matched_rows(self):
        self.fake.liepin_branch = "expanded"
        listing = runtime.list_conversations("liepin")
        self.assertTrue(listing["ok"], listing)
        self.assertEqual(listing["count"], len(ZHILIAN_ROWS))
        self.assertEqual(listing["drawer_branch"], "expanded")
        self.assertEqual(listing["matched"], len(ZHILIAN_ROWS))
        self.assertIn(runtime.JS_LIEPIN_ENSURE_DRAWER_WWW, self.fake.scripts)

    def test_clicked_entry_reports_that_branch(self):
        self.fake.liepin_branch = "clicked_entry"
        listing = runtime.list_conversations("liepin")
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["drawer_branch"], "clicked_entry")
        self.assertEqual(listing["matched"], len(ZHILIAN_ROWS))

    def test_zero_rows_with_zero_matched_means_no_conversations_shown(self):
        self.fake.liepin_rows = []
        self.fake.liepin_matched = 0
        listing = runtime.list_conversations("liepin")
        self.assertTrue(listing["ok"])
        self.assertTrue(listing["available"])
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["matched"], 0)
        self.assertEqual(listing["drawer_branch"], "clicked_entry")

    def test_rows_matched_but_none_parsed_is_visible_in_the_result(self):
        self.fake.liepin_rows = []
        self.fake.liepin_matched = 3
        listing = runtime.list_conversations("liepin")
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["count"], 0)
        self.assertEqual(listing["matched"], 3)

    def test_missing_entry_reports_unavailable_and_no_branch(self):
        self.fake.liepin_branch = None
        listing = runtime.list_conversations("liepin")
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertIn("我的沟通", listing["error"])
        self.assertNotIn(runtime.JS_LIEPIN_CHAT_LIST, self.fake.scripts)


if __name__ == "__main__":
    unittest.main()
