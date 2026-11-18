"""「信号」岗位流水线打磨层：样式范围、采集粘性卡、批量条与空状态。

只做静态断言（读文件），不启动服务；对应 web/SIGNAL-UI-SPEC.md 第 3、4 节
里分给 sg-pipeline 的条目。
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = (ROOT / "web/static/sg-pipeline.css").read_text(encoding="utf-8")
HTML = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
APP = (ROOT / "web/static/app.js").read_text(encoding="utf-8")


class SignalPipelineCssTests(unittest.TestCase):
    def test_css_only_scopes_the_four_pipeline_views(self):
        for view in ("#view-collect", "#view-jobs", "#view-queue", "#view-mail"):
            self.assertIn(view, CSS)
        # 选择器统一挂在「信号」层上，且不碰其他 #view-*
        for view in ("#view-workbench", "#view-profile", "#view-resume", "#view-interview", "#view-push", "#view-data"):
            self.assertNotIn(view, CSS)
        self.assertIn("body.offer-ui:not(#wa-theme-off)", CSS)

    def test_table_rules_follow_spec_3_4(self):
        self.assertIn(".data-table caption", CSS)
        self.assertIn("clip-path: inset(50%)", CSS)
        self.assertIn("position: sticky", CSS)
        self.assertIn("tbody tr {", CSS)
        self.assertIn("height: 48px", CSS)
        self.assertIn(".sg-num", CSS)
        self.assertIn("white-space: nowrap", CSS)
        self.assertIn("mask-image: linear-gradient", CSS)

    def test_badges_and_empty_states_follow_spec_3_5_and_3_7(self):
        self.assertIn(".badge {", CSS)
        self.assertIn("height: 22px", CSS)
        self.assertIn(".sg-empty", CSS)
        self.assertIn(".sg-empty-text", CSS)
        self.assertIn(".sg-disabled-reason", CSS)

    def test_collect_rail_is_sticky_and_queue_bulk_bar_sticks(self):
        self.assertIn(".sg-collect-grid", CSS)
        self.assertIn(".sg-collect-rail", CSS)
        self.assertIn("position: sticky", CSS)
        self.assertIn(".sg-preflight-card", CSS)
        self.assertIn(".sg-bulk-bar", CSS)
        self.assertIn("bottom: 16px", CSS)


class SignalPipelineMarkupTests(unittest.TestCase):
    def test_collect_page_has_two_column_layout_and_visible_start_reason(self):
        self.assertIn('class="sg-collect-grid"', HTML)
        self.assertIn('class="sg-collect-main"', HTML)
        self.assertIn('class="sg-collect-rail"', HTML)
        self.assertIn('class="panel sg-preflight-card"', HTML)
        # 主按钮移到卡片底部后仍属于原来的表单，并保留全部原有 id
        self.assertIn('form="offerpilot-form"', HTML)
        self.assertIn('id="offerpilot-start"', HTML)
        self.assertIn('id="offerpilot-start-reason"', HTML)
        self.assertIn('class="hint offerpilot-start-reason sg-disabled-reason"', HTML)
        for anchor in ('id="collect-checks"', 'id="offerpilot-risk"', 'id="offerpilot-confirm"', 'id="collect-preflight"'):
            self.assertIn(anchor, HTML)

    def test_queue_bulk_bars_are_below_their_tables(self):
        pending_table = HTML.index('id="queue-pending-table"')
        pending_bar = HTML.index('id="queue-pending-actions"')
        approved_table = HTML.index('id="queue-approved-table"')
        approved_bar = HTML.index('id="queue-approved-actions"')
        self.assertGreater(pending_bar, pending_table)
        self.assertGreater(approved_bar, approved_table)
        self.assertIn('class="queue-toolbar sg-bulk-bar"', HTML)
        self.assertIn('id="queue-selection-count"', HTML)
        self.assertIn('id="queue-approved-selection-count"', HTML)
        # 禁用原因与按钮同排出现
        self.assertIn('sg-disabled-reason', HTML)

    def test_existing_jobs_ids_are_untouched(self):
        for anchor in ('id="jobs-table"', 'id="jobs-bulk-enqueue"', 'id="jobs-bulk-delete"', 'id="jobs-selection-count"'):
            self.assertIn(anchor, HTML)


class SignalPipelineScriptTests(unittest.TestCase):
    def test_render_table_supports_an_empty_state_node(self):
        self.assertIn("options.emptyNode", APP)
        self.assertIn("empty-cell", APP)
        self.assertIn("function queueEmptyNode", APP)
        self.assertIn("function queueTextCell", APP)
        self.assertIn("className: 'sg-empty'", APP)
        self.assertIn("showView('jobs')", APP)

    def test_queue_and_collect_cells_use_signal_classes(self):
        self.assertIn("className: 'sg-num'", APP)
        self.assertIn("className: 'sg-ellipsis'", APP)
        self.assertIn("sg-platform-tag", APP)
        self.assertIn("sg-platform-mark", APP)


if __name__ == "__main__":
    unittest.main()
