"""PDF 导出的中文字体选择：不能落到 Songti.ttc 的 Black 子字体（整页粗黑且缺「•」）。"""

import sys
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import resume_pdf

SONGTI = Path("/System/Library/Fonts/Supplemental/Songti.ttc")


class SubfontTests(unittest.TestCase):
    def test_mac_collections_use_simplified_regular_subfonts(self):
        self.assertEqual(resume_pdf.subfont_index("/x/Songti.ttc"), 6)
        self.assertEqual(resume_pdf.subfont_index("/x/STHeiti Medium.ttc"), 1)
        self.assertEqual(resume_pdf.subfont_index("/x/STHeiti Light.ttc"), 1)

    def test_other_fonts_keep_index_zero(self):
        for name in ("simsun.ttc", "msyh.ttc", "wqy-zenhei.ttc", "font.ttf"):
            self.assertEqual(resume_pdf.subfont_index(f"/x/{name}"), 0)

    @unittest.skipUnless(SONGTI.is_file(), "needs macOS Songti")
    def test_selected_songti_subfont_is_regular_and_has_bullet(self):
        from fontTools.ttLib import TTCollection
        font = TTCollection(str(SONGTI)).fonts[resume_pdf.subfont_index(SONGTI)]
        self.assertIn("Regular", font["name"].getDebugName(4))
        self.assertIn(0x2022, font.getBestCmap())

    def test_both_templates_render_a_pdf(self):
        for template in ("professional", "classic"):
            with self.subTest(template=template):
                data = resume_pdf.render_pdf("# 测试同学\n\n## 项目经历\n- 带领 5 人团队完成上线\n", role="产品经理", template=template)
                self.assertTrue(data.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
