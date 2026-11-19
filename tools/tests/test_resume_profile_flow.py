"""定制简历改为「从个人资料带出经历」：页面结构与说明文字。

只做静态断言，不启动服务；行为测试在 test_career_user.py。
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "web" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


HTML = read("index.html")
APP = read("app.js")
CAREER = read("career-user.js")


def view(name: str) -> str:
    start = HTML.index(f'id="view-{name}"')
    end = HTML.index('<section class="view"', start + 10)
    return HTML[start:end]


class ResumeProfileFlowTest(unittest.TestCase):
    def test_resume_view_no_longer_hosts_import_entries(self):
        resume = view("resume")
        for marker in (
            "cu-source-type", "cu-exp-file", "cu-extract-text",
            "career-public-title", "cu-github-panel", "cu-experience-form",
            "variant-form", "data-resume-tab",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, resume)

    def test_legacy_nodes_stay_in_dom_for_scripts_and_capabilities(self):
        # career-user.js / workbench.js 仍按 id 取这些节点，能力入口也指向它们，
        # 因此只移出定制简历页并隐藏，不删除节点。
        self.assertIn('id="cu-legacy-import"', HTML)
        for marker in ('name="cu-source-type"', 'id="cu-github-panel"',
                       'id="cu-experience-form"', 'id="variant-form"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, HTML)

    def test_four_steps_with_only_the_target_required(self):
        resume = view("resume")
        for marker in ('id="cu-step-target"', 'id="cu-step-material"', 'id="cu-step-generate"',
                       'id="cu-job-select"', 'id="cu-target-role"', 'id="cu-target-jd"',
                       'id="cu-entry-list"', 'id="cu-generate-consent"', 'id="cu-generate"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, resume)
        target = resume[resume.index('id="cu-step-target"'):resume.index('id="cu-step-material"')]
        self.assertEqual(target.count("sg-required"), 1)
        self.assertEqual(resume.count('id="cu-generate-consent"'), 1)
        self.assertNotIn('id="cu-exp-confirmed"', resume)

    def test_ats_moves_after_preview_as_self_check(self):
        resume = view("resume")
        self.assertLess(resume.index('id="cu-resume-preview"'), resume.index('id="ats-form"'))
        self.assertIn("导出后自检", resume)
        self.assertIn('id="variant-list"', resume)

    def test_unconfirmed_profile_shows_guidance_before_generating(self):
        resume = view("resume")
        self.assertIn('id="cu-profile-gate"', resume)
        self.assertIn("去个人资料补全", resume)
        self.assertIn("先到「个人资料」补一段可核实的经历", resume)
        self.assertIn("profileData.truth_confirmed", CAREER)
        self.assertIn("showView('profile')", CAREER)

    def test_client_uses_checked_profile_entries(self):
        self.assertIn("'/profile-experience'", CAREER)
        self.assertIn("const items = selectedEntries();", CAREER)
        self.assertIn("selectionForDraft", CAREER)
        self.assertIn("body.items=selectionForDraft", CAREER)
        self.assertIn("已保存的变体会在这里与主稿逐段对比", APP)


if __name__ == "__main__":
    unittest.main()
