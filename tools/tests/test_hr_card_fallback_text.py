#!/usr/bin/env python3
"""Fallback label for HR messages that carry no readable text (cards, links).

All names and ids here are fictional.

Contract locked here: when a BOSS card body, a Zhilian custom message or a
Liepin row has no text field the workbench can show, the fallback label says
what happened (a card the workbench cannot preview) instead of the opaque
"系统消息" placeholder, so the HR thread does not show an empty-looking bubble.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime as runtime  # noqa: E402

FALLBACK_TEXT = "[卡片消息，工作台不支持预览，请在平台内查看]"


class ZhilianCardFallbackTests(unittest.TestCase):
    def test_custom_message_without_any_text_field_uses_the_fallback(self):
        message = {"content": "{\"other\": \"value\"}"}
        self.assertEqual(runtime._zhilian_custom_text(message), FALLBACK_TEXT)

    def test_custom_message_with_fallback_text_is_not_overridden(self):
        message = {"content": "{\"fallbackText\": \"你有一份新简历附件\"}"}
        self.assertEqual(runtime._zhilian_custom_text(message), "你有一份新简历附件")


class LiepinCardFallbackTests(unittest.TestCase):
    def test_row_without_msg_or_body_text_uses_the_fallback(self):
        row = {"payload": "{\"bodies\": [{\"type\": \"card\"}]}"}
        self.assertEqual(runtime._liepin_message_text(row), FALLBACK_TEXT)

    def test_row_with_msg_is_not_overridden(self):
        row = {"msg": "您好，看到您的简历"}
        self.assertEqual(runtime._liepin_message_text(row), "您好，看到您的简历")


class BossCardFallbackTests(unittest.TestCase):
    def test_boss_history_card_without_head_title_uses_the_fallback(self):
        body = {
            "code": 0,
            "zpData": {
                "messages": [{
                    "from": {"uid": "hr-1"},
                    "body": {"type": 99},
                    "bodyType": 99,
                    "time": 1700000000000,
                    "mid": "1",
                }]
            },
        }
        messages = runtime._boss_history_messages(200, body, "hr-1")
        self.assertEqual(messages[0]["sender"], "system")
        self.assertEqual(messages[0]["text"], FALLBACK_TEXT)


if __name__ == "__main__":
    unittest.main()
