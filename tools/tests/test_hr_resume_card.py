#!/usr/bin/env python3
"""HR 简历请求卡片：识别、点击同意/拒绝的守卫，以及「通过」页删除与「筛选」排除。

全部是虚构数据；不打开浏览器，不访问平台。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
TOOLS_DIR = PROJECT_ROOT / "tools"
for _path in (str(WEB_DIR), str(VENDOR_SRC), str(PROJECT_ROOT), str(TOOLS_DIR), str(TOOLS_DIR / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import offerpilot_runtime as runtime  # noqa: E402

APP_JS = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB_DIR / "static" / "index.html").read_text(encoding="utf-8")


def _nim(flow: str, content: dict, idserver: str = "1") -> dict:
    return {"flow": flow, "type": "custom", "idServer": idserver, "time": 1763400000000,
            "content": json.dumps(content, ensure_ascii=False)}


class ZhilianCardTextTests(unittest.TestCase):
    def test_resume_request_card_reads_its_last_message(self):
        row = _nim("in", {
            "content": {"systemAskForContact": True, "referType": 4},
            "fallbackText": {"receiverText": "当前版本不支持显示该内容，请将APP更新至最新版本查看"},
            "lastMessage": {"receiverText": "我想要一份你的简历，你是否同意？"},
        })
        self.assertEqual(runtime._zhilian_custom_text(row), "我想要一份你的简历，你是否同意？")

    def test_known_cards_never_fall_back_to_the_placeholder(self):
        cases = [
            (_nim("out", {"content": {"jobTitle": "产品助理", "title": "当前沟通"},
                          "fallbackText": {"receiverText": "", "senderText": "当前沟通职位：产品助理"}}),
             "当前沟通职位：产品助理"),
            (_nim("out", {"content": {"title": "在线简历"},
                          "fallbackText": {"receiverText": "", "senderText": "在线简历"}}),
             "在线简历"),
            (_nim("in", {"content": {"jobTitle": "后端开发", "companyName": "示例公司",
                                     "receiverText": "11月17日 对方发起的职位沟通"}}),
             "11月17日 对方发起的职位沟通：后端开发（示例公司）"),
            (_nim("in", {"content": {"resume": {"desiredJob": "Java"}}}), "在线简历卡片"),
        ]
        for row, expected in cases:
            self.assertEqual(runtime._zhilian_custom_text(row), expected)

    def test_unknown_card_keeps_the_placeholder(self):
        self.assertEqual(
            runtime._zhilian_custom_text(_nim("in", {"content": {"x": 1}})),
            runtime._CARD_PLACEHOLDER,
        )

    def test_history_is_read_oldest_first_so_same_minute_messages_keep_order(self):
        newest_first = [
            {"flow": "in", "type": "text", "text": "第二句", "time": 1763400000000, "idServer": "2"},
            {"flow": "in", "type": "text", "text": "第一句", "time": 1763400000000, "idServer": "1"},
        ]
        messages = runtime._zhilian_history_messages(json.dumps({"msgs": newest_first}))
        self.assertEqual([m["text"] for m in messages], ["第一句", "第二句"])


class AnnotateCardTests(unittest.TestCase):
    def test_latest_unanswered_request_is_pending(self):
        messages = [
            {"sender": "hr", "text": "你好"},
            {"sender": "hr", "text": "我想要一份你的简历，你是否同意？"},
        ]
        result = runtime._annotate_cards(messages, "zhilian")
        self.assertNotIn("card", messages[1], "the input list is not mutated")
        self.assertEqual(result[1]["card"], {"kind": "resume_request", "attach": False, "pending": True})
        self.assertNotIn("card", result[0])

    def test_request_followed_by_our_resume_is_answered(self):
        result = runtime._annotate_cards([
            {"sender": "hr", "text": "我想要一份你的简历，你是否同意？"},
            {"sender": "me", "text": "在线简历已发送"},
        ], "zhilian")
        self.assertFalse(result[0]["card"]["pending"])

    def test_attachment_request_is_flagged_and_dom_button_words_are_dropped(self):
        result = runtime._annotate_cards([
            {"sender": "hr", "text": "我想要一份你的附件简历，你是否同意？ 拒绝 上传附件"},
        ], "zhilian")
        self.assertTrue(result[0]["card"]["attach"])
        self.assertEqual(result[0]["text"], "我想要一份你的附件简历，你是否同意？")

    def test_only_the_newest_request_can_be_pending(self):
        result = runtime._annotate_cards([
            {"sender": "hr", "text": "我想要一份你的简历，你是否同意？"},
            {"sender": "hr", "text": "我想要一份你的简历，你是否同意？"},
        ], "zhilian")
        self.assertFalse(result[0]["card"]["pending"])
        self.assertTrue(result[1]["card"]["pending"])

    def test_our_own_messages_are_never_cards(self):
        result = runtime._annotate_cards([{"sender": "me", "text": "我想要一份你的简历，你是否同意？"}], "boss")
        self.assertNotIn("card", result[0])


class RespondGuardTests(unittest.TestCase):
    ENTRY = {"id": "a" * 32, "platform": "zhilian", "hr_name": "周女士", "company": "示例公司"}

    def setUp(self) -> None:
        for patcher in (
            patch.object(runtime, "load_backend", return_value=MagicMock()),
            patch.object(runtime, "_runtime_config", return_value={}),
            patch.object(runtime, "_stop_requested", return_value=False),
            patch.object(runtime, "_risk_lock_reason", return_value=None),
            patch.object(runtime, "_background_task_running", return_value=False),
            patch.object(runtime, "_cached_conversation", return_value=dict(self.ENTRY)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _call(self, choice="agree", confirm="确认同意发送简历", risk=True):
        return runtime.respond_resume_request("a" * 32, choice, confirm=confirm, risk_acknowledged=risk)

    def test_needs_choice_phrase_and_risk_ack(self):
        with patch.object(runtime, "_click_zhilian_card") as click:
            with self.assertRaises(ValueError):
                self._call(choice="maybe")
            with self.assertRaises(ValueError):
                self._call(confirm="确认发送这条回复")
            with self.assertRaises(ValueError):
                self._call(risk=False)
            with self.assertRaises(ValueError):
                self._call(choice="refuse", confirm="确认同意发送简历")
            click.assert_not_called()

    def test_agree_clicks_once_and_reports(self):
        with patch.object(runtime, "_click_zhilian_card", return_value={"ok": True, "answered": True}) as click:
            result = self._call()
        click.assert_called_once()
        self.assertEqual(result["choice"], "agree")
        self.assertEqual(result["platform"], "zhilian")

    def test_missing_button_and_attachment_request_are_clear_errors(self):
        with patch.object(runtime, "_click_zhilian_card", return_value={"ok": False, "reason": "needs_upload"}):
            with self.assertRaises(ValueError) as ctx:
                self._call()
        self.assertIn("附件", str(ctx.exception))
        with patch.object(runtime, "_click_zhilian_card", return_value={"ok": False, "reason": "no_pending_card"}):
            with self.assertRaises(ValueError):
                self._call()

    def test_click_without_page_response_is_not_reported_as_done(self):
        with patch.object(runtime, "_click_zhilian_card", return_value={"ok": True, "answered": False}):
            with self.assertRaises(ValueError) as ctx:
                self._call()
        self.assertIn("核实", str(ctx.exception))

    def test_stop_and_risk_locks_block_the_click(self):
        with patch.object(runtime, "_click_zhilian_card") as click:
            with patch.object(runtime, "_stop_requested", return_value=True):
                with self.assertRaises(ValueError):
                    self._call()
            with patch.object(runtime, "_risk_lock_reason", return_value="风控冷却中"):
                with self.assertRaises(ValueError):
                    self._call()
            with patch.object(runtime, "_background_task_running", return_value=True):
                with self.assertRaises(ValueError):
                    self._call()
            click.assert_not_called()

    def test_ambiguous_conversation_is_refused(self):
        with patch.object(runtime, "_cached_conversation", return_value={**self.ENTRY, "ambiguous": True}):
            with patch.object(runtime, "_click_zhilian_card") as click:
                with self.assertRaises(ValueError):
                    self._call()
                click.assert_not_called()


class CardScriptTests(unittest.TestCase):
    ENTRY = {"hr_name": "周女士", "company": "示例公司"}

    def test_zhilian_script_targets_only_cards_with_buttons_and_the_chosen_label(self):
        script = runtime._zhilian_card_click_expression(self.ENTRY, "agree")
        self.assertIn(".im-msg-11-wrap", script)
        self.assertIn('"同意"', script)
        self.assertIn("周女士", script)
        self.assertNotIn("__", script, "every placeholder is filled")
        refuse = runtime._zhilian_card_click_expression(self.ENTRY, "refuse")
        self.assertIn('"拒绝"', refuse)

    def test_generic_script_is_scoped_and_filled(self):
        script = runtime._generic_card_click_expression(self.ENTRY, "agree", ".im-ui-basic-chat-modal")
        self.assertIn(".im-ui-basic-chat-modal", script)
        self.assertNotIn("__", script)


class ActionWiringTests(unittest.TestCase):
    def test_action_is_registered_and_validates_the_id(self):
        self.assertIs(backend.ACTIONS["offerpilot-resume-request"], backend.respond_offerpilot_resume_request)
        with self.assertRaises(backend.ApiError):
            backend.respond_offerpilot_resume_request({"id": "bad", "choice": "agree"})

    def test_backend_logs_company_only(self):
        store = MagicMock()
        result = {"conversation_id": "a" * 32, "company": "示例公司", "choice": "agree"}
        with patch.object(runtime, "respond_resume_request", return_value=result), \
                patch.object(backend, "get_store", return_value=store):
            response = backend.respond_offerpilot_resume_request({
                "id": "a" * 32, "choice": "agree",
                "confirm": "确认同意发送简历", "risk_acknowledged": True,
            })
        self.assertTrue(response["ok"])
        store.log.assert_called_once_with("同意发送简历", "示例公司")

    def test_risk_page_stops_with_a_clear_message(self):
        class MonitorRiskDetected(Exception):
            pass
        with patch.object(runtime, "respond_resume_request", side_effect=MonitorRiskDetected()):
            with self.assertRaises(backend.ApiError) as ctx:
                backend.respond_offerpilot_resume_request({"id": "a" * 32, "choice": "agree"})
        self.assertEqual(ctx.exception.status, 409)


class PipelinePageSourceTests(unittest.TestCase):
    def test_card_buttons_confirm_inline_before_clicking(self):
        self.assertIn("function hrResumeCardNode", APP_JS)
        self.assertIn("postAction('offerpilot-resume-request'", APP_JS)
        self.assertEqual(APP_JS.count("postAction('offerpilot-resume-request'"), 1)
        self.assertIn("HR_CARD_CONFIRM_PHRASES", APP_JS)
        body = APP_JS[APP_JS.index("function hrResumeCardNode"):APP_JS.index("async function submitHrResumeCard")]
        self.assertIn("card.attach", body, "attachment requests have no click button")
        self.assertIn("reply_allowed", body)
        self.assertNotIn("postAction", body, "the first click only opens the confirmation")

    def test_card_state_is_part_of_the_render_signature(self):
        self.assertIn("message && message.card ? JSON.stringify(message.card)", APP_JS)

    def test_screening_tab_hides_jobs_already_in_the_approval_queue(self):
        self.assertIn("function poolJobs", APP_JS)
        body = APP_JS[APP_JS.index("function poolJobs"):APP_JS.index("function renderJobs")]
        self.assertIn("'pending'", body)
        self.assertIn("'approved'", body)
        render = APP_JS[APP_JS.index("function renderJobs"):APP_JS.index("function renderJobs") + 600]
        self.assertIn("poolJobs(snapshot)", render)

    def test_passed_tab_can_delete_with_include_approved(self):
        self.assertIn('id="queue-approved-delete"', INDEX_HTML)
        self.assertIn('id="queue-pending-delete"', INDEX_HTML)
        self.assertIn("include_approved: true", APP_JS)
        self.assertIn("window.confirm", APP_JS[APP_JS.index("async function queueDeleteSelected"):][:400])


class DeleteApprovedTests(unittest.TestCase):
    def test_include_approved_deletes_an_approved_job_but_default_protects_it(self):
        import tempfile
        import local_fixtures
        with tempfile.TemporaryDirectory() as tmp, patch.object(backend, "WEB_DIR", Path(tmp)):
            store = backend.get_store("user")
            local_fixtures.seed_local_data(store)
            protected = backend.delete_jobs({"mode": "user", "ids": ["demo-job-001"]})
            self.assertEqual(protected["deleted"], 0)
            result = backend.delete_jobs({"mode": "user", "ids": ["demo-job-001"], "include_approved": True})
            self.assertEqual(result["deleted"], 1)
            self.assertNotIn("demo-job-001", {str(row.get("id")) for row in store.queue()})
            self.assertNotIn("demo-job-001", {job["id"] for job in store.jobs()})


if __name__ == "__main__":
    unittest.main()
