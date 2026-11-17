#!/usr/bin/env python3
"""Tests for the application dossier and must-have traceability.

Every test works on in-memory fixtures. Nothing reads ``web/data``, sends a
message, opens a browser or calls the network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "tools"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import job_dossier  # noqa: E402


def _profile() -> dict:
    return {
        "projects": [
            {
                "name": "移动应用程序开发",
                "role": "产品经理",
                "summary": "完成需求分析与原型设计，使用 Axure 输出 PRD，推动小程序上线。",
            },
            {
                "name": "VR app原型设计",
                "role": "项目组长",
                "summary": "使用 Axure 完成原型设计，并进行可用性测试。",
            },
        ],
        "experiences": [
            {
                "company": "虚构数据公司",
                "title": "产品专员",
                "summary": "负责订单与结算流程的需求梳理，支撑电商业务上线。",
            }
        ],
    }


def _job(**extra: object) -> dict:
    row = {
        "id": "j-dossier-1",
        "company": "虚构星河科技有限公司",
        "title": "产品经理",
        "city": "上海",
        "score": 49,
        "score_coverage": 0.95,
        "score_reason": "匹配分 49/100",
        "mandatory_status": "unsatisfied",
        "hiring_status": "unknown",
        "source_channel": "boss",
        "raw_text": "任职要求：\n- 熟练使用 Axure 输出原型；\n- 有电商订单与结算经验；\n- 熟悉 Kubernetes 集群运维。",
        "mandatory_conditions": [
            {"condition": "熟练使用 Axure 输出原型", "status": "已满足", "evidence": "简历使用 Axure"},
            {"condition": "有电商订单与结算经验", "status": "明确不满足", "evidence": "无完整项目"},
            {"condition": "熟悉 Kubernetes 集群运维", "status": "待确认", "evidence": ""},
        ],
    }
    row.update(extra)
    return row


class ContactGuardTests(unittest.TestCase):
    def test_detects_phone_email_wechat_and_links(self) -> None:
        for sample in (
            "请加微信 demo_wechat 联系",
            "联系邮箱 demo@example.com",
            "电话 13800000000",
            "见 https://example.com/profile",
            "QQ：12345678",
            "vx: abc",
        ):
            with self.subTest(sample=sample):
                self.assertTrue(job_dossier.contains_contact(sample))

    def test_plain_professional_text_passes(self) -> None:
        self.assertFalse(job_dossier.contains_contact("您好，我想了解这个岗位。方便进一步沟通吗？"))


class AnalysisCardTests(unittest.TestCase):
    def test_groups_conditions_and_keeps_signals_separate(self) -> None:
        card = job_dossier.analysis_card(_job())
        self.assertEqual(card["fit_score"], 49)
        self.assertEqual(card["fit_confidence"], 0.67)
        self.assertEqual(card["risk_level"], "medium")
        self.assertEqual(card["satisfied"], ["熟练使用 Axure 输出原型"])
        self.assertEqual(card["gaps"], ["有电商订单与结算经验"])
        self.assertEqual(card["pending"], ["熟悉 Kubernetes 集群运维"])

    def test_none_when_row_has_no_analysis(self) -> None:
        self.assertIsNone(job_dossier.analysis_card({"id": "bare", "source_channel": "manual_paste"}))


class ResumeVariantTests(unittest.TestCase):
    def test_uses_explicit_id_then_matching_saved_variant(self) -> None:
        variants = [{"id": "variant-abc123", "project": "产品经理"}]
        self.assertEqual(
            job_dossier.resume_variant_id({"resume_variant": "variant-explicit"}, variants),
            "variant-explicit",
        )
        self.assertEqual(job_dossier.resume_variant_id(_job(), variants), "variant-abc123")

    def test_never_invents_a_variant_id(self) -> None:
        self.assertIsNone(job_dossier.resume_variant_id(_job(), []))
        self.assertIsNone(job_dossier.resume_variant_id(_job(), [{"id": "v1", "project": "会计"}]))

    def test_substring_overlap_is_not_a_match(self) -> None:
        variants = [{"id": "variant-wrong", "project": "资深产品经理"}]
        self.assertIsNone(job_dossier.resume_variant_id(_job(), variants))


class GreetingDraftTests(unittest.TestCase):
    def test_stored_draft_is_reused_when_contact_free(self) -> None:
        job = _job(greeting="您好，我想了解这个岗位。")
        self.assertEqual(job_dossier.greeting_draft(job), "您好，我想了解这个岗位。")

    def test_stored_draft_with_contact_is_rejected(self) -> None:
        job = _job(greeting="您好，微信 demo_wechat 联系我")
        self.assertIsNone(job_dossier.greeting_draft(job))

    def test_generates_through_existing_greeter_when_cv_available(self) -> None:
        with patch.object(
            job_dossier.greeting_module,
            "make_greeting",
            return_value={"greeting": "您好，我想了解这个岗位。方便进一步沟通吗？"},
        ) as make:
            text = job_dossier.greeting_draft(_job(), "需求分析 Axure")
        make.assert_called_once()
        self.assertEqual(text, "您好，我想了解这个岗位。方便进一步沟通吗？")

    def test_no_cv_and_no_stored_draft_is_null(self) -> None:
        self.assertIsNone(job_dossier.greeting_draft(_job(), None))

    def test_generated_draft_with_contact_is_dropped(self) -> None:
        with patch.object(
            job_dossier.greeting_module,
            "make_greeting",
            return_value={"greeting": "加我微信 demo_wechat"},
        ):
            self.assertIsNone(job_dossier.greeting_draft(_job(), "需求分析"))

    def test_real_greeter_output_is_contact_free(self) -> None:
        draft = job_dossier.greeting_draft(_job(), "需求分析 Axure 用户调研")
        self.assertIsNotNone(draft)
        self.assertFalse(job_dossier.contains_contact(draft))


class BuildDossierTests(unittest.TestCase):
    def test_contract_keys_and_gap_routes_to_hold(self) -> None:
        dossier = job_dossier.build_dossier(_job(), profile=_profile(), variants=[], cv_text="需求分析")
        self.assertEqual(
            set(dossier),
            {"analysis_card", "resume_variant", "greeting", "checklist", "recommended_action"},
        )
        self.assertIsNone(dossier["resume_variant"])
        self.assertEqual(dossier["recommended_action"], "hold")
        self.assertIsInstance(dossier["checklist"], list)
        self.assertTrue(all(isinstance(item, str) for item in dossier["checklist"]))
        self.assertTrue(any("明确不满足" in item for item in dossier["checklist"]))

    def test_closed_posting_is_skipped(self) -> None:
        dossier = job_dossier.build_dossier(_job(hiring_status="closed"), profile=_profile())
        self.assertEqual(dossier["recommended_action"], "skip")

    def test_unscored_job_asks_for_more_collection(self) -> None:
        dossier = job_dossier.build_dossier({"id": "bare", "title": "产品经理", "source_channel": "boss"})
        self.assertEqual(dossier["recommended_action"], "collect_more")
        self.assertIsNone(dossier["analysis_card"])
        self.assertIsNone(dossier["greeting"])

    def test_clean_scored_job_with_draft_is_ready_for_review(self) -> None:
        job = _job(
            mandatory_status="satisfied",
            mandatory_conditions=[
                {"condition": "熟练使用 Axure 输出原型", "status": "已满足", "evidence": "简历使用 Axure"}
            ],
            hiring_status="not_closed",
            greeting="您好，我想了解这个岗位。",
        )
        dossier = job_dossier.build_dossier(job, profile=_profile())
        self.assertEqual(dossier["recommended_action"], "review_and_send")
        self.assertEqual(dossier["greeting"], "您好，我想了解这个岗位。")


class TraceabilityTests(unittest.TestCase):
    def test_each_must_have_maps_to_profile_evidence_or_null(self) -> None:
        rows = job_dossier.build_traceability(_job(), profile=_profile())
        self.assertEqual([row["requirement"] for row in rows], [
            "熟练使用 Axure 输出原型",
            "有电商订单与结算经验",
            "熟悉 Kubernetes 集群运维",
        ])
        axure = rows[0]
        self.assertEqual(axure["source"], "profile.projects[0]")
        self.assertIn("移动应用程序开发", axure["project_evidence"])
        ecommerce = rows[1]
        self.assertEqual(ecommerce["source"], "profile.experiences[0]")
        self.assertIn("订单与结算", ecommerce["project_evidence"])
        kubernetes = rows[2]
        self.assertEqual(kubernetes, {
            "requirement": "熟悉 Kubernetes 集群运维",
            "project_evidence": None,
            "source": None,
        })

    def test_generic_words_alone_do_not_create_evidence(self) -> None:
        job = _job(raw_text="任职要求：\n- 有良好的沟通能力；", mandatory_conditions=[])
        rows = job_dossier.build_traceability(job, profile=_profile())
        self.assertEqual(rows, [{"requirement": "有良好的沟通能力；", "project_evidence": None, "source": None}])

    def test_latin_terms_need_word_boundaries(self) -> None:
        # "AI" must not match inside "email"; "UI" must not match inside "build".
        self.assertFalse(job_dossier._term_in("ai", "email reply"))
        self.assertTrue(job_dossier._term_in("ai", "ai 产品"))
        self.assertFalse(job_dossier._term_in("ui", "build tools"))

    def test_no_requirements_returns_empty_list(self) -> None:
        job = {"id": "bare", "title": "产品经理", "source_channel": "boss"}
        self.assertEqual(job_dossier.build_traceability(job, profile=_profile()), [])

    def test_no_profile_gives_null_evidence(self) -> None:
        rows = job_dossier.build_traceability(_job(), profile=None)
        self.assertTrue(all(row["project_evidence"] is None and row["source"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
