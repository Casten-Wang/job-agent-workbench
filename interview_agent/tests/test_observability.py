import os
import unittest
from unittest.mock import patch

from interview_agent.observability import AgentTrace, status


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_without_api_key_and_redacts_content(self):
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "", "LANGSMITH_CAPTURE_CONTENT": "true"}, clear=False):
            self.assertFalse(status()["enabled"])
            self.assertFalse(status()["capture_content"])
            trace = AgentTrace("profile_extract", {"resume_text": "private"}, {"model": "test"})
            await trace.start()
            await trace.finish(output={"name": "private"})

    async def test_trace_constructor_is_best_effort(self):
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false", "LANGSMITH_API_KEY": "test"}, clear=False):
            trace = AgentTrace("prepare", {"source": "synthetic"}, {"model": "test"})
            await trace.start()
            await trace.finish(error=RuntimeError("synthetic"))
            self.assertIsNone(trace.run)

    async def test_agent_address_uses_agent_page_without_project_conflict(self):
        class FakeRun:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def post(self): pass
            def end(self, **kwargs): pass
            def patch(self): pass
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "synthetic", "LANGSMITH_AGENT_ID": "offerpilot-local-agent", "LANGSMITH_AGENT_ENVIRONMENT": "production"}, clear=False):
            with patch("langsmith.run_trees.RunTree", FakeRun):
                trace = AgentTrace("prepare", {"source": "synthetic"}, {"model": "test"})
                self.assertIsNotNone(trace.run.kwargs["address"])
                self.assertIsNone(trace.run.kwargs["project_name"])

    async def test_enabled_trace_posts_redacted_run_and_never_blocks_product(self):
        class FakeRun:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.events = []
            def post(self):
                self.events.append("post")
            def end(self, **kwargs):
                self.events.append(("end", kwargs))
            def patch(self):
                self.events.append("patch")
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "synthetic", "LANGSMITH_CAPTURE_CONTENT": "false"}, clear=False):
            with patch("langsmith.run_trees.RunTree", FakeRun):
                trace = AgentTrace("profile_extract", {"resume_text": "private"}, {"model": "test"})
                inputs = trace.run.kwargs["inputs"]
                self.assertEqual(inputs["stage"], "profile_extract")
                self.assertIn("input_chars", inputs)
                self.assertIn("input_sha256", inputs)
                self.assertNotIn("private", inputs)
                await trace.start()
                await trace.finish(output={"name": "private"})
                self.assertEqual(trace.run.events[0], "post")
                self.assertEqual(trace.run.events[-1], "patch")


if __name__ == "__main__":
    unittest.main()
