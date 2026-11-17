import copy
import json
import unittest

from interview_hub.recap import build_recap, validate_result


SHA = "a" * 40


def material():
    evidence = [{"evidence_id": f"e{i}", "commit_sha": SHA, "path": f"src/module{i}.py",
                 "line_start": 10, "line_end": 12, "source_url": f"https://github.com/example/demo/blob/{SHA}/src/module{i}.py#L10-L12",
                 "text": "def operation(value):\n    return value\n", "source_kind": "source_text", "extraction_kind": "extracted"}
                for i in range(1, 4)]
    return {"material_id": "m1", "resume_version_id": "resume-v1", "project_snapshot_id": "snapshot-v1",
            "source_commit": SHA, "is_demo": False,
            "claims": [{"claim_id": "c1", "text": "负责一个已确认的具体模块", "personal_contribution": "confirmed", "evidence_ids": ["e1", "e2"]},
                       {"claim_id": "c2", "text": "项目中另有待确认职责", "personal_contribution": "unconfirmed", "evidence_ids": ["e3"]}],
            "evidence": evidence,
            "questions": [{"question_id": "q1", "claim_id": "c1", "text": "说明正常流程和失败边界", "evidence_ids": ["e1"],
                           "ua_learning_support": [{"path": "src/module1.py", "lineRange": [10, 12], "tourOrder": 2,
                                                    "title": "关键实现", "explanation": "从输入到输出定位实际分支。", "evidence_id": "e1"}]},
                          {"question_id": "q2", "claim_id": "c1", "text": "说明另一处调用", "evidence_ids": ["e2"]},
                          {"question_id": "q3", "claim_id": "c2", "text": "说明本人职责", "evidence_ids": ["e3"]}]}


def result(status="partial", assistance="independent"):
    return {"answers": [{"question_id": "q1", "text": "能解释输入，还需要核对失败分支。", "assistance_mode": assistance}],
            "observations": [{"question_id": "q1", "status": status, "gap_type": "understanding",
                              "notes": "上游面试服务记录为待复核反馈。", "evidence_ids": ["e1"]}]}


SESSION = {"session_id": "s1", "material_id": "m1", "mode": "mock_interview",
           "target": {"company": "示例公司", "role": "后端初级岗位", "round": "一面"}}


class RecapTests(unittest.TestCase):
    def test_partial_feedback_becomes_a_sourced_reviewable_task(self):
        recap = build_recap(material(), SESSION, result())
        task = recap["improvement_tasks"][0]
        self.assertEqual(task["materials"][0]["evidence_id"], "e1")
        self.assertEqual(task["materials"][0]["tour_order"], 2)
        self.assertTrue(task["action"] and task["completion_criterion"] and task["retest"]["prompt"])
        self.assertEqual(task["status"], "pending_confirmation")
        self.assertFalse(task["retest"]["mastery_verified"])
        self.assertEqual(recap["resume_suggestions"][0]["action"], "preserve_fact_and_prepare")
        self.assertTrue(recap["resume_suggestions"][0]["preserve_confirmed_facts"])
        self.assertFalse(recap["applied_to_resume"])
        self.assertIsNone(recap["ability_verdict"])
        self.assertEqual(recap["review_status"], "pending_user_confirmation")

    def test_missing_answers_are_not_an_ability_gap(self):
        data = {"answers": [], "observations": []}
        recap = build_recap(material(), SESSION, data)
        self.assertEqual(len(recap["not_assessed"]), 3)
        self.assertFalse(recap["needs_review"])
        self.assertFalse(recap["improvement_tasks"])
        self.assertFalse(recap["resume_suggestions"])
        self.assertTrue(all(item["reason"] == "no_answer" for item in recap["not_assessed"]))

    def test_skipped_answer_and_missing_observation_stay_unassessed(self):
        data = {"answers": [{"question_id": "q1", "skipped": True, "assistance_mode": "independent"},
                            {"question_id": "q2", "text": "有回答但无观察", "assistance_mode": "independent"}],
                "observations": [{"question_id": "q1", "status": "insufficient_evidence", "notes": "材料不足", "evidence_ids": []}]}
        recap = build_recap(material(), SESSION, data)
        self.assertEqual({item["question_id"]: item["reason"] for item in recap["not_assessed"]},
                         {"q1": "skipped", "q2": "no_observation", "q3": "no_answer"})
        self.assertFalse(recap["improvement_tasks"])

    def test_absent_or_blank_answers_cannot_be_judged(self):
        for status in ("consistent", "partial", "conflict"):
            for answer in (None, {"question_id": "q1", "text": "  ", "assistance_mode": "independent"},
                           {"question_id": "q1", "text": "草稿", "skipped": True, "assistance_mode": "hinted"}):
                data = result(status)
                data["answers"] = [] if answer is None else [answer]
                with self.subTest(status=status, answer=answer), self.assertRaises(ValueError):
                    validate_result(material(), data)

    def test_assisted_consistency_does_not_certify_independent_readiness(self):
        for assistance in ("independent", "open_book", "hinted", "ai_assisted"):
            recap = build_recap(material(), SESSION, result("consistent", assistance))
            observation = recap["what_went_well"][0]
            self.assertFalse(observation["independent_readiness_verified"])
            self.assertEqual(observation["assistance_mode"], assistance)
            self.assertEqual(observation["retest_recommended"], assistance != "independent")
            self.assertIsNone(recap["ability_verdict"])
            self.assertFalse(recap["mastery_verified"])

    def test_result_version_metadata_must_match(self):
        for field, value in (("source_commit", "b" * 40), ("material_id", "m2"), ("resume_version_id", "resume-v2")):
            data = result()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_result(material(), data)
        data = result()
        data.update({"source_commit": SHA, "material_id": "m1", "resume_version_id": "resume-v1"})
        self.assertIsNone(validate_result(material(), data))

    def test_source_evidence_at_another_commit_is_rejected(self):
        value = material()
        value["evidence"][0]["commit_sha"] = "b" * 40
        with self.assertRaises(ValueError):
            validate_result(value, result())

    def test_session_snapshot_and_result_session_must_match(self):
        for field in ("source_commit", "project_snapshot_id", "resume_version_id"):
            session = {**SESSION, field: "another-version"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_recap(material(), session, result())
        data = result()
        data["session_id"] = "another-session"
        with self.assertRaises(ValueError):
            build_recap(material(), SESSION, data)

    def test_observation_evidence_cannot_cross_question_or_claim(self):
        for ref in ("e2", "e3", "unknown"):
            data = result("conflict")
            data["observations"][0]["evidence_ids"] = [ref]
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                validate_result(material(), data)
        value = material()
        value["questions"][0]["evidence_ids"] = ["e3"]
        with self.assertRaises(ValueError):
            validate_result(value, result())

    def test_conflict_requires_original_source_not_an_inference(self):
        data = result("conflict")
        data["observations"][0]["evidence_ids"] = []
        with self.assertRaises(ValueError):
            validate_result(material(), data)
        for field, value in (("source_kind", "model_summary"), ("extraction_kind", "inferred")):
            mat = material()
            mat["evidence"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_result(mat, result("conflict"))

    def test_conflict_checks_version_before_diagnosing_understanding(self):
        recap = build_recap(material(), SESSION, result("conflict"))
        self.assertIn("先确认回答所指的代码版本", recap["improvement_tasks"][0]["action"])
        self.assertEqual(recap["resume_suggestions"][0]["action"], "review_source_and_version")

    def test_insufficient_material_does_not_become_understanding_training(self):
        recap = build_recap(material(), SESSION, result("insufficient_evidence"))
        task = recap["improvement_tasks"][0]
        self.assertIn("目前不推导为理解不足", task["action"])
        self.assertEqual(recap["resume_suggestions"][0]["action"], "collect_evidence")

    def test_unknown_and_duplicate_questions_are_rejected(self):
        data = result()
        data["answers"][0]["question_id"] = "unknown"
        with self.assertRaises(ValueError):
            validate_result(material(), data)
        for collection in ("answers", "observations"):
            data = result()
            data[collection].append(copy.deepcopy(data[collection][0]))
            with self.subTest(collection=collection), self.assertRaises(ValueError):
                validate_result(material(), data)

    def test_learning_support_cannot_invent_source_coordinates(self):
        for field, value in (("lineRange", [10, 999]), ("lineRange", [True, 12]),
                             ("path", "src/different.py"), ("evidence_id", "e2"), ("tourOrder", True)):
            mat = material()
            mat["questions"][0]["ua_learning_support"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_result(mat, result())

    def test_source_only_task_uses_actual_refs_and_absent_source_stays_missing(self):
        mat = material()
        del mat["questions"][0]["ua_learning_support"]
        recap = build_recap(mat, SESSION, result())
        self.assertEqual(recap["improvement_tasks"][0]["materials"][0]["evidence_id"], "e1")
        mat["questions"][0]["evidence_ids"] = []
        data = result("insufficient_evidence")
        data["observations"][0]["evidence_ids"] = []
        recap = build_recap(mat, SESSION, data)
        self.assertEqual(recap["improvement_tasks"][0]["materials_status"], "missing")
        self.assertFalse(recap["improvement_tasks"][0]["materials"])

    def test_responsibility_suggestions_do_not_delete_or_invent_wording(self):
        data = {"answers": [{"question_id": "q3", "text": "团队职责还需核对", "assistance_mode": "independent"}],
                "observations": [{"question_id": "q3", "status": "partial", "gap_type": "responsibility",
                                  "notes": "需要本人确认实际承担部分", "evidence_ids": ["e3"]}]}
        recap = build_recap(material(), SESSION, data)
        suggestion = recap["resume_suggestions"][0]
        self.assertEqual(suggestion["action"], "clarify_scope_pending_confirmation")
        self.assertEqual(suggestion["personal_contribution"], "unconfirmed")
        self.assertIsNone(suggestion["proposed_text"])
        self.assertFalse(suggestion["applied"])
        self.assertNotIn("delete", json.dumps(recap))

    def test_recap_is_deterministic_and_does_not_mutate_inputs(self):
        mat, data = material(), result()
        before = copy.deepcopy((mat, data, SESSION))
        first = build_recap(mat, SESSION, data, [{"session_id": "s0"}, {"session_id": "s0"}, {"session_id": "s1"}])
        second = build_recap(mat, SESSION, data, [{"session_id": "s0"}])
        self.assertEqual(first, second)
        self.assertEqual((mat, data, SESSION), before)
        self.assertEqual(first["related_history_session_ids"], ["s0"])

    def test_malformed_feedback_uses_safe_value_errors(self):
        for collection, field, value in (("answers", "assistance_mode", []), ("observations", "status", {}),
                                         ("observations", "gap_type", []), ("observations", "notes", "")):
            data = result()
            data[collection][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError) as caught:
                validate_result(material(), data)
            self.assertNotIn("能解释输入", str(caught.exception))
        mat = material()
        mat["questions"][0]["claim_id"] = []
        with self.assertRaises(ValueError):
            validate_result(mat, result())


if __name__ == "__main__":
    unittest.main()
