import asyncio
import json
import unittest

import httpx

from interview_agent.model_adapter import ModelAdapter, ModelError
from interview_agent.model_stream import public_text


def event(delta, finish=None):
    return ("data: " + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}, ensure_ascii=False) + "\n\n").encode()


class ModelStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_arrives_before_provider_finishes_and_final_schema_is_validated(self):
        partial, release, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        texts, requests = [], []
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield event({"reasoning_content": "PRIVATE_REASONING", "content": '{"decision":{"action":"reply","message":"你好'})
                await release.wait()
                yield event({"content": '，世界😀","arguments":{}}}'}, "stop")
                yield b"data: [DONE]\n\n"
            async def aclose(self):
                closed.set()
        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Body())
        async def receive(text):
            texts.append(text)
            if text:
                partial.set()
        adapter = await ModelAdapter({"STEP_API_KEY": "synthetic-stream-key"}, transport=httpx.MockTransport(handler)).start()
        task = asyncio.create_task(adapter.decide_stream("workbench_decide", {}, receive))
        try:
            await asyncio.wait_for(partial.wait(), 2)
            self.assertFalse(task.done())
            self.assertEqual(texts[-1], "你好")
            self.assertTrue(requests[0]["stream"])
            self.assertTrue(requests[0]["response_format"]["json_schema"]["strict"])
            release.set()
            result = await task
            self.assertEqual(result["message"], "你好，世界😀")
            self.assertEqual(texts[-1], result["message"])
            self.assertNotIn("PRIVATE_REASONING", "".join(texts))
            self.assertTrue(closed.is_set())
        finally:
            release.set()
            await adapter.close()

    async def test_public_extraction_never_streams_actions_arguments_or_references(self):
        self.assertEqual(public_text("workbench_decide", '{"decision":{"action":"search_jobs","message":"PRIVATE","arguments":{"query":"SECRET"}}}'), "")
        self.assertEqual(public_text("workbench_draft", '{"bullets":[{"text":"实际工作","claim_ids":["PRIVATE_ID"]}],"greeting":"您好"}'), "实际工作\n\n您好")
        self.assertEqual(public_text("prepare_experience", '{"claims":[{"text":"参与校验","source_quote":"PRIVATE_QUOTE","evidence_ids":["E1"]}]}'), "参与校验")
        self.assertEqual(public_text("workbench_decide", '{"decision":{"message":"先缓冲","action":"rep'), "")
        self.assertEqual(public_text("workbench_decide", '{"decision":{"message":"先缓冲","action":"reply"'), "先缓冲")

    async def test_repair_replaces_provisional_text_and_keeps_strict_validation(self):
        calls, texts = [], []
        def handler(request):
            calls.append(json.loads(request.content))
            decision = {"action": "reply", "message": "正确回复" if len(calls) > 1 else "待修正", "arguments": {}}
            if len(calls) == 1:
                decision["unknown"] = True
            raw = json.dumps({"decision": decision}, ensure_ascii=False)
            return httpx.Response(200, content=event({"content": raw}, "stop") + b"data: [DONE]\n\n")
        async def receive(text):
            texts.append(text)
        adapter = await ModelAdapter({"STEP_API_KEY": "synthetic-stream-key"}, transport=httpx.MockTransport(handler)).start()
        try:
            result = await adapter.decide_stream("workbench_decide", {}, receive)
            self.assertEqual(result["message"], "正确回复")
            self.assertEqual(texts, ["", "待修正", "", "正确回复"])
            self.assertEqual(len(calls), 2)
        finally:
            await adapter.close()

    async def test_cancel_closes_provider_stream(self):
        entered, closed = asyncio.Event(), asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield event({"content": '{"decision":{"action":"reply","message":"部分文字'})
                entered.set()
                await asyncio.Event().wait()
            async def aclose(self):
                closed.set()
        async def receive(text):
            pass
        adapter = await ModelAdapter({"STEP_API_KEY": "synthetic-stream-key"}, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=Body()))).start()
        try:
            task = asyncio.create_task(adapter.decide_stream("workbench_decide", {}, receive))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(closed.is_set())
        finally:
            await adapter.close()

    async def test_stream_without_finish_reason_is_not_accepted(self):
        wire = event({"content": '{"decision":{"action":"reply","message":"半句'})
        async def receive(text):
            pass
        adapter = await ModelAdapter({"STEP_API_KEY": "synthetic-stream-key"}, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=wire))).start()
        try:
            with self.assertRaises(ModelError) as error:
                await adapter.decide_stream("workbench_decide", {}, receive)
            self.assertEqual(error.exception.code, "invalid_model_stream")
        finally:
            await adapter.close()

    async def test_tool_argument_stream_uses_only_public_text_and_still_validates_evidence(self):
        value = {"summary": "参与校验", "project_name": "合成项目", "project_overview": "校验输入", "positioning": "后端",
                 "claims": [{"text": "参与输入校验。", "pillar": "校验", "evidence_ids": ["E1"], "source_quote": "参与输入校验。"}]}
        args = json.dumps(value, ensure_ascii=False)
        first = args.index("校验输入") + 2
        wire = event({"tool_calls": [{"index": 0, "id": "call_test", "type": "function",
            "function": {"name": "submit_prepare_experience", "arguments": args[:first]}}]})
        wire += event({"tool_calls": [{"index": 0, "function": {"arguments": args[first:]}}]}, "tool_calls")
        wire += b"data: [DONE]\n\n"
        texts = []
        async def receive(text):
            texts.append(text)
        adapter = await ModelAdapter({"STEP_API_KEY": "synthetic-stream-key"}, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=wire))).start()
        try:
            result = await adapter.decide_stream("prepare_experience", {"evidence": [{"evidence_id": "E1", "text": "参与输入校验。"}]}, receive)
            self.assertEqual(result["claims"][0]["text"], "参与输入校验。")
            self.assertTrue(any(text and text != texts[-1] for text in texts))
            self.assertNotIn('"source_quote"', texts[-1])
            self.assertNotIn("E1", texts[-1])
        finally:
            await adapter.close()
