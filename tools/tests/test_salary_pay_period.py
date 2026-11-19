"""Daily/hourly quotes must never be compared with a monthly salary floor."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "vendor/offerpilot/src"), str(ROOT / "tools")]

from offerpilot.ai.prefilter import _parse_salary_range_k, quick_score
import filters


class SalaryPayPeriodTests(unittest.TestCase):
    def profile(self, **overrides):
        return {"profile": {"allow_internship": True, "salary_min": 15, "salary_max": 25,
                            "filter_unparsed_salary": True, "target_cities": ["上海"], **overrides}}

    def job(self, salary, **overrides):
        return {"title": "Agent应用开发实习生", "company": "测试科技有限公司", "city": "上海",
                "salary": salary, **overrides}

    def test_daily_and_hourly_pay_are_not_monthly_salary(self):
        for salary in ("400-500元/天", "200元/日", "80-100元/小时", "时薪80元", "周薪2000元", "300/天"):
            with self.subTest(salary=salary):
                self.assertIsNone(_parse_salary_range_k(salary))
                self.assertEqual(quick_score(self.job(salary), self.profile())[0], 100)

    def test_monthly_floor_and_ceiling_still_apply(self):
        self.assertEqual(quick_score(self.job("10-14K"), self.profile())[0], 0)
        self.assertEqual(quick_score(self.job("15-25K·14薪"), self.profile())[0], 100)
        self.assertEqual(quick_score(self.job("50-60K"), self.profile())[0], 0)
        self.assertEqual(_parse_salary_range_k("20-30K，5天/周"), (20, 30))

    def test_accepting_daily_pay_does_not_enable_internships(self):
        self.assertEqual(quick_score(self.job("400-500元/天"), self.profile(allow_internship=False))[0], 0)

    def test_local_filter_keeps_raw_pay_without_fabricating_monthly_numbers(self):
        salary = "400-500元/天"
        parsed = filters.parse_salary(salary)
        self.assertIsNone(parsed["salary_min"])
        self.assertIsNone(parsed["salary_max"])
        self.assertEqual(parsed["text"], salary)
        result = filters.apply_hard_filters({"company": "测试科技有限公司", "title": "Agent应用开发实习生",
                                            "city": "上海", "salary_text": salary})
        self.assertTrue(result["hard_filter"]["pass"])


if __name__ == "__main__":
    unittest.main()
