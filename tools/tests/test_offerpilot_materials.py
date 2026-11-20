#!/usr/bin/env python3
"""Prompt principles and the custom application materials package.

The model is always mocked: no network call, no AI request, no send. Every
database is a temporary file and every company/resume below is test data.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "tools"), str(PROJECT_ROOT / "vendor" / "offerpilot" / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot.ai.greeter as greeter  # noqa: E402
from offerpilot.db import get_db  # noqa: E402

RESUME = """测试数据：示例求职者

教育经历
- 示例大学 本科

项目经历
- 负责需求梳理与原型设计，参与用户访谈 6 人。
"""

VALID_PAYLOAD = {
    "mapping": [
        {
            "requirement": "本科及以上学历",
            "evidence": "示例大学 本科",
            "source": "教育经历",
        },
        {
            "requirement": "熟悉需求分析",
            "evidence": "负责需求梳理与原型设计",
            "source": "项目经历",
        },
    ],
    "conditions": [
        {"condition": "本科及以上学历", "status": "已满足", "evidence": "示例大学 本科"},
        {"condition": "有电商行业经验", "status": "待确认", "evidence": "未知"},
    ],
    "unknown_fields": ["到岗时间", "团队规模"],
    "resume_suggestions": [
        {
            "original": "负责需求梳理与原型设计",
            "suggested": "负责需求梳理、原型设计与用户访谈",
            "evidence": "项目经历：参与用户访谈 6 人",
            "reason": "对应岗位需求分析要求；访谈范围未写明是否独立负责",
        }
    ],
    "greetings": {
        "concise": "您好，我有需求梳理与原型设计经验，想了解这个岗位。",
        "project": "您好，我在项目中负责需求梳理与原型设计，参与过用户访谈，想进一步了解岗位。",
        "safe": "您好，我想了解这个岗位。我做过需求梳理与原型设计，可进一步沟通。",
    },
    "confirm_items": ["确认项目经历中用户访谈的负责范围"],
}

CONFIG = {
    "profile": {
        "ai_greeting_enabled": True,
        "greeting_preference": "",
        "resume_path": "",
    },
    "ai": {},
}


def _materials_call(payload: dict | None = None):
    text = json.dumps(VALID_PAYLOAD if payload is None else payload, ensure_ascii=False)
    return patch.object(greeter, "_call_claude", return_value=text)


class PromptPrincipleTests(unittest.TestCase):
    def test_broken_json_is_repaired_once_without_echoing_raw_output(self):
        reasons = []
        with patch.object(greeter, "_call_claude", side_effect=["private malformed response", json.dumps(VALID_PAYLOAD)]) as call:
            result = greeter._generate_materials_once(
                {"title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG, failure_reasons=reasons,
            )
        self.assertIsNotNone(result)
        self.assertEqual(call.call_count, 2)
        self.assertIn(RESUME, call.call_args.args[0])
        self.assertIn("JSON", call.call_args.args[0])
        self.assertNotIn("private malformed response", call.call_args.args[0])
        self.assertEqual(reasons, [])

    def test_source_quote_is_repaired_or_rejected_by_the_same_checks(self):
        invalid = json.loads(json.dumps(VALID_PAYLOAD))
        invalid["resume_suggestions"][0]["original"] = "private fabricated original"
        for final in (VALID_PAYLOAD, invalid):
            with self.subTest(repaired=final is VALID_PAYLOAD):
                reasons = []
                with patch.object(greeter, "_call_claude", side_effect=[json.dumps(invalid), json.dumps(final)]) as call:
                    result = greeter._generate_materials_once(
                        {"title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG, failure_reasons=reasons,
                    )
                self.assertEqual(result is not None, final is VALID_PAYLOAD)
                self.assertEqual(call.call_count, 2)
                self.assertIn("resume_suggestions[0].original", call.call_args.args[0])
                self.assertNotIn("private fabricated original", call.call_args.args[0])
                if final is not VALID_PAYLOAD:
                    self.assertIn("resume_suggestions[0].original", reasons[0])
                    self.assertNotIn("private fabricated original", reasons[0])
                else:
                    self.assertEqual(reasons, [])

    def test_repair_and_truncation_share_a_three_call_budget(self):
        truncation = greeter.AIRequestError("output_truncated", "fixture truncation")
        cases = (
            ([truncation, "bad JSON", json.dumps(VALID_PAYLOAD)], True),
            (["bad JSON", truncation, "still bad JSON"], False),
        )
        for responses, succeeds in cases:
            with self.subTest(succeeds=succeeds):
                with patch.object(greeter, "_call_claude", side_effect=responses) as call:
                    result = greeter._generate_materials_once(
                        {"title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG,
                    )
                self.assertEqual(result is not None, succeeds)
                self.assertEqual(call.call_count, 3)
                for request in call.call_args_list:
                    self.assertIn(RESUME, request.args[0])

    def test_truncated_materials_retry_once_without_dropping_source(self):
        error = greeter.AIRequestError("output_truncated", "fixture truncation")
        with patch.object(greeter, "_call_claude", side_effect=[error, json.dumps(VALID_PAYLOAD)]) as call:
            result = greeter._generate_materials_once({"id": "job-1", "title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG)
        self.assertIsNotNone(result)
        self.assertEqual(call.call_count, 2)
        first, second = call.call_args_list
        self.assertEqual(first.args[0], second.args[0])
        self.assertIn(RESUME, first.args[0])
        self.assertGreater(second.kwargs["max_tokens"], first.kwargs["max_tokens"])
        self.assertLessEqual(second.kwargs["max_tokens"], 32768)

    def test_materials_network_errors_do_not_retry(self):
        error = greeter.AIRequestError("network", "fixture network failure")
        with patch.object(greeter, "_call_claude", side_effect=error) as call:
            with self.assertRaises(greeter.AIRequestError):
                greeter._generate_materials_once({"title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG)
        self.assertEqual(call.call_count, 1)

    def test_repeated_truncation_still_fails_without_a_partial_package(self):
        error = greeter.AIRequestError("output_truncated", "fixture truncation")
        with patch.object(greeter, "_call_claude", side_effect=error) as call:
            with self.assertRaises(greeter.AIRequestError):
                greeter._generate_materials_once({"title": "测试岗位", "company": "测试公司"}, RESUME, CONFIG)
        self.assertEqual(call.call_count, 2)

    def test_materials_output_budget_covers_full_resume_package(self):
        with patch.object(greeter, "_call_claude", return_value="invalid") as call:
            greeter._generate_materials_once(
                {"id": "job-1", "title": "开发实习生", "company": "测试公司"},
                RESUME, {"ai": {"greeting_max_tokens": 8192}},
            )
        self.assertEqual(call.call_args.kwargs["max_tokens"], 16384)
        self.assertEqual(call.call_args.kwargs["purpose"], "materials")

    def test_greeting_and_review_prompts_carry_the_user_principles(self) -> None:
        greeting_prompt = greeter.GREETING_PROMPT
        review_prompt = greeter.REVIEW_PROMPT
        for text in (greeting_prompt, review_prompt):
            self.assertIn("只使用档案中明确存在的经历", text)
            self.assertIn("编造", text)
            self.assertIn("保留团队协作边界", text)
            self.assertIn("未知", text)
        self.assertIn("不大段复制JD", greeting_prompt)
        self.assertIn("不发送消息、不提交申请", greeting_prompt)
        self.assertIn("对应岗位要求、引用的档案证据和证据缺口", greeting_prompt)

    def test_materials_prompt_has_principles_and_the_fixed_schema(self) -> None:
        prompt = greeter.MATERIALS_PROMPT
        self.assertIn("每条简历建议都列出对应岗位要求、引用的档案证据及证据缺口", prompt)
        self.assertIn("适配分、判断置信度、风险线索由程序另行提供", prompt)
        self.assertIn("不得包含电话、邮箱、微信、QQ、网址", prompt)
        self.assertIn("只作草稿，不发送消息、不提交申请", prompt)
        for key in ("mapping", "conditions", "unknown_fields", "resume_suggestions", "greetings", "confirm_items"):
            self.assertIn(f'"{key}"', prompt)


class MaterialsShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = {
            "id": "demo-job-1",
            "title": "产品助理",
            "company": "示例公司",
            "city": "示例城市",
            "salary": "10-15K",
            "education": "本科",
            "recruitment_type": "campus",
            "jd": "负责需求分析与原型设计。",
            "score_reason": "匹配分 70/100",
        }

    def test_valid_payload_has_exactly_the_contract_shape(self) -> None:
        with _materials_call():
            materials = greeter._generate_materials_once(self.job, RESUME, CONFIG)
        self.assertIsNotNone(materials)
        self.assertEqual(
            set(materials),
            {"mapping", "conditions", "unknown_fields", "resume_suggestions", "greetings", "confirm_items"},
        )
        self.assertEqual(set(materials["greetings"]), {"concise", "project", "safe"})
        self.assertEqual(
            set(materials["mapping"][0]), {"requirement", "evidence", "source"}
        )
        self.assertEqual(
            set(materials["resume_suggestions"][0]),
            {"original", "suggested", "evidence", "reason"},
        )
        self.assertEqual(materials["conditions"][1]["status"], "待确认")

    def test_three_greetings_stay_short_and_contact_free(self) -> None:
        with _materials_call():
            materials = greeter._generate_materials_once(self.job, RESUME, CONFIG)
        for key, text in materials["greetings"].items():
            with self.subTest(version=key):
                self.assertLessEqual(len(text), greeter.MATERIALS_GREETING_MAX_CHARS)
                self.assertFalse(greeter._contains_contact(text))

    def test_contact_in_any_greeting_rejects_the_whole_package(self) -> None:
        for contact in ("加微信 hr_demo", "hr@example.com", "电话 13800138000", "见 https://example.com"):
            with self.subTest(contact=contact):
                payload = json.loads(json.dumps(VALID_PAYLOAD))
                payload["greetings"]["safe"] = contact
                with _materials_call(payload):
                    self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG))

    def test_overlong_greeting_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["greetings"]["concise"] = "您好，" + "需求梳理" * 80
        with _materials_call(payload):
            self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG))

    def test_invented_number_in_a_suggestion_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["resume_suggestions"][0]["suggested"] = "把转化率提升了80%"
        with _materials_call(payload):
            self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG))

    def test_resume_suggestion_must_quote_the_facts(self) -> None:
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["resume_suggestions"][0]["original"] = "独立负责电商平台从0到1"
        with _materials_call(payload):
            self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG))

    def test_broken_json_is_rejected(self) -> None:
        with patch.object(greeter, "_call_claude", return_value="这不是 JSON"):
            self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG))

    def test_validation_diagnostics_name_fields_without_the_rejected_values(self):
        cases = (
            ("conditions", "status", "private invalid status", "conditions[0].status"),
            ("resume_suggestions", "original", "private fabricated original", "resume_suggestions[0].original"),
            ("resume_suggestions", "suggested", "提高了83%", "resume_suggestions[0].suggested"),
        )
        for section, key, value, expected_path in cases:
            with self.subTest(path=expected_path):
                payload = json.loads(json.dumps(VALID_PAYLOAD))
                payload[section][0][key] = value
                reasons = []
                self.assertIsNone(greeter._normalize_materials(payload, resume=RESUME, config=CONFIG, failure_reasons=reasons))
                self.assertIn(expected_path, reasons[0])
                self.assertNotIn(value, reasons[0])

    def test_array_limits_are_not_relaxed_during_repair(self):
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["mapping"] = payload["mapping"] * (greeter.MATERIALS_LIMITS["mapping"] + 1)
        reasons = []
        with _materials_call(payload) as call:
            self.assertIsNone(greeter._generate_materials_once(self.job, RESUME, CONFIG, failure_reasons=reasons))
        self.assertEqual(call.call_count, 2)
        self.assertIn("mapping", reasons[0])


class UnknownHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.job = {"id": "demo-job-2", "title": "产品助理", "company": "示例公司", "jd": "负责需求分析。"}

    def test_missing_information_stays_unknown_and_is_not_marked_satisfied(self) -> None:
        payload = {
            "mapping": [{"requirement": "有电商经验", "evidence": "未知", "source": "未知"}],
            "conditions": [
                {"condition": "有电商经验", "status": "待确认", "evidence": "未知"},
            ],
            "unknown_fields": ["行业经验"],
            "resume_suggestions": [],
            "greetings": {
                "concise": "您好，我想了解这个岗位。",
                "project": "您好，我有需求梳理经验，想了解岗位。",
                "safe": "您好，我想了解这个岗位，方便时请回复。",
            },
            "confirm_items": ["确认是否有电商行业经历"],
        }
        with _materials_call(payload):
            materials = greeter._generate_materials_once(self.job, RESUME, CONFIG)
        self.assertIsNotNone(materials)
        self.assertEqual(materials["mapping"][0]["evidence"], "未知")
        self.assertEqual(materials["conditions"][0]["status"], "待确认")
        self.assertEqual(materials["unknown_fields"], ["行业经验"])

    def test_satisfied_condition_without_evidence_is_rejected(self) -> None:
        payload = json.loads(json.dumps(VALID_PAYLOAD))
        payload["conditions"][0]["evidence"] = "未知"
        with _materials_call(payload):
            self.assertIsNone(greeter._generate_materials_once(
                {"id": "demo-job-3", "title": "产品助理", "company": "示例公司"}, RESUME, CONFIG
            ))


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        resume_path = self.root / "resume.md"
        resume_path.write_text(RESUME, encoding="utf-8")
        self.db_path = self.root / "offerpilot.db"
        self.config = {
            "profile": {
                "ai_greeting_enabled": True,
                "resume_path": str(resume_path),
                "greeting_preference": "",
            },
            "ai": {},
        }
        self.db = get_db(self.db_path)
        self.addCleanup(self.db.close)

    def _insert(self, job_id: str, greeting: str, status: str = "approved") -> None:
        self.db.execute(
            "INSERT INTO jobs (id, title, company, status, greeting, greeting_selection, score, jd)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, "产品助理", "示例公司", status, greeting, "generated", 70, "负责需求分析与原型设计。"),
        )
        self.db.commit()

    def _read(self, job_id: str) -> dict:
        row = self.db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row)

    def test_materials_failure_keeps_the_existing_greeting_and_writes_nothing(self) -> None:
        job_id = "demo-fail-1"
        self._insert(job_id, "原有草稿：您好，我想了解这个岗位。")
        with patch.object(greeter, "_generate_materials_once", return_value=None):
            generated = greeter.generate_greetings(self.config, [job_id], db_path=self.db_path)
        self.assertEqual(generated, 0)
        row = self._read(job_id)
        self.assertEqual(row["greeting"], "原有草稿：您好，我想了解这个岗位。")
        self.assertIsNone(row["materials"])
        report = self.config["_workbench_greeting_report"]
        self.assertEqual(report["materials_failed"], 1)
        self.assertEqual(report["failed_count"], 1)
        actions = [item["action"] for item in self.db.execute(
            "SELECT action FROM history WHERE job_id = ?", (job_id,)
        ).fetchall()]
        self.assertIn("materials_failed", actions)

    def test_new_greeting_is_not_saved_when_materials_fail(self) -> None:
        job_id = "demo-fail-2"
        self._insert(job_id, "")
        with patch.object(greeter, "_generate_with_token_retry", return_value="新草稿：您好，我想了解岗位。"), \
                patch.object(greeter, "_generate_materials_once", return_value=None):
            generated = greeter.generate_greetings(self.config, [job_id], db_path=self.db_path)
        self.assertEqual(generated, 0)
        row = self._read(job_id)
        self.assertFalse(str(row["greeting"] or "").strip())
        self.assertIsNone(row["materials"])

    def test_final_validation_reason_reaches_report_and_history_without_raw_response(self):
        job_id = "demo-private-fail"
        self._insert(job_id, "")
        private_response = "private malformed model response"
        with patch.object(greeter, "_generate_with_token_retry", return_value="您好，我想了解岗位。"), \
                patch.object(greeter, "_call_claude", return_value=private_response):
            self.assertEqual(greeter.generate_greetings(self.config, [job_id], db_path=self.db_path), 0)
        report = self.config["_workbench_greeting_report"]
        self.assertEqual(report["failed_count"], 1)
        self.assertIn("JSON", report["failure_reasons"][0])
        history = self.db.execute("SELECT detail FROM history WHERE job_id = ? AND action = 'materials_failed'", (job_id,)).fetchone()
        self.assertIn("JSON", history[0])
        self.assertNotIn(private_response, history[0])
        self.assertNotIn(private_response, json.dumps(report))
        self.assertFalse(str(self._read(job_id)["greeting"] or "").strip())

    def test_repaired_materials_are_not_counted_as_failed(self):
        job_id = "demo-repaired"
        self._insert(job_id, "原有草稿：您好。")
        with patch.object(greeter, "_call_claude", side_effect=["bad JSON", json.dumps(VALID_PAYLOAD)]):
            self.assertEqual(greeter.generate_greetings(self.config, [job_id], db_path=self.db_path), 0)
        report = self.config["_workbench_greeting_report"]
        self.assertEqual(report["failed_count"], 0)
        self.assertEqual(report["materials_generated"], 1)
        self.assertEqual(report["failure_reasons"], [])
        self.assertEqual(json.loads(self._read(job_id)["materials"]), VALID_PAYLOAD)

    def test_safe_version_becomes_the_default_and_other_versions_are_kept(self) -> None:
        job_id = "demo-ok-2"
        self._insert(job_id, "")
        with patch.object(greeter, "_generate_with_token_retry", return_value="模型草稿：您好。"), \
                patch.object(greeter, "_generate_materials_once", return_value=VALID_PAYLOAD):
            generated = greeter.generate_greetings(self.config, [job_id], db_path=self.db_path)
        self.assertEqual(generated, 1)
        row = self._read(job_id)
        self.assertEqual(row["greeting"], VALID_PAYLOAD["greetings"]["safe"])
        self.assertEqual(row["greeting_original"], VALID_PAYLOAD["greetings"]["concise"])
        self.assertEqual(row["greeting_optimized"], VALID_PAYLOAD["greetings"]["project"])
        self.assertEqual(row["greeting_selection"], "generated")
        self.assertEqual(json.loads(row["materials"]), VALID_PAYLOAD)

    def test_successful_materials_are_saved_next_to_the_greeting(self) -> None:
        job_id = "demo-ok-1"
        self._insert(job_id, "原有草稿：您好，我想了解这个岗位。")
        with patch.object(greeter, "_generate_materials_once", return_value=VALID_PAYLOAD):
            generated = greeter.generate_greetings(self.config, [job_id], db_path=self.db_path)
        self.assertEqual(generated, 0)  # existing greetings are preserved, not regenerated
        row = self._read(job_id)
        self.assertEqual(row["greeting"], "原有草稿：您好，我想了解这个岗位。")
        self.assertEqual(json.loads(row["materials"]), VALID_PAYLOAD)
        self.assertEqual(self.config["_workbench_greeting_report"]["materials_generated"], 1)


if __name__ == "__main__":
    unittest.main()
