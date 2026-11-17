#!/usr/bin/env python3
"""Tests for the read-only ``job.standard`` view.

No test writes to ``web/data``, calls the network or invents a value.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "tools"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import job_standardize  # noqa: E402

JD_TEXT = """公司：虚构星河科技有限公司
岗位：产品经理
城市：上海
薪资：20-30K
岗位职责：
1. 负责产品需求分析与原型设计；
2. 推动版本上线与数据复盘。
任职要求：
- 本科及以上学历；
- 熟练使用 Axure、Visio 输出原型与 PRD。
加分项：
有 B2B 电商或供应链项目经验优先。
"""


def _job(**extra: object) -> dict:
    row = {
        "id": "j-standard-1",
        "company": "虚构星河科技有限公司",
        "title": "产品经理",
        "city": "上海",
        "raw_text": "",
        "source_channel": "boss",
        "salary_text": "20-30K",
        "posted_at": "2026-11-16 11:52:58",
        "hiring_status": "unknown",
    }
    row.update(extra)
    return row


class SplitSectionsTests(unittest.TestCase):
    def test_extracts_three_sections_and_strips_bullets(self) -> None:
        sections = job_standardize.split_sections(JD_TEXT)
        self.assertEqual(
            sections["responsibilities"],
            ["负责产品需求分析与原型设计；", "推动版本上线与数据复盘。"],
        )
        self.assertEqual(
            sections["must_have"],
            ["本科及以上学历；", "熟练使用 Axure、Visio 输出原型与 PRD。"],
        )
        self.assertEqual(sections["nice_to_have"], ["有 B2B 电商或供应链项目经验优先。"])

    def test_missing_sections_are_none(self) -> None:
        sections = job_standardize.split_sections("公司：虚构公司\n岗位：产品经理")
        self.assertEqual(
            sections,
            {"responsibilities": None, "must_have": None, "nice_to_have": None},
        )

    def test_empty_raw_text_is_none(self) -> None:
        for value in (None, "", "   "):
            with self.subTest(value=value):
                sections = job_standardize.split_sections(value)
                self.assertIsNone(sections["responsibilities"])

    def test_heading_without_separator_stays_body_text(self) -> None:
        sections = job_standardize.split_sections("岗位要求相关文档编写经验五年以上")
        self.assertIsNone(sections["must_have"])

    def test_colon_heading_keeps_inline_content(self) -> None:
        sections = job_standardize.split_sections("职位描述：负责虚构产品的需求分析")
        self.assertEqual(sections["responsibilities"], ["负责虚构产品的需求分析"])


class StandardizeJobTests(unittest.TestCase):
    def test_standard_view_derives_from_existing_fields(self) -> None:
        standard = job_standardize.standardize_job(_job(raw_text=JD_TEXT))
        self.assertEqual(standard["title"], "产品经理")
        self.assertEqual(standard["location"], "上海")
        self.assertEqual(standard["must_have"][0], "本科及以上学历；")
        self.assertEqual(standard["nice_to_have"], ["有 B2B 电商或供应链项目经验优先。"])
        self.assertEqual(standard["responsibilities"][0], "负责产品需求分析与原型设计；")
        self.assertEqual(
            standard["salary_and_start"], {"salary": "20-30K", "start": None}
        )
        self.assertEqual(standard["hiring_status"], "unknown")
        self.assertEqual(standard["source_platform"], "boss")
        self.assertEqual(standard["source_updated_at"], "2026-11-16 11:52:58")

    def test_standard_view_has_exactly_the_contract_keys(self) -> None:
        standard = job_standardize.standardize_job(_job())
        self.assertEqual(
            set(standard),
            {
                "title",
                "location",
                "responsibilities",
                "must_have",
                "nice_to_have",
                "salary_and_start",
                "hiring_status",
                "source_platform",
                "source_updated_at",
            },
        )

    def test_scored_conditions_win_over_raw_text_section(self) -> None:
        job = _job(
            raw_text=JD_TEXT,
            mandatory_conditions=[
                {"condition": "五年以上 B2B 产品经验", "status": "明确不满足", "evidence": "不足五年"},
                {"condition": "本科及以上学历", "status": "已满足", "evidence": "本科"},
                {"condition": "", "status": "待确认", "evidence": ""},
            ],
        )
        standard = job_standardize.standardize_job(job)
        self.assertEqual(standard["must_have"], ["五年以上 B2B 产品经验", "本科及以上学历"])

    def test_missing_and_placeholder_values_are_null(self) -> None:
        job = {
            "title": "未填写岗位",
            "company": "未填写公司",
            "city": "",
            "raw_text": "",
            "salary_text": "未填写",
            "salary_label": "未填写",
            "source_channel": "manual_paste",
        }
        standard = job_standardize.standardize_job(job)
        self.assertIsNone(standard["title"])
        self.assertIsNone(standard["location"])
        self.assertIsNone(standard["responsibilities"])
        self.assertIsNone(standard["must_have"])
        self.assertIsNone(standard["nice_to_have"])
        self.assertIsNone(standard["salary_and_start"])
        self.assertIsNone(standard["hiring_status"])
        self.assertIsNone(standard["source_platform"])
        self.assertIsNone(standard["source_updated_at"])

    def test_salary_uses_numeric_range_only_when_text_missing(self) -> None:
        job = _job(salary_text="", salary_label="未填写", salary_min=15000, salary_max=25000)
        self.assertEqual(
            job_standardize.standardize_job(job)["salary_and_start"],
            {"salary": "15–25k", "start": None},
        )

    def test_start_is_taken_only_from_an_explicit_start_field(self) -> None:
        job = _job(start="一个月内", posted_at="2026-11-16")
        standard = job_standardize.standardize_job(job)
        self.assertEqual(standard["salary_and_start"], {"salary": "20-30K", "start": "一个月内"})
        # posted_at feeds source_updated_at, never the start date.
        self.assertEqual(standard["source_updated_at"], "2026-11-16")

    def test_source_platform_prefers_explicit_then_known_channel(self) -> None:
        self.assertEqual(
            job_standardize.standardize_job(_job(source_platform="zhilian"))["source_platform"],
            "zhilian",
        )
        self.assertEqual(
            job_standardize.standardize_job(_job(source_channel="BOSS"))["source_platform"],
            "boss",
        )
        self.assertIsNone(
            job_standardize.standardize_job(_job(source_channel="manual_paste"))["source_platform"]
        )


if __name__ == "__main__":
    unittest.main()
