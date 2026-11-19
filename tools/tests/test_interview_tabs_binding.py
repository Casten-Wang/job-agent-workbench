"""回归：模拟面试页内页签不能触发整页跳转，旧版模式下也要能切换。

缺陷：app.js 给所有 .ui-hub-tab 绑定 showView(button.dataset.view)，
模拟面试的页签只有 data-iv-tab、没有 data-view，点击后 showView(undefined) 隐藏所有面板，整页空白。
"""

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "web" / "static"


class InterviewTabsBindingTests(unittest.TestCase):
    def setUp(self):
        self.app = (STATIC / "app.js").read_text(encoding="utf-8")
        self.workbench = (STATIC / "workbench.js").read_text(encoding="utf-8")
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")

    def test_hub_tab_navigation_only_binds_tabs_with_data_view(self):
        self.assertNotRegex(
            self.app,
            r"querySelectorAll\('\.ui-hub-tab'\)\.forEach\(\(button\) => \{\s*button\.addEventListener\('click', \(\) => showView\(button\.dataset\.view\)\)",
        )
        self.assertIn(
            "querySelectorAll('.ui-hub-tab[data-view]')", self.app,
            "跨页跳转只能绑定带 data-view 的页签",
        )

    def test_interview_tabs_have_no_data_view(self):
        tabs = re.findall(r'<button[^>]*data-iv-tab="[^"]+"[^>]*>', self.html)
        self.assertEqual(len(tabs), 3)
        for tag in tabs:
            self.assertNotIn("data-view=", tag)

    def test_legacy_mode_wires_interview_tabs_before_returning(self):
        legacy_block = self.workbench.split("if (legacy) {", 1)[1].split("const node =", 1)[0]
        self.assertIn("data-iv-tab", legacy_block)
        self.assertIn("ivMode", legacy_block)
        self.assertIn("return;", legacy_block)


if __name__ == "__main__":
    unittest.main()
