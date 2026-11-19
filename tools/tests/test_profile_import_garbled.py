"""乱码文字层必须明确报错，不能让模型对乱码猜字段后返回「成功」。数据全部为虚构。"""

import sys
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import profile_import

# 模拟「字体无 ToUnicode 映射」的抽取结果：大量埃塞俄比亚/亚美尼亚/泰米尔等无关字符夹杂少量 ASCII
GARBLED = "\n".join([
    "ӻՈמ௳   ", "ᦜ஛Ớ҅ካ҅ଠӳ࿯ᳪՈ", "ᘶᔮොୗ   ", "ಋ๢ғ13800000000",
    "ᆧᕞഩൎObjective-C̵HTML̵JavaScript̵CSS҅ԧᥴSwift", "ᆧఀXcode୏ݎሾह҅ᚆᬰᤈच๜ጱӱۓ",
    "ᨮᨱሿํۑᚆጱbug᧣ᦶ̵ץ॔҅ڥአBuglyਧ֖Კ᧏դᎱ", "ᨮᨱḒᶭ̵ᭌᙎᶭ̵ෛ᳼ᶭ̵ӻՈמ௳ᶭᒵෛӱۓጱ୏ݎ",
])
GOOD_CN = "姓名：测试同学\n教育经历：某某大学 软件工程 本科\n工作经历：某某科技 产品实习生，负责用户访谈与需求整理，输出访谈纪要。\n技能：Python SQL Excel Axure"
GOOD_EN = "Jane Doe\nSoftware Engineer\nExperience: built REST APIs with Python and PostgreSQL, résumé parsing, naïve Bayes classifier."


class GarbledTextTests(unittest.TestCase):
    def test_garbled_text_is_detected(self):
        self.assertTrue(profile_import.looks_garbled(GARBLED))

    def test_normal_chinese_english_and_accents_are_not_flagged(self):
        self.assertFalse(profile_import.looks_garbled(GOOD_CN))
        self.assertFalse(profile_import.looks_garbled(GOOD_EN))

    def test_short_text_is_never_flagged(self):
        self.assertFalse(profile_import.looks_garbled("ᦜᘶᔮ"))

    def test_extract_resume_text_rejects_garbled_plain_text_with_actionable_message(self):
        with self.assertRaises(ValueError) as caught:
            profile_import.extract_resume_text("resume.txt", GARBLED.encode("utf-8"))
        message = str(caught.exception)
        self.assertIn("乱码", message)
        self.assertIn("重新导出", message)

    def test_extract_resume_text_still_accepts_normal_text(self):
        self.assertIn("测试同学", profile_import.extract_resume_text("resume.txt", GOOD_CN.encode("utf-8")))

    def test_kangxi_radicals_are_folded_to_common_characters(self):
        text = "产品经理实习\u2f63，负责用户访谈与需求整理，输出访谈纪要，熟悉 SQL 与 Axure。"
        self.assertIn("实习生", profile_import.extract_resume_text("r.txt", text.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
