import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

from interview_agent.evaluation import evaluate
from interview_agent.langfuse_monitor import LangfuseTrace, status
from interview_agent.model_adapter import ModelAdapter
from interview_agent.observability import AgentTrace, capture_content

ENV = {"LANGFUSE_TRACING": "true", "LANGFUSE_BASE_URL": "https://example.invalid",
       "LANGFUSE_PUBLIC_KEY": "synthetic-public", "LANGFUSE_SECRET_KEY": "synthetic-secret",
       "LANGSMITH_CAPTURE_CONTENT": "true", "LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "test"}
PRIVATE = "PRIVATE_RESUME_SOURCE_AND_ANSWER_勿上传"
INTENT = {"intent": "answer", "reason": PRIVATE, "clarification": ""}


class FakeSpan:
    def __init__(self, **kwargs):
        self.events = [kwargs]
        self.ended = False
    def update(self, **kwargs): self.events.append(kwargs)
    def score(self, **kwargs): self.events.append(kwargs)
    def end(self): self.ended = True


class FakeClient:
    def start_observation(self, **kwargs):
        self.span = FakeSpan(**kwargs)
        return self.span


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_sends_only_safe_metadata_and_scores(self):
        client = FakeClient()
        def response(request):
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"type": "function", "function": {"name": "submit_intent",
                "arguments": json.dumps(INTENT)}}]}}]})
        with patch.dict(os.environ, ENV), patch("interview_agent.langfuse_monitor.client", return_value=client):
            adapter = await ModelAdapter({"STEP_API_KEY": "synthetic"}, transport=httpx.MockTransport(response)).start()
            try:
                self.assertEqual(await adapter.decide("intent", {"resume": PRIVATE, "source": PRIVATE}), INTENT)
            finally:
                await adapter.close()
            self.assertTrue(client.span.ended)
            payload = json.dumps(client.span.events)
            self.assertNotIn(PRIVATE, payload)
            self.assertNotIn("synthetic-secret", payload)
            self.assertIn('"schema_valid"', payload)
            self.assertFalse(capture_content())

    async def test_errors_and_unknown_stage_cannot_leak(self):
        client = FakeClient()
        with patch("interview_agent.langfuse_monitor.client", return_value=client):
            trace = LangfuseTrace(PRIVATE, {"resume": PRIVATE})
            trace.start()
            await asyncio.to_thread(trace.finish, None, RuntimeError(PRIVATE))
            self.assertNotIn(PRIVATE, json.dumps(client.span.events))
            self.assertTrue(client.span.ended)

    async def test_telemetry_failure_never_breaks_business(self):
        with patch("interview_agent.langfuse_monitor.client", side_effect=RuntimeError(PRIVATE)):
            trace = AgentTrace("intent", {}, {})
            await trace.start()
            await trace.finish(INTENT)

    async def test_evaluation_failure_closes_span_without_private_reason(self):
        client = FakeClient()
        with patch("interview_agent.langfuse_monitor.client", return_value=client), patch(
                "interview_agent.evaluation.evaluate", side_effect=ValueError(PRIVATE)):
            trace = LangfuseTrace("intent", {})
            trace.start()
            trace.finish(INTENT)
            self.assertTrue(client.span.ended)
            self.assertNotIn(PRIVATE, json.dumps(client.span.events))
            self.assertIn({"name": "evaluation_completed", "value": 0.0}, client.span.events)

    async def test_real_sdk_exports_no_content_or_unrelated_spans(self):
        from langfuse import Langfuse
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        requests = []
        def handler(request):
            requests.append(request.content.decode())
            return httpx.Response(200, json={"successes": [], "errors": []})
        exporter = InMemorySpanExporter()
        lf = Langfuse(public_key="synthetic-wire-test", secret_key="synthetic", base_url="https://example.invalid",
                      tracer_provider=TracerProvider(), span_exporter=exporter,
                      httpx_client=httpx.Client(transport=httpx.MockTransport(handler)))
        try:
            unrelated = TracerProvider()
            with unrelated.get_tracer("unrelated").start_as_current_span(PRIVATE) as span:
                span.set_attribute("private", PRIVATE)
            with patch("interview_agent.langfuse_monitor.client", return_value=lf):
                trace = LangfuseTrace("intent", {"source": PRIVATE})
                trace.start()
                trace.finish(INTENT)
                lf.flush()
            spans = exporter.get_finished_spans()
            self.assertEqual(len(spans), 1)
            self.assertNotIn(PRIVATE, str(spans[0].attributes))
            self.assertTrue(requests)
            self.assertNotIn(PRIVATE, "".join(requests))
            self.assertIn("schema_valid", "".join(requests))
        finally:
            lf.shutdown()


class EvaluationTests(unittest.TestCase):
    def test_project_references_and_numeric_claims(self):
        source = "访谈12位用户，整理反馈。"
        output = {"summary": "需求分析", "claims": [{"text": source,
                  "source_quote": source, "evidence_ids": ["E1"]}]}
        inputs = {"evidence": [{"evidence_id": "E1", "text": source}]}
        self.assertEqual(evaluate("prepare_experience", inputs, output)["experience_source_supported"], 1)
        output["claims"][0]["text"] = "访谈120位用户。"
        self.assertEqual(evaluate("prepare_experience", inputs, output)["experience_source_supported"], 0)
        output["claims"][0]["evidence_ids"] = ["missing"]
        self.assertEqual(evaluate("prepare_experience", inputs, output)["evidence_references_valid"], 0)

    def test_schema_and_unknown_stage(self):
        self.assertEqual(evaluate("intent", {}, INTENT), {"schema_valid": 1.0})
        self.assertEqual(evaluate("intent", {}, {"intent": "invalid"}), {"schema_valid": 0.0})
        self.assertEqual(evaluate("unknown", {}, {}), {})

    def test_extract_fabrication_and_supported_fields(self):
        output = {"basic": {"name": "Alice"}, "job_intent": {}, "skills": {},
                  "education": [], "experiences": [], "projects": [], "summary": ""}
        self.assertEqual(evaluate("profile_extract", {"resume_text": "Alice"}, output)["extracted_fields_supported"], 1)
        self.assertEqual(evaluate("profile_extract", {"resume_text": "Bob"}, output)["extracted_fields_supported"], 0)

    def test_disabled_and_insecure_endpoint(self):
        with patch.dict(os.environ, ENV):
            self.assertTrue(status()["enabled"])
            with patch.dict(os.environ, {"LANGFUSE_BASE_URL": "http://remote.example"}):
                self.assertFalse(status()["enabled"])
            with patch.dict(os.environ, {"LANGFUSE_SECRET_KEY": ""}):
                self.assertFalse(status()["enabled"])
            with patch.dict(os.environ, {"LANGFUSE_BASE_URL": "https://[invalid"}):
                self.assertFalse(status()["enabled"])


if __name__ == "__main__":
    unittest.main()
