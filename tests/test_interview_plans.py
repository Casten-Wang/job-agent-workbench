import copy
import unittest

import test_interview_api as fixture
from interview_hub.store import ConflictError, NotFoundError


def plan():
    return {"material_id": "mat_demo", "source_commit": fixture.COMMIT, "resume_version_id": None,
            "project_snapshot_id": "snapshot_1", "generation": {"provider": "test", "model": "test", "kind": "contract_test"},
            "questions": [{"question_id": "pi_q1", "claim_id": "claim_1", "text": "签名方法实际保留了哪些输入？",
                           "evidence_ids": ["ev_1"], "intent": "implementation", "reason": "核验本条项目事实的实现边界"}]}


class InterviewPlanTests(unittest.TestCase):
    setUp = fixture.InterviewAPITests.setUp
    tearDown = fixture.InterviewAPITests.tearDown
    request = fixture.InterviewAPITests.request
    session = fixture.InterviewAPITests.session

    def test_plan_is_fixed_to_source_and_idempotent_without_changing_material(self):
        self.session()
        wrong = plan()
        wrong["source_commit"] = "b" * 40
        self.assertEqual(self.request("/v1/sessions/s1/question-plan", wrong)[0], 400)
        self.assertEqual(self.request("/v1/sessions/s1/question-plan")[0], 404)
        status, first = self.request("/v1/sessions/s1/question-plan", plan())
        self.assertEqual(status, 201)
        self.assertEqual(self.request("/v1/sessions/s1/question-plan", plan())[1], first)
        changed = plan()
        changed["questions"][0]["text"] = "另一道问题"
        self.assertEqual(self.request("/v1/sessions/s1/question-plan", changed)[0], 409)
        self.assertEqual(self.store.get_material("owner-a", "mat_demo")["payload"], fixture.material())

    def test_unknown_or_cross_claim_evidence_and_injected_answer_keys_are_rejected(self):
        self.session()
        for change in ({"evidence_ids": ["unknown"]}, {"evidence_ids": []}, {"claim_id": "foreign"},
                       {"expected_facts": ["Invented answer"]}, {"question_id": "../bad"}):
            bad = plan()
            bad["questions"][0].update(change)
            with self.subTest(change=change):
                self.assertEqual(self.request("/v1/sessions/s1/question-plan", bad)[0], 400)

    def test_context_uses_generated_questions_and_keeps_learning_out_of_interviewer(self):
        self.session()
        self.request("/v1/sessions/s1/question-plan", plan())
        context = self.request("/v1/sessions/s1/context")[1]["material"]
        evaluation = self.request("/v1/sessions/s1/evaluation-context")[1]["material"]
        self.assertEqual(context["questions"][0]["question_id"], "pi_q1")
        self.assertNotIn("ua_learning_support", context["questions"][0])
        self.assertEqual(evaluation["questions"][0]["expected_facts"], [])
        self.assertEqual(evaluation["questions"][0]["ua_learning_support"][0]["evidence_id"], "ev_1")

    def test_generated_question_result_and_recap_roundtrip_with_history(self):
        self.session()
        saved = self.request("/v1/sessions/s1/question-plan", plan())[1]["payload"]
        result = fixture.result()
        self.assertEqual(self.request("/v1/sessions/s1/results", result)[0], 400)
        result["question_plan_id"] = saved["question_plan_id"]
        self.assertEqual(self.request("/v1/sessions/s1/results", result)[0], 400)
        for kind in ("answers", "observations"):
            result[kind][0]["question_id"] = "pi_q1"
        self.assertEqual(self.request("/v1/sessions/s1/results", result)[0], 201)
        status, recap = self.request("/v1/sessions/s1/recap", {})
        self.assertEqual(status, 201)
        self.assertEqual(recap["payload"]["question_plan_id"], saved["question_plan_id"])
        self.assertEqual(recap["payload"]["needs_review"][0]["question_id"], "pi_q1")
        history = self.request("/v1/history")[1]["items"][0]
        self.assertEqual(history["question_plan"]["payload"], saved)

    def test_completed_session_rejects_late_plan_and_cross_owner_access(self):
        self.session()
        self.request("/v1/sessions/s1/results", fixture.result())
        self.assertEqual(self.request("/v1/sessions/s1/question-plan", plan())[0], 409)
        with self.assertRaises(NotFoundError):
            self.store.get_plan("other", "s1")
        with self.assertRaises(NotFoundError):
            self.store.save_plan("other", "s1", plan())

    def test_storage_transaction_rejects_stale_plan_binding_before_finalization(self):
        self.session()
        saved = self.request("/v1/sessions/s1/question-plan", plan())[1]["payload"]
        with self.assertRaises(ConflictError):
            self.store.save_result("owner-a", "s1", fixture.result())
        self.assertEqual(self.store.get_session("owner-a", "s1")["state"], "in_progress")
        valid = copy.deepcopy(fixture.result())
        valid["question_plan_id"] = saved["question_plan_id"]
        self.store.save_result("owner-a", "s1", valid)


if __name__ == "__main__":
    unittest.main()
