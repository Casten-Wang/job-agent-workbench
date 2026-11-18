#!/usr/bin/env python3
"""HR 会话正文读成空时的兜底（智联/猎聘）与强制刷新。

全部是虚构数据：不连浏览器、不联网、不发送任何消息。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "web"), str(PROJECT_ROOT / "vendor" / "offerpilot" / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import offerpilot_runtime as runtime  # noqa: E402

ENTRY = {
    "id": "a" * 32,
    "company": "虚构猎聘科技有限公司",
    "hr_name": "示例招聘官",
    "last_message": "你好，这里有个岗位适合你",
    "last_message_at": "11-17 20:32",
    "last_direction": "hr",
}
EMPTY_OK = {"ok": True, "available": True, "messages": [], "reply_allowed": False}


class PreviewFallbackTests(unittest.TestCase):
    def test_empty_body_on_a_web_read_platform_shows_the_list_preview(self):
        for platform in ("liepin", "zhilian"):
            with self.subTest(platform=platform):
                response = runtime._with_preview_fallback(dict(EMPTY_OK), ENTRY, platform)
                self.assertEqual(len(response["messages"]), 1)
                message = response["messages"][0]
                self.assertEqual(message["sender"], "hr")
                self.assertEqual(message["text"], ENTRY["last_message"])
                self.assertTrue(message["preview"])
                self.assertTrue(response["preview_only"])
                self.assertFalse(response["reply_allowed"])

    def test_preview_is_not_added_for_boss_real_messages_or_failures(self):
        self.assertEqual(runtime._with_preview_fallback(dict(EMPTY_OK), ENTRY, "boss")["messages"], [])
        real = {**EMPTY_OK, "messages": [{"sender": "hr", "text": "真实消息"}]}
        self.assertEqual(runtime._with_preview_fallback(real, ENTRY, "liepin")["messages"], real["messages"])
        failed = {"ok": False, "messages": []}
        self.assertEqual(runtime._with_preview_fallback(failed, ENTRY, "liepin")["messages"], [])
        quiet = {**ENTRY, "last_message": "  "}
        self.assertEqual(runtime._with_preview_fallback(dict(EMPTY_OK), quiet, "liepin")["messages"], [])

    def test_my_own_last_message_is_attributed_to_me(self):
        mine = {**ENTRY, "last_direction": "me"}
        message = runtime._with_preview_fallback(dict(EMPTY_OK), mine, "liepin")["messages"][0]
        self.assertEqual(message["sender"], "me")

    def test_preview_text_never_leaks_contact_details(self):
        leaky = {**ENTRY, "last_message": "加我邮箱 demo.person@example.com 聊聊"}
        text = runtime._with_preview_fallback(dict(EMPTY_OK), leaky, "liepin")["messages"][0]["text"]
        self.assertNotIn("demo.person@example.com", text)


class EmptyStoredBodyRetryTests(unittest.TestCase):
    def _record(self, fetched_at):
        return {"messages": [], "body_read": True, "fetched_at": fetched_at, "stale": False}

    def _stored(self, platform, record):
        key = runtime._hr_store_key({**ENTRY, "platform": platform})
        with patch.object(runtime, "_load_hr_store", return_value={key: record}):
            return runtime._stored_body_for(dict(ENTRY), platform)

    def test_recent_empty_body_is_served_without_reading_again(self):
        self.assertIsNotNone(self._stored("liepin", self._record(runtime._hr_now())))

    def test_old_empty_body_is_read_again_when_the_list_shows_a_message(self):
        old = "2020-01-01T00:00:00+00:00"
        self.assertIsNone(self._stored("liepin", self._record(old)))

    def test_boss_empty_body_stays_authoritative(self):
        old = "2020-01-01T00:00:00+00:00"
        self.assertIsNotNone(self._stored("boss", self._record(old)))


class ForceRefreshTests(unittest.TestCase):
    def test_force_is_only_forwarded_when_requested(self):
        with patch.object(runtime, "get_thread", return_value={"ok": True, "messages": []}) as thread:
            backend.get_offerpilot_conversation("user", "b" * 32, "liepin")
            thread.assert_called_with("b" * 32, "liepin")
            backend.get_offerpilot_conversation("user", "b" * 32, "liepin", force=True)
            thread.assert_called_with("b" * 32, "liepin", force=True)

    def test_force_skips_the_stored_body(self):
        stored = {"messages": [], "body_read": True, "platform": "liepin"}
        with patch.object(runtime, "_cached_conversation", return_value=dict(ENTRY, platform="liepin")), \
                patch.object(runtime, "_stored_body_for", return_value=stored) as stored_body, \
                patch.object(runtime, "_open_and_store_thread", return_value=dict(EMPTY_OK)) as opened:
            runtime.get_thread("c" * 32, "liepin", force=True)
            stored_body.assert_not_called()
            opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
