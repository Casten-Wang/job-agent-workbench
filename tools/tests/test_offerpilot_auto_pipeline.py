#!/usr/bin/env python3
"""Tests for the automatic collection → confirmation-gate pipeline.

All job data is fictional.  The real runtime is never started: the collection
task is replaced with a no-op and runtime job reads/greeting starts are mocked.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(TOOLS_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402  (local module in web/)
import offerpilot_runtime  # noqa: E402
from offerpilot.web import server as vendor_server  # noqa: E402
from offerpilot.web.tasks import WorkbenchTask  # noqa: E402


def _runtime_job(job_id: str, **overrides: object) -> dict:
    job = {
        "id": job_id,
        "company": "示例云图科技有限公司",
        "title": "AI 产品经理",
        "city": "上海·长宁",
        "salary": "15-25K",
        "status": "scored",
        "score": 85,
        "created_at": "2026-11-16T09:00:00+08:00",
    }
    job.update(overrides)
    return job


class VendorFullFlowTests(unittest.TestCase):
    def test_workbench_full_stops_right_after_scoring(self):
        task = WorkbenchTask(id="task-1", mode="full", label="采集 + 评分 + 招呼语")
        db = MagicMock()
        with patch.object(vendor_server, "_execute_collect") as collect, patch.object(
            vendor_server, "_get_web_db", return_value=db
        ), patch.object(vendor_server, "get_jobs_ready_to_send", return_value=[]), patch.object(
            vendor_server, "get_jobs_pending_confirmation", return_value=[{"score": 64}, {"score": 72}]
        ), patch.object(vendor_server, "_execute_deliver") as deliver:
            vendor_server._execute_full(task, {
                "scoring": {"threshold": 71},
                "_workbench_auto_pipeline": True,
                "_collection_options": {
                    "platform_order": ["boss"],
                    "platforms": {"boss": {}},
                    "auto_score": True,
                },
            })
        collect.assert_called_once()
        deliver.assert_not_called()
        self.assertFalse(task.context.get("waiting_confirmation"))
        self.assertTrue(task.context.get("confirmation_complete"))
        self.assertNotIn("confirmation_event", task.context)
        self.assertTrue(any("最终确认门" in line for line in task.logs), task.logs)
        # 64 < 71 被运行时门槛过滤；只有 72 达标（0–100 分制）。
        self.assertTrue(any("1 个岗位评分达标" in line for line in task.logs), task.logs)


class RuntimeStartTests(unittest.TestCase):
    def _fake_server(self) -> MagicMock:
        server = MagicMock()
        server.task_runner.start.return_value = {"id": "task-1", "mode": "full", "status": "running"}
        server._preflight_messages.return_value = []
        return server

    def _options(self) -> dict:
        return {
            "platform_order": ["boss"],
            "platforms": {"boss": {"keywords": ["示例产品"], "cities": ["上海"], "max_pages": 1}},
            "auto_score": True,
            "pace": "cautious",
        }

    def test_full_mode_sets_the_auto_pipeline_flag(self):
        server = self._fake_server()
        with patch.object(offerpilot_runtime, "load_backend", return_value=server), patch.object(
            offerpilot_runtime, "_resume_blocker", return_value=None
        ), patch("offerpilot.web.preflight.collect_preflight_checks", return_value=[]), patch(
            "offerpilot.web.preflight.error_messages", return_value=[]
        ):
            result = offerpilot_runtime.start_task("full", self._options())
        mode, config = server.task_runner.start.call_args.args
        self.assertEqual(mode, "full")
        self.assertIs(config["_workbench_auto_pipeline"], True)
        self.assertTrue(result["auto_pipeline"])

    def test_collect_mode_leaves_the_flag_off(self):
        server = self._fake_server()
        with patch.object(offerpilot_runtime, "load_backend", return_value=server), patch.object(
            offerpilot_runtime, "_resume_blocker", return_value=None
        ), patch("offerpilot.web.preflight.collect_preflight_checks", return_value=[]), patch(
            "offerpilot.web.preflight.error_messages", return_value=[]
        ):
            result = offerpilot_runtime.start_task("collect", self._options())
        _mode, config = server.task_runner.start.call_args.args
        self.assertNotIn("_workbench_auto_pipeline", config)
        self.assertFalse(result["auto_pipeline"])


class ThresholdScaleTests(unittest.TestCase):
    def test_live_threshold_pair_maps_runtime_gate_onto_queue_gate(self):
        with patch.object(offerpilot_runtime, "get_score_threshold", return_value=71):
            raw, workbench = backend._offerpilot_thresholds()
        self.assertEqual((raw, workbench), (71.0, 4.0))
        self.assertEqual(backend._offerpilot_score(71, raw, workbench), 4.0)
        self.assertEqual(backend._offerpilot_score(64, raw, workbench), 3.6)
        self.assertEqual(backend._offerpilot_score(72, raw, workbench), 4.1)

    def test_mapping_follows_a_changed_runtime_threshold(self):
        with patch.object(offerpilot_runtime, "get_score_threshold", return_value=60):
            raw, workbench = backend._offerpilot_thresholds()
        self.assertEqual((raw, workbench), (60.0, 4.0))
        # 运行时门槛整体下移时，映射跟着移动，两个门仍同时通过/拒绝。
        self.assertEqual(backend._offerpilot_score(60, raw, workbench), 4.0)
        self.assertEqual(backend._offerpilot_score(58, raw, workbench), 3.9)

    def test_36_fails_and_40_passes_the_real_queue_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            class _Store:
                def __init__(self):
                    self.files = {"queue": Path(tmp) / "approval-queue.json"}

                def jobs(self):
                    return [
                        {"id": "job-3-6", "company": "示例丙公司", "title": "产品经理",
                         "city": "上海", "score": 3.6, "source_channel": "boss", "offerpilot_id": "rt-64"},
                        {"id": "job-4-0", "company": "示例丁公司", "title": "产品经理",
                         "city": "上海", "score": 4.0, "source_channel": "boss", "offerpilot_id": "rt-71"},
                    ]

                def profile(self):
                    return {"job_intent": {"cities": ["上海"]}}

                def queue(self):
                    return []

                def deliveries(self):
                    return []

                def log(self, *args):
                    pass

            store = _Store()
            with patch.object(backend, "get_store", return_value=store):
                result = backend.enqueue({"mode": "user", "ids": ["job-3-6", "job-4-0"]})
        self.assertEqual(result["approved"], ["job-4-0"])
        self.assertIn("job-3-6", result["dropped"])

    def test_runtime_reads_the_configured_threshold(self):
        class _Server:
            CONFIG_PATH = Path("config.yaml")

        with patch.object(offerpilot_runtime, "load_backend", return_value=_Server()), patch(
            "offerpilot.config.load_config", return_value={"scoring": {"threshold": 71}}
        ):
            self.assertEqual(offerpilot_runtime.get_score_threshold(), 71)
        with patch.object(offerpilot_runtime, "load_backend", return_value=_Server()), patch(
            "offerpilot.config.load_config", return_value={"scoring": {"threshold": "bad"}}
        ):
            self.assertEqual(offerpilot_runtime.get_score_threshold(), 71)


class AutoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.web_dir_patch = patch.object(backend, "WEB_DIR", Path(self.tmp.name))
        self.web_dir_patch.start()
        self.addCleanup(self.web_dir_patch.stop)
        self.store = backend.Store("user")
        self.store.set_profile({"job_intent": {"cities": ["上海"], "titles": ["示例产品"]}})
        self.store.set_jobs([])
        self.store.set_queue([])
        self.store.set_deliveries([])
        self.store_patch = patch.object(backend, "get_store", return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.threshold_patch = patch.object(offerpilot_runtime, "get_score_threshold", return_value=71)
        self.threshold_patch.start()
        self.addCleanup(self.threshold_patch.stop)
        backend._last_pipeline = None
        self.addCleanup(setattr, backend, "_last_pipeline", None)

        self.jobs = [
            _runtime_job("rt-shanghai", city="上海·长宁", score=85),
            _runtime_job("rt-guangzhou", company="示例星海网络有限公司", city="广州", score=85),
            _runtime_job("rt-low", company="示例低分科技有限公司", title="产品助理", score=50),
            _runtime_job("rt-no-city", company="示例无城市有限公司", title="数据分析师", city="", score=80),
        ]

    def _run(self, greetings: list[dict] | None = None):
        with patch.object(
            offerpilot_runtime, "get_jobs", return_value={"ok": True, "jobs": self.jobs}
        ), patch.object(
            offerpilot_runtime,
            "get_greetings",
            return_value={"ok": True, "greetings": greetings or []},
        ), patch.object(
            offerpilot_runtime, "start_greet_task", return_value={"task": {"id": "greet-1"}, "requested": 2}
        ) as greet, patch.object(offerpilot_runtime, "start_deliver_task") as deliver:
            result = backend.run_offerpilot_pipeline({
                "data_mode": "user",
                "task_id": "task-1",
                "ids": [job["id"] for job in self.jobs],
            })
        return result, greet, deliver

    def test_pipeline_imports_queues_and_greets_without_sending(self):
        result, greet, deliver = self._run()
        self.assertTrue(result["ok"])
        self.assertEqual(result["imported"]["added"], 4)
        self.assertIs(result["auto_submit"], False)
        self.assertTrue(result["awaiting_confirmation"])

        jobs_by_vendor = {str(job["offerpilot_id"]): job for job in self.store.jobs()}
        approved = {
            str(row["id"]) for row in self.store.queue() if row.get("status") == "approved"
        }
        self.assertEqual(approved, {
            str(jobs_by_vendor["rt-shanghai"]["id"]),
            str(jobs_by_vendor["rt-no-city"]["id"]),
        })
        # 广州被城市门拦截；50 分映射为 2.8，低于 4.0 门槛。
        self.assertEqual(
            {item["id"] for item in result["queued"]["city_blocked"]},
            {str(jobs_by_vendor["rt-guangzhou"]["id"])},
        )
        self.assertIn(str(jobs_by_vendor["rt-low"]["id"]), result["queued"]["dropped"])
        greet.assert_called_once()
        self.assertEqual(sorted(greet.call_args.args[0]), ["rt-no-city", "rt-shanghai"])
        deliver.assert_not_called()
        self.assertIn("最终确认门", result["message"])
        self.assertIn("尚未发送任何消息", result["message"])

    def test_pipeline_is_idempotent_on_retry(self):
        self._run()
        # The first greeting task finished before the retry: both are ready now.
        ready = [{"id": "rt-shanghai", "ready": True}, {"id": "rt-no-city", "ready": True}]
        result, greet, _deliver = self._run(greetings=ready)
        self.assertEqual(result["imported"]["added"], 0)
        self.assertEqual(result["imported"]["duplicates"], 4)
        self.assertEqual(result["queued"]["approved"], [])
        self.assertEqual(result["greeting"]["already_ready"], 2)
        greet.assert_not_called()

    def test_batch_actions_log_one_row_each(self):
        self._run()
        rows = self.store.activity(200)
        by_action: dict[str, list[dict]] = {}
        for row in rows:
            by_action.setdefault(str(row.get("action")), []).append(row)
        # 一批导入 / 入队 / 招呼语各写一行汇总，不按岗位逐条写。
        self.assertEqual(len(by_action.get("导入采集岗位", [])), 1)
        self.assertEqual(len(by_action.get("加入审批队列", [])), 1)
        self.assertEqual(len(by_action.get("生成招呼语", [])), 1)
        self.assertEqual(set(by_action["导入采集岗位"][0]), {"at", "action", "detail", "ok"})
        self.assertIn("新增 4 条", by_action["导入采集岗位"][0]["detail"])
        self.assertIn("2 条", by_action["生成招呼语"][0]["detail"])

    def test_state_reports_the_confirmation_stop(self):
        self._run()
        with patch.object(offerpilot_runtime, "get_state", return_value={
            "ok": True,
            "preferences": {},
            "capabilities": {},
            "task": None,
            "last_task": None,
            "resume": {"available": True},
        }):
            state = backend.get_offerpilot_state("user")
        self.assertTrue(state["pipeline"]["awaiting_confirmation"])
        self.assertEqual(state["pipeline"]["approved_count"], 2)
        self.assertIn("最终确认门", state["pipeline"]["message"])

    def test_action_is_registered(self):
        self.assertIs(backend.ACTIONS["offerpilot-automate"], backend.run_offerpilot_pipeline)

    def test_demo_mode_is_rejected(self):
        with self.assertRaises(backend.ApiError) as ctx:
            backend.run_offerpilot_pipeline({"data_mode": "demo", "ids": ["x"]})
        self.assertEqual(ctx.exception.status, 403)


class ActivityBatchLogTests(unittest.TestCase):
    """One activity row per import batch, never one row per job."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        web_dir_patch = patch.object(backend, "WEB_DIR", Path(self.tmp.name))
        web_dir_patch.start()
        self.addCleanup(web_dir_patch.stop)
        threshold_patch = patch.object(offerpilot_runtime, "get_score_threshold", return_value=71)
        threshold_patch.start()
        self.addCleanup(threshold_patch.stop)
        self.store = backend.Store("user")
        self.jobs = [
            _runtime_job("rt-three-1", score=85),
            _runtime_job("rt-three-2", company="示例二公司", title="数据分析师", score=80),
            _runtime_job("rt-three-3", company="示例三公司", title="产品运营", score=60),
        ]

    def _import_rows(self) -> list[dict]:
        return [row for row in self.store.activity(200) if row.get("action") == "导入采集岗位"]

    def test_three_jobs_write_one_summary_row_with_counts(self):
        backend._import_offerpilot_records(self.store, self.jobs, [job["id"] for job in self.jobs])
        rows = self._import_rows()
        self.assertEqual(len(rows), 1)
        self.assertIn("新增 3 条", rows[0]["detail"])
        self.assertIn("重复 0 条", rows[0]["detail"])
        self.assertIn("未评分 0 条", rows[0]["detail"])
        self.assertIn("回填评分 0 条", rows[0]["detail"])
        self.assertEqual(set(rows[0]), {"at", "action", "detail", "ok"})

    def test_retry_adds_one_row_per_batch_not_per_duplicate(self):
        ids = [job["id"] for job in self.jobs]
        backend._import_offerpilot_records(self.store, self.jobs, ids)
        backend._import_offerpilot_records(self.store, self.jobs, ids)
        rows = self._import_rows()
        self.assertEqual(len(rows), 2)
        # Newest first: the retry reports all three as duplicates in one row.
        self.assertIn("新增 0 条", rows[0]["detail"])
        self.assertIn("重复 3 条", rows[0]["detail"])


class DefaultModeTests(unittest.TestCase):
    def test_full_pipeline_is_the_default_mode(self):
        html = (PROJECT_ROOT / "web" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<option value="full" selected>')
        self.assertNotRegex(html, r'<option value="collect" selected>')


if __name__ == "__main__":
    unittest.main()
