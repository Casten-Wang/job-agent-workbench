#!/usr/bin/env python3
"""智联投递适配器：只用假页面，不联网、不点真实按钮。

锁住的约定：
- 点「立即投递」后看到 ``deliver-greeting-modal`` 的成功标题才算成功，并记录平台预置招呼语；
- 页面已显示「继续沟通」说明投递过，按成功处理但不重复点击；
- 没有成功提示时报 ``deliver_unconfirmed`` 并保留页面，不重试（避免重复投递）；
- 出现验证、岗位下线、没有投递按钮都不点击；
- ``send_greetings`` 通过 ``_send_greeting_once`` 把智联岗位交给这个适配器。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot.executor import sender, sender_zhilian as zl  # noqa: E402

JOB = {"id": "zhilian:J1", "source_platform": "zhilian", "url": "https://www.zhaopin.com/jobdetail/J1.htm"}
MODAL = "已向对方发送简历和打招呼语\n您好，我对贵司【示例岗位】很感兴趣。\n留在此页\n继续沟通"


class _Page:
    def __init__(self, **state):
        self.state = {"title": "示例岗位招聘", "text": "职位描述", "has_apply": True,
                      "has_continue": False, "modal_text": ""}
        self.state.update(state)
        self.after_click = {"modal_text": MODAL}
        self.clicked = 0
        self.closed: list[str] = []
        self.modal_closed = 0

    def evaluate(self, target_id, script):
        if script == zl._CLICK_APPLY_JS:
            self.clicked += 1
            self.state.update(self.after_click)
            return json.dumps({"clicked": self.state["has_apply"]})
        if script == zl._CLOSE_MODAL_JS:
            self.modal_closed += 1
            return json.dumps({"closed": True})
        return json.dumps(self.state)


class ZhilianDeliverTests(unittest.TestCase):
    def _run(self, page, job=JOB):
        with patch.object(zl, "new_tab", return_value="tab-1"), patch.object(
            zl, "evaluate", side_effect=page.evaluate
        ), patch.object(zl, "close_tab", side_effect=page.closed.append), patch.object(zl.random, "uniform", return_value=0):
            return zl.send_zhilian_application(
                job, {}, stop_requested=lambda event: False, sleep_or_stop=lambda seconds, event: False,
            )

    def test_success_modal_records_the_platform_greeting(self):
        page = _Page()
        result, failed = self._run(page)
        self.assertTrue(result["success"])
        self.assertIn("您好，我对贵司", result["sent_text"])
        self.assertEqual(page.clicked, 1)
        self.assertEqual(page.modal_closed, 1)
        self.assertEqual(page.closed, ["tab-1"])
        self.assertIsNone(failed)

    def test_already_delivered_page_is_not_clicked_again(self):
        page = _Page(has_apply=False, has_continue=True)
        result, _ = self._run(page)
        self.assertTrue(result["success"])
        self.assertTrue(result["already_applied"])
        self.assertEqual(page.clicked, 0)

    def test_no_confirmation_keeps_the_page_and_does_not_retry(self):
        page = _Page()
        page.after_click = {"modal_text": ""}
        result, failed = self._run(page)
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "deliver_unconfirmed")
        self.assertEqual(page.clicked, 1)
        self.assertEqual(failed, "tab-1")

    def test_risk_page_and_closed_job_never_click(self):
        for text, error in (("请完成安全验证", "captcha"), ("职位已下线", "job_page_unavailable")):
            with self.subTest(error=error):
                page = _Page(text=text)
                result, _ = self._run(page)
                self.assertEqual(result["error"], error)
                self.assertEqual(page.clicked, 0)

    def test_missing_apply_button_is_a_failure(self):
        page = _Page(has_apply=False)
        result, _ = self._run(page)
        self.assertEqual(result["error"], "no_apply_button")

    def test_foreign_url_is_refused_before_opening_a_tab(self):
        with patch.object(zl, "new_tab") as new_tab:
            result, _ = zl.send_zhilian_application(
                {**JOB, "url": "https://example.invalid/x"}, {},
                stop_requested=lambda e: False, sleep_or_stop=lambda s, e: False,
            )
        new_tab.assert_not_called()
        self.assertEqual(result["error"], "invalid_job_url")

    def test_sender_hands_zhilian_jobs_to_the_adapter(self):
        with patch("offerpilot.executor.sender_zhilian.send_zhilian_application",
                   return_value=({"success": True}, None)) as adapter, patch.object(sender, "new_tab") as boss_tab:
            result, _ = sender._send_greeting_once(JOB, "你好", {})
        adapter.assert_called_once()
        boss_tab.assert_not_called()
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
