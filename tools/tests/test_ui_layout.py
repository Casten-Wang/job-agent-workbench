#!/usr/bin/env python3
"""Tests for the workbench layout layer (page heads, jobs table, HR page).

Offline only: reads the shipped static files.  No endpoint is called, no
message is sent, and no platform page is opened.
"""

from __future__ import annotations

import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
INDEX = STATIC_DIR / "index.html"
APP = STATIC_DIR / "app.js"
THEME = STATIC_DIR / "offer-theme.css"

VIEW_IDS = (
    "view-collect",
    "view-jobs",
    "view-queue",
    "view-mail",
    "view-profile",
    "view-interview",
    "view-push",
    "view-resume",
    "view-data",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class PageHeadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.theme = _read(THEME)

    def test_layout_layer_is_scoped_to_the_opt_in_class(self):
        self.assertIn('<body class="offer-ui">', self.html)
        self.assertIn("body.offer-ui {", self.theme)

    def test_every_secondary_view_uses_one_page_head(self):
        for view_id in VIEW_IDS:
            with self.subTest(view_id=view_id):
                view = _between(self.html, f'id="{view_id}"', "</section>")
                self.assertIn('<header class="view-head">', view)
                self.assertEqual(view.count('class="view-head"'), 1)
                # 页头里依次是标题、说明、主线页签；说明不再是负 margin 的浮层。
                head = view[view.index('class="view-head"'):]
                self.assertLess(head.index("view-title"), head.index("view-lede"))
                if "ui-hub-tabs" in head:
                    self.assertLess(head.index("view-lede"), head.index("ui-hub-tabs"))

    def test_home_keeps_its_own_head(self):
        home = _between(self.html, 'id="view-workbench"', 'id="view-collect"')
        self.assertIn('class="home-head"', home)
        self.assertNotIn('class="view-head"', home)

    def test_page_head_spacing_is_shared(self):
        head = _between(self.theme, "body.offer-ui .view-head {", "}")
        self.assertIn("gap: 10px", head)
        self.assertIn("border-bottom: 1px solid var(--op-line)", head)
        view = _between(self.theme, "body.offer-ui .view {", "}")
        self.assertIn("gap: 20px", view)

    def test_display_type_is_serif_and_body_stays_sans(self):
        self.assertIn('--op-font-display: "Songti SC"', self.theme)
        self.assertIn("body.offer-ui .view-title", self.theme)
        self.assertIn("font-family: var(--op-font-display)", self.theme)

    def test_decorative_layers_are_not_rendered(self):
        block = _between(self.theme, "body.offer-ui .offer-ticker,", "}")
        self.assertIn("display: none", block)
        self.assertIn("body.offer-ui .ambient", self.theme)

    def test_motion_is_opt_out_friendly(self):
        reduced = self.theme[self.theme.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("body.offer-ui *", reduced)
        self.assertIn("animation: none !important", reduced)


class JobsTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = _read(THEME)
        cls.script = _read(APP)

    def test_action_column_has_a_fixed_width_and_stacks_buttons(self):
        self.assertIn("body.offer-ui .jobs-table th:nth-child(13) { width: 176px; }", self.theme)
        actions = _between(self.theme, "body.offer-ui .jobs-actions {", "}")
        self.assertIn("flex-direction: column", actions)
        buttons = self.theme[
            self.theme.index("body.offer-ui .jobs-actions .button,"):
            self.theme.index("body.offer-ui .jobs-actions .terminal-note")
        ]
        self.assertIn("white-space: normal", buttons)
        self.assertIn("width: 100%", buttons)

    def test_status_and_approval_columns_do_not_overlap(self):
        self.assertIn("body.offer-ui .jobs-table th:nth-child(10) { width: 96px; }", self.theme)
        self.assertIn("body.offer-ui .jobs-table th:nth-child(11) { width: 104px; }", self.theme)
        state = _between(self.theme, "body.offer-ui .jobs-state {", "}")
        self.assertIn("white-space: normal", state)
        approval = _between(self.theme, "body.offer-ui .jobs-approval,", "}")
        self.assertIn("flex-direction: column", approval)
        badge = _between(self.theme, "body.offer-ui .badge {", "}")
        self.assertIn("white-space: normal", badge)

    def test_table_scrolls_instead_of_clipping(self):
        wrap = _between(self.theme, "body.offer-ui .table-wrap {", "}")
        self.assertIn("overflow-x: auto", wrap)
        table = _between(self.theme, "body.offer-ui .jobs-table {", "}")
        self.assertIn("min-width: 1280px", table)

    def test_renderer_still_builds_one_action_stack_per_row(self):
        render = _between(self.script, "function renderJobs(", "function renderQueue(")
        self.assertIn("className: 'row-actions jobs-actions'", render)
        for label in ("加入审批队列", "生成投递准备清单", "查看详情"):
            with self.subTest(label=label):
                self.assertIn(label, render)


class HrPageLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.mail_view = _between(cls.html, 'id="view-mail"', 'id="view-interview"')
        cls.hr = _between(cls.script, "/* Render: HR conversations", "/* Render: interview */")

    def test_platform_errors_collapse_to_one_line(self):
        self.assertIn("el('details', { className: 'hr-platform-errors-details' })", self.hr)
        self.assertIn("hr-platform-errors-summary", self.hr)
        summary = _between(self.theme, "body.offer-ui .hr-platform-errors-summary {", "}")
        self.assertIn("padding: 6px 10px", summary)

    def test_empty_thread_points_to_the_next_step(self):
        self.assertIn("这个会话还没有消息。", self.hr)
        self.assertIn("'刷新这个会话'", self.hr)
        self.assertIn("loadHrThread(String(conversation.id)", self.hr)
        self.assertIn("hr-empty-block", self.theme)

    def test_reply_block_reason_sits_inside_the_composer(self):
        form = _between(self.mail_view, 'id="hr-reply-form"', "</form>")
        self.assertIn('id="hr-reply-block-reason"', form)
        self.assertIn('id="hr-reply-input"', form)
        composer = _between(self.theme, "body.offer-ui .hr-composer {", "}")
        self.assertIn("border: 1px solid var(--op-line)", composer)
        reason = _between(self.theme, "body.offer-ui .hr-block-reason {", "}")
        self.assertIn("border-left: 2px solid var(--warn)", reason)

    def test_send_path_and_gating_are_untouched(self):
        self.assertIn("postAction('offerpilot-reply'", self.hr)
        self.assertEqual(self.script.count("postAction('offerpilot-reply'"), 1)
        self.assertIn("if (!dom.hrReplyModalRisk || !dom.hrReplyModalRisk.checked) return;", self.hr)


class ResumeCompareTests(unittest.TestCase):
    """经历变体与主稿的只读对比：入口、结果区与文案。"""

    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.view = _between(cls.html, 'id="view-resume"', 'id="view-data"')
        cls.render = _between(cls.script, "function renderVariants(", "/* Render: data and reports */")

    def test_entry_and_result_container_live_in_the_resume_view(self):
        self.assertIn('id="resume-compare-result"', self.view)
        self.assertIn('aria-live="polite"', self.view)
        self.assertIn("与主稿对比", self.render)
        self.assertIn("保存后才能与主稿对比", self.render)
        self.assertIn(
            "variantCompareResult: document.getElementById('resume-compare-result')",
            self.script,
        )

    def test_compare_button_calls_only_the_read_only_action(self):
        self.assertEqual(self.script.count("postAction('compare-variant'"), 1)
        handler = self.script[self.script.index("async function compareVariantWithMaster("):]
        handler = handler[: handler.index("\n}\n") + 3]
        self.assertIn("variant_id", handler)
        for forbidden in ("add-variant", "offerpilot-deliver", "offerpilot-reply", "delete-jobs"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, handler)

    def test_result_renders_verbatim_segments_with_a_clear_empty_state(self):
        compare = self.script[
            self.script.index("function renderVariantCompareResult("):
            self.script.index("async function compareVariantWithMaster(")
        ]
        for marker in (
            "resume-compare-list",
            "resume-compare-segment",
            "resume-compare-kind",
            "segment.before",
            "segment.after",
            "segment.text",
            "与主稿逐段一致",
            "主稿来源",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, compare)
        self.assertNotIn("innerHTML", compare)

    def test_error_text_is_shown_in_place_instead_of_being_swallowed(self):
        handler = self.script[self.script.index("async function compareVariantWithMaster("):]
        self.assertIn("catch (error)", handler)
        self.assertIn("renderVariantCompareMessage('warn', message)", handler)

    def test_styles_are_prefixed_and_survive_mobile_width(self):
        self.assertIn(".resume-compare-segment.is-added", self.theme)
        self.assertIn("border-left-color: var(--good)", self.theme)
        mobile = self.theme[self.theme.index("@media (max-width: 640px)"):]
        self.assertIn(".resume-compare-cell .button", mobile)
        self.assertIn("width: 100%", mobile)


class ResponsiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.theme = _read(THEME)

    def test_mobile_sidebar_stays_compact(self):
        mobile = self.theme[self.theme.index("@media (max-width: 900px)"):]
        self.assertIn("body.offer-ui .nav-group-label", mobile)
        self.assertIn("display: none", mobile)
        self.assertIn("flex-wrap: nowrap", mobile)
        self.assertIn("body.offer-ui .hr-layout", mobile)

    def test_focus_ring_is_visible_and_themed(self):
        self.assertIn("body.offer-ui :focus-visible", self.theme)
        self.assertIn("outline: 2px solid var(--op-accent)", self.theme)


if __name__ == "__main__":
    unittest.main()
