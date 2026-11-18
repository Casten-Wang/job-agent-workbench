#!/usr/bin/env python3
"""猎聘投递适配器：只用假页面，不联网、不点真实按钮。

锁住的约定：
- 在搜索页按岗位编号选中卡片，再点详情栏的「聊一聊」；聊天窗口里出现平台预置招呼语才算成功；
- 详情栏已是「继续聊」说明沟通过，按成功处理但不重复点击；
- 点击后没有招呼语时报 ``deliver_unconfirmed`` 并保留页面，不重试（避免重复发送）；
- 验证页、搜索前几页都找不到岗位、缺少岗位编号都不点击；
- ``send_greetings`` 通过 ``_send_greeting_once`` 把猎聘岗位交给这个适配器。
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

from offerpilot.executor import sender, sender_liepin as lp  # noqa: E402

JOB = {
    "id": "liepin:123", "source_platform": "liepin", "source_job_id": "123",
    "source_keyword": "产品经理", "source_city_code": "", "title": "示例岗位",
}
CHAT = "示例HR\n招聘方\n了解更多安全防范知识\n您好，我的背景与该职位要求较为匹配。\n未读\n发简历\n发送"


class _Page:
    def __init__(self, found_on_page=0, **state):
        self.found_on_page = found_on_page
        self.page = 0
        self.state = {"text": "职位列表", "cards": 3, "has_pane": True,
                      "has_chat": False, "has_continue": False, "chat_text": ""}
        self.state.update(state)
        self.selected = False
        self.clicked = 0
        self.closed: list[str] = []
        self.navigated: list[str] = []
        self.chat_closed = 0
        self.after_click = {"chat_text": CHAT, "has_chat": False, "has_continue": True}

    def navigate(self, target_id, url):
        self.navigated.append(url)
        self.page += 1
        self.selected = False
        return True

    def evaluate(self, target_id, script):
        if script == lp._CLICK_CHAT_JS:
            self.clicked += 1
            self.state.update(self.after_click)
            return json.dumps({"clicked": self.state.get("has_chat", False) or True})
        if script == lp._CLOSE_CHAT_JS:
            self.chat_closed += 1
            return json.dumps({"closed": True})
        if script == lp._SELECT_CARD_JS.replace("__JOB_ID__", "123"):
            self.selected = self.page == self.found_on_page
            if self.selected and not self.state["has_continue"]:
                self.state["has_chat"] = True
            return json.dumps({"selected": self.selected})
        return json.dumps(self.state)


class LiepinDeliverTests(unittest.TestCase):
    def _run(self, page, job=JOB):
        with patch.object(lp, "new_tab", return_value="tab-1"), patch.object(
            lp, "evaluate", side_effect=page.evaluate
        ), patch.object(lp, "navigate", side_effect=page.navigate), patch.object(
            lp, "close_tab", side_effect=page.closed.append
        ), patch.object(lp.random, "uniform", return_value=0):
            return lp.send_liepin_application(
                job, {}, stop_requested=lambda event: False, sleep_or_stop=lambda seconds, event: False,
            )

    def test_greeting_in_chat_window_is_success_and_recorded(self):
        page = _Page()
        result, failed = self._run(page)
        self.assertTrue(result["success"])
        self.assertEqual(result["sent_text"], "您好，我的背景与该职位要求较为匹配。")
        self.assertEqual(page.clicked, 1)
        self.assertEqual(page.chat_closed, 1)
        self.assertEqual(page.closed, ["tab-1"])
        self.assertIsNone(failed)

    def test_job_on_a_later_search_page_is_found_by_paging(self):
        page = _Page(found_on_page=2)
        result, _ = self._run(page)
        self.assertTrue(result["success"])
        self.assertEqual(len(page.navigated), 2)
        self.assertIn("curPage=2", page.navigated[-1])

    def test_job_missing_from_search_is_never_clicked(self):
        page = _Page(found_on_page=99)
        result, _ = self._run(page)
        self.assertEqual(result["error"], "job_not_in_search")
        self.assertEqual(page.clicked, 0)
        self.assertEqual(len(page.navigated), lp.MAX_SEARCH_PAGES - 1)

    def test_already_greeted_job_is_not_clicked_again(self):
        page = _Page(has_continue=True)
        result, _ = self._run(page)
        self.assertTrue(result["success"])
        self.assertTrue(result["already_applied"])
        self.assertEqual(page.clicked, 0)

    def test_no_greeting_keeps_the_page_and_does_not_retry(self):
        page = _Page()
        page.after_click = {"chat_text": "", "has_chat": False, "has_continue": True}
        result, failed = self._run(page)
        self.assertEqual(result["error"], "deliver_unconfirmed")
        self.assertEqual(page.clicked, 1)
        self.assertEqual(failed, "tab-1")

    def test_risk_page_never_clicks(self):
        page = _Page(text="请完成安全验证", cards=0)
        result, _ = self._run(page)
        self.assertEqual(result["error"], "captcha")
        self.assertEqual(page.clicked, 0)

    def test_missing_job_id_is_refused_before_opening_a_tab(self):
        with patch.object(lp, "new_tab") as new_tab:
            result, _ = lp.send_liepin_application(
                {**JOB, "source_job_id": ""}, {},
                stop_requested=lambda e: False, sleep_or_stop=lambda s, e: False,
            )
        new_tab.assert_not_called()
        self.assertEqual(result["error"], "invalid_job_url")

    def test_search_url_uses_keyword_city_and_page(self):
        url = lp._search_url({**JOB, "source_city_code": "020"}, 1)
        self.assertIn("dqs=020", url)
        self.assertIn("curPage=1", url)
        self.assertNotIn("dqs=", lp._search_url(JOB, 0))

    def test_sender_hands_liepin_jobs_to_the_adapter(self):
        with patch("offerpilot.executor.sender_liepin.send_liepin_application",
                   return_value=({"success": True}, None)) as adapter, patch.object(sender, "new_tab") as boss_tab:
            result, _ = sender._send_greeting_once(JOB, "你好", {})
        adapter.assert_called_once()
        boss_tab.assert_not_called()
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
