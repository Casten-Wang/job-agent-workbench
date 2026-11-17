"""User-visible workbench contracts, receipts and domain-adapter regression tests."""

import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))
import backend
import server
import workbench_runtime as wb
from interview_agent.workbench_catalog import BUSINESS_TOOLS, CAPABILITIES, validate_arguments
from workbench_services import ModelSettings


class UnifiedWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.web = patch.object(backend, "WEB_DIR", self.root / "web")
        self.web.start()
        self.addCleanup(self.web.stop)
        self.addCleanup(self.temp.cleanup)

    def test_overview_only_reads_domains_and_reports_unavailable_counts_as_unknown(self):
        store = backend.get_store("user", seed_if_empty=False)
        store.set_jobs([{"id": "j1", "company": "虚构公司", "title": "后端"}])
        with patch.object(backend, "snapshot", side_effect=AssertionError("overview must not sync deliveries")), \
                patch.object(backend, "get_offerpilot_state", return_value={"ok": False}), \
                patch.object(wb, "engine_get", return_value=None), patch.object(wb, "settings_status", return_value={"configured": False}):
            result = wb.overview("user")
        self.assertEqual(result["counts"]["jobs"], 1)
        self.assertIsNone(result["counts"]["materials"])
        self.assertTrue(result["partial"])
        self.assertEqual(result["next_action"]["capability"], "profile_import")
        self.assertFalse((store.root / "workbench-operations.db").exists())

    def test_reading_overview_does_not_start_tasks_or_inference(self):
        with patch.object(backend, "get_offerpilot_state", return_value={"ok": True}), \
                patch.object(wb, "engine_get", return_value={"tasks": [{"id": "wb_1", "title": "虚构任务", "status": "running", "capability": "application"}], "materials": [], "versions": []}), \
                patch.object(wb, "perform", side_effect=AssertionError("read only")):
            result = wb.overview("user")
        self.assertEqual(result["tasks"][0]["status"], "running")

    def test_catalog_covers_every_existing_panel_and_has_real_anchor_targets(self):
        html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        ids = re.findall(r'\bid="([^"]+)"', html)
        self.assertEqual(len(ids), len(set(ids)))
        for key, _, _, view, anchor, _ in CAPABILITIES:
            with self.subTest(capability=key):
                if anchor:
                    self.assertIn(anchor, ids)
                self.assertTrue("view-" + view in ids or view in {"experience", "application", "notes", "settings", "overview"})
        self.assertTrue({"collect", "jobs", "queue", "mail", "profile", "interview", "resume", "push", "data"}.issubset({c[3] for c in CAPABILITIES}))

    def test_every_named_business_tool_rejects_arbitrary_execution_arguments(self):
        for name, (_, _, _, fields) in BUSINESS_TOOLS.items():
            with self.subTest(tool=name):
                args = {k: ("synthetic" if kind == "text" else ["known-id"] if kind in {"ids", "strings"} else 1)
                        for k, (kind, default, _) in fields.items() if default is None}
                validate_arguments(name, args)
                with self.assertRaises(ValueError):
                    validate_arguments(name, {**args, "owner": "other"})
        for name in ("shell", "http", "sql", "offerpilot-deliver"):
            with self.assertRaises(ValueError):
                validate_arguments(name, {})

    def test_same_operation_receipt_does_not_repeat_business_write(self):
        with patch.object(wb, "perform", return_value={"ok": True, "id": "saved"}) as domain:
            first = wb.execute("user", "record_job", {"text": "虚构岗位"}, "once")
            second = wb.execute("user", "record_job", {"text": "虚构岗位"}, "once")
            self.assertEqual(first, second)
            domain.assert_called_once()
            with self.assertRaises(backend.ApiError):
                wb.execute("user", "record_job", {"text": "另一岗位"}, "once")
            # 本产品只有本机单一数据集（demo 模式已移除）；换一个操作编号才会真正再执行一次。
            wb.execute("user", "record_job", {"text": "虚构岗位"}, "twice")
            self.assertEqual(domain.call_count, 2)

    def test_uncertain_write_is_not_replayed_after_connection_loss(self):
        with patch.object(wb, "perform", side_effect=ConnectionError("ack lost")) as domain:
            with self.assertRaises(ConnectionError):
                wb.execute("user", "record_job", {"text": "虚构岗位"}, "uncertain")
            with self.assertRaises(backend.ApiError) as error:
                wb.execute("user", "record_job", {"text": "虚构岗位"}, "uncertain")
            self.assertEqual(error.exception.status, 409)
            domain.assert_called_once()

    def test_local_adapters_match_existing_domain_input_contracts(self):
        cases = [
            ("record_job", {"text": "虚构公司 后端岗位"}, "parse_jd", {"text": "虚构公司 后端岗位"}),
            ("import_job_json", {"text": '{"jobs":[]}'}, "import_jobs", {"text": '{"jobs":[]}'}),
            ("enqueue_jobs", {"ids": ["j1"]}, "enqueue", {"ids": ["j1"]}),
            ("import_collected_jobs", {"ids": ["v1"]}, "import_offerpilot_jobs", {"ids": ["v1"]}),
            ("prepare_greetings", {"ids": ["j1"]}, "start_offerpilot_greet", {"ids": ["j1"]}),
            ("parse_hr_mail", {"text": "虚构 HR 邀请\n明天面试", "received_date": "2026-11-17"}, "parse_mail", {"subject": "虚构 HR 邀请", "body": "虚构 HR 邀请\n明天面试", "date": "2026-11-17"}),
            ("export_calendar", {"mail_id": "m1"}, "generate_ics", {"id": "m1"}),
            ("build_worksheet", {"jd": "Python", "minutes": 30}, "worksheet", {"jd": "Python", "minutes": 30}),
            ("review_transcript", {"text": "问：职责？答：参与校验。"}, "debrief", {"transcript": "问：职责？答：参与校验。"}),
            ("add_interview_question", {"question": "如何验证？", "section": "项目深挖"}, "add_bank_question", {"question": "如何验证？", "section": "项目深挖"}),
            ("save_experience_variant", {"project": "虚构项目", "text": "参与校验"}, "add_variant", {"project": "虚构项目", "text": "参与校验"}),
        ]
        for name, args, method, expected in cases:
            with self.subTest(tool=name), patch.object(backend, method, return_value={"ok": True}) as domain:
                wb.perform("user", name, args)
                self.assertEqual(domain.call_args.args[0], {"mode": "user", "data_mode": "user", **expected})

    def test_note_and_knowledge_adapters_use_owner_bound_existing_routes(self):
        cases = [
            ("knowledge_sources", {}, "GET", "/knowledge/sources"),
            ("search_project_knowledge", {"snapshot_ids": ["s1"], "query": "校验"}, "POST", "/knowledge/search"),
            ("collect_note", {"url": "https://www.xiaohongshu.com/explore/synthetic"}, "POST", "/notes/collect"),
            ("subscribe_note", {"url": "https://www.xiaohongshu.com/explore/synthetic", "interval_hours": 24, "keywords": []}, "POST", "/notes/subscriptions"),
            ("note_subscriptions", {}, "GET", "/notes/subscriptions"),
            ("pause_note_subscription", {"subscription_id": "sub_one"}, "POST", "/notes/subscriptions/sub_one/pause"),
            ("resume_note_subscription", {"subscription_id": "sub_one"}, "POST", "/notes/subscriptions/sub_one/resume"),
            ("note_inbox", {"offset": 30}, "GET", "/notes/inbox"),
            ("read_note", {"note_id": "note_one"}, "GET", "/notes/items/note_one"),
            ("mark_note_read", {"message_id": "msg_one"}, "POST", "/notes/inbox/msg_one/read"),
            ("note_self_check", {}, "GET", "/notes/self-check"),
        ]
        for name, args, method, path in cases:
            with self.subTest(tool=name), patch.object(wb.career_user_runtime, "dispatch", return_value=({"ok": True}, 200)) as domain:
                wb.perform("user", name, args)
                self.assertEqual(domain.call_args.args[:2], (method, "/api/career-user" + path))
                self.assertEqual(domain.call_args.args[2]["mode"], "user")
                if name == "note_inbox":
                    self.assertEqual(domain.call_args.args[2]["offset"], "30")

    def test_natural_language_external_actions_only_prepare_existing_confirmation_forms(self):
        with patch.object(backend, "start_offerpilot_task") as collect, patch.object(backend, "start_offerpilot_deliver") as send:
            for name, args, capability in (("collect_jobs", {"keywords": "后端", "city": "上海"}, "collect"),
                    ("review_delivery", {"ids": ["j1"]}, "queue"), ("approve_jobs", {"ids": ["j1"]}, "queue"),
                    ("prepare_github_project", {"repository": "test/repo", "role": "后端", "contribution": "参与校验"}, "github")):
                self.assertEqual(wb.execute("user", name, args, "handoff")["ui_action"]["capability"], capability)
            collect.assert_not_called()
            send.assert_not_called()

    def test_delivery_confirmation_is_bound_to_current_text_and_is_receipted(self):
        store = backend.get_store("user")
        store.set_jobs([{"id": "j1", "company": "虚构", "title": "后端", "offerpilot_id": "v1"}])
        store.set_queue([{"id": "j1", "status": "approved"}])
        greeting = {"id": "v1", "greeting": "已核对文案", "ready": True}
        with patch.object(backend.offerpilot_runtime, "get_greetings", side_effect=lambda ids: {"greetings": [dict(greeting)]}), \
                patch.object(backend, "start_offerpilot_deliver", return_value={"ok": True, "batch": {"batch_id": "b1"}}) as send:
            preview = wb.delivery_preview("user", ["j1"])
            body = {"action": "offerpilot-deliver", "arguments": {"ids": ["j1"], "binding": preview["binding"], "confirm": "确认发送本批 1 条", "risk_acknowledged": True}, "operation_id": "send-once"}
            first = wb.confirmed_action("user", body)
            self.assertEqual(wb.confirmed_action("user", body), first)
            send.assert_called_once()
            greeting["greeting"] = "已变化文案"
            with self.assertRaises(backend.ApiError):
                wb.confirmed_action("user", {**body, "operation_id": "stale-review"})
            send.assert_called_once()

    def test_sensitive_internal_bridge_requires_the_matching_engine_token(self):
        body = {"mode": "user", "tool": "record_job", "arguments": {"text": "虚构岗位"}, "operation_id": "event"}
        with patch.dict(os.environ, {"OFFERPILOT_CAREER_USER_TOKEN": "synthetic-user-token-123456"}), patch.object(wb, "execute", return_value={"ok": True}) as execute, patch.object(wb.workbench_agent_runtime, "workspace", return_value={}):
            for headers in ({}, {"Authorization": "Bearer other-token"}):
                with self.assertRaises(backend.ApiError):
                    wb.internal(headers, body)
            execute.assert_not_called()
            self.assertTrue(wb.internal({"Authorization": "Bearer synthetic-user-token-123456"}, body)["result"]["ok"])

    def test_engine_model_follows_the_explicit_ai_settings_and_ignores_environment(self):
        class Server:
            CONFIG_PATH = "x"
            load_config = staticmethod(lambda _: {"ai": {"service": "deepseek", "model": "deepseek-flash", "base_url": "https://api.deepseek.com"}})
            get_ai_api_key = staticmethod(lambda _: "synthetic-settings-key")
        with patch.dict(os.environ, {"INTERVIEW_API_KEY": "synthetic-env-key", "STEP_API_KEY": "synthetic-step-key",
                                     "INTERVIEW_MODEL": "env-model"}), \
                patch.object(wb.career_user_runtime.offerpilot_runtime if hasattr(wb.career_user_runtime, "offerpilot_runtime") else __import__("offerpilot_runtime"), "load_backend", return_value=Server):
            settings = ModelSettings(self.root)
            settings.applied()
        config = settings.model_config()
        self.assertEqual((config["api_key"], config["model"], config["base_url"]),
                         ("synthetic-settings-key", "deepseek-flash", "https://api.deepseek.com"))
        env = settings.configured_environment("synthetic-settings-key")
        self.assertNotIn("env-model", env.values())
        self.assertNotIn("synthetic-env-key", env.values())
        self.assertNotIn("synthetic", json.dumps(settings.status()))

    def test_workbench_settings_route_no_longer_accepts_a_second_key_entry(self):
        with self.assertRaises(backend.ApiError) as error:
            wb.dispatch("POST", "/api/workbench/settings", {"mode": "user"}, {"api_key": "synthetic-key-0123456789"})
        self.assertEqual(error.exception.status, 400)

    def test_http_routes_mode_validation_and_static_assets(self):
        local_server = server.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=local_server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (local_server.shutdown(), local_server.server_close(), thread.join()))
        connection = http.client.HTTPConnection("127.0.0.1", local_server.server_port)
        self.addCleanup(connection.close)
        for path in ("/workbench-agent.js", "/workbench-agent.css", "/career-user.js", "/career-resume.css"):
            connection.request("GET", path);response = connection.getresponse();response.read();self.assertEqual(response.status, 200)
        connection.request("GET", "/api/workbench/overview?mode=other")
        response = connection.getresponse();response.read();self.assertEqual(response.status, 400)
        connection.request("POST", "/api/workbench/settings?mode=demo", json.dumps({"api_key": "synthetic-secret"}), {"Content-Type": "application/json"})
        response = connection.getresponse();raw=response.read();self.assertEqual(response.status, 400);self.assertNotIn(b"synthetic-secret", raw)


if __name__ == "__main__":
    unittest.main()
