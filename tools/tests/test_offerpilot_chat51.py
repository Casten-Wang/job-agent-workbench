#!/usr/bin/env python3
"""51job chat-list parser contracts — pure HTML in, read-only rows out.

依据 JS 与 DOM 线索合成，未经真实页面验证。

The parser mirrors the class names of the 51job IM SDK conversation templates
(see ``web/offerpilot_chat51.py``).  Every test here reads the fictional fixture
``fixtures/job51_chat_list.html`` or a small inline page: no browser, no
network, no token, no accountId.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _path in (str(WEB_DIR),):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_chat51  # noqa: E402

FIXTURE = FIXTURES / "job51_chat_list.html"


def _fixture_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


EMPTY_LIST_PAGE = (
    "<html><body><div id='conversation-list' class='conversation-list'>"
    "<div class='conversation-list-header'>消息</div>"
    "</div></body></html>"
)

OUTSIDE_ITEM_PAGE = (
    "<html><body>"
    "<div id='conversation-list' class='conversation-list'>"
    "<div class='conversation-item'><div class='info'><div class='name'>"
    "<span class='username'>示例招聘官戊</span></div></div></div>"
    "</div>"
    "<div class='recommend-list'>"
    "<div class='conversation-item'><div class='info'><div class='name'>"
    "<span class='username'>列表外推荐位</span></div></div></div>"
    "</div>"
    "</body></html>"
)


class FixtureParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = offerpilot_chat51.parse_chat_rows(_fixture_html())

    def test_module_marks_itself_unverified(self):
        self.assertIn("未经真实页面验证", offerpilot_chat51.__doc__ or "")

    def test_parses_every_conversation_in_document_order(self):
        self.assertEqual(len(self.rows), 4)
        self.assertEqual(
            [row["hr_name"] for row in self.rows],
            ["示例招聘官甲", "示例招聘官乙", "示例招聘官丙", "示例招聘官丁"],
        )

    def test_row_carries_the_shared_read_only_shape(self):
        first = self.rows[0]
        self.assertEqual(first["platform"], "51job")
        self.assertEqual(first["company"], "")
        self.assertEqual(first["title"], "虚构产品经理")
        self.assertEqual(first["hr_title"], "虚构产品经理")
        self.assertEqual(first["last_message"], "您好，方便沟通一下岗位吗")
        self.assertEqual(first["date"], "11-17 09:20")
        self.assertEqual(first["last_message_at"], "11-17 09:20")
        self.assertTrue(first["unread"])
        self.assertTrue(first["has_unread"])
        self.assertTrue(first["has_reply"])
        self.assertRegex(first["conversation_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(first["id"], first["conversation_id"])

    def test_missing_unread_badge_means_read(self):
        third = self.rows[2]
        self.assertFalse(third["unread"])
        self.assertFalse(third["has_unread"])
        self.assertFalse(third["pinned"])

    def test_pinned_marker_is_reported_and_order_is_kept(self):
        self.assertTrue(self.rows[0]["pinned"])
        self.assertFalse(any(row["pinned"] for row in self.rows[1:]))
        self.assertEqual(self.rows[0]["hr_name"], "示例招聘官甲")

    def test_hidden_badge_does_not_mark_unread(self):
        fourth = self.rows[3]
        self.assertFalse(fourth["unread"])

    def test_missing_fields_do_not_crash_the_parser(self):
        fourth = self.rows[3]
        self.assertEqual(fourth["hr_name"], "示例招聘官丁")
        self.assertEqual(fourth["title"], "")
        self.assertEqual(fourth["last_message"], "")
        self.assertEqual(fourth["date"], "")
        self.assertFalse(fourth["has_reply"])
        self.assertRegex(fourth["conversation_id"], r"^[0-9a-f]{32}$")

    def test_ids_are_stable_across_parses_and_distinct_per_row(self):
        first_pass = [row["conversation_id"] for row in self.rows]
        second_pass = [
            row["conversation_id"]
            for row in offerpilot_chat51.parse_chat_rows(_fixture_html())
        ]
        self.assertEqual(first_pass, second_pass)
        self.assertEqual(len(set(first_pass)), len(first_pass))

    def test_wrapper_reports_available_and_count(self):
        payload = offerpilot_chat51.parse_chat_list(_fixture_html())
        self.assertTrue(payload["available"])
        self.assertEqual(payload["count"], 4)
        self.assertEqual(len(payload["rows"]), 4)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_list_returns_no_rows(self):
        self.assertEqual(offerpilot_chat51.parse_chat_rows(EMPTY_LIST_PAGE), [])
        payload = offerpilot_chat51.parse_chat_list(EMPTY_LIST_PAGE)
        self.assertEqual(payload["count"], 0)
        self.assertTrue(payload["available"])

    def test_page_without_a_chat_list_returns_no_rows(self):
        self.assertEqual(offerpilot_chat51.parse_chat_rows("<html><body>空白</body></html>"), [])

    def test_items_outside_the_conversation_list_are_ignored(self):
        rows = offerpilot_chat51.parse_chat_rows(OUTSIDE_ITEM_PAGE)
        self.assertEqual([row["hr_name"] for row in rows], ["示例招聘官戊"])

    def test_malformed_html_does_not_raise(self):
        rows = offerpilot_chat51.parse_chat_rows(
            "<div id='conversation-list'><div class='conversation-item'>"
            "<div class='info'><div class='name'><span class='username'>示例招聘官己"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hr_name"], "示例招聘官己")

    def test_none_and_blank_input_are_tolerated(self):
        self.assertEqual(offerpilot_chat51.parse_chat_rows(""), [])
        self.assertEqual(offerpilot_chat51.parse_chat_rows(None), [])

    def test_module_imports_no_browser_or_network_library(self):
        source = Path(offerpilot_chat51.__file__).read_text(encoding="utf-8")
        for forbidden in ("import requests", "urllib.request", "import socket", "selenium", "playwright"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class FixtureSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _fixture_html()

    def test_fixture_has_no_contact_details_or_credentials(self):
        patterns = (
            re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
            re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
            re.compile(r"微信|wechat|weixin", re.IGNORECASE),
            re.compile(r"accountId|token|sdkAppId", re.IGNORECASE),
        )
        for pattern in patterns:
            with self.subTest(pattern=pattern.pattern):
                self.assertIsNone(pattern.search(self.html))

    def test_fixture_is_obviously_fictional(self):
        for marker in ("虚构", "示例"):
            self.assertIn(marker, self.html)

    def test_fixture_contains_every_selector_the_parser_reads(self):
        for selector in (
            "conversation-list", "conversation-item", "username", "jobname",
            "message-date", "messageforshow", "last-message",
            "el-badge__content", "to-top",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.html)


if __name__ == "__main__":
    unittest.main()
