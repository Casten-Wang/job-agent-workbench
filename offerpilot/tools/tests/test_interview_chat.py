#!/usr/bin/env python3
"""Offline tests for API-001 interview-start and API-004 material upload.

Fake planners only. These tests never call a paid AI endpoint and never treat
a missing key as a successful start.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"

for _path in (str(WEB_DIR), str(TOOLS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import interview_chat  # noqa: E402

HIDDEN_KEYS = ("blueprint", "competencies", "main_questions", "stem_intent")
RESUME_SPAN = "参与需求分析"
FAKE_SPAN_MISSING = "这段经历完全不在简历里XYZ"


def _plan(*, kinds: list[str] | None = None, extra_span: str | None = FAKE_SPAN_MISSING) -> dict:
    kinds = kinds or ["resume_probe"] * 6
    questions = [
        {"id": f"q{index}", "kind": kind, "stem_intent": f"内部意图{index}"}
        for index, kind in enumerate(kinds, start=1)
    ]
    evidence = [{"competency_id": "c1", "resume_span": RESUME_SPAN}]
    if extra_span:
        evidence.append({"competency_id": "c1", "resume_span": extra_span})
    return {
        "competencies": [
            {"id": "c1", "label": "需求理解", "weight": 0.25},
            {"id": "c2", "label": "项目推进", "weight": 0.25},
            {"id": "c3", "label": "沟通协作", "weight": 0.25},
            {"id": "c4", "label": "复盘意识", "weight": 0.25},
        ],
        "evidence_map": evidence,
        "main_questions": questions,
    }


def _fake_complete(plan: dict):
    def complete(system_prompt: str, user_text: str, timeout: float = 45) -> str:
        complete.calls.append({"system": system_prompt, "user": user_text, "timeout": timeout})
        return json.dumps(plan, ensure_ascii=False)

    complete.calls = []
    return complete


class InterviewChatUnitTests(unittest.TestCase):
    def test_prompt_file_matches_planning_contract(self):
        prompt = interview_chat.load_plan_system_prompt()
        self.assertIn("只输出一个 JSON 对象", prompt)
        self.assertIn("resume_probe", prompt)
        self.assertIn("business_scenario", prompt)
        self.assertNotIn("target_answers", prompt)
        self.assertNotIn("10 问", prompt)
        self.assertNotIn("interview-points", prompt)

    def test_rules_text_is_capped_and_includes_required_phrases(self):
        text = interview_chat.build_rules_text("business", 30, True)
        self.assertLessEqual(len(text), 120)
        self.assertIn("本轮是通用岗位模拟", text)
        self.assertIn("业务专业", text)
        self.assertIn("30", text)
        self.assertIn("一次一问", text)
        self.assertIn("不点评", text)
        self.assertIn("复盘", text)

    def test_plan_discards_unmatched_resume_span(self):
        resume = interview_chat.resume_evidence_text({
            "experiences": [{"company": "虚构科技", "title": "实习生", "summary": "参与需求分析与原型"}],
            "projects": [],
        })
        plan = interview_chat.plan_interview(
            round_key="hr",
            duration_minutes=20,
            resume_text=resume,
            complete=_fake_complete(_plan(kinds=["resume_probe"] * 4)),
        )
        spans = [row["resume_span"] for row in plan["evidence_map"]]
        self.assertIn(RESUME_SPAN, spans)
        self.assertNotIn(FAKE_SPAN_MISSING, spans)

    def test_plan_without_materials_rejects_scenario_questions(self):
        with self.assertRaises(interview_chat.PlanGenerationError):
            interview_chat.plan_interview(
                round_key="tech",
                duration_minutes=20,
                resume_text="实习：参与需求分析",
                complete=_fake_complete(_plan(kinds=["resume_probe", "business_scenario"] * 2)),
            )


class InterviewApiTests(unittest.TestCase):
    def setUp(self) -> None:
        backend.reset_demo()

    def tearDown(self) -> None:
        backend.reset_demo()

    def _start(self, payload: dict, complete, configured: bool = True):
        with patch.object(backend, "interview_ai_configured", return_value=configured), patch.object(
            backend, "_complete_interview_plan", complete
        ):
            return backend.interview_start({"mode": "demo", **payload})

    def test_missing_internship_or_project_is_400(self):
        profile = backend.get_store("demo").profile()
        profile["experiences"] = []
        profile["projects"] = []
        backend.get_store("demo").set_profile(profile)
        complete = _fake_complete(_plan())
        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "business"}, complete)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_NO_RESUME)
        self.assertIsNone(backend.get_store("demo").interview_session())
        self.assertEqual(complete.calls, [])

    def test_unconfigured_ai_is_400_and_does_not_call_planner(self):
        complete = _fake_complete(_plan())
        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "hr"}, complete, configured=False)
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("尚未配置外部 AI，无法开始文字面试", ctx.exception.message)
        self.assertEqual(complete.calls, [])
        self.assertIsNone(backend.get_store("demo").interview_session())

    def test_invalid_round_or_duration_is_400(self):
        complete = _fake_complete(_plan())
        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "boss", "duration_minutes": 30}, complete)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_ROUND_DURATION)
        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "hr", "duration_minutes": 15}, complete)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_ROUND_DURATION)
        self.assertEqual(complete.calls, [])

    def test_empty_main_questions_is_400_or_503(self):
        complete = _fake_complete({"main_questions": []})
        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "manager"}, complete)
        self.assertIn(ctx.exception.status, (400, 503))
        self.assertEqual(ctx.exception.message, interview_chat.MSG_PLAN_FAILED)
        self.assertIsNone(backend.get_store("demo").interview_session())

    def test_planner_timeout_is_503(self):
        def boom(system_prompt: str, user_text: str, timeout: float = 45) -> str:
            raise TimeoutError("fake timeout")

        with self.assertRaises(backend.ApiError) as ctx:
            self._start({"round": "tech"}, boom)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_PLAN_FAILED)

    def test_start_success_hides_blueprint_and_defaults_to_30(self):
        complete = _fake_complete(_plan())
        result = self._start({"round": "business"}, complete)
        self.assertTrue(result["ok"])
        self.assertEqual(result["round"], "business")
        self.assertEqual(result["duration_minutes"], 30)
        self.assertEqual(result["user_status"], "preparing")
        self.assertEqual(result["remaining_seconds"], 1800)
        self.assertTrue(result["generic_role"])
        self.assertIn("本轮是通用岗位模拟", result["rules_text"])
        self.assertLessEqual(len(result["rules_text"]), 120)
        self.assertIn("业务专业", result["rules_text"])
        self.assertIn("一次一问", result["rules_text"])
        self.assertIn("不点评", result["rules_text"])
        self.assertIn("复盘", result["rules_text"])
        encoded = json.dumps(result, ensure_ascii=False)
        for key in HIDDEN_KEYS:
            self.assertNotIn(f'"{key}"', encoded)
        self.assertNotIn("target_answers", encoded)
        self.assertNotIn("10 问", encoded)
        self.assertEqual(complete.calls[0]["timeout"], 45)
        session = backend.get_store("demo").interview_session()
        self.assertIsNotNone(session)
        self.assertIn("blueprint", session)
        kinds = {item["kind"] for item in session["blueprint"]["main_questions"]}
        self.assertEqual(kinds, {"resume_probe"})
        spans = [row["resume_span"] for row in session["blueprint"]["evidence_map"]]
        self.assertNotIn(FAKE_SPAN_MISSING, spans)

    def test_selected_job_is_not_generic_role(self):
        job = backend.get_store("demo").jobs()[0]
        complete = _fake_complete(_plan(kinds=["resume_probe"] * 3 + ["business_scenario"] * 3))
        result = self._start({"round": "hr", "duration_minutes": 20, "job_id": job["id"]}, complete)
        self.assertFalse(result["generic_role"])
        self.assertNotIn("本轮是通用岗位模拟", result["rules_text"])
        self.assertEqual(result["display"].get("company"), job.get("company"))
        self.assertEqual(result["display"].get("title"), job.get("title"))
        self.assertEqual(result["remaining_seconds"], 1200)

    def test_materials_require_both_question_kinds(self):
        jingyan = backend.interview_material_upload({
            "mode": "demo",
            "kind": "jingyan",
            "body": "测试面经：候选人被问过一次需求评审里如何取舍范围。",
        })
        knowledge = backend.interview_material_upload({
            "mode": "demo",
            "kind": "knowledge",
            "body": "测试岗位知识：该岗位要推动一次活动报名漏斗改版。",
        })
        complete = _fake_complete(_plan(kinds=["resume_probe"] * 3 + ["business_scenario"] * 3))
        result = self._start(
            {
                "round": "business",
                "material_ids": [jingyan["id"], knowledge["id"]],
            },
            complete,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["jingyan_is_not_official"])
        session = backend.get_store("demo").interview_session()
        kinds = {item["kind"] for item in session["blueprint"]["main_questions"]}
        self.assertEqual(kinds, {"resume_probe", "business_scenario"})
        user_payload = json.loads(complete.calls[0]["user"])
        self.assertTrue(user_payload["materials"][0]["jingyan_is_not_official"])
        self.assertNotIn("00000000000", complete.calls[0]["user"])

    def test_discard_unfinished_session(self):
        complete = _fake_complete(_plan())
        first = self._start({"round": "hr"}, complete)
        self.assertFalse(first["discarded_in_progress"])
        second = self._start({"round": "tech", "duration_minutes": 20}, complete)
        self.assertTrue(second["discarded_in_progress"])
        self.assertEqual(second["user_status"], "preparing")
        session = backend.get_store("demo").interview_session()
        self.assertEqual(session["round"], "tech")
        self.assertNotEqual(session["id"], first["id"])

    def test_material_upload_persists_and_rejects_empty_body(self):
        with self.assertRaises(backend.ApiError) as ctx:
            backend.interview_material_upload({"mode": "demo", "kind": "jingyan", "body": "  "})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_MATERIAL_EMPTY)
        created = backend.interview_material_upload({
            "mode": "demo",
            "kind": "knowledge",
            "body": "测试岗位知识：本机应在刷新后仍能按 id 选中。",
        })
        rows = backend.get_store("demo").interview_materials()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], created["id"])
        complete = _fake_complete(_plan(kinds=["resume_probe"] * 3 + ["business_scenario"] * 3))
        result = self._start({"round": "manager", "material_ids": [created["id"]]}, complete)
        self.assertTrue(result["ok"])
        selected = json.loads(complete.calls[0]["user"])["materials"]
        self.assertEqual(len(selected), 1)
        self.assertIn("本机应在刷新后仍能按 id 选中", selected[0]["body"])

    def test_real_complete_is_not_used_when_key_missing(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("must not call the real paid planner")

        with patch.object(backend, "interview_ai_configured", return_value=False), patch.object(
            backend, "_complete_interview_plan", forbidden
        ):
            with self.assertRaises(backend.ApiError) as ctx:
                backend.interview_start({"mode": "demo", "round": "hr"})
        self.assertIn("尚未配置外部 AI，无法开始文字面试", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
