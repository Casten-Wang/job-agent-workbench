#!/usr/bin/env python3
"""Static checks for the 「信号」 polish layer (sg-base).

Offline only: reads the shipped static files.  No endpoint is called and
nothing is sent.
"""

from __future__ import annotations

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
        self.assertIn("#view-data .sg-system > summary", self.css)
        self.assertIn("#view-data .sg-legacy-activity", self.css)
        self.assertIn("#view-data .sg-system-body", self.css)

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

    def test_settings_puts_ai_first_and_folds_the_board(self):
        view = self.html[self.html.index('id="view-data"'):]
        self.assertLess(view.index('id="ai-settings-panel"'), view.index('id="ops-title"'))
        self.assertIn('class="sg-help"', view)
        self.assertIn('id="sg-system"', view)
        self.assertIn("运行看板与操作记录", view)
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

    def test_ai_provider_switch_fills_defaults(self):
        self.assertIn("const AI_PROVIDER_DEFAULTS = {", self.script)
        self.assertIn("applyAiProviderDefaults", self.script)
        self.assertIn(
            "dom.aiSettingsService.addEventListener('change', applyAiProviderDefaults)",
            self.script,
        )

    def test_boundary_labels_include_the_embedded_component(self):
        self.assertIn("offerpilot_integration: '岗位自动化组件'", self.script)
        self.assertIn("embedded: '内嵌，已就绪'", self.script)

    def test_home_renderer_fills_the_side_column(self):
        block = _between(self.script, "function renderHomeSide(", "function renderHomeToday(")
        for marker in ("homePipelineStageCount(snapshot, key)", "snapshot.activity.slice(0, 5)", "sg-side-num"):
            with self.subTest(marker=marker):
                self.assertIn(marker, block)


if __name__ == "__main__":
    unittest.main()
