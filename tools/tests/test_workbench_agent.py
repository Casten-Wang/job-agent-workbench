import base64
import http.client
import json
import os
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))
import backend
import server
import workbench_agent_runtime as bridge


def stream_connection(wire):
    response = MagicMock(status=200)
    response.getheader.return_value = "text/event-stream; charset=utf-8"
    response.readline.side_effect = BytesIO(wire).readline
    connection = MagicMock()
    connection.getresponse.return_value = response
    return connection


class WorkbenchBridgeTests(unittest.TestCase):
    def test_material_retry_uses_owner_snapshot_and_rejects_extra_fields(self):
        path = "/api/workbench-agent/conversations/wb_x/retry-material"
        payload = {"event_id": "retry-once", "run_id": "run_original"}
        with patch.object(bridge, "workspace", return_value={"profile": {}}), patch.object(bridge, "upstream", return_value={}) as upstream:
            self.assertEqual(bridge.dispatch("POST", path, {"mode": "user"}, payload)[1], 202)
            self.assertEqual(upstream.call_args.args, ("user", "POST", "/v1/workbench/conversations/wb_x/retry-material",
                {**payload, "source": {"profile": {}}}))
            for mode, body in (("demo", payload), ("user", {**payload, "source": {}}),
                               ("user", {**payload, "text": "替代原文"}), ("user", {**payload, "run_id": "../other"})):
                with self.assertRaises(backend.ApiError):
                    bridge.dispatch("POST", path, {"mode": mode}, body)

    def test_stream_forwards_live_frames_without_polling_or_buffering(self):
        wire = b'id: 1\nevent: snapshot\ndata: {}\n\nevent: text_delta\ndata: {"delta":"first"}\n\nevent: settled\ndata: {}\n\n'
        connection = stream_connection(wire)
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "synthetic-engine-token-at-least20"}), patch.object(bridge, "HTTPConnection", return_value=connection) as factory, patch.object(bridge, "dispatch", side_effect=AssertionError("SSE must not poll")):
            frames = bridge.stream_events("/api/workbench-agent/conversations/wb_x/stream", {"mode": "user", "after": "0"})
            self.assertEqual(next(frames), b"id: 1\n")
            self.assertEqual(connection.getresponse.return_value.readline.call_count, 1)
            self.assertEqual(b"id: 1\n" + b"".join(frames), wire)
            factory.assert_called_once_with("127.0.0.1", 18748, timeout=150)
        connection.close.assert_called_once()

    def test_stream_resume_validates_cursor_and_keeps_owner_scope(self):
        connection = stream_connection(b"event: settled\ndata: {}\n\n")
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "synthetic-engine-token-at-least20"}), patch.object(bridge, "HTTPConnection", return_value=connection) as factory:
            list(bridge.stream_events("/api/workbench-agent/conversations/wb_x/stream", {"mode": "user", "after": "0"}, "7"))
            factory.assert_called_once_with("127.0.0.1", 18748, timeout=150)
            self.assertEqual(connection.request.call_args.args, ("GET", "/v1/workbench/conversations/wb_x/stream?after=7"))
            self.assertEqual(connection.request.call_args.kwargs["headers"]["Authorization"], "Bearer synthetic-engine-token-at-least20")
            for query, cursor in (({"mode": "other"}, None), ({"mode": "user", "owner": "other"}, None), ({"mode": "user"}, "-1")):
                with self.assertRaises(backend.ApiError):
                    next(bridge.stream_events("/api/workbench-agent/conversations/wb_x/stream", query, cursor))

    def test_user_and_demo_are_fixed_services_and_browser_cannot_inject_context(self):
        with patch.object(bridge, "service_request", return_value={"items": []}) as upstream:
            bridge.dispatch("GET", "/api/workbench-agent/conversations", {"mode": "user"})
            self.assertEqual(upstream.call_args.args[:2], (18748, "OFFERPILOT_CAREER_USER_TOKEN"))
            with self.assertRaises(backend.ApiError):
                bridge.dispatch("GET", "/api/workbench-agent/conversations", {"mode": "demo"})
            for body in ({"owner": "other"}, {"source": {}}, {"mode": "demo"}):
                with self.assertRaises(backend.ApiError):
                    bridge.dispatch("POST", "/api/workbench-agent/conversations/wb_x/messages", {"mode": "user"}, body)
            with self.assertRaises(backend.ApiError):
                bridge.dispatch("POST", "/api/workbench-agent/send", {"mode": "user"}, {"confirmed": True})

    def test_workspace_uses_domain_records_and_excludes_contact_fields_from_professional_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(backend, "WEB_DIR", Path(directory)):
            store = backend.Store("user")
            store.set_profile({"truth_confirmed": True, "basic": {"name": "虚构", "email": "synthetic@example.invalid"}, "skills": {"tools": ["Python"]}})
            store.set_jobs([{"id": "one", "company": "虚构公司", "title": "后端", "city": "上海", "contact": "private"}])
            with patch.object(backend, "snapshot", side_effect=AssertionError("snapshot mutates deliveries")), patch.object(backend, "get_offerpilot_state", return_value={"task": {"id": "t1", "status": "running"}}):
                value = bridge.workspace("user")
            self.assertNotIn("synthetic@example.invalid", json.dumps(value["profile"]))
            self.assertNotIn("contact", value["jobs"][0])
            self.assertTrue(value["coverage"]["complete"])
            self.assertEqual(value["tasks"][0]["status"], "running")

    def test_attachment_text_extraction_requires_consent_and_stays_in_selected_service(self):
        payload = {"event_id": "upload", "kind": "experience", "name": "虚构项目", "role": "后端",
                   "model_consent": True, "filename": "note.txt", "content_base64": base64.b64encode("项目经历".encode()).decode()}
        with patch.object(bridge, "workspace", return_value={}), patch.object(bridge, "upstream", return_value={}) as upstream:
            bridge.dispatch("POST", "/api/workbench-agent/conversations/wb_x/attachments", {"mode": "user"}, payload)
            self.assertEqual(upstream.call_args.args[3]["attachment"]["text"], "项目经历")
            self.assertNotIn("content_base64", upstream.call_args.args[3]["attachment"])
            for mode, body in (("demo", payload), ("user", {**payload, "model_consent": False})):
                with self.assertRaises(backend.ApiError):
                    bridge.dispatch("POST", "/api/workbench-agent/conversations/wb_x/attachments", {"mode": mode}, body)

    def test_existing_material_attachment_is_scoped_and_cannot_mix_sources(self):
        path = "/api/workbench-agent/conversations/wb_x/attachments"
        payload = {"event_id": "organize", "kind": "experience", "material_id": "mat_confirmed",
                   "role": "产品经理", "model_consent": True}
        with patch.object(bridge, "workspace", return_value={}), patch.object(bridge, "upstream", return_value={}) as upstream:
            bridge.dispatch("POST", path, {"mode": "user"}, payload)
            self.assertEqual(upstream.call_args.args[:3], ("user", "POST", "/v1/workbench/conversations/wb_x/attachments"))
            self.assertEqual(upstream.call_args.args[3]["attachment"]["material_id"], "mat_confirmed")
            for mode, extra in (("demo", {}), ("user", {"text": "替代原文"}), ("user", {"filename": "x.txt"}),
                                ("user", {"material_id": "../other"}), ("user", {"kind": "profile"})):
                with self.assertRaises(backend.ApiError):
                    bridge.dispatch("POST", path, {"mode": mode}, {**payload, **extra})

    def test_profile_internal_callback_requires_engine_token_and_current_snapshot(self):
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "test-engine-token-at-least-20-chars"}):
            with self.assertRaises(backend.ApiError) as error:
                bridge.commit_profile({}, {"mode": "user"})
            self.assertEqual(error.exception.status, 401)
            with tempfile.TemporaryDirectory() as directory, patch.object(backend, "WEB_DIR", Path(directory)):
                payload = {"mode": "user", "operation_id": "approval_test", "expected": "stale", "profile": {}}
                with self.assertRaises(backend.ApiError) as error:
                    bridge.commit_profile({"Authorization": "Bearer test-engine-token-at-least-20-chars"}, payload)
                self.assertEqual(error.exception.status, 409)

    def test_profile_commit_recovers_an_acknowledgement_failure_without_writing_twice(self):
        token = "test-engine-token-at-least-20-chars"
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": token}), tempfile.TemporaryDirectory() as directory, patch.object(backend, "WEB_DIR", Path(directory)):
            current = backend.profile_public(backend.get_store("user").profile())
            payload = {"mode": "user", "operation_id": "approval_recover", "expected": bridge.fingerprint(current),
                       "profile": {"truth_confirmed": True, "basic": {"name": "虚构候选人"}, "skills": {"tools": ["Python"]}}}
            headers = {"Authorization": "Bearer " + token}
            original = backend.save_profile
            def write_then_fail(data):
                original(data)
                raise OSError("synthetic lost acknowledgement")
            with patch.object(backend, "save_profile", side_effect=write_then_fail) as writer:
                with self.assertRaises(OSError):
                    bridge.commit_profile(headers, payload)
                recovered = bridge.commit_profile(headers, payload)
                repeated = bridge.commit_profile(headers, payload)
                self.assertEqual(writer.call_count, 1)
            self.assertEqual(recovered["profile"]["basic"]["name"], "虚构候选人")
            self.assertEqual(recovered, repeated)
            with self.assertRaises(backend.ApiError):
                bridge.commit_profile(headers, {**payload, "profile": {"basic": {"name": "changed"}}})


class WorkbenchHTTPTests(unittest.TestCase):
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

    def get(self, path, origin=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request("GET", path, headers={"Origin": origin} if origin else {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def post(self, path, body, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request("POST", path, json.dumps(body), {"Content-Type": "application/json", **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_engine_callbacks_are_routed_and_reject_requests_without_the_engine_token(self):
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "{{SECRET_c7g2m9xw}}"}):
            for path in ("/api/workbench/internal/business", "/api/workbench-agent/internal/profile"):
                with self.subTest(path=path):
                    status, raw = self.post(path, {"mode": "user"})
                    self.assertIn(status, {400, 401, 403})
                    self.assertNotIn(b"{{SECRET_c7g2m9xw}}", raw)

    def test_resume_pdf_and_print_exports_are_served_with_download_headers(self):
        with patch.object(server.career_user_runtime, "pdf_document", return_value=b"%PDF-1.4 synthetic"), \
                patch.object(server.career_user_runtime, "print_document", return_value="<p>synthetic</p>"):
            status, body = self.get("/api/career-user/resumes/resume_test/pdf?mode=user")
            self.assertEqual((status, body[:5]), (200, b"%PDF-"))
            status, body = self.get("/api/career-user/resumes/resume_test/print?mode=user")
            self.assertEqual((status, body), (200, b"<p>synthetic</p>"))

    def test_workbench_assets_tabs_and_same_origin_route(self):
        for path in ("/workbench-agent.js", "/workbench-agent.css", "/"):
            status, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
        self.assertIn(b'id="wa-panel"', self.get("/")[1])
        self.assertEqual(self.get("/api/workbench-agent/conversations?mode=user", "https://example.com")[0], 403)
        with patch.object(bridge, "upstream", return_value={"items": []}):
            self.assertEqual(self.get("/api/workbench-agent/conversations?mode=user")[0], 200)
        with patch.dict(os.environ, {"OFFERPILOT_WORKBENCH_AGENT_DISABLED": "1"}):
            self.assertEqual(self.get("/api/workbench-agent/conversations?mode=user")[0], 503)

    def test_sse_content_type_frames_and_origin_guard(self):
        path = "/api/workbench-agent/conversations/wb_x/stream?mode=user"
        value = {"events": [], "view": {"cursor": 3, "status": "completed", "messages": [{"text": "合成回复"}]}}
        wire = ("id: 3\nevent: snapshot\ndata: " + json.dumps(value, ensure_ascii=False) + "\n\nevent: settled\ndata: {}\n\n").encode()
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "synthetic-engine-token-at-least20"}), patch.object(bridge, "HTTPConnection", return_value=stream_connection(wire)):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
            try:
                connection.request("GET", path, headers={"Last-Event-ID": "2"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "text/event-stream; charset=utf-8")
                body = response.read().decode("utf-8")
                self.assertIn("retry: 1500\n\n", body)
                self.assertIn("event: snapshot\n", body)
                self.assertIn("合成回复", body)
                self.assertIn("event: settled\n", body)
            finally:
                connection.close()
        self.assertEqual(self.get(path, "https://example.com")[0], 403)
        self.assertEqual(self.get(path.replace("mode=user", "mode=other"))[0], 400)
