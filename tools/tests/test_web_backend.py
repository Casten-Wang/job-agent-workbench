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
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
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
        # Qualified demo jobs are auto-approved; no demo row waits for a human pass.
        self.assertEqual(len(pending_rows), 0)
        self.assertGreaterEqual(sum(1 for row in snapshot["queue"] if row.get("status") == "approved"), 4)
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

    def test_offerpilot_reimport_backfills_score_on_existing_unscored_row(self):
        store = backend.get_store("demo")
        base = {
            "title": "产品经理",
            "company": "虚构回填公司",
            "city": "上海",
            "salary": "15-20k",
            "created_at": "2026-11-15T10:00:00+08:00",
        }
        # First import happens before OfferPilot has scored the job.
        backend._import_offerpilot_records(store, [dict(base, id="op-backfill-1", score=0)], ["op-backfill-1"])
        before = next(job for job in store.jobs() if job.get("offerpilot_id") == "op-backfill-1")
        self.assertIsNone(before["score"])

        # Re-import after scoring: the existing row must pick up the score.
        result = backend._import_offerpilot_records(store, [dict(base, id="op-backfill-1", score=61)], ["op-backfill-1"])
        self.assertEqual(result["added"], [])
        self.assertEqual(result["duplicates"], 1)
        after = next(job for job in store.jobs() if job.get("offerpilot_id") == "op-backfill-1")
        self.assertEqual(after["score"], 3.4)
        self.assertEqual(after["score_raw"], 61)
        self.assertEqual(len([job for job in store.jobs() if job.get("offerpilot_id") == "op-backfill-1"]), 1)

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

    def test_offerpilot_collect_and_full_require_uploaded_resume(self):
        runtime = backend.offerpilot_runtime
        for mode in ("collect", "full"):
            fake = {
                "offerpilot": MagicMock(),
                "offerpilot.config": MagicMock(load_config=lambda _path: {}),
                "offerpilot.web": MagicMock(),
                "offerpilot.web.preflight": MagicMock(),
            }
            with self.subTest(mode=mode), patch.dict("sys.modules", fake), \
                    patch.object(runtime, "load_backend", return_value=MagicMock()), \
                    patch.object(runtime, "_resume_info", return_value={"available": False}), \
                    patch.object(runtime, "_task_options", return_value=None):
                result = runtime.preflight(mode, None)
                self.assertFalse(result["ok"])
                self.assertEqual(result["checks"][0]["id"], "resume_required")
                with self.assertRaises(ValueError) as ctx:
                    runtime.start_task(mode, None)
                self.assertIn("上传评分简历", str(ctx.exception))
        self.assertIsNone(runtime._resume_blocker(object(), "monitor", {}))

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

    def test_demo_profile_is_rich_and_matches_demo_resume(self):
        profile = backend.snapshot("demo")["profile"]
        self.assertEqual(profile["completeness"]["percent"], 100)
        self.assertEqual(len(profile["experiences"]), 2)
        self.assertEqual(len(profile["projects"]), 2)
        self.assertGreaterEqual(len(profile["skills"]["tools"]), 5)
        self.assertGreaterEqual(len(profile["skills"]["strengths"]), 3)
        self.assertEqual(profile["basic"]["name"], "虚构应聘者乙")
        self.assertEqual(profile["education"][0]["school"], "虚构理工大学")
        # Fictional-only guard: no real phone-like number or non-example email.
        serialized = json.dumps(profile, ensure_ascii=False)
        self.assertIsNone(re.search(r"1[3-9]\d{9}", serialized))
        self.assertNotIn("@qq.com", serialized)
        self.assertNotIn("@163.com", serialized)
        self.assertNotIn("@gmail.com", serialized)

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


class JobsDeleteTests(DemoDataTestCase):
    """delete-jobs: soft delete from the job pool (jobs.json keeps the record)."""

    @staticmethod
    def _extra_job(job_id: str, company: str) -> dict:
        return {
            "id": job_id,
            "company": company,
            "title": "产品助理",
            "city": "上海",
            "score": 4.8,
            "source_channel": "manual_paste",
            "raw_text": "测试数据：普通产品助理岗位。",
        }

    def test_delete_unqueued_job_hides_it_but_keeps_the_record(self):
        store = backend.get_store("demo")
        rows = store.jobs()
        rows.append(self._extra_job("del-plain-job", "虚构删除有限公司"))
        store.set_jobs(rows)
        self.assertIn("del-plain-job", {job["id"] for job in backend.snapshot("demo")["jobs"]})
        before = backend.snapshot("demo")["kpis"]["jobs"]

        result = backend.ACTIONS["delete-jobs"]({"mode": "demo", "ids": ["del-plain-job"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["skipped"], [])
        self.assertIn("已删除 1 条", result["message"])

        snap = backend.snapshot("demo")
        self.assertNotIn("del-plain-job", {job["id"] for job in snap["jobs"]})
        self.assertEqual(snap["kpis"]["jobs"], before - 1)
        self.assertNotIn("del-plain-job", {job["id"] for job in store.jobs()})
        # Soft delete: the record is still on disk, flagged with deleted_at.
        kept = next(job for job in store.all_jobs() if job["id"] == "del-plain-job")
        self.assertTrue(kept["deleted_at"])
        # A deleted job can no longer be queued.
        queued = backend.enqueue({"mode": "demo", "ids": ["del-plain-job"]})
        self.assertEqual(queued["accepted"], [])
        self.assertTrue(any("删除岗位" in row["action"] for row in store.activity()))

    def test_approved_and_delivered_jobs_are_skipped_with_reason(self):
        store = backend.get_store("demo")
        # demo-job-001 is approved in the seeded queue.
        rows = store.jobs()
        rows.append(self._extra_job("del-delivered-job", "虚构已发送有限公司"))
        rows.append(self._extra_job("del-pending-job", "虚构待处理有限公司"))
        store.set_jobs(rows)
        store.set_deliveries([{
            "batch_id": "dlv-test",
            "status": "completed",
            "items": [{"job_id": "del-delivered-job", "status": "sent"}],
        }])
        queue = store.queue()
        queue.append({
            "id": "del-pending-job", "score": 4.1, "company": "虚构待处理有限公司",
            "title": "产品助理", "status": "pending", "Source_Channel": "manual_paste",
        })
        store.set_queue(queue)

        result = backend.delete_jobs({
            "mode": "demo",
            "ids": ["demo-job-001", "del-delivered-job", "del-pending-job", "no-such-job"],
        })
        self.assertEqual(result["deleted"], 1)
        reasons = {item["id"]: item["reason"] for item in result["skipped"]}
        self.assertEqual(reasons["demo-job-001"], "approved")
        self.assertEqual(reasons["del-delivered-job"], "delivered")
        self.assertEqual(reasons["no-such-job"], "not_found")
        self.assertIn("2 条因已通过或已发送未删除", result["message"])
        visible = {job["id"] for job in store.jobs()}
        self.assertIn("demo-job-001", visible)
        self.assertIn("del-delivered-job", visible)
        self.assertNotIn("del-pending-job", visible)
        # Pending queue row is removed together with the job; approved row stays.
        queue_ids = {str(row.get("id")) for row in store.queue()}
        self.assertNotIn("del-pending-job", queue_ids)
        self.assertIn("demo-job-001", queue_ids)

    def test_deleted_job_is_not_revived_by_reimport(self):
        store = backend.get_store("demo")
        record = {
            "id": "op-del-1", "title": "AI 产品经理", "company": "虚构复活测试公司",
            "city": "北京", "salary": "20-30k", "score": 80,
        }
        first = backend._import_offerpilot_records(store, [record], ["op-del-1"])
        self.assertEqual(len(first["added"]), 1)
        job_id = first["added"][0]
        deleted = backend.delete_jobs({"mode": "demo", "ids": [job_id]})
        self.assertEqual(deleted["deleted"], 1)
        self.assertNotIn(job_id, {job["id"] for job in store.jobs()})

        again = backend._import_offerpilot_records(store, [record], ["op-del-1"])
        self.assertEqual(again["added"], [])
        self.assertEqual(again["duplicates"], 1)
        self.assertNotIn(job_id, {job["id"] for job in store.jobs()})
        self.assertEqual(len([job for job in store.all_jobs() if job.get("offerpilot_id") == "op-del-1"]), 1)

        # Other writers keep soft-deleted records and treat them as duplicates.
        text = (
            "测试数据：复活测试\n公司：虚构手动复活公司\n岗位：产品经理\n城市：上海\n"
            "来源渠道：manual_paste\n发布时间：2026-11-14\n记录类型：JD\n职位描述：测试数据。\n"
        )
        parsed = backend.parse_jd({"mode": "demo", "text": text, "id": "del-manual-jd"})
        self.assertTrue(parsed["ok"])
        backend.delete_jobs({"mode": "demo", "ids": [parsed["job"]["id"]]})
        second = backend.parse_jd({"mode": "demo", "text": text, "id": "del-manual-jd"})
        self.assertFalse(second["ok"])
        self.assertTrue(second["duplicate"])
        self.assertIn(parsed["job"]["id"], {job["id"] for job in store.all_jobs()})

    def test_delete_validates_ids(self):
        for ids in (None, [], "demo-job-001", [1], [""], ["  "], [f"job-{i}" for i in range(101)]):
            with self.subTest(ids=ids):
                with self.assertRaises(backend.ApiError):
                    backend.delete_jobs({"mode": "demo", "ids": ids})
        with self.assertRaises(backend.ApiError):
            backend.delete_jobs({"mode": "other", "ids": ["demo-job-001"]})
        # Exactly 100 ids is accepted (unknown ids are reported as not_found).
        result = backend.delete_jobs({"mode": "demo", "ids": [f"job-{i}" for i in range(100)]})
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["skipped"]), 100)

    def test_demo_and_user_modes_are_isolated(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(backend, "WEB_DIR", Path(tmp)):
                user_store = backend.Store("user")  # data dir lives under tmp, never web/data/user
            demo_store = backend.get_store("demo")
            user_store.set_jobs([self._extra_job("shared-id", "虚构隔离有限公司")])
            demo_rows = demo_store.jobs()
            demo_rows.append(self._extra_job("shared-id", "虚构隔离有限公司"))
            demo_store.set_jobs(demo_rows)

            stores = {"demo": demo_store, "user": user_store}
            with patch.object(backend, "get_store", side_effect=lambda mode, seed_if_empty=True: stores[mode]):
                result = backend.delete_jobs({"mode": "user", "ids": ["shared-id"]})
                self.assertEqual(result["deleted"], 1)
                self.assertEqual(user_store.jobs(), [])
                self.assertIn("shared-id", {job["id"] for job in demo_store.jobs()})

                result = backend.delete_jobs({"mode": "demo", "ids": ["shared-id"]})
                self.assertEqual(result["deleted"], 1)
                self.assertNotIn("shared-id", {job["id"] for job in demo_store.jobs()})
                self.assertEqual(len(user_store.all_jobs()), 1)

    def test_delete_jobs_is_registered_and_served_over_http_action_table(self):
        self.assertIs(backend.ACTIONS["delete-jobs"], backend.delete_jobs)


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
            "override_reason": "值得沟通，人工判断",
        })
        self.assertIn("demo-job-003", manual["manual"])
        self.assertNotIn("demo-job-003", manual["dropped"], "手动入队的岗位不应再算作未入队")
        queue = backend.approval_queue.load_queue(backend.get_store("demo").files["queue"])
        row = next(item for item in queue if item["id"] == "demo-job-003")
        self.assertTrue(row["manual_override"])
        self.assertEqual(row["status"], "approved")

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

    def test_high_risk_job_is_blocked_from_queue_even_when_manual(self):
        store = backend.get_store("demo")
        rows = store.jobs()
        rows.append({
            "id": "risk-demo-job",
            "company": "虚构风险有限公司",
            "title": "产品助理",
            "city": "上海",
            "score": 4.8,
            "source_channel": "manual_paste",
            "raw_text": "测试数据：入职需缴纳培训费，包就业。",
        })
        store.set_jobs(rows)
        result = backend.enqueue({
            "mode": "demo",
            "ids": ["risk-demo-job"],
            "allow_low_score": True,
            "override_reason": "值得沟通，人工判断",
        })
        self.assertEqual(result["risk_blocked"], ["risk-demo-job"])
        self.assertEqual(result["accepted"], [])
        self.assertIn("拦截", result["message"])
        queue = store.queue()
        self.assertFalse(any(str(row.get("id")) == "risk-demo-job" for row in queue))

    def test_unscored_job_is_reported_not_silently_dropped(self):
        store = backend.get_store("demo")
        rows = store.jobs()
        rows.append({
            "id": "unscored-demo-job",
            "company": "虚构未评分有限公司",
            "title": "产品助理",
            "city": "上海",
            "source_channel": "manual_paste",
            "raw_text": "测试数据：普通产品助理岗位。",
        })
        store.set_jobs(rows)
        result = backend.enqueue({"mode": "demo", "ids": ["unscored-demo-job"]})
        self.assertEqual(result["unscored"], ["unscored-demo-job"])
        self.assertIn("未评分", result["message"])
        self.assertTrue(result["message"].startswith("没有岗位入队"))
        self.assertFalse(any(str(row.get("id")) == "unscored-demo-job" for row in store.queue()))

    def test_snapshot_jobs_expose_read_only_risk(self):
        store = backend.get_store("demo")
        rows = store.jobs()
        rows.append({
            "id": "risk-demo-job-2",
            "company": "虚构风险有限公司二",
            "title": "产品助理",
            "city": "上海",
            "score": 4.5,
            "source_channel": "manual_paste",
            "raw_text": "测试数据：需缴纳押金。",
        })
        store.set_jobs(rows)
        snap = backend.snapshot("demo", {})
        by_id = {job["id"]: job for job in snap["jobs"]}
        self.assertEqual(by_id["risk-demo-job-2"]["risk"]["level"], "high")
        for job in snap["jobs"]:
            self.assertIn(job["risk"]["level"], ("low", "verify", "high"))

    def test_snapshot_queue_rows_carry_read_only_contact_plan(self):
        snap = backend.snapshot("demo", {})
        approved = [row for row in snap["queue"] if row["status"] == "approved"]
        self.assertTrue(approved)
        for row in approved:
            self.assertIn("plan", row)
            self.assertIn(row["plan"]["today"], (True, False))
            self.assertTrue(row["plan"]["reason"])
        ranks = sorted(row["plan"]["rank"] for row in approved if row["plan"]["today"])
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))
        quota = snap["pipeline"]["delivery"]["quota"]
        self.assertEqual(quota["daily"], backend.DEFAULT_DAILY_CONTACT_QUOTA)
        self.assertEqual(quota["planned_today"], len(ranks))
        self.assertLessEqual(quota["planned_today"], quota["remaining"])

    def test_confirm_requires_at_least_one_selected_row(self):
        with self.assertRaises(backend.ApiError):
            backend.confirm_queue({"mode": "demo", "ids": []})

    def test_confirm_marks_selected_pending_rows_approved(self):
        store = backend.get_store("demo")
        rows = store.queue()
        for row in rows:
            row["status"] = "pending"
        store.set_queue(rows)
        result = backend.confirm_queue({"mode": "demo", "ids": ["demo-job-001"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["confirmed"], ["demo-job-001"])
        self.assertIs(result["auto_submit"], False)
        self.assertEqual(result["status"], "ready_for_manual_submission_only")
        self.assertIn("复核", result["message"])
        rows = {str(row.get("id")): row for row in store.queue()}
        self.assertEqual(rows["demo-job-001"]["status"], "approved")
        self.assertEqual(rows["demo-job-002"]["status"], "pending")

    def test_greet_rejects_demo_mode_and_oversized_batches(self):
        with self.assertRaises(backend.ApiError) as ctx:
            backend.start_offerpilot_greet({"mode": "demo", "ids": ["demo-job-001"]})
        self.assertEqual(ctx.exception.status, 403)
        with self.assertRaises(backend.ApiError):
            backend.start_offerpilot_greet({"mode": "user", "ids": [f"job-{i}" for i in range(11)]})

    def test_greet_requires_approved_jobs_with_runtime_ids(self):
        class _Store:
            def queue(self):
                return [
                    {"id": "job-pending", "status": "pending"},
                    {"id": "job-approved", "status": "approved"},
                    {"id": "job-no-runtime", "status": "approved"},
                ]

            def jobs(self):
                return [
                    {"id": "job-pending", "offerpilot_id": "vp"},
                    {"id": "job-approved", "offerpilot_id": "va"},
                    {"id": "job-no-runtime"},
                ]

            def log(self, *args):
                pass

        store = _Store()
        with patch.object(backend, "get_store", return_value=store), patch.object(
            backend.offerpilot_runtime, "start_greet_task"
        ) as start:
            for ids in (["job-pending"], ["job-no-runtime"], ["missing"]):
                with self.subTest(ids=ids):
                    with self.assertRaises(backend.ApiError) as ctx:
                        backend.start_offerpilot_greet({"mode": "user", "ids": ids})
                    self.assertEqual(ctx.exception.status, 409)
            start.assert_not_called()

            start.return_value = {"task": {"id": "task-1"}, "requested": 1}
            result = backend.start_offerpilot_greet({"mode": "user", "ids": ["job-approved"]})
        self.assertTrue(result["ok"])
        start.assert_called_once_with(["va"])
        self.assertIn("只生成，不发送", result["message"])
        self.assertEqual(result["task"], {"id": "task-1"})


class DeliveryActionTests(unittest.TestCase):
    def _store(self):
        class _Store:
            def __init__(self):
                self._deliveries = []
                self.logs = []

            def queue(self):
                return [{"id": "job-approved", "status": "approved"}]

            def jobs(self):
                return [{
                    "id": "job-approved",
                    "offerpilot_id": "vendor-1",
                    "company": "示例公司",
                    "title": "示例岗位",
                }]

            def deliveries(self):
                return self._deliveries

            def set_deliveries(self, rows):
                self._deliveries = rows

            def log(self, *args):
                self.logs.append(args)

        return _Store()

    def test_deliver_rejects_demo_bad_phrase_and_missing_risk(self):
        with self.assertRaises(backend.ApiError) as ctx:
            backend.start_offerpilot_deliver({
                "mode": "demo", "ids": ["job-approved"], "confirm": "确认发送本批 1 条",
                "risk_acknowledged": True,
            })
        self.assertEqual(ctx.exception.status, 403)

        store = self._store()
        with patch.object(backend, "get_store", return_value=store), patch.object(
            backend.offerpilot_runtime, "start_deliver_task"
        ) as start:
            with self.assertRaises(backend.ApiError):
                backend.start_offerpilot_deliver({
                    "mode": "user", "ids": ["job-approved"], "confirm": "确认发送",
                    "risk_acknowledged": True,
                })
            with self.assertRaises(backend.ApiError):
                backend.start_offerpilot_deliver({
                    "mode": "user", "ids": ["job-approved"], "confirm": "确认发送本批 1 条",
                })
            start.assert_not_called()
        self.assertEqual(store.deliveries(), [])

    def test_deliver_starts_task_and_records_batch(self):
        store = self._store()
        with patch.object(backend, "get_store", return_value=store), patch.object(
            backend.offerpilot_runtime,
            "start_deliver_task",
            return_value={"task": {"id": "task-9", "mode": "deliver"}, "requested": 1},
        ) as start:
            result = backend.start_offerpilot_deliver({
                "mode": "user",
                "ids": ["job-approved"],
                "confirm": "确认发送本批 1 条",
                "risk_acknowledged": True,
            })
        start.assert_called_once_with(["vendor-1"])
        self.assertTrue(result["ok"])
        batch = result["batch"]
        self.assertEqual(batch["status"], "sending")
        self.assertEqual(batch["task_id"], "task-9")
        self.assertEqual(batch["requested"], 1)
        self.assertEqual(batch["items"][0]["job_id"], "job-approved")
        self.assertEqual(batch["items"][0]["offerpilot_id"], "vendor-1")
        self.assertEqual(store.deliveries()[0]["batch_id"], batch["batch_id"])

    def test_deliver_start_failure_is_recorded(self):
        store = self._store()
        with patch.object(backend, "get_store", return_value=store), patch.object(
            backend.offerpilot_runtime,
            "start_deliver_task",
            side_effect=ValueError("当前不在发送时间窗口内"),
        ):
            with self.assertRaises(backend.ApiError):
                backend.start_offerpilot_deliver({
                    "mode": "user",
                    "ids": ["job-approved"],
                    "confirm": "确认发送本批 1 条",
                    "risk_acknowledged": True,
                })
        batch = store.deliveries()[0]
        self.assertEqual(batch["status"], "failed")
        self.assertEqual(batch["stop_reason"], "start_failed")
        self.assertEqual(batch["items"][0]["status"], "failed")

    def test_sync_finalizes_batch_and_writes_pipeline_events(self):
        class _Store:
            def __init__(self):
                self._deliveries = [{
                    "batch_id": "dlv-1",
                    "task_id": "task-1",
                    "status": "sending",
                    "requested": 2,
                    "items": [
                        {"job_id": "job-1", "offerpilot_id": "v1", "company": "A", "title": "甲", "status": "sending"},
                        {"job_id": "job-2", "offerpilot_id": "v2", "company": "B", "title": "乙", "status": "sending"},
                    ],
                }]
                self.events = []

            def deliveries(self):
                return self._deliveries

            def set_deliveries(self, rows):
                self._deliveries = rows

            def append_pipeline_event(self, event):
                self.events.append(event)

        store = _Store()
        boss_state = {"task": None, "last_task": {"id": "task-1", "stop_reason": "daily_limit"}}
        with patch.object(
            backend.offerpilot_runtime,
            "get_greetings",
            return_value={"ok": True, "greetings": [
                {"id": "v1", "status": "sent"},
                {"id": "v2", "status": "approved"},
            ]},
        ):
            backend._sync_deliveries(store, boss_state)
        batch = store.deliveries()[0]
        self.assertEqual(batch["status"], "completed")
        self.assertEqual((batch["sent"], batch["deferred"]), (1, 1))
        self.assertEqual(batch["items"][0]["status"], "sent")
        self.assertEqual(batch["items"][1]["status"], "deferred")
        self.assertEqual(batch["items"][1]["error_code"], "daily_limit")
        self.assertEqual([event["status"] for event in store.events], ["succeeded", "skipped"])
        self.assertEqual({event["actor"] for event in store.events}, {"embedded_runtime"})
        self.assertEqual({event["stage"] for event in store.events}, {"send"})

    def test_sync_marks_risk_stop_as_blocked(self):
        class _Store:
            def __init__(self):
                self._deliveries = [{
                    "batch_id": "dlv-2",
                    "task_id": "task-2",
                    "status": "sending",
                    "requested": 1,
                    "items": [{"job_id": "job-1", "offerpilot_id": "v1", "status": "sending"}],
                }]
                self.events = []

            def deliveries(self):
                return self._deliveries

            def set_deliveries(self, rows):
                self._deliveries = rows

            def append_pipeline_event(self, event):
                self.events.append(event)

        store = _Store()
        with patch.object(
            backend.offerpilot_runtime,
            "get_greetings",
            return_value={"ok": True, "greetings": [{"id": "v1", "status": "approved"}]},
        ):
            backend._sync_deliveries(store, {"task": None, "last_task": {"id": "task-2", "stop_reason": "captcha"}})
        batch = store.deliveries()[0]
        self.assertEqual(batch["items"][0]["status"], "blocked")
        self.assertEqual(batch["items"][0]["error_code"], "captcha")
        self.assertEqual(batch["status"], "failed")
        self.assertEqual(store.events[0]["status"], "failed")


class GreetingPreviewTests(unittest.TestCase):
    def test_get_greetings_returns_whitelisted_preview(self):
        vendor_src = str(PROJECT_ROOT / "vendor" / "offerpilot" / "src")
        if vendor_src not in sys.path:
            sys.path.insert(0, vendor_src)
        from offerpilot.db import get_db  # noqa: E402  (vendored module)

        import tempfile  # local import keeps the module header small

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "offerpilot.db"
            conn = get_db(db_path)
            conn.execute(
                "INSERT INTO jobs (id, title, company, status, greeting, greeting_selection, greeting_style_issues)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("job-a", "产品经理", "示例公司", "ready", "你好，我是示例。", "generated", '["太长了"]'),
            )
            conn.commit()
            conn.close()

            class _Server:
                DATA_DIR = Path(tmp)

                def get_db(self, path):
                    return get_db(path)

            with patch.object(backend.offerpilot_runtime, "load_backend", return_value=_Server()):
                result = backend.offerpilot_runtime.get_greetings(["job-a", "missing"])

        self.assertTrue(result["ok"])
        self.assertTrue(result["read_only"])
        self.assertEqual(len(result["greetings"]), 1)
        item = result["greetings"][0]
        self.assertEqual(item["id"], "job-a")
        self.assertEqual(item["greeting"], "你好，我是示例。")
        self.assertEqual(item["selection"], "generated")
        self.assertEqual(item["style_issues"], ["太长了"])
        self.assertTrue(item["ready"])
        self.assertEqual(
            set(item),
            {"id", "company", "title", "status", "greeting", "selection", "style_issues", "reviewed", "ready"},
        )


class GreetingEvidenceCheckTests(DemoDataTestCase):
    def test_snapshot_flags_numbers_missing_from_profile_facts(self):
        store = backend.get_store("demo")
        jobs = store.jobs()
        jobs[0]["offerpilot_id"] = "v-evidence"
        store.set_jobs(jobs)
        queue = store.queue()
        queue[0]["status"] = "approved"
        store.set_queue(queue)
        job_id = str(queue[0]["id"])
        for job in jobs:
            if str(job.get("id")) == job_id:
                job["offerpilot_id"] = "v-evidence"
        store.set_jobs(jobs)
        profile = store.profile()
        profile["summary"] = "访谈了6名用户。"
        store.set_profile(profile)
        greeting = {
            "id": "v-evidence",
            "status": "approved",
            "greeting": "我访谈过6名用户，并把转化率提升了80%。",
            "selection": "",
            "style_issues": [],
            "reviewed": False,
            "ready": True,
        }
        with patch.object(backend, "get_offerpilot_state", return_value={"ok": True, "task": None, "last_task": None}), \
                patch.object(backend.offerpilot_runtime, "get_greetings", return_value={"ok": True, "greetings": [greeting]}):
            snap = backend.snapshot("demo")
        row = next(item for item in snap["queue"] if str(item.get("id")) == job_id)
        check = row["greeting"]["evidence_check"]
        self.assertFalse(check["ok"])
        self.assertEqual([c["value"] for c in check["unsupported_claims"]], ["80"])
        # Read-only: the greeting text itself is untouched.
        self.assertEqual(row["greeting"]["greeting"], greeting["greeting"])


class GreetRuntimeTests(unittest.TestCase):
    def test_start_greet_task_marks_ready_and_starts_greet_mode(self):
        vendor_src = str(PROJECT_ROOT / "vendor" / "offerpilot" / "src")
        if vendor_src not in sys.path:
            sys.path.insert(0, vendor_src)
        from offerpilot.db import get_db  # noqa: E402  (vendored module)

        import tempfile
        import types

        # The greet path imports modules that need the optional runtime deps
        # (rich, browser stack). This test only exercises the wrapper contract,
        # so stand in for those two modules instead of installing packages.
        fake_greeter = types.ModuleType("offerpilot.ai.greeter")
        fake_greeter.greeting_config_error = lambda config: ""
        fake_tasks = types.ModuleType("offerpilot.web.tasks")

        class _TaskBusy(RuntimeError):
            pass

        fake_tasks.TaskAlreadyRunningError = _TaskBusy

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "offerpilot.db"
            conn = get_db(db_path)
            conn.execute(
                "INSERT INTO jobs (id, title, company, status) VALUES (?, ?, ?, ?)",
                ("job-a", "产品经理", "示例公司", "pending"),
            )
            conn.commit()
            conn.close()

            calls = {}

            class _Runner:
                def start(self, mode, config, *, before_start=None):
                    calls["mode"] = mode
                    calls["job_ids"] = list(config.get("_workbench_job_ids") or [])
                    if before_start is not None:
                        before_start()
                    return {"id": "task-1", "mode": mode, "status": "running"}

            class _Server:
                DATA_DIR = Path(tmp)
                CONFIG_PATH = Path(tmp) / "config.yaml"
                BASE_DIR = Path(tmp)
                job_mutation_lock = threading.Lock()
                task_runner = _Runner()

                def load_config(self, path):
                    return {
                        "profile": {
                            "ai_greeting_enabled": False,
                            "fixed_greeting": "固定招呼语",
                        }
                    }

                def get_ai_api_key(self, config):
                    return ""

                def get_db(self, path):
                    return get_db(path)

            with patch.dict(
                sys.modules,
                {
                    "offerpilot.ai.greeter": fake_greeter,
                    "offerpilot.web.tasks": fake_tasks,
                },
            ), patch.object(backend.offerpilot_runtime, "load_backend", return_value=_Server()):
                result = backend.offerpilot_runtime.start_greet_task(["job-a"])

            self.assertEqual(result["requested"], 1)
            self.assertEqual(result["task"]["id"], "task-1")
            self.assertEqual(calls["mode"], "greet")
            self.assertEqual(calls["job_ids"], ["job-a"])

            conn = get_db(db_path)
            try:
                row = conn.execute("SELECT status FROM jobs WHERE id = 'job-a'").fetchone()
                history = conn.execute(
                    "SELECT action FROM history WHERE job_id = 'job-a'"
                ).fetchall()
            finally:
                conn.close()
        self.assertEqual(row["status"], "ready")
        self.assertEqual([item["action"] for item in history], ["workbench_greet"])


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


class VariantQualityTests(DemoDataTestCase):
    def test_add_variant_reports_missing_star_and_quant_hints(self):
        response = backend.add_variant(
            {
                "mode": "demo",
                "project": "质量检查-缺结构",
                "text": "负责产品的需求分析与竞品研究，参与跨部门沟通协调推进项目落地。",
            }
        )
        self.assertTrue(response["ok"])
        quality = response["quality"]
        self.assertFalse(quality["has_star_structure"])
        self.assertFalse(quality["has_quantified_result"])
        self.assertTrue(quality["hints"])

    def test_add_variant_with_full_star_and_quant_has_no_hints(self):
        text = (
            "背景：学生跨院选课资源分散。"
            "问题：发帖响应率偏低。"
            "动作：完成500份问卷和10场访谈，输出原型。"
            "结果：响应流程从5步精简至3步，80%用户认可。"
        )
        response = backend.add_variant(
            {"mode": "demo", "project": "质量检查-完整结构", "text": text}
        )
        self.assertTrue(response["ok"])
        quality = response["quality"]
        self.assertTrue(quality["has_star_structure"])
        self.assertTrue(quality["has_quantified_result"])
        self.assertEqual(quality["hints"], [])

    def test_duplicate_variant_still_returns_quality(self):
        text = "背景：A。问题：B。动作：C。结果：提升30%。"
        first = backend.add_variant({"mode": "demo", "project": "去重检查", "text": text})
        self.assertTrue(first["ok"])
        second = backend.add_variant({"mode": "demo", "project": "去重检查", "text": text})
        self.assertFalse(second["ok"])
        self.assertTrue(second["duplicate"])
        self.assertIn("quality", second)

    def test_add_variant_never_rewrites_input_text(self):
        text = "背景：A。问题：B。动作：C。结果：无量化数据。"
        response = backend.add_variant({"mode": "demo", "project": "原文不改写", "text": text})
        store = backend.get_store("demo")
        rows = store.variants()
        saved = next(row for row in rows if row["project"] == "原文不改写")
        self.assertEqual(saved["text"], text)
        self.assertIn("建议补充一个量化结果", response["quality"]["hints"][0])


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
            'id="queue-approved-select-all"',
            'id="queue-generate-greetings"',
            'id="queue-send-greetings"',
            'id="queue-greetings"',
            'id="queue-delivery-panel"',
            'id="queue-delivery-risk"',
            'id="queue-delivery-start"',
            'id="queue-delivery-results"',
            'id="jobs-override-reason"',
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
            "enqueueJobs",
            "uploadOfferPilotResume",
            "syncCollectResumeUI",
            "offerpilot-resume",
            "offerpilot-greet",
            "generateQueueGreetings",
            "renderQueueGreetings",
            "greetingStatusBadge",
            "updateQueueApprovedSelectionUI",
            "queueConfirmButton",
            "offerpilot-deliver",
            "openDeliveryPanel",
            "startQueueDelivery",
            "renderDeliveryResults",
            "deliveryStatusBadge",
            "offerpilot-stop",
            "offerpilot.importedTasks",
            "renderWorkbenchNextStep",
            "collectProfileForm",
            "save-profile",
            "import-profile-cv",
            "renderProfileMeter",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)

    def test_workbench_shows_one_next_step_and_drops_unused_filters(self):
        status, _, raw = self.request("GET", "/")
        self.assertEqual(status, 200)
        html = raw.decode("utf-8", "replace")
        self.assertIn('id="workbench-next-text"', html)
        for removed in (
            'id="filter-period"',
            'id="filter-channel"',
            'id="filter-state"',
            'class="filter-bar"',
            'id="scope-line"',
        ):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, html)
        status, _, raw = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        script = raw.decode("utf-8", "replace")
        for marker in ("renderWorkbenchNextStep", "workbenchNextText"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        self.assertNotIn("filterPeriod", script)

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

    def test_profile_endpoint_reports_saved_and_cv_flags(self):
        status, _, raw = self.request("GET", "/api/profile?mode=demo")
        self.assertEqual(status, 200)
        profile = json.loads(raw.decode("utf-8"))["profile"]
        self.assertIs(profile["saved"], True)
        self.assertIs(profile["cv_available"], False)

    def test_profile_page_wires_cv_prefill_banner_and_draft_save_state(self):
        html = (WEB_DIR / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="profile-draft-banner"', html)
        script = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
        for marker in ("autoPrefillProfileFromCv", "profileShouldAutoPrefill", "renderProfileDraftBanner", "profileCountPrefilled"):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)
        self.assertIn("button-draft", script)
        self.assertIn("button-draft", (WEB_DIR / "static" / "offer-theme.css").read_text(encoding="utf-8"))

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


class WorkbenchFlowTests(unittest.TestCase):
    """六段后端契约只在前端合并成四步；最后一步为 0 时要说明原因。"""

    @staticmethod
    def _stage_model(snapshot: dict) -> list:
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过前端四步渲染校验")
        script = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
        start = script.index("/* workbench-four-stages:start")
        end = script.index("/* workbench-four-stages:end")
        harness = (
            script[start:end]
            + "\nconst fs = require('fs');\n"
            "const snap = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify(workbenchFourStages(snap)));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps(snapshot),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行前端四步渲染失败：{completed.stderr[:800]}")
        return json.loads(completed.stdout)

    @staticmethod
    def _fixture(*, intake: int, jobs: list, queue: list, threshold: float = 4.0) -> dict:
        return {
            "pipeline": {
                "stages": [
                    {"key": "intake", "count": intake},
                    {"key": "screening", "count": sum(1 for job in jobs if job.get("score") is not None)},
                    {"key": "approval", "count": sum(1 for row in queue if row.get("status") == "approved")},
                    {"key": "greeting", "count": 0},
                    {"key": "send", "count": 0},
                    {"key": "monitor", "count": 0},
                ]
            },
            "jobs": jobs,
            "queue": queue,
            "config": {
                "score": {"approval_min": threshold, "high_threshold": 4.5, "approval_max": 4.4}
            },
        }

    def test_four_stage_model_merges_six_stage_contract(self):
        queue = [
            {"id": "j1", "status": "approved", "greeting": {"greeting": "您好，我是虚构应聘者。", "ready": True}},
            {"id": "j2", "status": "approved", "greeting": {"greeting": ""}},
            {"id": "j3", "status": "approved"},
            {"id": "j4", "status": "pending"},
        ]
        jobs = [{"id": f"j{index}", "score": 4.5} for index in range(1, 7)]
        model = self._stage_model(self._fixture(intake=6, jobs=jobs, queue=queue))
        self.assertEqual([stage["key"] for stage in model], ["intake", "queue", "greeting", "confirm"])
        self.assertEqual(
            [stage["title"] for stage in model],
            ["采集", "评分入队", "招呼语已生成", "等你确认"],
        )
        self.assertEqual([stage["index"] for stage in model], ["01", "02", "03", "04"])
        self.assertEqual([stage["count"] for stage in model], [6, 4, 1, 3])
        # 只有第四步有动作；前三步只读。
        self.assertEqual([stage["action"] for stage in model], [False, False, False, True])

    def test_confirm_zero_explains_below_enqueue_threshold(self):
        jobs = [
            {"id": "low-1", "score": 3.5},
            {"id": "low-2", "score": 3.8},
            {"id": "not-yet-queued", "score": 4.6},
        ]
        model = self._stage_model(self._fixture(intake=5, jobs=jobs, queue=[]))
        confirm = model[3]
        self.assertEqual(confirm["count"], 0)
        self.assertEqual(confirm["reason"], "已评分 2 条，未达到入队线（当前 4.0 分）")

    def test_confirm_zero_explains_missing_jobs(self):
        model = self._stage_model(self._fixture(intake=0, jobs=[], queue=[]))
        confirm = model[3]
        self.assertEqual(confirm["count"], 0)
        self.assertEqual(confirm["reason"], "还没有采集到岗位")

    def test_workbench_flow_markup_and_renderer_are_four_stage(self):
        html = (WEB_DIR / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="pipeline workbench-stages"', html)
        self.assertIn('aria-label="求职四步流程"', html)
        script = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
        for marker in (
            "/* workbench-four-stages:start",
            "function workbenchFourStages",
            "data-workbench-stage",
            "workbench-confirm-button",
            "去审批队列确认",
            "renderPipeline(snapshot);",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, script)


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

    def test_collect_page_defaults_to_one_page_with_guidance_and_criteria(self):
        html = (WEB_DIR / "static" / "index.html").read_text(encoding="utf-8")
        match = re.search(r'<input id="collect-pages"[^>]*>', html)
        self.assertIsNotNone(match, "采集页缺少翻页数输入框")
        tag = match.group(0)
        self.assertIn('value="1"', tag)
        self.assertIn('min="1"', tag)
        self.assertIn('max="10"', tag)
        self.assertIn("每次都从第 1 页开始；已抓过的岗位会自动跳过，不会重复。想看到更多新岗位，就多翻几页。", html)
        self.assertIn('id="collect-criteria"', html)
        self.assertIn("本次初筛条件", html)
        self.assertIn('data-view-link="profile"', html)
        script = (WEB_DIR / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function renderCollectCriteria", script)
        self.assertIn("snapshot.profile", script)

    def test_snapshot_profile_exposes_job_intent_fields_used_by_collect_page(self):
        profile = backend.snapshot("demo")["profile"]
        intent = profile["job_intent"]
        for key in ("titles", "cities", "salary_min", "salary_max", "job_type"):
            self.assertIn(key, intent)
        options = backend._offerpilot_options({"options": {"keywords": ["a"], "cities": ["b"], "max_pages": 10}})
        self.assertEqual(options["platforms"]["boss"]["max_pages"], 10)
        with self.assertRaises(backend.ApiError):
            backend._offerpilot_options({"options": {"keywords": ["a"], "cities": ["b"], "max_pages": 11}})

    def test_make_server_rejects_non_loopback_bindings(self):
        for host in ("0.0.0.0", "192.168.1.10", "example.com"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    server.make_server(host, 0)



class ProfileCvImportTests(unittest.TestCase):
    """Resume-to-profile parsing and the import source choice.

    Every resume here is an obviously fictional placeholder fixture. Nothing
    reads workspace/resume.md or web/data/user: paths are patched to a
    temporary directory and the store is an isolated temp Store.
    """

    RESUME = (
        "# 示例应聘者 — 简历\n"
        "\n"
        "**Location:** 示例城市甲\n"
        "**Phone:** 示例电话占位\n"
        "**Email:** candidate@example.com\n"
        "\n"
        "## Professional Summary\n"
        "\n"
        "- 熟悉用户研究与需求分析，能独立完成从访谈到原型的流程 [[ILLEGIBLE]]\n"
        "- 使用 Axure 与 Visio 完成原型和流程图\n"
        "\n"
        "## Work Experience\n"
        "\n"
        "### 示例公司甲 — 示例城市甲\n"
        "\n"
        "**示例岗位甲**\n"
        "2019年10月 - 至今\n"
        "\n"
        "- 整理需求文档并跟进上线 [[ILLEGIBLE]]\n"
        "- 与设计部门沟通原型图 [[ILLEGIBLE]]\n"
        "\n"
        "### 示例公司乙\n"
        "\n"
        "**示例岗位乙**\n"
        "2019.03-2019.06\n"
        "\n"
        "* 推动小程序上线并汇报数据\n"
        "\n"
        "## Projects\n"
        "\n"
        "### 示例项目甲 — 示例角色甲（2018年3月 - 2018年6月）\n"
        "\n"
        "- 设计问卷并完成调研报告\n"
        "\n"
        "## Education\n"
        "\n"
        "### 示例大学 — 示例专业，本科（2015年9月 - 2019年6月，示例城市甲）\n"
        "\n"
        "## Skills\n"
        "\n"
        "- 技能：Axure、Visio、Excel、需求分析\n"
    )

    def _run_import(self, text: str | None, runtime_files: dict[str, str] | None = None, cv_exists: bool = True):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cv_path = root / "workspace" / "resume.md"
            if cv_exists and text is not None:
                cv_path.parent.mkdir(parents=True, exist_ok=True)
                cv_path.write_text(text, encoding="utf-8")
            runtime = root / "runtime"
            (runtime / "data" / "resumes").mkdir(parents=True, exist_ok=True)
            for name, body in (runtime_files or {}).items():
                (runtime / "data" / "resumes" / name).write_text(body, encoding="utf-8")
            with patch.object(backend, "CV_PATH", cv_path), \
                    patch.object(backend.offerpilot_runtime, "runtime_dir", lambda mode: runtime), \
                    patch.object(backend, "WEB_DIR", root):
                store = backend.Store("user")
                with patch.object(backend, "get_store", lambda mode, seed_if_empty=True: store):
                    return backend.import_profile_cv({"mode": "user"}), store

    def test_structured_sections_fill_experiences_projects_education_and_skills(self):
        profile = backend._extract_profile_from_cv(self.RESUME)
        self.assertEqual(len(profile["experiences"]), 2)
        first = profile["experiences"][0]
        self.assertEqual(first["company"], "示例公司甲")
        self.assertEqual(first["title"], "示例岗位甲")
        self.assertEqual(first["start"], "2019-10")
        self.assertEqual(first["end"], "至今")
        self.assertIn("整理需求文档", first["summary"])
        self.assertEqual(len(profile["projects"]), 1)
        self.assertEqual(profile["projects"][0]["name"], "示例项目甲")
        self.assertEqual(profile["projects"][0]["role"], "示例角色甲")
        self.assertEqual(profile["projects"][0]["start"], "2018-03")
        self.assertEqual(profile["projects"][0]["end"], "2018-06")
        self.assertEqual(len(profile["education"]), 1)
        edu = profile["education"][0]
        self.assertEqual((edu["school"], edu["major"], edu["degree"]), ("示例大学", "示例专业", "本科"))
        self.assertEqual((edu["start"], edu["end"]), ("2015-09", "2019-06"))
        self.assertIn("Axure", profile["skills"]["tools"])
        self.assertIn("需求分析", profile["skills"]["tools"])
        self.assertEqual(len(profile["skills"]["tools"]), len(set(profile["skills"]["tools"])))
        self.assertIn("用户研究", profile["summary"])
        normalized = backend.normalize_profile(profile)
        self.assertEqual(len(normalized["experiences"]), 2)
        self.assertEqual(len(normalized["projects"]), 1)
        self.assertEqual(len(normalized["education"]), 1)

    def test_date_variants_and_chinese_english_headings(self):
        text = (
            "# 示例\n\n"
            "## 工作经历\n\n"
            "### 示例公司丙 — 示例城市甲\n"
            "**示例岗位丙**\n"
            "2019-03 ~ 2019-06\n"
            "- 完成示例任务一\n\n"
            "### 示例公司丁｜示例岗位丁｜2020.07–2020.12\n"
            "- 完成示例任务二\n\n"
            "## Experience\n\n"
            "### 示例公司戊 — 示例岗位戊（2021年3月 - 至今）\n"
            "- 完成示例任务三\n\n"
            "## 教育背景\n\n"
            "### 示例大学二 — 示例专业二，硕士（2016.09 - 2019.06）\n"
        )
        profile = backend._extract_profile_from_cv(text)
        spans = [(row["company"], row["start"], row["end"]) for row in profile["experiences"]]
        self.assertEqual(
            spans,
            [
                ("示例公司丙", "2019-03", "2019-06"),
                ("示例公司丁", "2020-07", "2020-12"),
                ("示例公司戊", "2021-03", "至今"),
            ],
        )
        self.assertEqual(profile["experiences"][1]["title"], "示例岗位丁")
        self.assertEqual(profile["experiences"][2]["title"], "示例岗位戊")
        self.assertEqual(profile["education"][0]["degree"], "硕士")
        self.assertEqual((profile["education"][0]["start"], profile["education"][0]["end"]), ("2016-09", "2019-06"))

    def test_illegible_markers_are_stripped_and_empty_lines_dropped(self):
        text = (
            "## 工作经历\n\n"
            "### 示例公司己\n"
            "- [[ILLEGIBLE]]\n"
            "- 与 [[ILLEGIBLE]]\n"
            "- 负责示例模块 [[ILLEGIBLE]] 的数据整理\n"
        )
        profile = backend._extract_profile_from_cv(text)
        summary = profile["experiences"][0]["summary"]
        self.assertNotIn("ILLEGIBLE", summary)
        self.assertIn("负责示例模块", summary)
        self.assertIn("的数据整理", summary)
        self.assertNotIn("与。", summary)
        self.assertEqual(summary.count("负责示例模块"), 1)

    def test_unparseable_fields_stay_empty_without_invented_content(self):
        text = "# 示例人物\n\n## Skills\n\n- 无\n"
        profile = backend._extract_profile_from_cv(text)
        self.assertEqual(profile["experiences"], [])
        self.assertEqual(profile["projects"], [])
        self.assertEqual(profile["education"], [])
        self.assertEqual(profile["job_intent"]["titles"], [])
        self.assertIsNone(profile["job_intent"]["salary_min"])
        self.assertIsNone(profile["job_intent"]["salary_max"])
        self.assertEqual(profile["basic"]["email"], "")
        self.assertEqual(profile["basic"]["phone"], "")
        self.assertEqual(profile["summary"], "")

    def test_import_prefers_workspace_resume_over_runtime_resume(self):
        runtime_body = "# 示例运行时简历\n\n## Work Experience\n\n### 示例公司庚\n**示例岗位庚**\n2022.01-2022.06\n- 运行时示例要点\n"
        result, _ = self._run_import(self.RESUME, {"resume.md": runtime_body})
        self.assertEqual(result["profile"]["experiences"][0]["company"], "示例公司甲")
        self.assertEqual(result["source"], "workspace/resume.md")

    def test_import_falls_back_to_runtime_markdown_resume_when_workspace_missing(self):
        runtime_body = "# 示例运行时简历\n\n## Work Experience\n\n### 示例公司庚\n**示例岗位庚**\n2022.01-2022.06\n- 运行时示例要点\n"
        result, _ = self._run_import(None, {"resume.md": runtime_body}, cv_exists=False)
        self.assertEqual(result["profile"]["experiences"][0]["company"], "示例公司庚")
        self.assertEqual(result["profile"]["experiences"][0]["start"], "2022-01")
        self.assertIn("运行时示例要点", result["profile"]["experiences"][0]["summary"])
        self.assertIn("采集页", result["source"])

    def test_import_rejects_non_markdown_runtime_resume_and_missing_everywhere(self):
        with self.assertRaises(backend.ApiError) as ctx:
            self._run_import(None, {"resume.pdf": "%PDF-示例"}, cv_exists=False)
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("Markdown", ctx.exception.message)
        with self.assertRaises(backend.ApiError) as ctx:
            self._run_import(None, {}, cv_exists=False)
        self.assertEqual(ctx.exception.status, 404)

    def test_demo_mode_still_refuses_cv_import(self):
        with self.assertRaises(backend.ApiError) as ctx:
            backend.import_profile_cv({"mode": "demo"})
        self.assertIn("演示模式", ctx.exception.message)

    def test_profile_flags_report_saved_and_cv_availability_without_touching_real_data(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cv_path = root / "workspace" / "resume.md"
            cv_path.parent.mkdir(parents=True, exist_ok=True)
            cv_path.write_text(self.RESUME, encoding="utf-8")
            runtime = root / "runtime"
            (runtime / "data" / "resumes").mkdir(parents=True, exist_ok=True)
            with patch.object(backend, "CV_PATH", cv_path), \
                    patch.object(backend.offerpilot_runtime, "runtime_dir", lambda mode: runtime), \
                    patch.object(backend, "WEB_DIR", root):
                store = backend.Store("user")
                fresh = backend.profile_for_api("user", store)
                self.assertIs(fresh["saved"], False)
                self.assertIs(fresh["cv_available"], True)
                self.assertIn("completeness", fresh)
                self.assertEqual(fresh["basic"]["name"], "")
                self.assertIs(backend.profile_for_api("demo", backend.Store("demo"))["cv_available"], False)

                cv_path.unlink()
                self.assertIs(backend.profile_for_api("user", store)["cv_available"], False)

                store.set_profile(backend.normalize_profile({"basic": {"name": "示例保存"}}))
                saved = backend.profile_for_api("user", store)
                self.assertIs(saved["saved"], True)
                self.assertEqual(saved["basic"]["name"], "示例保存")

    def test_snapshot_profile_has_only_new_keys_added_to_profile_object(self):
        snapshot = backend.snapshot("demo")
        self.assertIn("saved", snapshot["profile"])
        self.assertIs(snapshot["profile"]["cv_available"], False)
        self.assertEqual(set(snapshot), EXPECTED_SNAPSHOT_KEYS)


class OfferPilotScorerTests(unittest.TestCase):
    """六项评分（总分 100）、封顶规则，以及 schema_version 1/2 的 trace 读取。全部使用虚构数据。"""

    scorer = None

    @classmethod
    def setUpClass(cls):
        import importlib

        vendor_src = str(PROJECT_ROOT / "vendor" / "offerpilot" / "src")
        if vendor_src not in sys.path:
            sys.path.insert(0, vendor_src)
        # 直接导入真实模块：依赖缺失时测试应明确失败，而不是用假模块通过。
        cls.scorer = importlib.import_module("offerpilot.ai.scorer")

    def _payload(self, scores=None, **extra):
        values = dict(self.scorer.COMPONENT_LIMITS)
        values.update(scores or {})
        payload = {
            "role_summary": "示例产品助理岗位",
            "caps": [],
            "hard_gaps": [],
            "reason": "示例匹配判断",
            "missing": "",
        }
        for key, score in values.items():
            payload[key] = {"evidence": f"示例证据-{key}", "score": score}
        payload.update(extra)
        return payload

    def test_component_limits_are_the_six_document_items_summing_to_100(self):
        self.assertEqual(self.scorer.COMPONENT_LIMITS, {
            "core_skills": 30,
            "transferable_evidence": 25,
            "duty_similarity": 20,
            "tools_industry": 10,
            "practical_fit": 10,
            "resume_expressibility": 5,
        })
        self.assertEqual(sum(self.scorer.COMPONENT_LIMITS.values()), 100)
        self.assertNotIn("hard_requirements", self.scorer.COMPONENT_LIMITS)
        self.assertNotIn("core_duties", self.scorer.COMPONENT_LIMITS)

    def test_full_marks_sum_to_100_and_never_exceed_100(self):
        result = self.scorer.validate_structured_score_payload(self._payload())
        self.assertIsNotNone(result)
        self.assertEqual(result.raw_score, 100)
        self.assertEqual(result.score, 100)
        self.assertLessEqual(result.score, 100)
        for label in ("核心技能 30/30", "证据 25/25", "职责相似 20/20",
                      "行业偏好 10/10", "实际条件 10/10", "表达 5/5"):
            self.assertIn(label, result.reason)

    def test_any_component_over_its_limit_returns_none(self):
        for key, limit in self.scorer.COMPONENT_LIMITS.items():
            with self.subTest(component=key):
                payload = self._payload({key: limit + 1})
                self.assertIsNone(self.scorer.validate_structured_score_payload(payload))

    def test_negative_non_integer_and_bool_scores_return_none(self):
        for bad in (-1, 3.5, True, "7", None):
            with self.subTest(score=bad):
                payload = self._payload({"core_skills": bad})
                self.assertIsNone(self.scorer.validate_structured_score_payload(payload))

    def test_missing_resume_expressibility_fails_validation(self):
        payload = self._payload()
        del payload["resume_expressibility"]
        self.assertIsNone(self.scorer.validate_structured_score_payload(payload))
        self.assertIn(
            "resume_expressibility",
            self.scorer._score_validation_failure_reason(json.dumps(payload, ensure_ascii=False)),
        )

    def test_old_five_component_payload_is_rejected(self):
        legacy = {"role_summary": "示例岗位", "caps": [], "hard_gaps": [], "reason": "示例", "missing": ""}
        for key, limit in self.scorer.LEGACY_COMPONENT_LIMITS_V1.items():
            legacy[key] = {"evidence": "示例", "score": limit}
        self.assertIsNone(self.scorer.validate_structured_score_payload(legacy))

    def test_technical_required_cap_still_pins_score_to_55(self):
        result = self.scorer.validate_structured_score_payload(
            self._payload(caps=["technical_required"], hard_gaps=["示例：必须掌握某硬技术→未体现"])
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.raw_score, 100)
        self.assertEqual(result.score, 55)
        self.assertIn("硬技术缺口封顶55", result.reason)
        self.assertEqual(result.hard_gaps, ("示例：必须掌握某硬技术→未体现",))

    def test_strictest_cap_wins_when_several_caps_apply(self):
        result = self.scorer.validate_structured_score_payload(
            self._payload(caps=["weak_core_transfer", "sales_acquisition_core"])
        )
        self.assertEqual(result.score, 65)

    def test_v2_trace_has_six_components_and_round_trips(self):
        result = self.scorer.validate_structured_score_payload(
            self._payload({"core_skills": 20, "resume_expressibility": 3})
        )
        trace = self.scorer.build_score_trace(result)
        self.assertEqual(trace["schema_version"], 2)
        self.assertEqual(self.scorer.TRACE_SCHEMA_VERSION, 2)
        self.assertEqual(list(trace["components"]), list(self.scorer.COMPONENT_LIMITS))
        self.assertEqual(trace["components"]["resume_expressibility"]["max_score"], 5)
        self.assertEqual(trace["raw_score"], 88)
        self.assertEqual(trace["final_score"], 88)
        sanitized = self.scorer.sanitize_score_trace(json.loads(json.dumps(trace, ensure_ascii=False)))
        self.assertEqual(sanitized, trace)

    def test_v2_trace_with_a_missing_or_over_limit_component_is_rejected(self):
        trace = self.scorer.build_score_trace(
            self.scorer.validate_structured_score_payload(self._payload())
        )
        missing = json.loads(json.dumps(trace))
        del missing["components"]["resume_expressibility"]
        self.assertIsNone(self.scorer.sanitize_score_trace(missing))
        too_high = json.loads(json.dumps(trace))
        too_high["components"]["duty_similarity"]["score"] = 21
        self.assertIsNone(self.scorer.sanitize_score_trace(too_high))

    def test_legacy_schema_version_1_trace_is_still_readable_unchanged(self):
        legacy_trace = {
            "schema_version": 1,
            "role_summary": "示例旧版岗位",
            "components": {
                key: {"score": limit // 2, "max_score": limit, "evidence": f"示例旧证据-{key}"}
                for key, limit in self.scorer.LEGACY_COMPONENT_LIMITS_V1.items()
            },
            "raw_score": 50,
            "final_score": 50,
            "caps": ["weak_core_transfer"],
            "hard_gaps": ["示例旧版硬缺口"],
            "summary_reason": "示例旧版理由",
            "missing": "示例缺失",
            "review_status": "initial",
        }
        original = json.loads(json.dumps(legacy_trace))
        sanitized = self.scorer.sanitize_score_trace(legacy_trace)
        self.assertIsNotNone(sanitized)
        self.assertEqual(sanitized["schema_version"], 1)
        self.assertEqual(
            set(sanitized["components"]),
            {"core_duties", "transferable_evidence", "hard_requirements", "tools_industry", "practical_fit"},
        )
        self.assertEqual(sanitized, original)
        self.assertEqual(legacy_trace, original)  # 输入不会被修改

    def test_unknown_trace_schema_versions_are_rejected_without_error(self):
        trace = self.scorer.build_score_trace(
            self.scorer.validate_structured_score_payload(self._payload())
        )
        for version in (0, 3, "2", True, None):
            with self.subTest(version=version):
                self.assertIsNone(self.scorer.sanitize_score_trace(dict(trace, schema_version=version)))
        self.assertIsNone(self.scorer.sanitize_score_trace(None))
        self.assertIsNone(self.scorer.sanitize_score_trace("not-a-trace"))

    def test_scoring_prompt_formats_and_lists_exactly_the_six_fields(self):
        job = {
            "title": "示例产品助理", "company": "示例公司", "salary": "10-15K",
            "experience": "1-3年", "education": "本科", "recruitment_type": "campus",
            "jd": "负责需求整理与数据看板。",
        }
        config = {"profile": {"salary_min": 8, "salary_max": 12, "target_cities": ["示例城市"],
                              "education": "本科", "recruitment_type": "campus"}}
        prompt = self.scorer._build_scoring_prompt(job, "示例简历内容", config)
        for key in self.scorer.COMPONENT_LIMITS:
            self.assertIn(f'"{key}"', prompt)
        self.assertNotIn('"hard_requirements"', prompt)
        self.assertNotIn('"core_duties"', prompt)
        self.assertNotIn("{{", prompt)
        self.assertIn("hard_gaps中列出", prompt)

    def test_merge_review_keeps_six_components_and_stricter_cap(self):
        first = self.scorer.validate_structured_score_payload(self._payload({"core_skills": 20}))
        review = self.scorer.validate_structured_score_payload(
            self._payload({"core_skills": 10}, caps=["technical_required"]), reviewed=True
        )
        merged = self.scorer._merge_review_results(first, review)
        self.assertEqual(set(merged.components), set(self.scorer.COMPONENT_LIMITS))
        self.assertEqual(merged.components["core_skills"], 15)
        self.assertEqual(merged.score, 55)


if __name__ == "__main__":
    unittest.main()
