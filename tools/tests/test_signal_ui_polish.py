#!/usr/bin/env python3
"""Static checks for the 「信号」 polish layer (sg-base).

Offline only: reads the shipped static files.  No endpoint is called and
nothing is sent.
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
SG_BASE = STATIC_DIR / "sg-base.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class SignalBaseStylesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _read(SG_BASE)

    def test_layer_is_scoped_and_does_not_restyle_other_themes(self):
        self.assertIn("body.offer-ui:not(#wa-theme-off)", self.css)
        for selector in (".panel", ".badge", ".button", ".table-wrap", ".sg-empty"):
            with self.subTest(selector=selector):
                self.assertIn(f"body.offer-ui:not(#wa-theme-off) {selector}", self.css)

    def test_tokens_are_calibrated_for_light_and_dark(self):
        self.assertIn("--ink-2: #55574F", self.css)
        self.assertIn("--mute: #8D8F87", self.css)
        self.assertIn("--line: rgba(13, 14, 12, .08)", self.css)
        self.assertIn(':root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)', self.css)
        self.assertIn("--ink-2: #A3A59C", self.css)
        self.assertIn("--mute: #6A6C64", self.css)

    def test_status_becomes_a_floating_toast(self):
        status = _between(self.css, "#status.status {", "}")
        self.assertIn("position: fixed", status)
        self.assertIn("border-radius: 999px", status)
        self.assertIn("box-shadow: var(--sg-shadow-float)", status)
        self.assertIn("top: 66px", status)

    def test_home_uses_two_columns_and_a_huge_day_number(self):
        home = _between(self.css, ".home-today {", "}")
        self.assertIn("grid-template-columns: minmax(0, 1fr) 320px", home)
        self.assertIn("max-width: 1000px", home)
        day = _between(self.css, ".sg-home-day {", "}")
        self.assertIn("font-size: 140px", day)
        self.assertIn("var(--sg-num)", day)

    def test_settings_system_board_is_collapsed(self):
        self.assertIn("#view-data .sg-fold > summary", self.css)
        self.assertIn("#view-data .sg-legacy-activity", self.css)
        self.assertIn("#view-data .sg-system-body", self.css)

    def test_inputs_are_styled_without_a_form_field_wrapper(self):
        selector = (
            'input:not([type="checkbox"]):not([type="radio"])'
            ':not([type="range"]):not([type="file"])'
        )
        self.assertIn(selector, self.css)
        self.assertIn(f"body.offer-ui:not(#wa-theme-off) {selector}:focus-visible", self.css)
        self.assertIn("outline: 2px solid var(--sg)", self.css)

    def test_belt_wraps_instead_of_clipping(self):
        self.assertIn("#view-data .belt-node {", self.css)
        node = _between(self.css, "#view-data .belt-node {", "}")
        self.assertIn("flex: 1 1 0", node)
        self.assertIn("min-width: 88px", node)
        belt = _between(self.css, "#view-data .belt {", "}")
        self.assertIn("flex-wrap: wrap", belt)

    def test_motion_is_short_and_reduced_motion_disables_it(self):
        self.assertIn("--sg-dur-mid: 320ms", self.css)
        self.assertIn("@keyframes sg-view-in", self.css)
        reduced = self.css[self.css.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("animation: none !important", reduced)


class SignalMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)

    def test_topbar_shows_the_current_page_name(self):
        topbar = _between(self.html, '<header class="topbar">', "</header>")
        self.assertIn('id="topbar-title"', topbar)
        self.assertIn(">首页<", topbar)

    def test_home_adds_the_date_block_and_right_column(self):
        home = _between(self.html, 'id="view-workbench"', 'id="view-collect"')
        for marker in (
            'id="sg-home-day"',
            'id="sg-home-live-text"',
            'class="sg-home-side"',
            'id="sg-pipe-list"',
            'id="sg-home-activity"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, home)
        # 原有三行待办与入口不变。
        self.assertEqual(home.count('data-view-link="queue"'), 2)
        self.assertEqual(home.count('data-view-link="mail"'), 1)

    def test_agent_note_buttons_use_plain_language(self):
        self.assertIn("面经怎么用", self.html)
        self.assertIn("检查更新", self.html)

    def test_ai_test_button_explains_saved_config(self):
        view = self.html[self.html.index('id="view-data"'):]
        self.assertIn('id="ai-settings-test-note"', view)
        self.assertIn("测试的是已保存的配置，改动后请先保存", view)

    def test_settings_puts_ai_first_and_folds_the_board(self):
        view = self.html[self.html.index('id="view-data"'):]
        self.assertLess(view.index('id="ai-settings-panel"'), view.index('id="ops-title"'))
        self.assertIn('class="sg-help"', view)
        self.assertIn('class="sg-fold" id="sg-system"', view)
        self.assertIn("系统信息（四步流程、岗位状态、计数、图表）", view)
        # 最近操作日志留在折叠之外，便于先看。
        self.assertLess(view.index('id="activity-data"'), view.index('id="sg-system"'))
        # 看板与日志仍在 DOM 中，只收进 details，不删除任何 id。
        for marker in ('id="pipeline"', 'id="belt"', 'id="kpi-row"', 'id="activity-data"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, view)


class SignalScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = _read(APP)

    def test_topbar_title_follows_navigation(self):
        self.assertIn("const VIEW_TITLES = {", self.script)
        self.assertIn("dom.topbarTitle.textContent = VIEW_TITLES[name]", self.script)

    def test_status_toast_hides_after_three_seconds(self):
        block = _between(self.script, "function setStatus(", "\nfunction setRefreshing(")
        self.assertIn("window.setTimeout", block)
        self.assertIn("}, 3000);", block)
        self.assertIn("if (safeKind === 'error') return;", block)

    def test_switching_pages_clears_the_status(self):
        # 状态条跨页残留：切页时必须清掉上一页的成功/信息提示，错误也不带进新页面。
        clear = _between(self.script, "function clearStatus(", "\nfunction ")
        self.assertIn("window.clearTimeout(statusToastTimer)", clear)
        self.assertIn("dom.status.textContent = ''", clear)
        view = _between(self.script, "function showView(", "\nfunction ")
        self.assertIn("clearStatus();", view)

    def test_ai_provider_switch_fills_defaults(self):
        self.assertIn("const AI_PROVIDER_DEFAULTS = {", self.script)
        self.assertIn("applyAiProviderDefaults", self.script)
        self.assertIn(
            "dom.aiSettingsService.addEventListener('change', applyAiProviderDefaults)",
            self.script,
        )

    def test_boundary_labels_include_the_embedded_component(self):
        self.assertIn("offerpilot_integration: '内嵌岗位自动化'", self.script)
        self.assertIn("embedded: '已内嵌'", self.script)

    def test_ai_defaults_only_use_supported_services(self):
        block = _between(self.script, "const AI_PROVIDER_DEFAULTS = {", "};")
        for service in ("anthropic", "deepseek", "doubao", "custom"):
            with self.subTest(service=service):
                self.assertIn(f"{service}: {{", block)
        self.assertIn("claude-sonnet-4-6", block)
        self.assertNotIn("claude-sonnet-5-5", block)

    def test_activity_rows_merge_adjacent_duplicates(self):
        group_fn = _between(self.script, "function groupActivityRows(", "function renderActivity(")
        self.assertIn("/；?\\s*auto_submit=\\w+/g", group_fn)
        self.assertIn("last.count += 1", group_fn)
        # 设置页与首页共用同一个分组函数，都用 ×N 表示次数。
        settings = _between(self.script, "function renderActivity(", "function renderDefinitionList(")
        self.assertIn("groupActivityRows(rows)", settings)
        self.assertIn("×${group.count}", settings)
        home = _between(self.script, "function renderHomeSide(", "\nfunction ")
        self.assertIn("groupActivityRows(", home)
        self.assertIn("×${group.count}", home)
        self.assertIn(".slice(0, 5)", home)

    def test_group_activity_rows_behaviour(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用")
        fn = _between(self.script, "function groupActivityRows(", "function renderActivity(")
        harness = (
            fn
            + "\nconst rows = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify(groupActivityRows(rows).map(g => [g.title, g.detail, g.count])));\n"
        )
        rows = [
            {"title": "导入岗位", "detail": "新增 3；auto_submit=false", "at": "2026-11-18T10:00:00"},
            {"title": "导入岗位", "detail": "新增 3", "at": "2026-11-18T09:59:00"},
            {"title": "导入岗位", "detail": "新增 3；auto_submit=true", "at": "2026-11-18T09:58:00"},
            {"action": "save-profile", "at": "2026-11-18T09:50:00"},
            {"title": "导入岗位", "detail": "新增 3", "at": "2026-11-18T09:40:00"},
            None,
        ]
        done = subprocess.run(
            [node, "-e", harness], input=json.dumps(rows, ensure_ascii=False),
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr[:500])
        self.assertEqual(
            json.loads(done.stdout),
            [["导入岗位", "新增 3", 3], ["save-profile", "", 1], ["导入岗位", "新增 3", 1], ["操作", "", 1]],
        )

    def test_home_replies_add_platform_unread_and_change_zero_buttons(self):
        block = _between(self.script, "function renderHomeToday(", "/* 六段契约")
        self.assertIn("state.hrUnreadTotal", block)
        self.assertIn("counts.replies + hrUnread", block)
        self.assertIn("'去采集岗位'", block)
        self.assertIn("'去看收件箱'", block)

    def test_switching_views_scrolls_and_focuses_the_heading(self):
        view = _between(self.script, "function showView(", "\nfunction ")
        self.assertIn("dom.views.scrollTop = 0", view)
        self.assertIn("heading.focus({ preventScroll: true })", view)
        self.assertIn("heading.setAttribute('tabindex', '-1')", view)

    def test_ai_settings_hint_allows_empty_base_url_for_claude_only(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用")
        defaults = _between(self.script, "const AI_PROVIDER_DEFAULTS = {", "const OFFERPILOT_IMPORTED_TASKS_KEY")
        fn = _between(self.script, "function applyAiProviderDefaults()", "async function loadAiSettings()")
        harness = (
            defaults + fn + """
const messages = [];
function showInline(_el, text) { messages.push(text); }
function run(service, baseUrl, model) {
  global.dom = {
    aiSettingsService: { value: service, dataset: { previousService: service }, selectedOptions: [{ textContent: service }] },
    aiSettingsBaseUrl: { value: baseUrl },
    aiSettingsModel: { value: model },
    aiSettingsResult: {},
  };
  messages.length = 0;
  applyAiProviderDefaults();
  return messages[0];
}
process.stdout.write(JSON.stringify({
  claude_empty_url: run('anthropic', '', 'claude-sonnet-4-6'),
  claude_no_model: run('anthropic', '', ''),
  deepseek_no_model: run('deepseek', 'https://api.deepseek.com', ''),
  custom_all_empty: run('custom', '', ''),
  custom_no_url: run('custom', '', 'my-model'),
}));
""".replace("global.dom =", "dom =")
        )
        harness = "var dom;\n" + harness
        done = subprocess.run([node, "-e", harness], text=True, capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[:500])
        out = json.loads(done.stdout)
        self.assertNotIn("Base URL", out["claude_empty_url"])
        # Claude 的模型名为空时会先被填入默认模型，不再提示缺失。
        self.assertIn("已填入", out["claude_no_model"])
        self.assertEqual(out["deepseek_no_model"], "请填写模型名")
        self.assertEqual(out["custom_all_empty"], "请填写 Base URL 与模型名")
        self.assertEqual(out["custom_no_url"], "请填写 Base URL")

    def test_home_renderer_fills_the_side_column(self):
        block = _between(self.script, "function renderHomeSide(", "function renderHomeToday(")
        for marker in ("homePipelineStageCount(snapshot, key)", "groupActivityRows(snapshot && Array.isArray(snapshot.activity)", ").slice(0, 5)", "sg-side-num"):
            with self.subTest(marker=marker):
                self.assertIn(marker, block)


if __name__ == "__main__":
    unittest.main()
