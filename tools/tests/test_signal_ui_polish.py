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
        # 设置页只保留一份「最近操作」，旧的隐藏副本已移除。
        self.assertNotIn("sg-legacy-activity", self.css)
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

    def test_settings_keeps_a_single_activity_list(self):
        self.assertNotIn("activity-overview", _read(INDEX))
        self.assertNotIn("activityOverview", self.script)
        self.assertEqual(_read(INDEX).count('id="activity-data"'), 1)
        self.assertIn("renderActivity(dom.activityData, snapshot.activity)", self.script)

    def test_collect_wizard_offers_four_platforms_for_every_mode(self):
        html = _read(INDEX)
        select = _between(html, 'id="collect-platform"', "</select>")
        for value in ("boss", "zhilian", "51job", "liepin"):
            self.assertIn(f'value="{value}"', select)
        self.assertNotIn("BOSS 直聘岗位采集", html)
        self.assertNotIn("platform: 'boss',", self.script)
        self.assertIn("platform: collectPlatform(),", self.script)
        # 平台不再因为「完整流程」被锁定成 Boss。
        picker = _between(self.script, "function collectPlatform()", "function collectPlatformLabel(")
        self.assertNotIn("collectMode()", picker)
        sync = _between(self.script, "function syncCollectModeUI()", "function syncCollectResumeUI()")
        self.assertNotIn("dom.collectPlatform.disabled = locked", sync)
        self.assertNotIn("目前只有 Boss直聘 开放投递", self.script)
        self.assertIn("COLLECT_PLATFORMS", self.script)
        key = _between(self.script, "function collectFormKey()", "function buildOfferPilotOptions(")
        self.assertIn("collectPlatform()", key)

    def test_collect_page_has_pass_line_and_short_scoring_explainer(self):
        html = _read(INDEX)
        self.assertIn('id="collect-min-score"', html)
        self.assertIn("合格线", html)
        for weight in ("核心职责 30", "项目成果 25", "技能工具 15"):
            self.assertIn(weight, html)
        self.assertNotIn("会采集什么、不会做什么", html)
        # 合格线随自动流程一起发给后端，并记在本机浏览器里。
        auto = _between(self.script, "async function maybeAutoImportCollected(", "async function uploadOfferPilotResume(")
        self.assertIn("min_score: collectMinScore()", auto)
        self.assertIn("COLLECT_MIN_SCORE_KEY", self.script)

    def test_collect_platform_picker_behaviour(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用")
        fn = _between(self.script, "const COLLECT_PLATFORMS", "/* 采集页「本次初筛条件」")
        harness = (
            "const CHANNEL_LABELS = {boss:'Boss直聘', liepin:'猎聘', '51job':'前程无忧', zhilian:'智联招聘'};\n"
            "var dom = {offerpilotMode:{value:'collect'}, collectPlatform:{value:'liepin'}};\n"
            "function collectMode(){ return dom.offerpilotMode.value; }\n"
            + fn + """
const out = {};
out.collect_liepin = collectPlatform();
dom.collectPlatform.value = 'bad'; out.bad = collectPlatform();
dom.collectPlatform.value = 'zhilian'; dom.offerpilotMode.value = 'full'; out.full_keeps_choice = collectPlatform();
out.label = collectPlatformLabel('51job');
process.stdout.write(JSON.stringify(out));
"""
        )
        done = subprocess.run([node, "-e", harness], text=True, capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[:500])
        self.assertEqual(
            json.loads(done.stdout),
            {"collect_liepin": "liepin", "bad": "boss", "full_keeps_choice": "zhilian", "label": "前程无忧"},
        )

    def test_collect_count_explains_gap_to_job_pool(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node 不可用")
        fn = _between(self.script, "function offerpilotJobsCountText(", "function renderOfferPilotJobs(")
        harness = (
            fn + """
const jobs = [{id:'a'},{id:'b'},{id:'c'}];
const pool = new Set(['a','c']);
process.stdout.write(JSON.stringify({
  trimmed: offerpilotJobsCountText(jobs, 126, pool),
  full: offerpilotJobsCountText(jobs, 3, new Set()),
  empty: offerpilotJobsCountText([], 0, pool),
}));
"""
        )
        done = subprocess.run([node, "-e", harness], text=True, capture_output=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[:500])
        out = json.loads(done.stdout)
        self.assertEqual(out["trimmed"], "显示前 3 条 / 共 126 条；其中 2 条已在岗位池，其余需勾选后导入")
        self.assertEqual(out["full"], "共 3 条；其中 0 条已在岗位池，其余需勾选后导入")
        self.assertEqual(out["empty"], "共 0 条")
        render = _between(self.script, "function renderOfferPilotJobs(", "function syncOfferPilotSelection(")
        self.assertIn("offerpilotPoolIds()", render)
        self.assertIn("'；已在岗位池'", render)

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


class WindowsLauncherTests(unittest.TestCase):
    """Windows 启动脚本要用仓库内 .venv、不加 -I，且 README 不再留下已不存在的启动/凭据说法。"""

    def test_ps1_uses_repo_venv_without_isolated_mode(self):
        ps1 = _read(PROJECT_ROOT / "run_career_demo.ps1")
        self.assertIn(".venv\\Scripts\\python.exe", ps1)
        self.assertNotIn(".venv-interview", ps1)
        self.assertNotIn(" -I ", ps1)
        self.assertIn("tools\\run_career_demo.py", ps1)
        self.assertIn("--engine-root", ps1)
        self.assertIn("NO_PROXY", ps1)

    def test_docs_do_not_mention_removed_launcher_pieces(self):
        for rel in ("README.md", "web/WORKBENCH-AGENT-API.md", "web/PERSONAL-CAREER-API.md"):
            text = _read(PROJECT_ROOT / rel)
            for stale in ("start-background.py", "--reset-keys", ".venv-interview", "上级 Python 引擎", "上级目录的 Python 引擎"):
                self.assertNotIn(stale, text, (rel, stale))
        readme = _read(PROJECT_ROOT / "README.md")
        self.assertIn("run_career_demo.ps1", readme)
        self.assertIn("--remote-debugging-port=9222", readme)
        self.assertIn("chrome.exe", readme)

    def test_markdown_relative_links_resolve(self):
        import re
        for rel in ("README.md", "interview_agent/README.md", "web/KNOWLEDGE-API.md", "web/WORKBENCH-AGENT-API.md", "web/PERSONAL-CAREER-API.md"):
            base = (PROJECT_ROOT / rel).parent
            for target in re.findall(r"\]\((?!https?://|#|mailto:)([^)#\s]+)", _read(PROJECT_ROOT / rel)):
                self.assertTrue((base / target).exists(), (rel, target))

    def test_launcher_has_no_dead_key_option(self):
        source = _read(PROJECT_ROOT / "tools/run_career_demo.py")
        self.assertNotIn("--key-stdin", source)
        self.assertNotIn("getpass.getpass(\"Step API key", source)

    def test_launcher_banner_does_not_claim_fixed_model(self):
        self.assertNotIn("step-5-preview", _read(PROJECT_ROOT / "tools/run_career_demo.py"))


class TestGateAndPdfFontTests(unittest.TestCase):
    def test_run_tests_script_runs_all_three_suites(self):
        script = _read(PROJECT_ROOT / "tools/run_tests.sh")
        for suite in ("-s tools/tests", "-s tests", "-s interview_agent/tests"):
            self.assertIn(suite, script)
        self.assertIn("status=1", script)
        self.assertIn("exit $status", script)

    def test_pdf_export_has_non_windows_cjk_font_candidates(self):
        source = _read(PROJECT_ROOT / "web/resume_pdf.py")
        for font in ("simsun.ttc", "msyh.ttc", "Songti.ttc", "STHeiti Medium.ttc"):
            self.assertIn(font, source)
        self.assertIn("def cjk_font_candidates", source)


class ReadmeRunStepsTests(unittest.TestCase):
    """README 里的安装与启动步骤要和仓库里真实存在的文件、命令一致。"""

    @classmethod
    def setUpClass(cls):
        cls.readme = _read(PROJECT_ROOT / "README.md")

    def test_commands_point_at_files_that_exist(self):
        for command in (
            "python3 -m venv .venv",
            "-r requirements-offerpilot.txt -r interview_agent/requirements.lock.txt",
            "tools/run_career_demo.py --engine-root .",
            "./run_web.sh",
            "sh tools/run_tests.sh",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.readme)
        for path in (
            "requirements-offerpilot.txt",
            "interview_agent/requirements.lock.txt",
            "tools/run_career_demo.py",
            "run_web.sh",
            "tools/run_tests.sh",
        ):
            with self.subTest(path=path):
                self.assertTrue((PROJECT_ROOT / path).is_file())

    def test_old_launch_instructions_are_gone(self):
        self.assertNotIn("--key-stdin", self.readme)
        self.assertNotIn("<引擎目录>", self.readme)

    def test_platform_table_matches_the_collector_capabilities(self):
        caps = _read(PROJECT_ROOT / "vendor" / "offerpilot" / "src" / "offerpilot" / "collection" / "capabilities.py")
        self.assertIn('"boss": frozenset({"collect", "score", "greet", "deliver", "monitor"})', caps)
        for platform in ("zhilian", "51job", "liepin"):
            self.assertIn(f'"{platform}": frozenset({{"collect", "score", "greet"}})', caps)
        for label in ("Boss直聘", "智联招聘", "前程无忧", "猎聘"):
            self.assertIn(label, self.readme)


if __name__ == "__main__":
    unittest.main()
