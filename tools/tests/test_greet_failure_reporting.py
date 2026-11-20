"""Greeting task results must expose generation failures without sending anything."""

from pathlib import Path
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "vendor/offerpilot/src"))
sys.dont_write_bytecode = True

from offerpilot.ai import greeter  # noqa: E402
from offerpilot.web import server  # noqa: E402
from offerpilot.web.tasks import WorkbenchTask, WorkbenchTaskRunner  # noqa: E402


class GreetFailureReportingTests(unittest.TestCase):
    def run_task(self, report, generated=0, *, cancelled=False):
        task = WorkbenchTask(id="synthetic-greet", mode="greet", label="生成招呼语")
        config = {"_workbench_job_ids": ["example-job"], "profile": {"ai_greeting_enabled": True}}

        def generate(batch_config, **kwargs):
            batch_config["_workbench_greeting_report"] = report
            if cancelled:
                task.stop_reason = "用户已请求停止"
                task.stop_requested.set()
            return generated

        with patch.object(greeter, "greeting_config_error", return_value=""), patch.object(
            greeter, "_get_resume_summary", return_value="测试数据：示例大学本科，参与需求分析"
        ), patch.object(greeter, "generate_greetings", side_effect=generate), patch.object(
            server, "_execute_deliver"
        ) as deliver:
            WorkbenchTaskRunner({"greet": server._execute_greet})._run(task, config)
        deliver.assert_not_called()
        return task.snapshot()

    def test_zero_output_validation_failure_is_failed(self):
        task = self.run_task({"failed_count": 1, "materials_failed": 1})
        self.assertEqual(task["status"], "failed")
        self.assertIn("1", task["error"])
        self.assertIn("校验", task["error"])
        self.assertEqual(task["metrics"]["greet_generated"], 0)
        self.assertEqual(task["metrics"]["greet_failed"], 1)
        self.assertEqual(task["metrics"]["greet_materials_failed"], 1)

    def test_safe_validation_reasons_are_reported_with_a_limit(self):
        reasons = [f"conditions[{index}].status：不支持的状态" for index in range(4)]
        task = self.run_task({"failed_count": 1, "failure_reasons": reasons})
        self.assertEqual(task["status"], "failed")
        for reason in reasons[:3]:
            self.assertIn(reason, task["error"])
        self.assertNotIn(reasons[3], task["error"])

    def test_partial_generation_keeps_saved_output_and_reports_failure(self):
        task = self.run_task({"failed_count": 1}, generated=1)
        self.assertEqual(task["status"], "completed")
        self.assertIsNone(task["error"])
        self.assertIn("失败", task["stop_reason"])
        self.assertIn("已保存", task["stop_reason"])
        self.assertEqual(task["metrics"]["greet_generated"], 1)
        self.assertEqual(task["metrics"]["greet_failed"], 1)

    def test_preserved_manual_draft_with_material_failure_is_reported(self):
        task = self.run_task({"failed_count": 1, "materials_failed": 1, "skipped_existing": 1})
        self.assertEqual(task["status"], "completed")
        self.assertIn("失败", task["stop_reason"])
        self.assertEqual(task["metrics"]["greet_preserved"], 1)

    def test_state_conflicts_keep_their_existing_semantics(self):
        task = self.run_task({"failed_count": 0, "conflict_ids": ["example-job"]})
        self.assertEqual(task["status"], "completed")
        self.assertIsNone(task["error"])
        self.assertEqual(task["progress"]["conflict_ids"], ["example-job"])
        self.assertEqual(task["metrics"]["greet_conflicts"], 1)

    def test_cancelled_generation_stays_stopped(self):
        task = self.run_task({"failed_count": 1}, cancelled=True)
        self.assertEqual(task["status"], "stopped")
        self.assertIsNone(task["error"])
        self.assertEqual(task["stop_reason"], "用户已请求停止")

    def test_service_pause_with_zero_output_stays_failed(self):
        task = self.run_task({"failed_count": 1, "pause_reason": "服务暂时不可用"})
        self.assertEqual(task["status"], "failed")
        self.assertIn("安全暂停", task["error"])

    def test_service_pause_keeps_partial_success(self):
        task = self.run_task({"failed_count": 1, "pause_reason": "服务暂时不可用"}, generated=1)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["metrics"]["greet_pause_reason"], "服务暂时不可用")

    def test_successful_generation_keeps_completed_semantics(self):
        task = self.run_task({"failed_count": 0}, generated=1)
        self.assertEqual(task["status"], "completed")
        self.assertIsNone(task["error"])
        self.assertIsNone(task["stop_reason"])


if __name__ == "__main__":
    unittest.main()
