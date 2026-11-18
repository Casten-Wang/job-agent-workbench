#!/usr/bin/env python3
"""Covers the 置信 column, the low-score marker and the update-time semantics.

- The queue's 判断置信度 column reads ``fit_confidence`` from the snapshot.
- Enqueue no longer writes the ``high_threshold: 101`` override.
- Enqueue no longer compares a numeric threshold, so the frontend has no
  low-score / 入队线 marker at all; only unscored jobs need a manual add.
- Local write times (``created_at``/``updated_at``) never become a platform
  update time, and imported rows without a platform date have no
  ``posted_at``/``source_updated_at``.

Every test uses in-memory fakes or a temporary directory; nothing touches
``web/data`` and nothing calls the network.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "web"), str(PROJECT_ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import job_match  # noqa: E402
import job_risk  # noqa: E402
import job_standardize  # noqa: E402

APP_JS = PROJECT_ROOT / "web" / "static" / "app.js"
TODAY = datetime.date(2026, 11, 20)


class _FakeStore:
    """Minimal store for ``enqueue`` and the OfferPilot import."""

    def __init__(self, root: Path, jobs: list, queue: list | None = None):
        self._jobs = list(jobs)
        self._queue = list(queue or [])
        self.files = {"queue": root / "approval-queue.json"}

    def jobs(self):
        return list(self._jobs)

    def all_jobs(self):
        return list(self._jobs)

    def set_jobs(self, rows):
        self._jobs = list(rows)

    def profile(self):
        return {"job_intent": {"cities": ["上海"]}}

    def queue(self):
        return list(self._queue)

    def deliveries(self):
        return []

    def log(self, *args):
        pass


def _doc_job(job_id: str, **extra: object) -> dict:
    job = {
        "id": job_id,
        "company": "虚构星河科技有限公司",
        "title": "产品经理",
        "city": "上海",
        "score": 60,
        "score_raw": 60,
        "score_coverage": 0.9,
        "scoring_model": backend.MATCH_SCORE_MODEL,
        "mandatory_status": "pending",
        "hiring_status": "unknown",
        "source_channel": "boss",
        "offerpilot_id": f"rt-{job_id}",
        "mandatory_conditions": [
            {"condition": "熟练使用 Axure", "status": "已满足", "evidence": "简历写明"},
            {"condition": "B2B 经验", "status": "待确认", "evidence": "部分"},
        ],
    }
    job.update(extra)
    return job


class _SnapshotCase(unittest.TestCase):
    """Real Store in a temporary data directory, so snapshot runs unmodified."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for patcher in (
            patch.object(backend, "WEB_DIR", self.root),
            patch.object(backend, "CV_PATH", self.root / "missing-resume.md"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def snapshot(self) -> dict:
        with patch.object(backend, "get_offerpilot_state", return_value={"ok": False}):
            return backend.snapshot("user")


class ConfidenceColumnTests(_SnapshotCase):
    """The 置信 column must show fit_confidence, not the high_confidence flag."""

    def test_frontend_uses_confidence_helper_not_flag(self) -> None:
        source = APP_JS.read_text(encoding="utf-8")
        self.assertIn("confidenceCell(row)", source)
        self.assertNotIn("row.high_confidence ? badge", source)
        self.assertIn("'判断依据'", source)

    def test_snapshot_queue_row_carries_fit_confidence(self) -> None:
        job = _doc_job("job-conf-1")
        store = backend.get_store("user")
        store.set_jobs([job])
        store.set_queue([{"id": "job-conf-1", "status": "pending", "score": 60}])
        snap = self.snapshot()
        row = next(item for item in snap["queue"] if item["id"] == "job-conf-1")
        self.assertEqual(row["fit_confidence"], job_match.fit_confidence(job))
        self.assertEqual(row["fit_confidence"], 0.75)

    def test_queue_row_without_source_job_gets_null_confidence(self) -> None:
        store = backend.get_store("user")
        store.set_jobs([])
        store.set_queue([{"id": "gone", "status": "pending", "score": 50}])
        snap = self.snapshot()
        self.assertIsNone(snap["queue"][0]["fit_confidence"])


class HighThresholdOverrideTests(unittest.TestCase):
    """Enqueue lowers approval_min to 0 and no longer forces high_threshold to 101."""

    def test_enqueue_passes_no_101_threshold_and_still_auto_approves(self) -> None:
        captured: dict = {}
        real_enqueue = backend.approval_queue.enqueue

        def spy(candidates, path, config=None):
            captured["config"] = config
            return real_enqueue(candidates, path, config=config)

        with tempfile.TemporaryDirectory() as tmp:
            store = _FakeStore(Path(tmp), [_doc_job("job-thr-1")])
            with patch.object(backend, "get_store", return_value=store), patch.object(
                backend.approval_queue, "enqueue", side_effect=spy
            ):
                result = backend.enqueue({"mode": "user", "ids": ["job-thr-1"]})
        self.assertIsNotNone(captured.get("config"))
        self.assertNotEqual(captured["config"]["score"].get("high_threshold"), 101)
        self.assertEqual(captured["config"]["score"]["approval_min"], 0)
        self.assertEqual(result["approved"], ["job-thr-1"])

    def test_high_confidence_flag_does_not_change_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _FakeStore(Path(tmp), [_doc_job("job-thr-2")])
            with patch.object(backend, "get_store", return_value=store):
                result = backend.enqueue({"mode": "user", "ids": ["job-thr-2"]})
            rows = backend.approval_queue.load_queue(store.files["queue"])
        self.assertEqual(result["approved"], ["job-thr-2"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "approved")


class ApprovalMinResidueTests(unittest.TestCase):
    """入队已不再比较数字阈值，前端不应残留 4.0 / 入队线判定。"""

    def _source(self) -> str:
        return APP_JS.read_text(encoding="utf-8")

    def test_frontend_has_no_numeric_enqueue_threshold(self) -> None:
        source = self._source()
        for marker in (
            "approvalMinOf", "approvalMin", "approval_min",
            "入队线", "低于入队线", "未达到入队线",
            "< 4.0", "4.0 评分门", "评分达到 4.0",
        ):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, source)

    def test_manual_enqueue_matches_backend_rules(self) -> None:
        source = self._source()
        self.assertIn("function jobNeedsManualEnqueue(job)", source)
        self.assertIn("enqueueJob(job, enqueueButton, needsManual)", source)
        self.assertIn("selected.filter((job) => jobNeedsManualEnqueue(job))", source)
        self.assertIn("function jobHasDocumentScore(job)", source)
        self.assertIn("job.mandatory_status === 'unsatisfied'", source)
        self.assertIn("job.hiring_status === 'closed'", source)

    def test_queue_empty_text_mentions_no_threshold(self) -> None:
        source = self._source()
        self.assertIn("待确认队列为空。到「岗位池」把想联系的岗位加入队列。", source)
        self.assertNotIn("达到入队线", source)

    def test_helper_requires_document_score_and_open_conditions(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        source = self._source()
        start = source.index("const DOC_SCORE_SCALE")
        end = source.index("function formatJobScore(job)")
        script = source[start:end] + (
            "\nconsole.log(JSON.stringify(["
            "jobNeedsManualEnqueue(null),"
            "jobNeedsManualEnqueue({}),"
            "jobNeedsManualEnqueue({score:null}),"
            "jobNeedsManualEnqueue({score:'88'}),"
            "jobNeedsManualEnqueue({score:0}),"
            "jobNeedsManualEnqueue({score:88}),"
            "jobNeedsManualEnqueue({score:88,score_coverage:0.9}),"
            "jobNeedsManualEnqueue({score:88,score_coverage:0.9,score_scale:DOC_SCORE_SCALE}),"
            "jobNeedsManualEnqueue({score:88,score_coverage:0,score_scale:DOC_SCORE_SCALE}),"
            "jobNeedsManualEnqueue({score:88,score_scale:DOC_SCORE_SCALE}),"
            "jobNeedsManualEnqueue({score:0,score_coverage:0.9,score_scale:DOC_SCORE_SCALE}),"
            "jobNeedsManualEnqueue({score:88,score_coverage:0.9,score_scale:DOC_SCORE_SCALE,mandatory_status:'unsatisfied'}),"
            "jobNeedsManualEnqueue({score:88,score_coverage:0.9,score_scale:DOC_SCORE_SCALE,hiring_status:'closed'})"
            "]));\n"
        )
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=20, check=True
        )
        self.assertEqual(
            json.loads(result.stdout),
            [True, True, True, True, True, True, False, False, True, True, False, True, True],
        )


class LegacyScoreConfigTests(unittest.TestCase):
    """旧 0–5 分制阈值保留兼容，但必须注明已不参与工作台入队。"""

    def test_legacy_thresholds_are_annotated(self) -> None:
        config = json.loads(
            (PROJECT_ROOT / "tools" / "config_task06.json").read_text(encoding="utf-8")
        )
        self.assertEqual(config["score"]["approval_min"], 4.0)
        note = config["score"].get("_note") or ""
        self.assertIn("不再", note)
        self.assertIn("文档评分", note)


class UpdateTimeSemanticsTests(unittest.TestCase):
    """Local write times are never treated as the platform's update time."""

    def test_imported_runtime_row_has_no_posted_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = _FakeStore(Path(tmp), [])
            runtime = [{
                "id": "rt-time-1",
                "company": "虚构星河科技有限公司",
                "title": "产品经理",
                "city": "上海",
                "salary": "20-30K",
                "score": 80,
                "score_coverage": 0.9,
                "scoring_model": backend.MATCH_SCORE_MODEL,
                "source_platform": "boss",
                "created_at": "2026-11-16T09:00:00+08:00",
                "updated_at": "2026-11-17T10:00:00+08:00",
            }]
            backend._import_offerpilot_records(store, runtime, ["rt-time-1"])
        imported = store.all_jobs()[0]
        self.assertIsNone(imported["posted_at"])
        self.assertIsNone(job_standardize.source_updated_at(imported))
        self.assertEqual(imported["score"], 80)

    def test_legacy_imported_posted_at_is_ignored_for_offerpilot_rows(self) -> None:
        legacy = {
            "id": "legacy-1",
            "offerpilot_id": "rt-legacy-1",
            "posted_at": "2026-11-16T09:00:00+08:00",
            "updated_at": "2026-11-17T10:00:00+08:00",
        }
        self.assertIsNone(job_standardize.source_updated_at(legacy))

    def test_local_write_time_never_becomes_source_updated_at(self) -> None:
        local = {"id": "local-1", "created_at": "2026-11-16", "updated_at": "2026-11-17"}
        self.assertIsNone(job_standardize.source_updated_at(local))

    def test_explicit_source_updated_at_wins(self) -> None:
        job = {"offerpilot_id": "rt-x", "source_updated_at": "2026-11-10", "posted_at": "2026-11-01"}
        self.assertEqual(job_standardize.source_updated_at(job), "2026-11-10")

    def test_platform_posted_at_still_feeds_source_updated_at(self) -> None:
        job = {"source_channel": "boss", "posted_at": "2026-11-16 11:52:58"}
        self.assertEqual(job_standardize.source_updated_at(job), "2026-11-16 11:52:58")

    def test_stale_check_ignores_local_import_time(self) -> None:
        old_import = (TODAY - datetime.timedelta(days=200)).isoformat()
        job = {
            "title": "产品经理实习生",
            "company": "示例科技有限公司",
            "city": "上海",
            "salary_text": "200-300元/天",
            "raw_text": "负责需求调研与原型设计。",
            "offerpilot_id": "rt-stale-1",
            "posted_at": old_import,
            "created_at": old_import,
            "source_channel": "boss",
        }
        codes = [s["code"] for s in job_risk.assess_job_risk(job, today=TODAY)["signals"]]
        self.assertNotIn("stale_posting", codes)

    def test_stale_check_still_fires_for_platform_date(self) -> None:
        job = {
            "title": "产品经理实习生",
            "company": "示例科技有限公司",
            "city": "上海",
            "salary_text": "200-300元/天",
            "raw_text": "负责需求调研与原型设计。",
            "source_updated_at": (TODAY - datetime.timedelta(days=61)).isoformat(),
            "source_channel": "boss",
        }
        codes = [s["code"] for s in job_risk.assess_job_risk(job, today=TODAY)["signals"]]
        self.assertIn("stale_posting", codes)

    def test_contact_plan_candidates_do_not_use_import_time(self) -> None:
        job = _doc_job("job-plan-1", posted_at="2026-11-16T09:00:00+08:00")
        seen: list = []
        real = backend.quota_planner.plan_contact_queue

        def spy(candidates, **kwargs):
            seen.extend(candidates)
            return real(candidates, **kwargs)

        with patch.object(backend.quota_planner, "plan_contact_queue", side_effect=spy):
            backend._contact_plan(
                [{
                    "id": "job-plan-1",
                    "status": "approved",
                    "company": job["company"],
                    "title": job["title"],
                    "score": 60,
                }],
                [job],
                [],
                {},
            )
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0]["posted_at"])


class SnapshotShapeTests(_SnapshotCase):
    def test_top_level_key_count_stays_27(self) -> None:
        store = backend.get_store("user")
        store.set_jobs([_doc_job("job-shape-1")])
        snap = self.snapshot()
        self.assertEqual(len(snap), 27)

    def test_job_rows_gain_no_new_keys_from_this_change(self) -> None:
        store = backend.get_store("user")
        store.set_jobs([_doc_job("job-shape-2")])
        snap = self.snapshot()
        job_keys = set(snap["jobs"][0])
        self.assertFalse({"fit_confidence", "source_updated_at"} & job_keys)


if __name__ == "__main__":
    unittest.main()
