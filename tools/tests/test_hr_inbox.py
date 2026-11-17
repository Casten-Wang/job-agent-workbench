#!/usr/bin/env python3
"""Tests for the chat-first HR inbox on the reply page.

Every check is offline: it reads the shipped static files or runs the inbox
helpers with node.  No conversation endpoint is called and nothing is sent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
INDEX = STATIC_DIR / "index.html"
APP = STATIC_DIR / "app.js"
THEME = STATIC_DIR / "offer-theme.css"

INBOX_START = "/* hr-inbox:start"
INBOX_END = "/* hr-inbox:end */"
HR_BLOCK_START = "/* Render: HR conversations"
HR_BLOCK_END = "/* Render: interview */"
OFFLINE_OPEN = '<details class="mail-offline">'


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


def _function_source(script: str, name: str) -> str:
    start = script.index(f"function {name}(")
    end = script.index("\nfunction ", start + 1)
    return script[start:end]


def _run_node(harness_body: str, payload: dict, label: str):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest(f"node 不可用，跳过{label}校验")
    script = _read(APP)
    inbox = script[script.index(INBOX_START) : script.index(INBOX_END) + len(INBOX_END)]
    harness = (
        inbox
        + "\n"
        + _function_source(script, "hrPlatformErrorsFrom")
        + "\nconst fs = require('fs');\n"
        "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        + harness_body
    )
    completed = subprocess.run(
        [node, "-e", harness],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"node 执行{label}失败：{completed.stderr[:800]}")
    return json.loads(completed.stdout)


class HrInboxMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.theme = _read(THEME)
        cls.mail_view = _between(cls.html, 'id="view-mail"', 'id="view-interview"')
        cls.hr_panel = _between(cls.mail_view, 'id="hr-conversations-panel"', OFFLINE_OPEN)
        cls.offline = _between(cls.mail_view, OFFLINE_OPEN, "</details>")

    def test_reply_page_opens_with_the_conversation_inbox(self):
        self.assertLess(
            self.mail_view.index('id="hr-conversations-panel"'),
            self.mail_view.index(OFFLINE_OPEN),
        )
        lede = _between(self.mail_view, 'class="view-lede"', "</p>")
        self.assertIn("收件箱", lede)

    def test_offline_mail_parsing_is_folded_away_by_default(self):
        opening_tag = self.mail_view[self.mail_view.index(OFFLINE_OPEN) :].split(">", 1)[0] + ">"
        self.assertEqual(opening_tag, OFFLINE_OPEN)
        self.assertIn('<summary class="mail-offline-summary">离线邮件解析（可选）</summary>', self.offline)

    def test_offline_mail_block_keeps_every_existing_id(self):
        for element_id in (
            "mail-parse-title",
            "mail-form",
            "mail-subject",
            "mail-body",
            "mail-from",
            "mail-date",
            "mail-message-id",
            "mail-submit",
            "mail-result",
            "mail-list-title",
            "mail-action-result",
            "mail-list",
        ):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.offline)

    def test_hr_panel_keeps_its_own_ids_outside_the_fold(self):
        for element_id in ("hr-search", "hr-platform", "hr-conversation-list", "hr-reply-form", "hr-platform-errors"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.hr_panel)
                self.assertNotIn(f'id="{element_id}"', self.offline)

    def test_platform_errors_container_sits_in_the_sidebar_and_starts_hidden(self):
        sidebar = _between(self.hr_panel, '<aside class="hr-sidebar"', "</aside>")
        self.assertIn('id="hr-platform-errors"', sidebar)
        tag = sidebar[sidebar.index('id="hr-platform-errors"') :][:120]
        self.assertIn("hidden", tag)

    def test_new_styles_use_the_module_prefixes(self):
        self.assertIn(".hr-platform-errors", self.theme)
        self.assertIn(".hr-platform-error", self.theme)
        self.assertIn(".mail-offline", self.theme)
        self.assertIn(".mail-offline-summary", self.theme)


class HrInboxOrderTests(unittest.TestCase):
    NOW = "2026-11-17T10:00:00"

    @classmethod
    def _run(cls, payload):
        body = (
            "const now = new Date(input.now);\n"
            "process.stdout.write(JSON.stringify({\n"
            "  times: input.values.map((value) => {\n"
            "    const time = hrMessageTime(value, now);\n"
            "    return Number.isFinite(time) ? time : null;\n"
            "  }),\n"
            "  order: sortHrConversationsByRecent(input.rows).map((row) => row.id)\n"
            "}));\n"
        )
        return _run_node(body, payload, "收件箱排序")

    def test_platform_time_labels_are_understood(self):
        values = [
            "11-16 10:20",
            "11-15 18:00",
            "09:20",
            "昨天 10:20",
            "昨天",
            "前天",
            "2026-11-16 09:00",
            "30 分钟前",
            "3 小时前",
            "",
            "待定",
        ]
        times = self._run({"now": self.NOW, "values": values, "rows": []})["times"]
        self.assertTrue(all(value is not None for value in times[:9]))
        self.assertGreater(times[0], times[1])
        self.assertGreater(times[2], times[3])
        self.assertGreater(times[3], times[4])
        self.assertGreater(times[4], times[5])
        self.assertGreater(times[7], times[8])
        self.assertIsNone(times[9])
        self.assertIsNone(times[10])

    def test_full_and_short_dates_for_the_same_day_agree(self):
        values = ["2026-11-16 09:00", "11-16 09:00", "昨天 09:00"]
        times = self._run({"now": self.NOW, "values": values, "rows": []})["times"]
        self.assertEqual(len(set(times)), 1)

    def test_inbox_merges_platforms_and_sorts_newest_first(self):
        rows = [
            {"id": "old", "platform": "boss", "last_message_at": "11-15 18:00"},
            {"id": "none", "platform": "51job", "last_message_at": ""},
            {"id": "new", "platform": "zhilian", "last_message_at": "11-16 10:20"},
            {"id": "recent", "platform": "boss", "last_message_at": "昨天 09:00"},
            {"id": "today", "platform": "liepin", "last_message_at": "09:20"},
        ]
        result = self._run({"now": self.NOW, "values": [], "rows": rows})
        self.assertEqual(result["order"], ["today", "new", "recent", "old", "none"])
        self.assertEqual(
            {row["id"]: row["platform"] for row in rows},
            {"old": "boss", "none": "51job", "new": "zhilian", "recent": "boss", "today": "liepin"},
        )

    def test_four_platforms_merge_into_one_time_ordered_list(self):
        rows = [
            {"id": "boss-1", "platform": "boss", "last_message_at": "11-14 20:00"},
            {"id": "zhilian-1", "platform": "zhilian", "last_message_at": "11-16 11:00"},
            {"id": "51job-1", "platform": "51job", "last_message_at": "11-16 08:00"},
            {"id": "liepin-1", "platform": "liepin", "last_message_at": "11-13 09:30"},
        ]
        order = self._run({"now": self.NOW, "values": [], "rows": rows})["order"]
        self.assertEqual(order, ["zhilian-1", "51job-1", "boss-1", "liepin-1"])

    def test_unknown_times_keep_their_original_order_after_known_ones(self):
        rows = [
            {"id": "x", "last_message_at": ""},
            {"id": "y", "last_message_at": None},
            {"id": "z", "last_message_at": "待定"},
            {"id": "k", "last_message_at": "11-16 10:20"},
        ]
        result = self._run({"now": self.NOW, "values": [], "rows": rows})
        self.assertEqual(result["order"], ["k", "x", "y", "z"])

    def test_plain_numbers_are_not_read_as_dates(self):
        times = self._run({"now": self.NOW, "values": ["3", "12"], "rows": []})["times"]
        self.assertEqual(times, [None, None])


class HrInboxPlatformErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = _read(APP)
        cls.hr = _between(cls.script, HR_BLOCK_START, HR_BLOCK_END)

    def test_each_platform_error_renders_on_its_own_line(self):
        inline = _between(self.hr, "function renderHrPlatformErrors(", "function renderHrConversations(")
        self.assertIn("Object.entries(state.hrPlatformErrors || {})", inline)
        self.assertIn("dom.hrPlatformErrors.append(", inline)
        self.assertIn("未读取", inline)
        self.assertIn("channelLabel(platform)", inline)

    def test_failing_platform_does_not_empty_the_merged_list(self):
        load = _between(self.hr, "async function loadHrConversations(", "async function loadHrThread(")
        self.assertIn("state.hrAvailable = Boolean(data && data.available !== false);", load)
        self.assertIn("state.hrAvailable && Array.isArray(data.conversations)", load)
        self.assertIn("state.hrPlatformErrors = hrPlatformErrorsFrom(data);", load)

    def test_each_row_carries_its_platform_label(self):
        render = _between(self.hr, "function renderHrConversations(", "function renderHrThread(")
        self.assertIn("channelLabel(conversation.platform)", render)
        self.assertIn("hr-platform-badge", render)

    def test_auto_selection_uses_the_newest_conversation(self):
        load = _between(self.hr, "async function loadHrConversations(", "async function loadHrThread(")
        self.assertIn("sortHrConversationsByRecent(state.hrConversations)[0]", load)

    def test_contracts_and_reply_send_path_are_unchanged(self):
        # 本轮只改展示顺序与页面结构，读取与会话接口、逐条发送路径保持原样。
        self.assertIn("`/api/offerpilot/conversations?platform=all&mode=", self.hr)
        self.assertIn("`/api/offerpilot/conversation?platform=", self.hr)
        send = _between(self.script, "async function submitHrReply(", HR_BLOCK_END)
        self.assertIn("postAction('offerpilot-reply'", send)
        self.assertIn("confirm: HR_REPLY_CONFIRM_PHRASE", send)
        self.assertIn("risk_acknowledged: true", send)
        self.assertIn("if (!dom.hrReplyModalRisk || !dom.hrReplyModalRisk.checked) return;", send)


class HrPlatformErrorModelTests(unittest.TestCase):
    @staticmethod
    def _errors(payload):
        body = "process.stdout.write(JSON.stringify(hrPlatformErrorsFrom(input.data)));\n"
        return _run_node(body, payload, "平台错误解析")

    def test_errors_map_keeps_only_the_failing_platforms(self):
        data = {
            "available": True,
            "conversations": [{"id": "a", "platform": "boss"}],
            "errors": {"liepin": "猎聘聊天列表不可读", "zhilian": ""},
        }
        self.assertEqual(self._errors({"data": data}), {"liepin": "猎聘聊天列表不可读"})

    def test_falls_back_to_per_platform_rows_when_errors_map_is_missing(self):
        data = {
            "available": True,
            "platforms": [
                {"platform": "boss", "ok": True, "available": True},
                {"platform": "51job", "ok": False, "available": False, "error": "未登录"},
            ],
        }
        self.assertEqual(self._errors({"data": data}), {"51job": "未登录"})

    def test_no_errors_gives_an_empty_map(self):
        self.assertEqual(self._errors({"data": {"available": True, "conversations": []}}), {})


if __name__ == "__main__":
    unittest.main()
