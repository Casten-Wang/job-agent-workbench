#!/usr/bin/env python3
"""Offline tests for TASK-06 CLI orchestration and human-in-the-loop gates."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "tools"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(f"task06_{name}", TOOLS_DIR / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


approval_queue = load_module("approval_queue")
greeting = load_module("greeting")
degrade = load_module("degrade")
orchestrator = load_module("orchestrator")


class ApprovalQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task06-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.queue = self.base / "queue.json"

    def test_high_and_mid_scores_stay_pending_until_explicit_confirm(self):
        jobs = [
            {"id": "high", "score": 4.7, "company": "虚构甲公司", "title": "AI产品经理", "Source_Channel": "manual"},
            {"id": "mid", "score": 4.2, "company": "虚构乙公司", "title": "商业分析师", "Source_Channel": "export"},
        ]
        result = approval_queue.enqueue(jobs, self.queue)
        self.assertEqual(result["accepted"], ["high", "mid"])
        rows = approval_queue.load_queue(self.queue)
        self.assertEqual([row["status"] for row in rows], ["pending", "pending"])
        self.assertEqual(rows[0]["high_confidence"], True)
        self.assertEqual(rows[1]["high_confidence"], False)
        confirmed = approval_queue.confirm(["high", "missing-id"], self.queue)
        self.assertEqual(confirmed["confirmed"], ["high"])
        self.assertEqual(confirmed["not_found"], ["missing-id"])
        self.assertFalse(confirmed["auto_submit"])
        rows = approval_queue.load_queue(self.queue)
        self.assertEqual(rows[0]["status"], "approved")
        self.assertEqual(rows[1]["status"], "pending")

    def test_low_score_dropped_and_duplicate_not_added(self):
        jobs = [
            {"id": "low", "score": 3.9, "company": "虚构低分公司", "title": "产品经理"},
            {"id": "same", "score": 4.5, "company": "虚构甲公司", "title": "产品经理"},
            {"id": "same", "score": 4.5, "company": "虚构甲公司", "title": "产品经理"},
        ]
        result = approval_queue.enqueue(jobs, self.queue)
        self.assertEqual(result["dropped"], ["low"])
        self.assertEqual(result["duplicate"], ["same"])
        self.assertEqual(len(approval_queue.load_queue(self.queue)), 1)

    def test_daily_pending_report_does_not_auto_approve(self):
        approval_queue.enqueue(
            [{"id": "job-a", "score": 4.6, "company": "虚构甲公司", "title": "产品经理", "Source_Channel": "manual"}],
            self.queue,
        )
        cfg = dict(orchestrator.load_config())
        cfg["approval"] = dict(cfg["approval"], report_dir=str(self.base), queue_path=str(self.queue))
        args = orchestrator.build_parser().parse_args(["approve", "--date", "2026-11-14"])
        with contextlib.redirect_stdout(io.StringIO()):
            result = orchestrator.cmd_approve(args, cfg, [])
        report = Path(result["report"])
        text = report.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertFalse(result["auto_approved"])
        self.assertIn("pending", text)
        self.assertIn("--confirm", text)
        self.assertEqual(approval_queue.load_queue(self.queue)[0]["status"], "pending")


class GreetingTests(unittest.TestCase):
    def test_greeting_under_150_chars_uses_cv_facts_and_has_no_invented_digits(self):
        cv = "测试数据：技能：需求分析、用户调研、产品设计、Axure。"
        result = greeting.make_greeting({"company": "虚构甲公司", "title": "产品经理"}, cv)
        self.assertLessEqual(result["length"], 150)
        self.assertIn("需求分析", result["greeting"])
        self.assertIn("虚构甲公司", result["greeting"])
        self.assertNotIn("5年", result["greeting"])
        self.assertNotIn("30%", result["greeting"])
        self.assertEqual(result["send_status"], "draft_only_not_sent")

    def test_overlong_input_truncates_and_warns(self):
        cv = "测试数据：需求分析、用户调研、产品设计、Axure、Visio。"
        long_company = "虚构" + "甲" * 300
        result = greeting.make_greeting({"company": long_company, "title": "产品经理"}, cv)
        self.assertLessEqual(result["length"], 150)
        self.assertIn("greeting-truncated-to-150-chars", result["warnings"])

    def test_numeric_jd_fields_are_not_included_as_facts(self):
        result = greeting.make_greeting({"company": "虚构3甲公司", "title": "P7产品经理"}, "需求分析")
        self.assertNotIn("虚构3甲公司", result["greeting"])
        self.assertNotIn("P7", result["greeting"])
        self.assertIn("jd-title-or-company-contains-numeric-characters-not-included", result["warnings"])


class DegradeAndOrchestratorTests(unittest.TestCase):
    def test_degrade_warns_and_appends_structured_log(self):
        with tempfile.TemporaryDirectory(prefix="task06-degrade-") as folder:
            log = Path(folder) / "nested" / "degrade.log"
            cfg = dict(degrade.load_config(), degrade_log=str(log))
            module, warning = degrade.load_module_safely("missing_module", Path(folder) / "missing.py", cfg)
            lines = log.read_text(encoding="utf-8").splitlines()
        self.assertIsNone(module)
        self.assertEqual(warning["status"], "module_unavailable")
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["module"], "missing_module")
        self.assertIn("action", warning)

    def test_intake_cli_and_illegal_status_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="task06-cli-") as folder:
            base = Path(folder)
            jd = base / "jd.md"
            jd.write_text("测试数据\n公司：虚构甲公司\n岗位：产品经理\n城市：上海\n薪资：20k-30k\n", encoding="utf-8")
            out = base / "intake.json"
            parser = orchestrator.build_parser()
            args = parser.parse_args(["intake", "--input", str(jd), "--out", str(out), "--id", "test-job"])
            with contextlib.redirect_stdout(io.StringIO()):
                result = orchestrator.cmd_intake(args, orchestrator.load_config(), [])
            record = json.loads(out.read_text(encoding="utf-8"))
            cfg = dict(orchestrator.load_config())
            cfg["approval"] = dict(cfg["approval"], queue_path=str(base / "queue.json"))
            warning = []
            with mock.patch.object(orchestrator, "_resolve", side_effect=lambda value: (base / "status-log.jsonl") if str(value).endswith("status-log.jsonl") else Path(value) if Path(value).is_absolute() else PROJECT_ROOT / value):
                illegal = orchestrator.cmd_status(parser.parse_args(["status", "--id", "test-job", "--to", "Offer"]), cfg, warning)
            self.assertTrue(result["ok"])
            self.assertEqual(record["id"], "test-job")
            self.assertEqual(record["hard_filter"]["status"], "pass")
            self.assertFalse(illegal["ok"])
            self.assertEqual(illegal["error"], "illegal-transition")

    def test_demo_generates_report_with_all_steps_and_no_approved_or_submitted_state(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result = orchestrator.cmd_demo(
                orchestrator.build_parser().parse_args(["demo"]),
                orchestrator.load_config(),
                [],
            )
        text = Path(result["report"]).read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertEqual(result["steps"], 7)
        self.assertFalse(result["auto_submit"])
        self.assertEqual(len([line for line in text.splitlines() if line.startswith("## ")]), 9)
        self.assertIn("已自动验证", text)
        self.assertIn("需人工验证", text)
        self.assertIn("未实现", text)
        self.assertIn("未显式 confirm", text)
        self.assertNotIn('"status": "approved"', text)
        demo_queue = json.loads((PROJECT_ROOT / "demo" / "approval-queue-demo.json").read_text(encoding="utf-8"))
        self.assertEqual([row["status"] for row in demo_queue], ["pending", "pending"])


if __name__ == "__main__":
    unittest.main()
