import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from interview_hub.server import make_server
from interview_hub.store import Store


TOKEN = "local-test-token-for-offline-api-tests"
COMMIT = "a" * 40


def material():
    return {"material_id": "mat_demo", "schema_version": 1, "is_demo": True,
            "resume_version_id": None, "project_snapshot_id": "snapshot_1", "source_commit": COMMIT,
            "source_repository": "example/demo", "claims": [{"claim_id": "claim_1", "text": "Project has a signer",
                 "personal_contribution": "unconfirmed", "evidence_ids": ["ev_1"]}],
            "evidence": [{"evidence_id": "ev_1", "commit_sha": COMMIT, "path": "main.py", "line_start": 1,
                          "line_end": 2, "text": "def sign(x):\n    return x", "source_url": "https://github.com/example/demo/blob/" + COMMIT + "/main.py#L1-L2"}],
            "questions": [{"question_id": "q1", "claim_id": "claim_1", "text": "Explain sign",
                           "evidence_ids": ["ev_1"], "expected_facts": ["Keeps the payload"],
                           "ua_learning_support": [{"path": "main.py", "lineRange": [1, 2], "title": "Signing",
                                "tourOrder": 1, "evidence_id": "ev_1", "explanation": "Source-guided lesson",
                                "source_url": "https://github.com/example/demo"}]}]}


def result():
    return {"material_id": "mat_demo", "source_commit": COMMIT, "resume_version_id": None,
            "answers": [{"question_id": "q1", "text": "I need to revisit the source", "skipped": False,
                         "assistance_mode": "open_book"}],
            "observations": [{"question_id": "q1", "status": "partial", "gap_type": "understanding",
                              "notes": "Synthetic test observation, not a real candidate", "evidence_ids": ["ev_1"]}]}


class InterviewAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "interview.db")
        self.store.put_material("owner-a", "mat_demo", material())
        self.server = make_server(self.store, "owner-a", TOKEN, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, data=None, token=TOKEN, headers=None):
        actual_headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        actual_headers.update(headers or {})
        raw = None if data is None else json.dumps(data).encode()
        req = Request(self.url + path, data=raw, headers=actual_headers)
        try:
            response = self.client.open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def session(self):
        status, record = self.request("/v1/sessions", {"session_id": "s1", "material_id": "mat_demo",
                                    "mode": "resume_readiness", "target": {"role": "backend", "round": "first"}})
        self.assertEqual(status, 201)
        return record

    def test_backend_requires_token_and_never_accepts_client_owner(self):
        self.assertEqual(self.request("/health", token="wrong")[0], 401)
        status, _ = self.request("/v1/sessions", {"owner_id": "owner-b", "material_id": "mat_demo"})
        self.assertEqual(status, 400)
        other = material()
        other["material_id"] = "private_other"
        self.store.put_material("owner-b", "private_other", other)
        self.assertEqual(self.request("/v1/materials/private_other")[0], 404)

    def test_interviewer_context_and_evaluator_context_are_separate(self):
        self.session()
        status, context = self.request("/v1/sessions/s1/context")
        self.assertEqual(status, 200)
        question = context["material"]["questions"][0]
        self.assertNotIn("expected_facts", question)
        self.assertNotIn("ua_learning_support", question)
        self.assertEqual(context["session"]["payload"]["source_commit"], COMMIT)
        status, evaluator = self.request("/v1/sessions/s1/evaluation-context")
        self.assertEqual(status, 200)
        self.assertIn("expected_facts", evaluator["material"]["questions"][0])

    def test_result_recap_history_roundtrip_and_immutable_retries(self):
        self.session()
        self.assertEqual(self.request("/v1/sessions/s1/recap", {})[0], 404)
        final = result()
        self.assertEqual(self.request("/v1/sessions/s1/results", final)[0], 201)
        self.assertEqual(self.request("/v1/sessions/s1/results", final)[0], 201)
        changed = copy.deepcopy(final)
        changed["answers"][0]["text"] = "Different final answer"
        self.assertEqual(self.request("/v1/sessions/s1/results", changed)[0], 409)
        status, first = self.request("/v1/sessions/s1/recap", {})
        self.assertEqual(status, 201)
        self.assertIsNone(first["payload"]["ability_verdict"])
        self.assertFalse(first["payload"]["applied_to_resume"])
        self.assertEqual(first["payload"]["review_status"], "pending_user_confirmation")
        status, second = self.request("/v1/sessions/s1/recap", {})
        self.assertEqual(status, 200)
        self.assertEqual(first, second)
        status, history = self.request("/v1/history?claim_id=claim_1")
        self.assertEqual(status, 200)
        self.assertEqual(len(history["items"]), 1)
        self.assertIsNotNone(history["items"][0]["recap"])

    def test_wrong_version_and_unknown_question_are_rejected_before_storage(self):
        self.session()
        wrong = result()
        wrong["source_commit"] = "b" * 40
        self.assertEqual(self.request("/v1/sessions/s1/results", wrong)[0], 400)
        wrong = result()
        wrong["answers"][0]["question_id"] = "not-in-this-session"
        self.assertEqual(self.request("/v1/sessions/s1/results", wrong)[0], 400)
        self.assertEqual(self.request("/v1/sessions/s1/results")[0], 404)

    def test_skipped_answer_cannot_be_assessed_as_consistent(self):
        self.session()
        bad = result()
        bad["answers"][0].update(text="", skipped=True)
        bad["observations"][0]["status"] = "consistent"
        self.assertEqual(self.request("/v1/sessions/s1/results", bad)[0], 400)

    def test_payload_session_and_snapshot_cannot_disagree_with_route(self):
        self.session()
        for field, value in [("session_id", "other-session"), ("project_snapshot_id", "other-snapshot")]:
            wrong = result()
            wrong[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.request("/v1/sessions/s1/results", wrong)[0], 400)
        self.assertEqual(self.request("/v1/sessions/s1/results")[0], 404)
        self.assertEqual(self.request("/v1/sessions/s1/results", result())[0], 201)
        _, saved = self.request("/v1/sessions/s1/results")
        self.assertEqual(saved["payload"]["session_id"], "s1")
        self.assertEqual(saved["payload"]["project_snapshot_id"], "snapshot_1")

    def test_later_session_can_find_a_previous_recap_without_changing_it(self):
        self.session()
        self.request("/v1/sessions/s1/results", result())
        _, original = self.request("/v1/sessions/s1/recap", {})
        status, _ = self.request("/v1/sessions", {"session_id": "s2", "material_id": "mat_demo"})
        self.assertEqual(status, 201)
        _, context = self.request("/v1/sessions/s2/context")
        self.assertEqual([h["session_id"] for h in context["related_history"]], ["s1"])
        self.request("/v1/sessions/s2/results", result())
        _, second = self.request("/v1/sessions/s2/recap", {})
        self.assertEqual(second["payload"]["related_history_session_ids"], ["s1"])
        self.assertEqual(self.request("/v1/sessions/s1/recap")[1], original)
        self.assertEqual(self.request("/v1/sessions/s1/context")[1]["related_history"], [])
        self.session()  # Idempotent create must not pull later-round feedback into an old session.
        self.assertEqual(self.request("/v1/sessions/s1/context")[1]["related_history"], [])

    def test_mock_interview_requires_saved_resume_version(self):
        self.assertEqual(self.request("/v1/sessions", {"material_id": "mat_demo", "mode": "mock_interview"})[0], 400)
        versioned = material()
        versioned.update(material_id="mat_versioned", resume_version_id="resume_v1")
        self.store.put_material("owner-a", "mat_versioned", versioned)
        status, record = self.request("/v1/sessions", {"material_id": "mat_versioned", "mode": "mock_interview"})
        self.assertEqual(status, 201)
        self.assertEqual(record["payload"]["resume_version_id"], "resume_v1")


if __name__ == "__main__":
    unittest.main()
