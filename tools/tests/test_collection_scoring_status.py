"""A model pause must not turn a partially scored collection into success."""
from pathlib import Path
from threading import Event
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor/offerpilot/src"))
from offerpilot.collection.models import JobCandidate, PlatformCollectionResult
from offerpilot.collection.orchestrator import CollectionOrchestrator
from offerpilot.collection.registry import CollectorRegistry
from offerpilot.collection_run_store import get_collection_run


class CollectionScoringStatusTests(unittest.TestCase):
    def run_collection(self, checkpoint, *, stop=False):
        class Collector:
            def collect(self, request, hooks):
                hooks.on_candidate(JobCandidate(
                    platform="boss", source_job_id="test-job", title="开发实习生",
                    company="测试科技", city="上海", jd="负责应用开发",
                ))
                return PlatformCollectionResult("boss", "completed")

        event = Event()
        observed = []

        def score(config, **kwargs):
            if stop:
                event.set()
            config["_workbench_score_checkpoint"](checkpoint)

        options = {
            "platform_order": ["boss"], "auto_score": True,
            "platforms": {"boss": {"keywords": ["开发"], "cities": ["上海"],
                                    "city_codes": {"上海": "101020100"}, "max_pages": 1}},
        }
        with tempfile.TemporaryDirectory() as tmp, patch(
            "offerpilot.collection.orchestrator.normalize_collection_options", return_value=options
        ), patch("offerpilot.ai.scorer.score_jobs", side_effect=score):
            path = Path(tmp) / "jobs.db"
            result = CollectionOrchestrator(
                {"profile": {"allow_internship": True}, "_workbench_stop_event": event,
                 "_workbench_score_checkpoint": observed.append},
                db_path=path, registry=CollectorRegistry({"boss": Collector}),
            ).run(options)
            saved = get_collection_run(path, result["run_id"])
        self.assertEqual(observed, [checkpoint])
        self.assertEqual(len(result["collected_job_ids"]), 1)
        self.assertEqual(saved["collected_job_ids"], result["collected_job_ids"])
        self.assertEqual(saved["status"], result["status"])
        return result, saved

    def test_network_pause_preserves_jobs_and_reports_incomplete(self):
        result, saved = self.run_collection({
            "status": "paused", "remaining_job_ids": ["test-job"],
            "pause_reason": "AI 服务连接失败 (network)", "error": "AI 服务连接失败 (network)",
        })
        self.assertEqual(result["status"], "completed_with_errors")
        self.assertIn("剩余 1 个岗位", result["error"])
        self.assertEqual(saved["error"], result["error"])

    def test_completed_scoring_stays_successful(self):
        result, saved = self.run_collection({"status": "completed", "remaining_job_ids": []})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["error"], "")

    def test_user_stop_during_scoring_stays_stopped(self):
        result, saved = self.run_collection({
            "status": "paused", "remaining_job_ids": ["test-job"], "pause_reason": "用户暂停",
        }, stop=True)
        self.assertEqual(result["status"], "stopped")


if __name__ == "__main__":
    unittest.main()
