"""「信号」打磨层：个人资料 / 定制简历 / 模拟面试 / 信息推送 的静态断言。

只检查标记、样式与渲染函数的连接关系，不启动服务；行为测试仍在 test_web_backend.py。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class SignalToolsUiTest(unittest.TestCase):
    def test_signal_tools_stylesheet_loads_after_shared_layers(self):
        html = read("index.html")
        for name in ("sg-base.css", "sg-pipeline.css", "sg-tools.css"):
            with self.subTest(name=name):
                self.assertIn(f'href="/{name}"', html)
        self.assertLess(html.index('href="/sg-base.css"'), html.index('href="/sg-tools.css"'))
        self.assertLess(html.index('href="/sg-pipeline.css"'), html.index('href="/sg-tools.css"'))

    def test_profile_has_section_nav_and_completeness_bar(self):
        html = read("index.html")
        for marker in (
            'id="profile-meter"',
            'id="sg-profile-nav-list"',
            'id="sg-profile-sec-basic"',
            'id="sg-profile-sec-intent"',
            'id="sg-profile-sec-education"',
            'id="sg-profile-sec-experiences"',
            'id="sg-profile-sec-projects"',
            'id="sg-profile-sec-skills"',
            'id="sg-profile-sec-summary"',
            'id="sg-profile-sec-truth"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        script = read("app.js")
        self.assertIn("function renderProfileNav(", script)
        self.assertIn("SG_PROFILE_NAV_SECTIONS", script)
        # 必填规则来自后端返回的 completeness.required，不在前端另写一套。
        self.assertIn("data.required", script)
        # 走查第 5 条：分节 hint 直接渲染在 chip 旁，选填邮箱写明「选填，影响完整度」。
        self.assertIn("sg-profile-chip-hint", script)
        self.assertIn("section.hint", script)
        self.assertIn("选填，影响完整度", html)

    def test_unconnected_agent_cards_move_to_page_bottom_details(self):
        html = read("index.html")
        self.assertEqual(html.count('<details class="sg-dev-note">'), 2)
        for marker in ('id="profile-api-title"', 'id="push-agent-title"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        # 四页视图中不再保留旧的编号角标，避免与左侧导航编号冲突（走查第 9 条）。
        for view in ("view-profile", "view-resume", "view-interview", "view-push"):
            start = html.index(f'id="{view}"')
            end = html.index("<section class=\"view\"", start + 10)
            with self.subTest(view=view):
                self.assertNotIn('class="integration-mark"', html[start:end])

    def test_variant_table_keeps_compare_column_visible(self):
        script = read("app.js")
        self.assertIn("columns: ['项目', '保存时间', '经历原文', '主稿对比']", script)
        html = read("index.html")
        self.assertIn('class="panel sg-variant-saved"', html)

    def test_interview_hub_cards_share_one_grid(self):
        css = read("sg-tools.css")
        self.assertIn("#interview-hub.pipeline", css)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", css)
        self.assertIn("sg-card-count", css)
        script = read("app.js")
        self.assertIn("sg-card-count", script)
        self.assertIn("sg-card-enter", script)

    def test_empty_submits_show_inline_feedback(self):
        script = read("app.js")
        for marker in (
            "showInline(dom.atsResult, message, 'error')",
            "showInline(dom.variantResult, message, 'error')",
            "showInline(dom.debriefResult, message, 'error')",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        html = read("index.html")
        self.assertIn('id="sg-chat-reason"', html)
        # 走查第 3 条：未开始时答题框与两个「模拟…」测试按钮都隐藏。
        self.assertIn('id="sg-chat-mock-tools"', html)
        self.assertIn("dom.chatAnswer.hidden = phase === 'idle'", script)
        self.assertIn("mockTools.hidden = phase === 'idle'", script)
        self.assertIn("预计", script)

    def test_push_form_uses_placeholders(self):
        html = read("index.html")
        self.assertIn('id="sg-dry-empty"', html)
        for marker in ('placeholder="例如 web-demo"', 'placeholder="例如 虚构公司"',
                       'placeholder="例如 产品经理"', 'placeholder="例如 已采集"',
                       'placeholder="例如 manual_paste"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)
        self.assertNotIn('id="dry-job-id" type="text" value=', html)


if __name__ == "__main__":
    unittest.main()
