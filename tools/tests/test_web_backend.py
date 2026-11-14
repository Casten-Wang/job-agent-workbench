#!/usr/bin/env python3
"""Offline tests for the local web workbench (backend + HTTP layer).

Every test uses the isolated demo dataset or an ephemeral loopback port.  No
test reads or writes ``web/data/user``, installs a package, or performs a
network request.  Product code is exercised as-is; failures are reported rather
than worked around.
"""

from __future__ import annotations

import base64
import datetime as dt
import http.client
import json
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"
SMOKE_PDF = PROJECT_ROOT / "_verify" / "smoke.pdf"

for _path in (str(WEB_DIR), str(TOOLS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402  (local module in web/)
import server  # noqa: E402  (local module in web/)

EXPECTED_SNAPSHOT_KEYS = {
    "mode",
    "generated_at",
    "filter",
    "states",
    "transitions",
    "scope",
    "kpis",
    "state_counts",
    "channels",
    "channel_rows",
    "quarterly_radar",
    "weakness_rows",
    "mail_rows",
    "jobs",
    "queue",
    "mails",
    "debriefs",
    "events",
    "variants",
    "question_bank",
    "activity",
    "downloads",
    "pipeline",
    "profile",
    "config",
    "cv_skills",
    "boundaries",
}

CREDENTIAL_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "credential",
    "access_key",
    "private_key",
)


def _iter_dict_keys(value: object):
    """Yield every dictionary key recursively (values are not interpreted)."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_dict_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_dict_keys(item)


class DemoDataTestCase(unittest.TestCase):
    """Reset the demo workspace before and after each test that mutates it."""

    def setUp(self) -> None:
        backend.reset_demo()

    def tearDown(self) -> None:
        backend.reset_demo()


class DemoSeedTests(DemoDataTestCase):
    def test_reset_demo_seeds_a_readable_snapshot(self):
        snapshot = backend.snapshot("demo")
        self.assertEqual(snapshot["mode"], "demo")
        self.assertGreater(len(snapshot["jobs"]), 0)
        self.assertGreater(len(snapshot["mails"]), 0)
        self.assertGreater(len(snapshot["debriefs"]), 0)
        self.assertGreater(len(backend.get_store("demo").events()), 0)

    def test_every_demo_job_has_a_numeric_score(self):
        snapshot = backend.snapshot("demo")
        self.assertGreater(len(snapshot["jobs"]), 0)
        for job in snapshot["jobs"]:
            with self.subTest(job=job["id"]):
                score = job["score"]
                self.assertIsInstance(score, (int, float))
                self.assertNotIsInstance(score, bool)
                self.assertEqual(score, score)  # reject NaN
                self.assertNotIn(score, (float("inf"), float("-inf")))

    def test_state_counts_sum_matches_job_count(self):
        snapshot = backend.snapshot("demo")
        self.assertEqual(sum(snapshot["state_counts"].values()), len(snapshot["jobs"]))
        self.assertEqual(set(snapshot["state_counts"]), set(snapshot["states"]))
        self.assertTrue(all(isinstance(value, int) for value in snapshot["state_counts"].values()))

    def test_queue_pending_count_is_reported_correctly(self):
        snapshot = backend.snapshot("demo")
        pending_rows = [row for row in snapshot["queue"] if row.get("status") == "pending"]
        self.assertEqual(snapshot["kpis"]["pending"], len(pending_rows))
        self.assertEqual(len(pending_rows), 2)
        for row in snapshot["queue"]:
            with self.subTest(job=row.get("id")):
                self.assertIsInstance(row.get("score"), (int, float))
                self.assertNotIsInstance(row.get("score"), bool)

    def test_demo_mails_and_debriefs_are_non_empty(self):
        snapshot = backend.snapshot("demo")
        self.assertGreaterEqual(len(snapshot["mails"]), 1)
        self.assertGreaterEqual(len(snapshot["debriefs"]), 1)
        self.assertEqual(snapshot["scope"]["mails"], len(snapshot["mails"]))
        self.assertEqual(snapshot["scope"]["debriefs"], len(snapshot["debriefs"]))

    def test_demo_events_are_all_legal_transitions(self):
        events = backend.get_store("demo").events()
        transitions = backend.state_machine.load_config()["transitions"]
        self.assertGreater(len(events), 0)
        for index, event in enumerate(events):
            with self.subTest(index=index, pair=(event.get("from"), event.get("to"))):
                allowed = transitions.get(str(event.get("from")), [])
                self.assertIn(
                    str(event.get("to")),
                    allowed,
                    f"演示事件 #{index} 是非法跃迁 {event.get('from')} → {event.get('to')}；"
                    "见 web/backend.py 的 _demo_events()",
                )
        # Explicit regression check: 简历已定制 must never jump straight to 一面.
        pairs = [(str(event.get("from")), str(event.get("to"))) for event in events]
        self.assertNotIn(
            ("简历已定制", "一面"),
            pairs,
            "演示数据出现非法跃迁「简历已定制 → 一面」；见 web/backend.py 的 _demo_events()",
        )

    def test_snapshot_has_27_typed_top_level_keys(self):
        snapshot = backend.snapshot("demo")
        self.assertEqual(len(snapshot), 27)
        self.assertEqual(set(snapshot), EXPECTED_SNAPSHOT_KEYS)
        for key in ("kpis", "scope", "state_counts", "quarterly_radar", "boundaries", "pipeline"):
            with self.subTest(key=key):
                self.assertIsInstance(snapshot[key], dict)
        for key in ("channel_rows", "weakness_rows", "mail_rows"):
            with self.subTest(key=key):
                self.assertIsInstance(snapshot[key], list)
        self.assertIs(snapshot["boundaries"]["auto_submit"], False)
        self.assertEqual(snapshot["boundaries"]["external_api"], "embedded_offerpilot_only")
        self.assertEqual(snapshot["boundaries"]["platform_scraping"], "embedded_offerpilot_only")

    def test_pipeline_snapshot_has_six_ordered_stages(self):
        pipeline = backend.snapshot("demo")["pipeline"]
        self.assertEqual(
            [stage["title"] for stage in pipeline["stages"]],
            ["岗位采集", "AI 评分与筛选", "人工确认", "生成招呼语", "发送", "监控 HR 回复"],
        )
        self.assertEqual([stage["key"] for stage in pipeline["stages"]], [
            "intake", "screening", "approval", "greeting", "send", "monitor",
        ])
        for stage in pipeline["stages"]:
            with self.subTest(stage=stage["key"]):
                self.assertIsInstance(stage["count"], int)
                self.assertIn(stage["status"], {"ready", "local", "connected", "waiting"})
        self.assertIs(pipeline["external_connected"], False)
        self.assertEqual(
            {feature["key"] for feature in pipeline["reserved_features"]},
            {"mock_interview", "push", "resume"},
        )

    def test_offerpilot_state_is_redacted_and_unavailable_is_safe(self):
        safe_state = {
            "ok": True,
            "embedded": True,
            "base_url": "embedded://offerpilot",
            "api_version": "v1",
            "preferences": {"cities": ["上海"], "score_threshold": 60},
            "ai": {"configured": True},
            "capabilities": {"monitor_without_ai": True},
            "task": {"id": "task-1", "mode": "monitor", "status": "running"},
            "last_task": None,
        }
        with patch.object(backend.offerpilot_runtime, "get_state", return_value=safe_state):
            state = backend.get_offerpilot_state("user")
        self.assertTrue(state["ok"])
        self.assertEqual(state["preferences"], {"cities": ["上海"], "score_threshold": 60})
        self.assertNotIn("api_key", json.dumps(state))
        self.assertNotIn("logs", json.dumps(state))

        with patch.object(backend.offerpilot_runtime, "get_state", return_value={"ok": False, "embedded": True, "error": "offline"}):
            state = backend.get_offerpilot_state("user")
        self.assertFalse(state["ok"])
        self.assertEqual(state["error"], "offline")

    def test_offerpilot_runtime_drops_task_logs_and_credentials(self):
        task = backend.offerpilot_runtime._safe_task({
            "id": "task-1",
            "mode": "collect",
            "status": "running",
            "logs": ["secret"],
            "error": "x",
            "metrics": {"collect_new": 2, "bad": "x"},
        })
        self.assertEqual(task["id"], "task-1")
        self.assertNotIn("logs", task)
        self.assertEqual(task["metrics"], {"collect_new": 2})
        preferences = backend.offerpilot_runtime._safe_preferences({
            "cities": ["上海"],
            "api_key": "never",
            "private_extra": "never",
        })
        self.assertEqual(preferences, {"cities": ["上海"]})

    def test_demo_offerpilot_state_is_fictional_and_read_only(self):
        state = backend.get_offerpilot_state("demo")
        self.assertTrue(state["ok"])
        self.assertEqual(state["mode"], "demo")
        self.assertFalse(state["capabilities"]["start_full_flow"])
        jobs = backend.get_offerpilot_jobs("demo")
        self.assertTrue(jobs["read_only"])
        self.assertEqual(jobs["source"], "demo")
        self.assertEqual(jobs["count"], len(backend.get_store("demo").jobs()))

    def test_offerpilot_task_requires_explicit_confirmation(self):
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_task({"mode": "full", "confirm": False, "risk_acknowledged": True})
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_task({"mode": "deliver", "confirm": True, "risk_acknowledged": True})
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_task({"mode": "full", "confirm": True})
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_task({
                "mode": "collect", "data_mode": "demo", "confirm": True, "risk_acknowledged": True,
            })

    def test_offerpilot_task_and_stop_use_embedded_runtime(self):
        with patch.object(
            backend.offerpilot_runtime,
            "start_task",
            return_value={"task": {"id": "task-1", "mode": "collect", "status": "running"}, "checks": [], "policy": {}},
        ) as start, patch.object(
            backend.offerpilot_runtime,
            "stop_task",
            return_value={"id": "task-1", "status": "stopping"},
        ) as stop:
            started = backend.start_offerpilot_task({
                "mode": "collect", "data_mode": "user", "confirm": True, "risk_acknowledged": True,
            })
            stopped = backend.stop_offerpilot_task("task-1", "user")
        self.assertTrue(started["ok"])
        self.assertTrue(stopped["ok"])
        start.assert_called_once_with("collect")
        stop.assert_called_once_with("task-1")

    def test_offerpilot_task_passes_validated_search_options(self):
        with patch.object(
            backend.offerpilot_runtime,
            "start_task",
            return_value={"task": {"id": "task-1", "mode": "collect", "status": "running"}, "checks": [], "policy": {}},
        ) as start:
            started = backend.start_offerpilot_task({
                "mode": "collect",
                "data_mode": "user",
                "confirm": True,
                "risk_acknowledged": True,
                "options": {
                    "platform": "boss",
                    "keywords": ["产品经理", "AI产品经理"],
                    "cities": ["北京"],
                    "max_pages": 2,
                    "auto_score": False,
                },
            })
        self.assertTrue(started["ok"])
        start.assert_called_once_with("collect", {
            "platform_order": ["boss"],
            "platforms": {"boss": {"keywords": ["产品经理", "AI产品经理"], "cities": ["北京"], "max_pages": 2}},
            "auto_score": False,
            "pace": "cautious",
        })

    def test_offerpilot_task_rejects_invalid_search_options(self):
        base = {"mode": "collect", "data_mode": "user", "confirm": True, "risk_acknowledged": True}
        for options in (
            {"platform": "zhilian", "keywords": ["产品经理"], "cities": ["北京"]},
            {"platform": "boss", "keywords": [], "cities": ["北京"]},
            {"platform": "boss", "keywords": ["产品经理"], "cities": []},
            {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "max_pages": 0},
            {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "max_pages": 11},
            {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "unexpected": True},
            {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "auto_score": "yes"},
            {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "pace": "turbo"},
        ):
            with self.subTest(options=options):
                with self.assertRaises(backend.ApiError):
                    backend.start_offerpilot_task({**base, "options": options})
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_task({
                "mode": "monitor",
                "data_mode": "user",
                "confirm": True,
                "risk_acknowledged": True,
                "options": {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"]},
            })

    def test_offerpilot_preflight_checks_without_starting(self):
        with patch.object(
            backend.offerpilot_runtime,
            "preflight",
            return_value={"ok": True, "checks": [{"id": "browser_runtime", "status": "pass"}], "messages": [], "summary": {"mode": "collect"}},
        ) as preflight:
            result = backend.preflight_offerpilot_task({
                "mode": "collect",
                "data_mode": "user",
                "options": {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "max_pages": 1},
            })
        self.assertTrue(result["ok"])
        preflight.assert_called_once_with("collect", {
            "platform_order": ["boss"],
            "platforms": {"boss": {"keywords": ["产品经理"], "cities": ["北京"], "max_pages": 1}},
            "auto_score": False,
            "pace": "cautious",
        })

    def test_offerpilot_preflight_reports_a_running_task_as_browser_busy(self):
        runtime = backend.offerpilot_runtime
        busy = runtime._busy_preflight(
            {"mode": "collect"},
            {"id": "task-1", "mode": "collect", "label": "单独采集"},
        )
        self.assertFalse(busy["ok"])
        self.assertEqual(busy["checks"][0]["id"], "browser_busy")
        self.assertIn("单独采集", busy["checks"][0]["message"])
        self.assertIn("停止任务", busy["checks"][0]["detail"])

        class Runner:
            def __init__(self, value):
                self.value = value

            def status(self):
                if isinstance(self.value, Exception):
                    raise self.value
                return self.value

        class Server:
            def __init__(self, value):
                self.task_runner = Runner(value)

        self.assertEqual(runtime._active_task(Server({"active": {"id": "task-1"}}))["id"], "task-1")
        self.assertIsNone(runtime._active_task(Server({"active": None})))
        self.assertIsNone(runtime._active_task(Server(RuntimeError("boom"))))

    def test_offerpilot_import_copies_scores_and_skips_duplicates(self):
        store = backend.get_store("demo")
        result = backend._import_offerpilot_records(store, [
            {
                "id": "op-test-1",
                "title": "AI 产品经理",
                "company": "虚构采集公司",
                "city": "北京",
                "salary": "20-30k",
                "score": 80,
                "created_at": "2026-11-14T10:00:00+08:00",
            },
            {
                "id": "op-test-2",
                "title": "产品助理",
                "company": "虚构未评分公司",
                "city": "北京",
                "salary": "10-15k",
                "score": 0,
            },
        ], ["op-test-1", "op-test-2"])
        self.assertEqual(len(result["added"]), 2)
        self.assertEqual(result["unscored"], 1)
        jobs = {job.get("offerpilot_id"): job for job in store.jobs()}
        self.assertEqual(jobs["op-test-1"]["score"], 4.5)
        self.assertEqual(jobs["op-test-1"]["score_raw"], 80)
        self.assertEqual(jobs["op-test-1"]["source_channel"], "boss")
        self.assertIsNone(jobs["op-test-2"]["score"])

        duplicate = backend._import_offerpilot_records(store, [
            {"id": "op-test-1", "title": "AI 产品经理", "company": "虚构采集公司", "city": "北京", "score": 80},
        ], ["op-test-1"])
        self.assertEqual(duplicate["added"], [])
        self.assertEqual(duplicate["duplicates"], 1)

    def test_offerpilot_import_rejects_demo_and_unknown_ids(self):
        with self.assertRaises(backend.ApiError):
            backend.import_offerpilot_jobs({"data_mode": "demo", "ids": ["op-test-1"]})
        with self.assertRaises(backend.ApiError):
            backend.import_offerpilot_jobs({"data_mode": "user", "ids": []})
        with self.assertRaises(backend.ApiError):
            backend.import_offerpilot_jobs({"data_mode": "user", "ids": ["../bad id"]})

    def test_offerpilot_import_accepts_platform_ids_and_skips_missing(self):
        runtime_jobs = [{
            "id": "abc:def/中文?x=1",
            "title": "产品经理",
            "company": "虚构公司",
            "city": "上海",
            "score": 80,
        }]
        with patch.object(
            backend.offerpilot_runtime,
            "get_jobs",
            return_value={"ok": True, "jobs": runtime_jobs},
        ), patch.object(
            backend,
            "get_store",
            return_value=object(),
        ), patch.object(
            backend,
            "_rescale_imported_jobs",
            return_value=0,
        ), patch.object(
            backend,
            "_import_offerpilot_records",
            return_value={"ok": True, "added": [], "duplicates": 0, "unscored": 0, "message": "已导入 0 条"},
        ) as import_records:
            result = backend.import_offerpilot_jobs({
                "data_mode": "user",
                "ids": ["abc:def/中文?x=1", "missing-id"],
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], 1)
        selected = import_records.call_args.args[2]
        self.assertEqual(selected, ["abc:def/中文?x=1"])

    def test_offerpilot_resume_upload_validates_and_saves(self):
        with self.assertRaises(backend.ApiError):
            backend.upload_offerpilot_resume({
                "mode": "demo", "filename": "cv.md", "content_base64": "aGk=",
            })
        with self.assertRaises(backend.ApiError):
            backend.upload_offerpilot_resume({"mode": "user", "content_base64": "aGk="})
        with self.assertRaises(backend.ApiError):
            backend.upload_offerpilot_resume({
                "mode": "user", "filename": "cv.md", "content_base64": "not base64!",
            })

        class _Store:
            def __init__(self):
                self.logs = []

            def log(self, *args):
                self.logs.append(args)

        store = _Store()
        with patch.object(
            backend.offerpilot_runtime,
            "save_resume",
            return_value={"filename": "cv.md", "available": True, "size_label": "1 KB"},
        ) as save, patch.object(backend, "get_store", return_value=store):
            result = backend.upload_offerpilot_resume({
                "mode": "user",
                "filename": "cv.md",
                "content_base64": base64.b64encode("测试简历".encode("utf-8")).decode("ascii"),
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["resume"]["filename"], "cv.md")
        self.assertIn("自动评分", result["message"])
        save.assert_called_once()
        self.assertEqual(len(store.logs), 1)

    def test_embedded_runtime_dependency_error_is_reported_not_raised(self):
        with patch.object(
            backend.offerpilot_runtime,
            "get_state",
            return_value={"ok": False, "embedded": True, "error": "deps missing"},
        ):
            state = backend.get_offerpilot_state("user")
        self.assertFalse(state["ok"])
        self.assertEqual(state["error"], "deps missing")

    def test_pipeline_contract_keeps_send_and_monitor_external(self):
        contract = backend.pipeline_contract()
        owners = {stage["key"]: stage["owner"] for stage in contract["stages"]}
        self.assertEqual(owners["send"], "external")
        self.assertEqual(owners["monitor"], "hybrid")
        self.assertEqual(contract["event_endpoint"], "POST /api/pipeline/event")
        self.assertIs(contract["guarantees"]["auto_submit"], False)
        self.assertIs(contract["guarantees"]["auto_send"], False)
        self.assertIs(contract["guarantees"]["event_is_record_only"], True)

    def test_pipeline_event_is_recorded_without_sending(self):
        result = backend.ingest_pipeline_event({
            "mode": "demo",
            "stage": "send",
            "status": "succeeded",
            "job_id": "demo-job-001",
            "message": "外部 Agent 测试回报",
        })
        self.assertTrue(result["ok"])
        self.assertIs(result["event"]["auto_submit"], False)
        self.assertEqual(result["event"]["actor"], "external_agent")
        events = backend.get_store("demo").pipeline_events()
        self.assertEqual(len(events), 1)
        pipeline = backend.snapshot("demo")["pipeline"]
        self.assertTrue(pipeline["external_connected"])
        self.assertEqual(pipeline["stages"][4]["status"], "connected")
        self.assertEqual(pipeline["stages"][4]["count"], 1)

    def test_demo_profile_is_fictional_and_ready(self):
        profile = backend.snapshot("demo")["profile"]
        self.assertTrue(profile["has_content"])
        self.assertEqual(profile["basic"]["email"], "demo@example.invalid")
        self.assertEqual(profile["completeness"]["level"], "ready")
        self.assertNotIn("{{", json.dumps(profile, ensure_ascii=False))
        self.assertIn("Axure", profile["skills"]["tools"])

    def test_save_profile_normalizes_persists_and_feeds_screening(self):
        try:
            result = backend.save_profile({
                "mode": "demo",
                "profile": {
                    "basic": {"name": "测试用户", "email": "test@example.com", "city": "上海", "unknown": "drop"},
                    "job_intent": {"titles": ["产品经理"], "cities": ["上海"]},
                    "skills": {"tools": ["Axure"], "strengths": ["需求分析"]},
                    "summary": "这是一段用于测试的个人简介，只包含可核实事实。",
                    "truth_confirmed": True,
                    "unknown": "drop",
                },
            })
            self.assertTrue(result["ok"])
            self.assertNotIn("unknown", result["profile"])
            self.assertNotIn("unknown", result["profile"]["basic"])
            self.assertEqual(result["profile"]["basic"]["name"], "测试用户")
            snapshot = backend.snapshot("demo")
            self.assertEqual(snapshot["profile"]["basic"]["name"], "测试用户")
            self.assertIn("Axure", snapshot["cv_skills"])
            self.assertEqual(snapshot["config"]["target_cities"], ["上海"])
        finally:
            backend.reset_demo()

    def test_prepare_prefers_profile_facts_for_greeting(self):
        try:
            backend.save_profile({
                "mode": "demo",
                "profile": {
                    "basic": {"name": "测试用户", "email": "test@example.com", "city": "上海"},
                    "job_intent": {"titles": ["产品经理"], "cities": ["上海"]},
                    "skills": {"tools": ["Axure"], "strengths": ["需求分析"]},
                    "summary": "这是一段用于测试的个人简介，只包含可核实事实。",
                    "truth_confirmed": True,
                },
            })
            result = backend.prepare({"mode": "demo", "id": "demo-job-001"})
            greeting = result["report"]["greeting"]
            self.assertIn("个人资料", greeting["source"])
            self.assertIn("需求分析", greeting["greeting"])
            self.assertIn("profile", result["report"])
        finally:
            backend.reset_demo()

    def test_pipeline_snapshot_exposes_safe_offerpilot_control_state(self):
        state = {
            "ok": True,
            "base_url": "http://127.0.0.1:8686",
            "api_version": "v1",
            "preferences": {"cities": ["上海"], "score_threshold": 4.0},
            "ai": {"configured": True},
            "capabilities": {"monitor_without_ai": True, "human_confirmation_before_delivery": True},
            "task": {"id": "task-1", "mode": "monitor", "status": "running", "stop_requested": False},
            "last_task": {"id": "task-0", "mode": "collect", "status": "completed"},
        }
        store = backend.get_store("demo")
        pipeline = backend.pipeline_status(store, store.jobs(), store.queue(), store.mails(), state)
        boss = pipeline["offerpilot"]
        self.assertTrue(boss["connected"])
        self.assertEqual(boss["task"]["id"], "task-1")
        self.assertEqual(boss["last_task"]["id"], "task-0")
        self.assertIs(boss["capabilities"]["monitor_without_ai"], True)
        self.assertNotIn("logs", json.dumps(boss))
        self.assertEqual(pipeline["stages"][5]["status"], "active")

    def test_pipeline_event_rejects_local_stages_and_unknown_status(self):
        with self.assertRaises(backend.ApiError):
            backend.ingest_pipeline_event({"mode": "demo", "stage": "approval", "status": "succeeded"})
        with self.assertRaises(backend.ApiError):
            backend.ingest_pipeline_event({"mode": "demo", "stage": "send", "status": "delivered"})


class DateFilterTests(unittest.TestCase):
    @staticmethod
    def _fixtures():
        today = dt.date.today()
        old = today - dt.timedelta(days=8)
        jobs = [
            {"id": "today", "date": today.isoformat(), "source_channel": "test"},
            {"id": "old", "date": old.isoformat(), "source_channel": "test"},
            {"id": "unknown", "date": "unknown", "source_channel": "test"},
            {"id": "empty", "date": "", "source_channel": "test"},
        ]
        mails = [
            {"id": "mail-today", "mail": {"date": today.isoformat()}},
            {"id": "mail-unknown", "mail": {"date": "unknown"}},
        ]
        debriefs = [
            {"id": "debrief-today", "created_at": today.isoformat()},
            {"id": "debrief-unknown", "created_at": "unknown"},
        ]
        return today, old, jobs, mails, debriefs

    def test_period_all_keeps_unknown_dates(self):
        _, _, jobs, mails, debriefs = self._fixtures()
        result = backend._filter_payload(jobs, mails, debriefs, [], {"period": "all"})
        job_ids = {job["id"] for job in result["jobs"]}
        self.assertEqual(job_ids, {"today", "old", "unknown", "empty"})
        self.assertIn("unknown", job_ids)
        self.assertIn("empty", job_ids)
        self.assertEqual({mail["id"] for mail in result["mails"]}, {"mail-today", "mail-unknown"})
        self.assertEqual(
            {card["id"] for card in result["debriefs"]}, {"debrief-today", "debrief-unknown"}
        )
        self.assertIsNone(result["start"])

    def test_period_7d_excludes_unknown_and_old_but_keeps_today(self):
        today, old, jobs, mails, debriefs = self._fixtures()
        result = backend._filter_payload(jobs, mails, debriefs, [], {"period": "7d"})
        job_ids = {job["id"] for job in result["jobs"]}
        self.assertIn("today", job_ids)
        self.assertNotIn("old", job_ids, "8 天前的岗位不应进入 7d 结果")
        self.assertNotIn("unknown", job_ids, "未知日期不应进入 7d 结果")
        self.assertNotIn("empty", job_ids, "空日期不应进入 7d 结果")
        self.assertEqual({mail["id"] for mail in result["mails"]}, {"mail-today"})
        self.assertEqual({card["id"] for card in result["debriefs"]}, {"debrief-today"})
        self.assertEqual(result["start"], (today - dt.timedelta(days=7)).isoformat())


class ApprovalGateTests(DemoDataTestCase):
    def test_enqueue_only_accepts_jobs_with_a_numeric_score(self):
        # demo-job-003 has a numeric score (3.5) but is below the 4.0 gate.
        low = backend.enqueue({"mode": "demo", "ids": ["demo-job-003"]})
        self.assertIn("demo-job-003", low["dropped"])
        self.assertEqual(low["accepted"], [])

        # An explicit manual override queues the same job without changing the
        # shared 4.0 gate for normal enqueue calls.
        manual = backend.enqueue({
            "mode": "demo",
            "ids": ["demo-job-003"],
            "allow_low_score": True,
        })
        self.assertIn("demo-job-003", manual["manual"])
        self.assertNotIn("demo-job-003", manual["dropped"], "手动入队的岗位不应再算作未入队")
        queue = backend.approval_queue.load_queue(backend.get_store("demo").files["queue"])
        row = next(item for item in queue if item["id"] == "demo-job-003")
        self.assertTrue(row["manual_override"])
        self.assertEqual(row["status"], "pending")

        # A job parsed without a score must be filtered out before the queue.
        text = (
            "测试数据：无评分岗位\n"
            "公司：虚构无评分有限公司\n"
            "岗位：产品助理\n"
            "城市：上海\n"
            "来源渠道：manual_paste\n"
            "发布时间：2026-11-14\n"
            "记录类型：JD\n"
            "职位描述：测试数据，仅用于验证评分门。\n"
        )
        parsed = backend.parse_jd({"mode": "demo", "text": text, "id": "scoreless-demo-job"})
        self.assertTrue(parsed["ok"])
        self.assertIsNone(parsed["job"]["score"])
        scoreless = backend.enqueue({"mode": "demo", "ids": [parsed["job"]["id"]]})
        self.assertEqual(scoreless["accepted"], [])

        queue = backend.get_store("demo").queue()
        self.assertFalse(any(str(row.get("id")) == parsed["job"]["id"] for row in queue))
        for row in queue:
            with self.subTest(job=row.get("id")):
                self.assertIsInstance(row.get("score"), (int, float))
                self.assertNotIsInstance(row.get("score"), bool)

    def test_confirm_requires_the_exact_confirmation_phrase(self):
        for token in ("", "确认", "确认可人工投递 ", "确认可人工投递\n", "可以投递"):
            with self.subTest(token=token):
                with self.assertRaises(backend.ApiError):
                    backend.confirm_queue(
                        {"mode": "demo", "ids": ["demo-job-001"], "confirm": token}
                    )
        rows = backend.get_store("demo").queue()
        self.assertTrue(all(row.get("status") == "pending" for row in rows))

    def test_confirm_marks_manual_submission_only(self):
        result = backend.confirm_queue(
            {"mode": "demo", "ids": ["demo-job-001"], "confirm": "确认可人工投递"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed"], ["demo-job-001"])
        self.assertIs(result["auto_submit"], False)
        self.assertEqual(result["status"], "ready_for_manual_submission_only")
        self.assertIn("仍需本人", result["message"])
        rows = {str(row.get("id")): row for row in backend.get_store("demo").queue()}
        self.assertEqual(rows["demo-job-001"]["status"], "approved")
        self.assertEqual(rows["demo-job-002"]["status"], "pending")


class StateMachineTests(DemoDataTestCase):
    def test_legal_transition_succeeds_and_appends_one_event(self):
        before = len(backend.get_store("demo").events())
        result = backend.transition(
            {"mode": "demo", "id": "demo-job-002", "from": "已过滤", "to": "简历已定制"}
        )
        self.assertTrue(result["ok"])
        events = backend.get_store("demo").events()
        self.assertEqual(len(events), before + 1)
        self.assertEqual(events[-1]["job_id"], "demo-job-002")
        self.assertEqual((events[-1]["from"], events[-1]["to"]), ("已过滤", "简历已定制"))

    def test_illegal_transition_raises_api_error_without_writing(self):
        before = len(backend.get_store("demo").events())
        with self.assertRaises(backend.ApiError) as context:
            backend.transition(
                {"mode": "demo", "id": "demo-job-001", "from": "简历已定制", "to": "一面"}
            )
        self.assertIn("illegal-transition", str(context.exception))
        self.assertEqual(len(backend.get_store("demo").events()), before)


class DedupeTests(DemoDataTestCase):
    def test_parse_jd_twice_reports_duplicate(self):
        text = (
            "测试数据：去重岗位\n"
            "公司：虚构去重有限公司\n"
            "岗位：产品经理\n"
            "城市：上海\n"
            "来源渠道：manual_paste\n"
            "发布时间：2026-11-14\n"
            "记录类型：JD\n"
            "职位描述：测试数据，用于重复检测。\n"
        )
        before = len(backend.get_store("demo").jobs())
        first = backend.parse_jd({"mode": "demo", "text": text, "id": "dedupe-jd"})
        second = backend.parse_jd({"mode": "demo", "text": text, "id": "dedupe-jd"})
        self.assertTrue(first["ok"])
        self.assertFalse(first.get("duplicate", False))
        self.assertFalse(second["ok"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(backend.get_store("demo").jobs()), before + 1)

    def test_parse_mail_twice_reports_duplicate_message_id(self):
        mail = {
            "mode": "demo",
            "from": "hr@test.invalid",
            "subject": "测试数据：面试邀请",
            "body": "公司：虚构甲公司\n岗位：产品经理\n请于2026年11月20日14:30参加一面。",
            "date": "2026-11-14",
            "message_id": "<dedupe-web@test.invalid>",
        }
        before = len(backend.get_store("demo").mails())
        first = backend.parse_mail(dict(mail))
        second = backend.parse_mail(dict(mail))
        self.assertTrue(first["ok"])
        self.assertFalse(first.get("duplicate", False))
        self.assertFalse(second["ok"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(backend.get_store("demo").mails()), before + 1)


class ChannelNormalizationTests(DemoDataTestCase):
    def test_chinese_channel_alias_is_canonicalized(self):
        text = (
            "测试数据：渠道归一化\n"
            "公司：虚构渠道测试有限公司\n"
            "岗位：数据分析师\n"
            "城市：上海\n"
            "来源渠道：手动粘贴\n"
            "发布时间：2026-11-14\n"
            "记录类型：JD\n"
            "职位描述：测试数据，用于渠道归一化。\n"
        )
        result = backend.parse_jd({"mode": "demo", "text": text, "id": "channel-alias"})
        self.assertTrue(result["ok"])
        job = next(
            row for row in backend.get_store("demo").jobs()
            if row.get("company") == "虚构渠道测试有限公司"
        )
        self.assertEqual(job["source_channel"], "manual_paste")
        self.assertNotIn("手动粘贴", backend.snapshot("demo")["channels"])


class PdfCheckTests(DemoDataTestCase):
    @unittest.skipUnless(SMOKE_PDF.is_file(), f"缺少 {SMOKE_PDF}")
    def test_smoke_pdf_returns_a_conservative_result(self):
        encoded = base64.b64encode(SMOKE_PDF.read_bytes()).decode("ascii")
        response = backend.check_pdf(
            {
                "mode": "demo",
                "content_base64": encoded,
                "keywords": "产品",
                "filename": "smoke.pdf",
            }
        )
        self.assertTrue(response["ok"])
        result = response["result"]
        self.assertIn(result["verdict"], {"pass", "fail", "needs_manual_check"})
        self.assertIn(result["text_layer"], {"available", "unavailable"})
        self.assertTrue(result["pdf_magic"])
        if result["text_layer"] == "unavailable":
            self.assertEqual(result["verdict"], "needs_manual_check")
            self.assertIsNone(result["all_keywords_found"])

    def test_unparseable_text_layer_never_reports_pass(self):
        raw = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
            b"2 0 obj\n<< /Type /Pages /Count 0 >>\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
        )
        response = backend.check_pdf(
            {
                "mode": "demo",
                "content_base64": base64.b64encode(raw).decode("ascii"),
                "keywords": "产品",
                "filename": "no-text-layer.pdf",
            }
        )
        result = response["result"]
        self.assertEqual(result["text_layer"], "unavailable")
        self.assertEqual(result["verdict"], "needs_manual_check")
        self.assertIsNone(result["all_keywords_found"])
        self.assertTrue(all(value is None for value in result["keyword_matches"].values()))

    def test_non_pdf_payload_is_rejected(self):
        with self.assertRaises(backend.ApiError):
            backend.check_pdf(
                {
                    "mode": "demo",
                    "content_base64": base64.b64encode(b"not a pdf").decode("ascii"),
                    "keywords": "",
                }
            )


class HttpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        backend.reset_demo()
        cls.server = server.make_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            raise RuntimeError("临时 HTTP 服务未能在 5 秒内启动")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        backend.reset_demo()

    def request(self, method: str, path: str, payload: dict | None = None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            headers = {}
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_health_endpoint(self):
        status, _, raw = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertIs(data["auto_submit"], False)
        self.assertIn(data["offline"], (True, False))
        self.assertEqual(data["external_api"], "embedded_offerpilot_only")

    def test_state_endpoint_returns_demo_snapshot_without_credentials(self):
        status, headers, raw = self.request("GET", "/api/state?mode=demo")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data["mode"], "demo")
        self.assertEqual(len(data), 27)
        for key in _iter_dict_keys(data):
            lowered = key.casefold()
            for part in CREDENTIAL_KEY_PARTS:
                self.assertNotIn(part, lowered, f"/api/state 暴露疑似凭据字段：{key}")

    def test_offerpilot_routes_are_controlled(self):
        state = {"ok": True, "api_version": "v1", "preferences": {"cities": ["上海"]}}
        with patch.object(backend, "get_offerpilot_state", return_value=state), patch.object(
            backend, "get_offerpilot_jobs", return_value={"ok": True, "source": "offerpilot", "read_only": True, "jobs": [], "count": 0, "limit": 100}
        ):
            status, _, raw = self.request("GET", "/api/offerpilot/state")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["state"], state)
            status, _, raw = self.request("GET", "/api/offerpilot/jobs")
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["read_only"])

        with patch.object(backend, "start_offerpilot_task", return_value={"ok": True, "task": {}}) as start:
            status, _, raw = self.request("POST", "/api/offerpilot/tasks", {
                "mode": "collect", "confirm": True, "risk_acknowledged": True,
            })
            self.assertEqual(status, 202)
            self.assertTrue(json.loads(raw)["ok"])
            start.assert_called_once()

        with patch.object(
            backend,
            "preflight_offerpilot_task",
            return_value={"ok": True, "checks": [{"id": "browser_runtime", "status": "pass"}], "messages": []},
        ) as preflight:
            status, _, raw = self.request("POST", "/api/offerpilot/preflight", {
                "mode": "collect",
                "data_mode": "user",
                "options": {"platform": "boss", "keywords": ["产品经理"], "cities": ["北京"], "max_pages": 1},
            })
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)["ok"])
            preflight.assert_called_once()

        status, _, raw = self.request("POST", "/api/offerpilot/tasks", {"mode": "full", "confirm": True})
        self.assertEqual(status, 400)
        self.assertIn("risk_acknowledged", json.loads(raw)["error"])

    def test_pipeline_endpoint_returns_contract_and_status(self):
        status, headers, raw = self.request("GET", "/api/pipeline?mode=demo")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["contract"]["stages"]), 6)
        self.assertEqual(len(data["status"]["stages"]), 6)
        self.assertIs(data["contract"]["guarantees"]["auto_submit"], False)

    def test_pipeline_event_endpoint_records_only(self):
        try:
            status, _, raw = self.request("POST", "/api/pipeline/event", {
                "mode": "demo",
                "stage": "monitor",
                "status": "succeeded",
                "job_id": "demo-job-001",
                "message": "HTTP 测试回报",
            })
            self.assertEqual(status, 200)
            data = json.loads(raw.decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertIs(data["event"]["auto_submit"], False)
            snapshot = json.loads(self.request("GET", "/api/state?mode=demo")[2].decode("utf-8"))
            self.assertTrue(snapshot["pipeline"]["external_connected"])
            self.assertIn("HTTP 测试回报", [
                row.get("message") for row in snapshot["pipeline"]["external_events"]
            ])
        finally:
            backend.reset_demo()

    def test_pipeline_event_endpoint_rejects_local_stage(self):
        status, _, raw = self.request("POST", "/api/pipeline/event", {
            "mode": "demo",
            "stage": "approval",
            "status": "succeeded",
        })
        self.assertEqual(status, 400)
        self.assertFalse(json.loads(raw.decode("utf-8"))["ok"])

    def test_index_serves_frontend_that_loads_app_js_and_styles_css(self):
        status, _, raw = self.request("GET", "/")
        self.assertEqual(
            status,
            200,
            "GET / 返回 %s；web/static 缺少 index.html/app.js/styles.css，"
            "前端尚未构建（见 web/server.py 的静态文件分支）" % status,
        )
        html = raw.decode("utf-8", "replace")
        self.assertIn("app.js", html)
        self.assertIn("styles.css", html)
        self.assertIn("offer-theme.css", html)
        for label in ("工作台", "岗位池", "审批队列", "HR 回复", "个人资料", "模拟面试", "信息推送", "定制简历", "数据与设置"):
            with self.subTest(label=label):
                self.assertIn(label, html)
        for marker in (
            'id="pipeline"',
            'id="view-collect"',
            'id="collect-keywords"',
            'id="collect-cities"',
            'id="collect-pace"',
            'id="collect-auto-score"',
            'id="collect-resume-upload"',
            'id="collect-checks"',
            'class="panel jobs-manual-entry"',
            'id="jobs-select-all"',
            'id="jobs-bulk-enqueue"',
            'id="view-push"',
            'id="view-resume"',
            "/api/doc/pipeline-api",
            'id="offerpilot-form"',
            'id="offerpilot-risk"',
            'id="offerpilot-confirm"',
            'id="offerpilot-start"',
            'id="offerpilot-jobs-table"',
            'id="offerpilot-import"',
            'id="view-profile"',
            'id="profile-form"',
            'id="profile-import"',
            'id="profile-truth"',
            'id="profile-meter"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_frontend_wires_offerpilot_status_and_controlled_tasks(self):
        status, _, raw = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        script = raw.decode("utf-8", "replace")
        for marker in (
            "/api/offerpilot/state",
            "/api/offerpilot/jobs",
            "/api/offerpilot/preflight",
            "/api/offerpilot/tasks",
            "risk_acknowledged: true",
            "confirm: true",
            "syncOfferPilotStartState",
            "renderOfferPilot",
            "buildOfferPilotOptions",
            "runOfferPilotPreflight",
            "offerpilot-import",
            "maybeAutoImportCollected",
            "armManualEnqueue",
            "enqueueJobs",
            "uploadOfferPilotResume",
            "syncCollectResumeUI",
            "offerpilot-resume",
            "offerpilot.importedTasks",
            "filterBar.hidden = name !== 'workbench'",
            "collectProfileForm",
            "save-profile",
            "import-profile-cv",
            "renderProfileMeter",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_profile_endpoint_returns_structured_profile(self):
        status, headers, raw = self.request("GET", "/api/profile?mode=demo")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(raw.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["mode"], "demo")
        self.assertIn("completeness", data["profile"])
        self.assertIs(data["guarantees"]["auto_submit"], False)
        self.assertIs(data["guarantees"]["contact_fields_in_drafts"], False)

    def test_pipeline_api_document_is_downloadable(self):
        status, headers, raw = self.request("GET", "/api/doc/pipeline-api")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers.get("Content-Type", ""))
        self.assertIn("POST /api/pipeline/event".encode("utf-8"), raw)

    def test_profile_api_document_is_downloadable(self):
        status, headers, raw = self.request("GET", "/api/doc/profile-api")
        self.assertEqual(status, 200)
        self.assertIn("text/markdown", headers.get("Content-Type", ""))
        self.assertIn("GET /api/profile".encode("utf-8"), raw)
        self.assertIn("save-profile".encode("utf-8"), raw)

    def test_offer_theme_stylesheet_is_served_locally(self):
        status, headers, raw = self.request("GET", "/offer-theme.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertIn(b"--offer-pink", raw)

    def test_unknown_action_returns_404(self):
        status, _, raw = self.request(
            "POST", "/api/action", {"action": "definitely-not-a-real-action"}
        )
        self.assertEqual(status, 404)
        data = json.loads(raw.decode("utf-8"))
        self.assertFalse(data["ok"])

    def test_download_path_traversal_cannot_read_arbitrary_files(self):
        readme_marker = "求职 Agent（本地离线工具层）".encode("utf-8")
        for path in (
            "/api/download/demo/..%2F..%2F..%2FREADME.md",
            "/api/download/demo/%2e%2e%2f%2e%2e%2fREADME.md",
            "/api/download/../README.md",
            "/api/download/demo/..",
        ):
            with self.subTest(path=path):
                status, _, raw = self.request("GET", path)
                self.assertNotEqual(status, 200, f"{path} 不应成功返回文件")
                self.assertNotIn(readme_marker, raw, f"{path} 泄露了仓库文件内容")


class SecurityTests(DemoDataTestCase):
    def _assert_no_credential_keys(self, value: object) -> None:
        for key in _iter_dict_keys(value):
            lowered = key.casefold()
            for part in CREDENTIAL_KEY_PARTS:
                self.assertNotIn(part, lowered, f"发现疑似凭据字段：{key}")

    def test_snapshot_has_no_credential_fields(self):
        snapshot = backend.snapshot("demo")
        self._assert_no_credential_keys(snapshot)

    def test_export_has_no_credential_fields(self):
        export = backend.export_data("demo")
        path = backend.get_store("demo").files["downloads"] / export["download"]
        try:
            text = path.read_text(encoding="utf-8")
            payload = json.loads(text)
            self._assert_no_credential_keys(payload)
            self.assertNotIn("UPCV_API_KEY", text)
            self.assertNotIn("password", text.casefold())
        finally:
            path.unlink(missing_ok=True)

    def test_vendored_offerpilot_keeps_license_and_excludes_frontend(self):
        vendor = PROJECT_ROOT / "vendor" / "offerpilot"
        self.assertTrue((vendor / "LICENSE").is_file())
        self.assertTrue((vendor / "README.md").is_file())
        self.assertTrue((vendor / "src" / "offerpilot" / "web" / "server.py").is_file())
        self.assertFalse((vendor / "src" / "offerpilot" / "web" / "frontend").exists())
        self.assertFalse((vendor / "config.yaml").exists())
        self.assertFalse((vendor / ".config.credentials.yaml").exists())
        self.assertIn("PolyForm Noncommercial", (vendor / "LICENSE").read_text(encoding="utf-8"))

    def test_offerpilot_dependency_manifest_and_venv_ignore(self):
        requirements = (PROJECT_ROOT / "requirements-offerpilot.txt").read_text(encoding="utf-8")
        for dependency in ("patchright", "bottle", "pyyaml", "anthropic"):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, requirements)
        ignored = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".venv/", ignored)

    def test_make_server_rejects_non_loopback_bindings(self):
        for host in ("0.0.0.0", "192.168.1.10", "example.com"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    server.make_server(host, 0)


if __name__ == "__main__":
    unittest.main()
