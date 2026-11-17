import copy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from interview_agent.api import create_app
from interview_agent.model_adapter import ModelError
from interview_hub.store import Store


TOKEN = "local-python-interview-test-token"
SHA = "a" * 40


def material():
    return {"material_id": "mat_test", "source_commit": SHA, "project_snapshot_id": "snapshot_test",
        "resume_version_id": None, "is_demo": True, "source_repository": "example/demo",
        "claims": [{"claim_id": "c1", "text": "Project signs messages", "personal_contribution": "unconfirmed", "evidence_ids": ["e1"]}],
        "evidence": [{"evidence_id": "e1", "commit_sha": SHA, "path": "main.py", "line_start": 1, "line_end": 2,
            "text": "def sign(value):\n    return value", "source_url": f"https://github.com/example/demo/blob/{SHA}/main.py#L1-L2"}],
        "questions": [{"question_id": "q1", "claim_id": "c1", "text": "Explain sign", "evidence_ids": ["e1"],
                       "expected_facts": ["Draft fact; should not reach intent detection"]}]}


class FakeAgent:
    generation = {"provider": "test", "model": "contract", "kind": "contract_test"}

    def __init__(self):
        self.calls = []
        self.fail = None
        self.foreign = False

    async def decide(self, stage, value):
        self.calls.append((stage, copy.deepcopy(value)))
        if self.fail == stage:
            self.fail = None
            raise ModelError("synthetic_model_failure")
        if stage == "plan":
            return {"questions": [{"question_id": f"pi_q{i}", "claim_id": "c1", "text": f"Explain sign boundary {i}",
                "evidence_ids": ["e1"], "intent": "implementation", "reason": "Synthetic flow test"} for i in [1, 2]]}
        if stage == "intent":
            intents = {"暂停": "pause", "继续": "resume", "这是另一个版本": "correct_version", "不是我写的": "correct_contribution",
                       "提示": "request_hint", "结束": "finish", "不确定怎么办": "clarify"}
            return {"intent": intents.get(value["user_text"], "answer"), "reason": "Synthetic test routing", "clarification": "请澄清。"}
        if stage == "hint":
            return {"text": "先确认返回值。", "evidence_ids": ["e1"]}
        return {"status": "partial", "gap_type": "understanding", "notes": "Synthetic test observation, pending confirmation",
                "evidence_ids": ["foreign" if self.foreign else "e1"]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "records.db"
        self.checkpoints = Path(self.temp.name) / "graph.db"
        self.store = Store(self.db)
        self.store.put_material("alice", "mat_test", material())
        self.agent = FakeAgent()
        self.headers = {"Authorization": "Bearer " + TOKEN}
        self.event = 0

    def tearDown(self):
        self.temp.cleanup()

    def client(self, owner="alice"):
        return TestClient(create_app(self.db, self.checkpoints, owner, TOKEN, self.agent))

    def start(self, client, sid="s1"):
        response = client.post("/v1/interviews", json={"session_id": sid, "material_id": "mat_test", "target": {"role": "junior"}}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def turn(self, client, text, command=None, sid="s1", event_id=None):
        self.event += 1
        payload = {"event_id": event_id or f"event_{self.event}", "text": text}
        if command:
            payload["command"] = command
        response = client.post(f"/v1/interviews/{sid}/turns", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_question_plan_pause_checkpoint_restart_hint_and_recap(self):
        with self.client() as client:
            initial = self.start(client)
            self.assertEqual(initial["question"]["question_id"], "pi_q1")
            self.assertNotIn("expected_facts", initial["question"])
            self.turn(client, "提示")
            self.turn(client, "返回原消息和签名")
            self.turn(client, "暂停")
            self.assertEqual(self.turn(client, "暂停时不评价这段回答")["answered"], 1)
        with self.client() as client:
            restored = client.get("/v1/interviews/s1", headers=self.headers).json()
            self.assertEqual(restored["status"], "paused")
            self.assertEqual(restored["question_plan_id"], initial["question_plan_id"])
            self.turn(client, "继续")
            self.turn(client, "/skip", "skip")
            finished = self.turn(client, "结束")
            self.assertEqual(finished["status"], "completed")
            self.assertIsNone(finished["recap"]["ability_verdict"])
            self.assertFalse(finished["recap"]["applied_to_resume"])
            self.assertEqual(len(finished["recap"]["not_assessed"]), 1)
            result = client.get("/v1/sessions/s1/results", headers=self.headers).json()["payload"]
            self.assertEqual(result["answers"][0]["assistance_mode"], "hinted")
            self.assertEqual(result["question_plan_id"], initial["question_plan_id"])
        self.assertEqual(self.store.get_material("alice", "mat_test")["payload"], material())

    def test_corrections_hold_prior_observations_and_history_is_frozen(self):
        with self.client() as client:
            self.start(client)
            self.turn(client, "普通回答")
            self.assertEqual(self.turn(client, "不是我写的")["status"], "held")
            self.assertEqual(self.turn(client, "继续")["status"], "held")
            done = self.turn(client, "结束")
            self.assertEqual(done["recap"]["pending_corrections"][0]["confirmed"], False)
            result = self.store.get_result("alice", "s1")["payload"]
            self.assertEqual(result["observations"][0]["status"], "not_assessed")
            self.start(client, "s2")
            self.assertEqual(self.store.get_session("alice", "s2")["payload"]["related_history"][0]["session_id"], "s1")
            self.assertEqual(self.store.get_session("alice", "s1")["payload"]["related_history"], [])

    def test_invalid_evidence_or_model_failure_keeps_pending_answer_retry_after_restart(self):
        with self.client() as client:
            self.start(client)
            self.agent.foreign = True
            failed = self.turn(client, "待评估原回答")
            self.assertTrue(failed["pending_evaluation"])
            self.assertEqual(failed["answered"], 0)
            self.assertEqual(failed["last_error"]["code"], "invalid_observation")
        with self.client() as client:
            self.agent.foreign = False
            self.agent.fail = "observation"
            failed = self.turn(client, "/retry", "retry")
            self.assertTrue(failed["pending_evaluation"])
            passed = self.turn(client, "/retry", "retry")
            self.assertFalse(passed["pending_evaluation"])
            self.assertEqual(passed["answered"], 1)

    def test_event_retries_do_not_advance_twice_and_reused_id_cannot_change_payload(self):
        with self.client() as client:
            self.start(client)
            first = self.turn(client, "回答", event_id="stable")
            calls = len(self.agent.calls)
            self.assertEqual(self.turn(client, "回答", event_id="stable"), first)
            self.assertEqual(len(self.agent.calls), calls)
            response = client.post("/v1/interviews/s1/turns", json={"event_id": "stable", "text": "改写"}, headers=self.headers)
            self.assertEqual(response.status_code, 409)

    def test_authentication_validation_and_owner_isolation(self):
        with self.client() as client:
            self.assertEqual(client.get("/health").status_code, 401)
            self.start(client)
            response = client.post("/v1/interviews", json={"material_id": "mat_test", "owner": "secret-body"}, headers=self.headers)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("secret-body", response.text)
            self.assertEqual(client.post("/v1/interviews", json={"material_id": "mat_test", "mode": "mock_interview"}, headers=self.headers).status_code, 400)
        with self.client("bob") as client:
            self.assertEqual(client.get("/v1/interviews/s1", headers=self.headers).status_code, 404)

    def test_failed_intent_retries_node_without_replaying_input(self):
        with self.client() as client:
            self.start(client)
            self.agent.fail = "intent"
            response = client.post("/v1/interviews/s1/turns", json={"event_id": "original", "text": "原回答"}, headers=self.headers)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(self.turn(client, "/retry", "retry")["answered"], 1)
            self.assertEqual(self.agent.calls[-1][1]["answer"]["text"], "原回答")

    def test_completed_session_and_model_change_cannot_overwrite_records(self):
        with self.client() as client:
            self.start(client)
            self.turn(client, "结束", event_id="finish")
            self.assertEqual(self.turn(client, "结束", event_id="finish")["status"], "completed")
            self.assertEqual(client.post("/v1/interviews/s1/turns", json={"event_id": "new", "text": "新回答"}, headers=self.headers).status_code, 409)
        self.agent.generation = {**self.agent.generation, "model": "changed"}
        with self.client() as client:
            self.assertEqual(client.get("/v1/interviews/s1", headers=self.headers).status_code, 409)

    def test_legacy_json_import_preserves_pause_without_replaying_models_or_changing_file(self):
        with self.client() as client:
            self.start(client)
            self.turn(client, "提示")
            self.turn(client, "暂停")
            workflow = client.app.state.workflow
            snapshot = client.portal.call(workflow.graph.aget_state, workflow.config("s1"))
            legacy = dict(snapshot.values["data"])
            for key in ("material", "processed_events", "last_error"):
                legacy.pop(key, None)
        path = Path(self.temp.name) / "legacy.json"
        encoded = json.dumps(legacy, ensure_ascii=False)
        path.write_text(encoded, encoding="utf-8")
        self.checkpoints = Path(self.temp.name) / "migrated.db"
        calls = len(self.agent.calls)
        with self.client() as client:
            imported = client.portal.call(client.app.state.workflow.import_legacy, path)
            self.assertEqual(imported["status"], "paused")
            self.assertEqual(len(self.agent.calls), calls)
            self.turn(client, "继续")
            self.turn(client, "回答")
            finished = self.turn(client, "结束")
            self.assertEqual(finished["recap"]["needs_review"][0]["assistance_mode"], "hinted")
        self.assertEqual(path.read_text(encoding="utf-8"), encoded)

    def test_initialization_failure_can_retry_without_creating_another_session(self):
        with self.client() as client:
            self.agent.fail = "plan"
            failed = client.post("/v1/interviews", json={"material_id": "mat_test", "session_id": "s1"}, headers=self.headers)
            self.assertEqual(failed.status_code, 502)
            retried = self.turn(client, "/retry", "retry")
            self.assertEqual(retried["question"]["question_id"], "pi_q1")
            self.assertEqual(len(self.store.history("alice")), 1)

    def test_pending_answer_can_finish_unassessed_and_version_correction_remains_held(self):
        with self.client() as client:
            self.start(client)
            self.agent.fail = "observation"
            self.turn(client, "未完成评价的回答")
            final = self.turn(client, "结束")
            self.assertEqual(len(final["recap"]["what_went_well"]), 0)
            self.assertEqual(final["recap"]["not_assessed"][0]["reason"], "no_observation")
            self.start(client, "s2")
            self.turn(client, "普通回答", sid="s2")
            self.turn(client, "这是另一个版本", sid="s2")
            self.assertEqual(self.turn(client, "继续", sid="s2")["status"], "held")
            corrected = self.turn(client, "结束", sid="s2")
            self.assertEqual(corrected["recap"]["pending_corrections"][0]["intent"], "correct_version")


if __name__ == "__main__":
    unittest.main()
