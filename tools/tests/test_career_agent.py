"""Public bridge contracts; no model, private runtime or platform access."""

import http.client
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))
import backend
import career_agent_runtime as career
import server


class CareerBridgeTests(unittest.TestCase):
    def test_only_local_mode_and_known_parameters_are_allowed(self):
        with patch.object(career, "_request") as upstream:
            for query in ({"mode": "prod"}, {"url": "http://example.com"}, {"owner": "someone"}):
                with self.assertRaises(backend.ApiError):
                    career.dispatch("GET", "/api/resume-agent/materials", query)
            upstream.assert_not_called()

    def test_material_list_filters_private_or_other_versions(self):
        good = {"material_id": career.MATERIAL_ID, "source_commit": career.SOURCE_COMMIT, "is_demo": True}
        with patch.object(career, "_request", return_value={"items": [good, {**good, "is_demo": False}, {**good, "material_id": "foreign"}]}):
            result, status = career.dispatch("GET", "/api/resume-agent/materials", {})
        self.assertEqual(status, 200)
        self.assertEqual(result["items"], [good])

    def test_start_forces_readiness_and_public_material(self):
        with patch.object(career, "_request", return_value={"is_demo": True}) as upstream:
            career.dispatch("POST", "/api/interview-agent/sessions", {}, {"session_id": "opdemo_test"})
        body = upstream.call_args.args[2]
        self.assertEqual(body["mode"], "resume_readiness")
        self.assertEqual(body["material_id"], career.MATERIAL_ID)
        self.assertNotIn("expected_facts", career._view({"is_demo": True}))

    def test_start_rejects_custom_material_owner_and_path(self):
        for payload in ({"session_id": "../x"}, {"session_id": "opdemo_x", "material_id": "private"},
                        {"session_id": "opdemo_x", "owner": "user"}):
            with self.assertRaises(backend.ApiError):
                career.dispatch("POST", "/api/interview-agent/sessions", {}, payload)

    def test_foreign_plan_cannot_be_read_or_mutated(self):
        with patch.object(career, "_request", return_value={"payload": {"material_id": "private"}}) as upstream:
            with self.assertRaises(backend.ApiError) as error:
                career.dispatch("POST", "/api/interview-agent/sessions/opdemo_test/turns", {},
                                {"event_id": "e1", "text": "synthetic"})
            self.assertEqual(error.exception.status, 403)
            self.assertEqual(upstream.call_count, 1)

    def test_invalid_command_is_a_validation_error(self):
        with self.assertRaises(backend.ApiError):
            career.dispatch("POST", "/api/interview-agent/sessions/opdemo_test/turns", {},
                            {"event_id": "e1", "text": "synthetic", "command": []})

    def test_upstream_error_does_not_echo_body_or_token(self):
        class Response:
            status = 401
            def read(self, limit):
                return b'{"error":"sensitive-upstream-body"}'
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_AGENT_TOKEN": "test-bridge-secret-value"}), \
                patch.object(http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = Response()
            with self.assertRaises(backend.ApiError) as error:
                career._request("GET", "/health")
            self.assertNotIn("sensitive", str(error.exception))
            self.assertNotIn("secret", str(error.exception))

    def test_model_failure_has_actionable_safe_message(self):
        class Response:
            status = 502
            def read(self, limit):
                return b'{"code":"invalid_model_decision","debug":"private-provider-content"}'
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_AGENT_TOKEN": "test-bridge-secret-value"}), \
                patch.object(http.client, "HTTPConnection") as connection:
            connection.return_value.getresponse.return_value = Response()
            with self.assertRaises(backend.ApiError) as error:
                career._request("POST", "/v1/interviews", {})
            self.assertIn("格式校验", str(error.exception))
            self.assertNotIn("private", str(error.exception))


class CareerHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def request(self, path, origin=None):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            client.request("GET", path, headers={"Origin": origin} if origin else {})
            response = client.getresponse()
            return response.status, response.read()
        finally:
            client.close()

    def test_route_is_same_origin_and_rejects_unknown_mode(self):
        self.assertEqual(self.request("/api/resume-agent/materials?mode=prod")[0], 400)
        self.assertEqual(self.request("/api/resume-agent/materials", "https://example.com")[0], 403)

    def test_unconfigured_service_is_actionable(self):
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_AGENT_TOKEN": ""}):
            status, body = self.request("/api/resume-agent/materials?mode=user")
        self.assertEqual(status, 503)
        self.assertIn("启动面试服务", json.loads(body)["error"])

    def test_capabilities_route_is_credential_free(self):
        status, body = self.request("/api/agent/capabilities")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["ok"])
        self.assertIn("modules", payload)
        self.assertNotIn("API_KEY", json.dumps(payload))
