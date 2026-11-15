#!/usr/bin/env python3
"""Offline tests for tools/job_risk.py (rule-based job posting risk screen)."""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import job_risk as jr  # noqa: E402


TODAY = datetime.date(2025, 6, 30)


def make_job(**overrides):
    job = {
        "title": "产品经理实习生",
        "company": "示例科技有限公司",
        "city": "上海",
        "salary_text": "200-300元/天",
        "raw_text": "负责需求调研与原型设计，每周三天以上，本科及以上在读。",
        "posted_at": "2025-06-20",
        "source_channel": "示例渠道",
    }
    job.update(overrides)
    return job


def codes(result):
    return [s["code"] for s in result["signals"]]


class CleanJobTests(unittest.TestCase):
    def test_clean_job_is_low(self):
        result = jr.assess_job_risk(make_job(), today=TODAY)
        self.assertEqual(result["level"], "low")
        self.assertEqual(result["signals"], [])
        self.assertFalse(result["blocks_queue"])


class AgencyTests(unittest.TestCase):
    def test_agency_keyword_flags_verify(self):
        result = jr.assess_job_risk(make_job(raw_text="我司代招多家企业岗位，欢迎猎头合作。"), today=TODAY)
        self.assertIn("agency_recruiter", codes(result))
        self.assertEqual(result["level"], "verify")
        self.assertFalse(result["blocks_queue"])

    def test_no_agency_keyword_no_signal(self):
        self.assertNotIn("agency_recruiter", codes(jr.assess_job_risk(make_job(), today=TODAY)))


class FeeTests(unittest.TestCase):
    def test_fee_keyword_is_high_and_blocks(self):
        result = jr.assess_job_risk(make_job(raw_text="入职前需缴费并办理培训贷。"), today=TODAY)
        self.assertIn("fee_or_training_loan", codes(result))
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["blocks_queue"])

    def test_no_fee_keyword_no_signal(self):
        self.assertNotIn("fee_or_training_loan", codes(jr.assess_job_risk(make_job(), today=TODAY)))


class PromiseTests(unittest.TestCase):
    def test_promise_keyword_is_high(self):
        result = jr.assess_job_risk(make_job(raw_text="课程结束包就业，躺赚高薪。"), today=TODAY)
        self.assertIn("guaranteed_promise", codes(result))
        self.assertTrue(result["blocks_queue"])

    def test_no_promise_keyword_no_signal(self):
        self.assertNotIn("guaranteed_promise", codes(jr.assess_job_risk(make_job(), today=TODAY)))


class SalaryTests(unittest.TestCase):
    def assertWide(self, salary_text, expected):
        result = jr.assess_job_risk(make_job(salary_text=salary_text), today=TODAY)
        self.assertEqual("salary_range_too_wide" in codes(result), expected, salary_text)

    def test_wide_ranges_flagged(self):
        self.assertWide("8-30K", True)
        self.assertWide("8k-30k", True)
        self.assertWide("8000-30000元", True)

    def test_ratio_exactly_three_is_flagged(self):
        self.assertWide("10-30K", True)

    def test_narrow_ranges_not_flagged(self):
        self.assertWide("15-25K", False)
        self.assertWide("8-20K", False)

    def test_unparseable_or_single_value_not_flagged(self):
        self.assertWide("15K·14薪", False)
        self.assertWide("面议", False)
        self.assertWide("", False)

    def test_fullwidth_digits_are_normalized(self):
        self.assertWide("８－３０Ｋ", True)


class MissingInfoTests(unittest.TestCase):
    def test_missing_each_field_flagged(self):
        for field in ("company", "title", "city"):
            result = jr.assess_job_risk(make_job(**{field: "  "}), today=TODAY)
            self.assertIn("missing_key_info", codes(result), field)
            self.assertEqual(result["level"], "verify")

    def test_complete_info_not_flagged(self):
        self.assertNotIn("missing_key_info", codes(jr.assess_job_risk(make_job(), today=TODAY)))


class DuplicateTests(unittest.TestCase):
    def test_duplicate_count_flags(self):
        result = jr.assess_job_risk(make_job(), duplicate_count=1, today=TODAY)
        self.assertIn("duplicate_posting", codes(result))

    def test_zero_duplicates_no_signal(self):
        result = jr.assess_job_risk(make_job(), duplicate_count=0, today=TODAY)
        self.assertNotIn("duplicate_posting", codes(result))


class StaleTests(unittest.TestCase):
    def test_older_than_60_days_flagged(self):
        old = (TODAY - datetime.timedelta(days=61)).isoformat()
        self.assertIn("stale_posting", codes(jr.assess_job_risk(make_job(posted_at=old), today=TODAY)))

    def test_exactly_60_days_not_flagged(self):
        edge = (TODAY - datetime.timedelta(days=60)).isoformat()
        self.assertNotIn("stale_posting", codes(jr.assess_job_risk(make_job(posted_at=edge), today=TODAY)))

    def test_date_formats(self):
        for value in ("2025/03/01", "2025-03-01T08:30:00", "2025-03-01 08:30:00"):
            result = jr.assess_job_risk(make_job(posted_at=value), today=TODAY)
            self.assertIn("stale_posting", codes(result), value)

    def test_empty_or_unparseable_date_no_signal(self):
        for value in ("", None, "最近", "2025-13-45"):
            result = jr.assess_job_risk(make_job(posted_at=value), today=TODAY)
            self.assertNotIn("stale_posting", codes(result), repr(value))


class LevelTests(unittest.TestCase):
    def test_high_wins_over_verify(self):
        result = jr.assess_job_risk(
            make_job(raw_text="猎头代招，需交费。"), duplicate_count=2, today=TODAY
        )
        self.assertEqual(result["level"], "high")
        self.assertTrue(result["blocks_queue"])
        self.assertIn("agency_recruiter", codes(result))

    def test_verify_does_not_block(self):
        result = jr.assess_job_risk(make_job(), duplicate_count=1, today=TODAY)
        self.assertEqual(result["level"], "verify")
        self.assertFalse(result["blocks_queue"])

    def test_case_insensitive_and_fullwidth_matching(self):
        result = jr.assess_job_risk(make_job(salary_text="8K-30K", raw_text="ＳＨＯＵ"), today=TODAY)
        self.assertIn("salary_range_too_wide", codes(result))


class EvidenceTests(unittest.TestCase):
    def test_evidence_is_short_and_not_whole_jd(self):
        long_text = "负责产品工作。" * 100 + "需要缴费。" + "补充说明。" * 100
        result = jr.assess_job_risk(make_job(raw_text=long_text), today=TODAY)
        self.assertTrue(result["signals"])
        for signal in result["signals"]:
            self.assertLessEqual(len(signal["evidence"]), 40)
            self.assertNotEqual(signal["evidence"], long_text)
            self.assertEqual(
                set(signal), {"code", "severity", "label", "evidence"}
            )
        fee = [s for s in result["signals"] if s["code"] == "fee_or_training_loan"][0]
        self.assertEqual(fee["evidence"], "缴费")


class RobustnessTests(unittest.TestCase):
    def test_none_values_do_not_crash(self):
        job = {key: None for key in ("title", "company", "city", "salary_text", "raw_text", "posted_at")}
        result = jr.assess_job_risk(job, today=TODAY)
        self.assertIn("missing_key_info", codes(result))

    def test_empty_and_non_dict_input(self):
        self.assertEqual(jr.assess_job_risk({}, today=TODAY)["level"], "verify")
        self.assertEqual(jr.assess_job_risk(None, today=TODAY)["level"], "verify")  # type: ignore[arg-type]

    def test_non_string_values_do_not_crash(self):
        job = make_job(title=123, company=["示例科技有限公司"], city=4.5, salary_text=10000, raw_text=b"x", posted_at=20250101)
        result = jr.assess_job_risk(job, duplicate_count="abc", today=TODAY)  # type: ignore[arg-type]
        self.assertIn(result["level"], {"low", "verify", "high"})

    def test_default_today_is_used(self):
        result = jr.assess_job_risk(make_job(posted_at="2000-01-01"))
        self.assertIn("stale_posting", codes(result))


if __name__ == "__main__":
    unittest.main()
