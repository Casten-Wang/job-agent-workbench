"""Workbench HTTP -> bridge -> real FastAPI/LangGraph/SQLite, synthetic model."""

import copy
import http.client
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from interview_agent.api import create_app
from interview_agent.model_adapter import ModelError
from interview_hub.store import Store

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "offerpilot/web"))
import backend
import career_agent_runtime as career
spec = importlib.util.spec_from_file_location("offerpilot_workbench_server", ROOT / "offerpilot/web/server.py")
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)
TOKEN = "public-integration-contract-test-token"


class DemoAgent:
    generation = {"provider": "test", "model": "contract", "kind": "contract_test"}

    def __init__(self):
        self.calls = []
        self.fail_plan = False
        self.fail_observation = False

    async def decide(self, stage, value):
        self.calls.append(stage)
        if stage == "plan":
            if self.fail_plan:
                self.fail_plan = False
                raise ModelError("synthetic_plan_failure")
            return {"questions": [{"question_id": f"demo_q{i}", "claim_id": q["claim_id"], "text": q["text"],
                "evidence_ids": q["evidence_ids"], "intent": "implementation", "reason": "Synthetic integration test"}
                for i, q in enumerate(value["material"]["questions"][:2], 1)]}
        if stage == "hint":
            return {"text": "合成测试提示：核对时间戳。", "evidence_ids": value["question"]["evidence_ids"]}
        if stage == "intent":
            return {"intent": "answer", "reason": "Synthetic intent", "clarification": ""}
        if self.fail_observation:
            self.fail_observation = False
            raise ModelError("synthetic_observation_failure")
        return {"status": "partial", "gap_type": "understanding", "notes": "合成反馈，待确认。",
                "evidence_ids": value["question"]["evidence_ids"]}


class OfferPilotIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.agent = DemoAgent()
        Store(self.directory / "data.db").put_material("public-test", career.MATERIAL_ID, copy.deepcopy(career.public_fixture()))
        self.open_client()
        self.bridge_patch = patch.object(career, "_request", side_effect=self.upstream)
        self.bridge_patch.start()
        self.server = workbench.make_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def open_client(self):
        self.client = TestClient(create_app(self.directory / "data.db", self.directory / "checkpoint.db", "public-test", TOKEN, self.agent))
        self.client.__enter__()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(5)
        self.bridge_patch.stop()
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def upstream(self, method, path, payload=None):
        response = self.client.request(method, path, json=payload, headers={"Authorization": "Bearer " + TOKEN})
        if response.status_code >= 400:
            raise backend.ApiError("Synthetic upstream error", response.status_code)
        return response.json()

    def call(self, method, path, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            connection.request(method, path + "?mode=demo", body=json.dumps(payload) if payload else None,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            data = json.loads(response.read())
            return response.status, data
        finally:
            connection.close()

    def turn(self, event_id, command=None, text="Synthetic public answer"):
        return self.call("POST", "/api/interview-agent/sessions/opdemo_test/turns",
                         {"event_id": event_id, "text": text, **({"command": command} if command else {})})

    def test_public_start_pause_restart_hint_answer_retry_and_recap(self):
        status, opened = self.call("POST", "/api/interview-agent/sessions", {"session_id": "opdemo_test"})
        self.assertEqual(status, 201)
        plan_id = opened["view"]["question_plan_id"]
        self.assertNotIn("expected_facts", opened["view"]["question"])
        self.assertEqual(self.turn("pause", "pause")[1]["view"]["status"], "paused")
        self.client.__exit__(None, None, None)
        self.open_client()
        restored = self.call("GET", "/api/interview-agent/sessions/opdemo_test")[1]
        self.assertEqual(restored["view"]["question_plan_id"], plan_id)
        self.assertEqual(restored["view"]["status"], "paused")
        self.turn("resume", "resume")
        self.assertIn("合成测试提示", self.turn("hint", "request_hint")[1]["view"]["message"])
        self.agent.fail_observation = True
        self.assertTrue(self.turn("answer")[1]["view"]["pending_evaluation"])
        self.assertFalse(self.turn("retry", "retry")[1]["view"]["pending_evaluation"])
        before = len(self.agent.calls)
        self.assertEqual(self.turn("answer")[0], 200)
        self.assertEqual(len(self.agent.calls), before)
        self.assertEqual(self.turn("answer", text="Changed payload")[0], 409)
        self.turn("skip", "skip")
        self.assertEqual(self.turn("finish", "finish")[1]["view"]["status"], "completed")
        status, result = self.call("GET", "/api/interview-agent/sessions/opdemo_test/recap")
        self.assertEqual(status, 200)
        recap = result["recap"]
        self.assertEqual(recap["needs_review"][0]["assistance_mode"], "hinted")
        self.assertEqual(len(recap["not_assessed"]), 1)
        self.assertTrue(recap["improvement_tasks"])
        self.assertFalse(recap["applied_to_resume"])
        self.assertIsNone(recap["resume_version_id"])

    def test_start_retries_failed_initialization_using_same_session(self):
        self.agent.fail_plan = True
        path, payload = "/api/interview-agent/sessions", {"session_id": "opdemo_test"}
        self.assertEqual(self.call("POST", path, payload)[0], 502)
        status, opened = self.call("POST", path, payload)
        self.assertEqual(status, 201)
        self.assertEqual(opened["view"]["session_id"], "opdemo_test")
        self.assertEqual(Store(self.directory / "data.db").get_session("public-test", "opdemo_test")["material_id"], career.MATERIAL_ID)
