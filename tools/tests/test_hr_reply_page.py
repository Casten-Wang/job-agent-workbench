#!/usr/bin/env python3
"""Tests for the HR reply tab: an in-page conversation page.

The page may only send a reply after the user confirms it in a dialog; every
check here is offline and reads the shipped static files.  No conversation
endpoint is called and no message is sent.
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

HR_BLOCK_START = "/* Render: HR conversations"
HR_BLOCK_END = "/* Render: interview */"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _hr_block(script: str) -> str:
    start = script.index(HR_BLOCK_START)
    end = script.index(HR_BLOCK_END, start)
    return script[start:end]


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class HrReplyPageMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.hr = _hr_block(cls.script)

    def test_required_conversation_ids_exist(self):
        ids = [
            "hr-conversations-panel",
            "hr-refresh",
            "hr-status",
            "hr-search",
            "hr-filter-all",
            "hr-filter-unread",
            "hr-filter-replied",
            "hr-conversation-count",
            "hr-conversation-list",
            "hr-detail-title",
            "hr-detail-meta",
            "hr-detail-job",
            "hr-messages",
            "hr-reply-block-reason",
            "hr-reply-form",
            "hr-reply-input",
            "hr-reply-send",
            "hr-draft-count",
            "hr-reply-confirm-panel",
            "hr-reply-dialog",
            "hr-reply-dialog-title",
            "hr-reply-who",
            "hr-reply-modal-text",
            "hr-reply-modal-progress",
            "hr-reply-modal-risk",
            "hr-reply-modal-cancel",
            "hr-reply-confirm",
            "hr-platform",
        ]
        for element_id in ids:
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', self.html)

    def test_hr_panel_lives_in_mail_view_and_keeps_mail_parser(self):
        mail_view = _between(self.html, 'id="view-mail"', 'id="view-interview"')
        for element_id in ("hr-conversations-panel", "mail-parse-title", "mail-form", "mail-list"):
            with self.subTest(element_id=element_id):
                self.assertIn(f'id="{element_id}"', mail_view)

    def test_reply_dialog_is_accessible_and_defaults_to_confirmed_risk(self):
        start = self.html.index('id="hr-reply-dialog"')
        tag = self.html[start : self.html.index(">", start)]
        self.assertIn('role="dialog"', tag)
        self.assertIn('aria-modal="true"', tag)
        self.assertIn('aria-labelledby="hr-reply-dialog-title"', tag)
        self.assertIn('aria-describedby="hr-reply-who"', tag)
        self.assertIn('id="hr-reply-confirm-panel" hidden', self.html)
        risk = self.html[self.html.index('id="hr-reply-modal-risk"') :][:160]
        self.assertIn("checked", risk)
        confirm = self.html[self.html.index('id="hr-reply-confirm"') :][:200]
        self.assertIn("disabled", confirm)
        self.assertIn("确认发送这条回复", self.html)

    def test_filters_and_search_are_present(self):
        for label in ("全部", "未读", "有 HR 回复"):
            with self.subTest(label=label):
                self.assertIn(label, self.html)
        self.assertIn('data-hr-filter="all"', self.html)
        self.assertIn('data-hr-filter="unread"', self.html)
        self.assertIn('data-hr-filter="replied"', self.html)
        self.assertIn('type="search"', self.html)
        self.assertIn("未关联岗位", self.hr)
        self.assertIn('id="hr-platform"', self.html)
        for platform in ('value="all"', 'value="boss"', 'value="zhilian"', 'value="liepin"'):
            with self.subTest(platform=platform):
                self.assertIn(platform, self.html)

    def test_fiftyonejob_is_hidden_from_the_reply_page(self):
        mail_view = _between(self.html, 'id="view-mail"', 'id="view-interview"')
        self.assertNotIn("51job", mail_view)
        self.assertNotIn("前程无忧", mail_view)
        # 会话列表与错误条都跳过前程无忧，接口本身不改。
        self.assertIn("if (hrPlatformHidden(conversation.platform)) return false;", self.hr)
        inline = _between(self.hr, "function renderHrPlatformErrors(", "function renderHrConversations(")
        self.assertIn(".filter(([platform]) => !hrPlatformHidden(platform))", inline)
        self.assertIn("function hrPlatformHidden(", self.hr)
        self.assertIn("'51job'", self.hr)

    def test_only_reads_the_two_conversation_endpoints(self):
        self.assertIn("/api/offerpilot/conversations?platform=all&mode=", self.hr)
        self.assertIn("/api/offerpilot/conversation?platform=${encodeURIComponent(platform)}&mode=", self.hr)
        self.assertIn("encodeURIComponent(key)", self.hr)
        self.assertIn("channelLabel(conversation.platform)", self.hr)
        self.assertIn("hr-platform-badge", self.hr)
        self.assertNotIn("/api/offerpilot/conversations?", self.hr.replace("/api/offerpilot/conversations?platform=all&mode=", ""))
        # 只读 GET；不得用写方法请求会话。
        self.assertNotIn("method: 'POST'", self.hr)

    def test_unavailable_state_is_explained_in_place(self):
        self.assertIn("请先在本机 Chrome 登录各招聘平台（BOSS / 智联 / 猎聘）、打开调试端口", self.hr)
        self.assertIn("刷新会话", self.html)
        self.assertNotIn("演示模式", self.hr)

    def test_forbidden_wording_is_absent_from_the_page(self):
        for token in ("一键回复", "自动回复"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.html)
                self.assertNotIn(token, self.hr)

    def test_hr_code_renders_external_text_without_innerhtml(self):
        self.assertNotIn("innerHTML", self.hr)
        self.assertIn("textContent", self.hr)
        self.assertIn("text: String", self.hr)


class HrReplyConfirmationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = _read(APP)
        cls.hr = _hr_block(cls.script)

    def test_send_button_only_opens_the_confirmation_dialog(self):
        form_handler = _between(self.script, "dom.hrReplyForm.addEventListener", "if (dom.hrReplyInput)")
        self.assertIn("openHrReplyModal", form_handler)
        self.assertNotIn("postAction", form_handler)
        self.assertNotIn("offerpilot-reply", form_handler)
        self.assertNotIn("window.confirm", form_handler)

    def test_reply_request_happens_only_in_confirmed_submit(self):
        submit = self.hr[self.hr.index("async function submitHrReply"):]
        self.assertIn("offerpilot-reply", submit)
        self.assertEqual(self.script.count("postAction('offerpilot-reply'"), 1)
        self.assertIn("confirm: HR_REPLY_CONFIRM_PHRASE", submit)
        self.assertIn("risk_acknowledged: true", submit)
        self.assertIn("conversation_id: id", submit)
        self.assertIn("text,", submit)
        self.assertIn("if (!dom.hrReplyModalRisk || !dom.hrReplyModalRisk.checked) return;", submit)
        self.assertNotIn("window.confirm", submit)
        # 确认按钮是唯一的提交入口。
        self.assertIn("dom.hrReplyConfirm.addEventListener('click', submitHrReply)", self.script)
        self.assertIn("const HR_REPLY_CONFIRM_PHRASE = '确认发送这条回复'", self.hr)

    def test_dialog_blocks_close_while_sending_and_restores_focus(self):
        close = self.hr[self.hr.index("function closeHrReplyModal"):self.hr.index("async function submitHrReply")]
        self.assertIn("if (state.hrReplyBusy) return;", close)
        self.assertIn("state.hrReplyReturnFocus", close)
        self.assertIn("target.focus()", self.hr)
        self.assertIn("handleHrReplyKeydown", close)
        self.assertIn("body.classList.add('hr-modal-open')", self.hr)
        self.assertIn("document.body.append(dom.hrReplyConfirmPanel)", self.hr)

    def test_sent_reply_clears_draft_and_refreshes_the_thread(self):
        submit = self.hr[self.hr.index("async function submitHrReply"):]
        self.assertIn("state.hrDrafts[id] = ''", submit)
        self.assertIn("await loadHrConversations()", submit)
        self.assertIn("await loadHrThread(state.hrSelectedId, { quiet: true })", submit)
        self.assertIn("status === 'sent'", submit)
        self.assertIn("(status === 'sent' || !status)", submit)
        self.assertIn("status === 'blocked'", submit)

    def test_thread_accepts_nested_or_flat_conversation_payload(self):
        # 后端当前返回平铺字段（conversation_id/company/title），早期契约是嵌套
        # conversation 对象；两种形状都要能渲染。
        self.assertIn("data.conversation", self.hr)
        self.assertIn("data.conversation_id", self.hr)
        self.assertIn("data.company || base.company", self.hr)

    def test_blocked_conversation_disables_the_composer(self):
        self.assertIn("thread.reply_allowed", self.hr)
        self.assertIn("reply_block_reason", self.hr)
        self.assertIn("dom.hrReplyInput.disabled = !allowed", self.hr)
        self.assertIn("dom.hrReplySend.disabled = !allowed || !draft.trim()", self.hr)

    def test_composer_is_gated_by_backend_reply_allowed_only(self):
        # 能否回复只由后端 reply_allowed / reply_block_reason 决定，前端不硬编码平台名单。
        gate = _between(self.hr, "const allowed = Boolean(thread && thread.reply_allowed)", "updateHrComposerState();")
        self.assertIn("thread.reply_block_reason", gate)
        self.assertIn("dom.hrReplyBlockReason.hidden = allowed", gate)
        self.assertIn("dom.hrReplyBlockReason.textContent", gate)
        self.assertNotIn("platform", gate)
        self.assertNotIn("boss", gate.lower())
        composer = _between(self.hr, "function updateHrComposerState", "async function ensureHrConversationsLoaded")
        self.assertIn("thread.reply_allowed", composer)
        self.assertNotIn("platform", composer)
        self.assertNotIn("boss", composer.lower())

    def test_entering_the_hr_view_loads_conversations(self):
        show_view = _between(self.script, "function showView(", "function clearTransientResults(")
        self.assertIn("if (name === 'mail')", show_view)
        self.assertIn("ensureHrConversationsLoaded();", show_view)
        self.assertIn(
            "ensureHrConversationsLoaded();",
            _between(self.script, "function renderMails(", HR_BLOCK_START),
        )


class HrConversationFilterTests(unittest.TestCase):
    @staticmethod
    def _function_source(script: str, name: str) -> str:
        start = script.index(f"function {name}(")
        end = script.index("\nfunction ", start + 1)
        return script[start:end]

    def _filter_ids(self, conversations, *, threads=None, search="", filter_name="all", platform_name="all"):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过会话筛选校验")
        script = _read(APP)
        harness = (
            self._function_source(script, "hrPlatformHidden")
            + "\n"
            + self._function_source(script, "hrConversationHasReply")
            + "\n"
            + self._function_source(script, "filteredHrConversations")
            + "\nconst fs = require('fs');\n"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "const state = {hrConversations: input.conversations, hrThreads: input.threads || {},"
            " hrSearch: input.search || '', hrFilter: input.filter || 'all',"
            " hrPlatform: input.platform || 'all'};\n"
            "process.stdout.write(JSON.stringify(filteredHrConversations().map((row) => row.id)));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps(
                {
                    "conversations": conversations,
                    "threads": threads or {},
                    "search": search,
                    "filter": filter_name,
                    "platform": platform_name,
                }
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行会话筛选失败：{completed.stderr[:800]}")
        return json.loads(completed.stdout)

    @classmethod
    def setUpClass(cls):
        cls.conversations = [
            {"id": "a", "platform": "boss", "company": "字节跳动", "title": "后端工程师", "hr_name": "林 HR", "last_message": "你好", "unread": True},
            {"id": "b", "platform": "zhilian", "company": "示例科技", "title": "平台工程师", "hr_name": "王 HR", "last_message": "", "unread": False},
            {"id": "c", "platform": "liepin", "company": "Sample Inc", "title": "Data Engineer", "hr_name": "Chen", "last_message": "old", "unread": False},
        ]
        cls.threads = {"c": {"messages": [{"sender": "me", "text": "hi"}, {"sender": "hr", "text": "hello"}]}}

    def test_all_unread_and_replied_filters(self):
        self.assertEqual(
            self._filter_ids(self.conversations, threads=self.threads, filter_name="all"),
            ["a", "b", "c"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, threads=self.threads, filter_name="unread"),
            ["a"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, threads=self.threads, filter_name="replied"),
            ["a", "c"],
        )

    def test_search_matches_company_title_or_hr(self):
        self.assertEqual(
            self._filter_ids(self.conversations, search="字节"),
            ["a"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, search="data engineer"),
            ["c"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, search="林 hr"),
            ["a"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, search="不存在的关键词"),
            [],
        )

    def test_platform_filter_narrows_without_changing_other_filters(self):
        self.assertEqual(
            self._filter_ids(self.conversations, threads=self.threads, platform_name="boss"),
            ["a"],
        )
        self.assertEqual(
            self._filter_ids(self.conversations, threads=self.threads, platform_name="zhilian"),
            ["b"],
        )
        self.assertEqual(
            self._filter_ids(
                self.conversations, threads=self.threads, platform_name="liepin", filter_name="replied"
            ),
            ["c"],
        )
        self.assertEqual(
            self._filter_ids(
                self.conversations, threads=self.threads, platform_name="liepin", filter_name="unread"
            ),
            [],
        )
        self.assertEqual(
            self._filter_ids(
                self.conversations, threads=self.threads, platform_name="51job"
            ),
            [],
        )

    def test_non_hr_system_message_does_not_count_as_reply(self):
        threads = {"c": {"messages": [{"sender": "me", "text": "hi"}, {"sender": "system", "text": "已读"}]}}
        self.assertEqual(
            self._filter_ids(self.conversations, threads=threads, filter_name="replied"),
            ["a"],
        )


class HrReplyStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = _read(THEME)

    def test_two_column_layout_and_bubbles_are_scoped_to_hr(self):
        for selector in (
            ".hr-layout",
            ".hr-sidebar",
            ".hr-thread",
            ".hr-messages",
            ".hr-message-me",
            ".hr-message-hr",
            ".hr-reply-modal[hidden]",
            "body.hr-modal-open",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.theme)

    def test_layout_has_a_single_column_fallback(self):
        self.assertIn("@media (max-width: 900px)", self.theme)
        mobile = self.theme[self.theme.index("@media (max-width: 900px)") :]
        self.assertIn(".hr-layout", mobile)
        self.assertIn("grid-template-columns: minmax(0, 1fr)", mobile)


if __name__ == "__main__":
    unittest.main()
