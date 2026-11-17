#!/usr/bin/env python3
"""Offline tests for API-005 interview stream and API-002 interview-reply.

Fake streams only. These tests never call a paid AI endpoint and never treat
a canned fallback question as a passing interviewer turn.
"""

from __future__ import annotations

import datetime as dt
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"

for _path in (str(WEB_DIR), str(TOOLS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402
import interview_chat  # noqa: E402
import server  # noqa: E402

HIDDEN_KEYS = ("blueprint", "competencies", "main_questions", "stem_intent")
SPECIFIC_ANSWER = (
    "我负责把报名转化从12%做到18%。当时在范围和上线日之间做了取舍，先砍掉分享页。"
    "第一次邀请口径失败后才改成现在的口径。"
)
VAGUE_ANSWER = "我们大概做了一些优化，还行。"
FIRST_QUESTION = "请具体讲一次你独立推进的需求。"
FOLLOWUP_QUESTION = "刚才这句里的「我们」具体是谁在做？"
NEXT_MAIN_QUESTION = "请讲一个材料里的业务场景，不要复述简历。"
RESUME_SPAN = "参与需求分析"


def _plan(*, kinds: list[str] | None = None) -> dict:
    kinds = kinds or ["resume_probe"] * 4
    return {
        "competencies": [
            {"id": "c1", "label": "需求理解", "weight": 0.25},
            {"id": "c2", "label": "项目推进", "weight": 0.25},
            {"id": "c3", "label": "沟通协作", "weight": 0.25},
            {"id": "c4", "label": "复盘意识", "weight": 0.25},
        ],
        "evidence_map": [{"competency_id": "c1", "resume_span": RESUME_SPAN}],
        "main_questions": [
            {"id": f"q{index}", "kind": kind, "stem_intent": f"内部意图{index}"}
            for index, kind in enumerate(kinds, start=1)
        ],
    }


def _seed_isolated_store() -> "backend.Store":
    """Point the single local dataset at a fresh temp dir and seed fiction."""
    store = backend.Store()
    profile = backend.default_profile()
    profile["experiences"] = [{
        "company": "虚构科技",
        "title": "实习生",
        "summary": "参与需求分析与报名转化改版",
    }]
    profile["projects"] = []
    store.set_profile(profile)
    store.set_jobs([{
        "id": "job-test-1",
        "company": "虚构公司",
        "title": "产品助理",
        "city": "上海",
        "raw_text": "负责需求分析与报名转化改版",
    }])
    store.set_debriefs([])
    store.set_interview_materials([])
    store.clear_interview_session()
    return store


def _fake_complete(plan: dict):
    def complete(system_prompt: str, user_text: str, timeout: float = 45) -> str:
        complete.calls.append({"system": system_prompt, "user": user_text, "timeout": timeout})
        return json.dumps(plan, ensure_ascii=False)

    complete.calls = []
    return complete


def _fake_stream(text: str, fail_after: int | None = None, error: str | None = None):
    def stream(system_prompt: str, user_text: str, timeout: float = 45):
        stream.calls.append({"system": system_prompt, "user": user_text, "timeout": timeout})
        if error and fail_after is None:
            raise interview_chat.StreamGenerationError(error)
        for index, char in enumerate(text):
            if fail_after is not None and index >= fail_after:
                raise interview_chat.StreamGenerationError("timeout")
            yield char

    stream.calls = []
    return stream


def _collect(events) -> list[tuple[str, dict]]:
    return list(events)


def _parse_sse(raw: bytes) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        event_name = ""
        data = {}
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
        events.append((event_name, data))
    return events


def _hidden_in(value: object) -> None:
    encoded = json.dumps(value, ensure_ascii=False)
    for key in HIDDEN_KEYS:
        if f'"{key}"' in encoded:
            raise AssertionError(f"public payload leaked {key}")
    if "target_answers" in encoded or "10 问" in encoded:
        raise AssertionError("payload restored 10-question counting")


class InterviewChatStreamUnitTests(unittest.TestCase):
    def test_prompt_file_matches_chat_contract(self):
        prompt = interview_chat.load_chat_system_prompt()
        self.assertIn("只输出当前这一问的中文正文", prompt)
        self.assertIn("move=followup", prompt)
        self.assertIn("resume_probe", prompt)
        self.assertIn("business_scenario", prompt)
        self.assertNotIn("target_answers", prompt)
        self.assertNotIn("10 问", prompt)

    def test_remaining_seconds_full_before_first_done(self):
        session = {"duration_minutes": 30, "interview_started_at": None}
        self.assertEqual(interview_chat.remaining_seconds(session), 1800)

    def test_remaining_seconds_counts_from_started_at(self):
        started = dt.datetime(2026, 11, 17, 8, 0, tzinfo=dt.timezone.utc)
        now = started + dt.timedelta(seconds=70)
        session = {"duration_minutes": 20, "interview_started_at": started.isoformat()}
        self.assertEqual(interview_chat.remaining_seconds(session, now), 20 * 60 - 70)

    def test_vague_answer_hits_expected_gaps(self):
        labels = interview_chat.detect_answer_gaps(VAGUE_ANSWER)
        self.assertIn(interview_chat.GAP_VAGUE, labels)
        self.assertIn(interview_chat.GAP_WE, labels)
        self.assertIn(interview_chat.GAP_NO_NUMBER, labels)

    def test_specific_answer_has_no_followup_gap(self):
        self.assertEqual(interview_chat.detect_answer_gaps(SPECIFIC_ANSWER), [])


class InterviewStreamApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="iv-stream-")
        self._web = patch.object(backend, "WEB_DIR", Path(self._tmp.name))
        self._web.start()
        self.store = _seed_isolated_store()

    def tearDown(self) -> None:
        self._web.stop()
        self._tmp.cleanup()

    def _start(self, payload: dict | None = None, kinds: list[str] | None = None):
        complete = _fake_complete(_plan(kinds=kinds))
        with patch.object(backend, "interview_ai_configured", return_value=True), patch.object(
            backend, "_complete_interview_plan", complete
        ):
            result = backend.interview_start({"mode": "user", "round": "business", **(payload or {})})
        return result, complete

    def _stream(self, intent: str, fake, extra: dict | None = None):
        with patch.object(backend, "_stream_interview_question", fake):
            return _collect(backend.interview_stream_events({"mode": "user", "intent": intent, **(extra or {})}))

    def _reply(self, answer: str) -> dict:
        return backend.interview_reply({"mode": "user", "answer": answer})

    def _assert_public_session(self) -> dict:
        session = backend.get_store("user").interview_session()
        self.assertIsNotNone(session)
        public = interview_chat.public_session(session)
        _hidden_in(public)
        return session

    def test_first_streams_tokens_and_enters_in_progress(self):
        started, _ = self._start()
        self.assertEqual(started["user_status"], "preparing")
        self.assertEqual(started["remaining_seconds"], 1800)
        fake = _fake_stream(FIRST_QUESTION)
        events = self._stream("first", fake)
        kinds = [name for name, _ in events]
        self.assertEqual(kinds[0], "meta")
        self.assertIn("token", kinds)
        self.assertEqual(kinds[-1], "done")
        meta = events[0][1]
        self.assertEqual(meta["session_id"], started["id"])
        self.assertEqual(meta["move"], "main")
        _hidden_in(meta)
        tokens = "".join(data["text"] for name, data in events if name == "token")
        self.assertEqual(tokens, FIRST_QUESTION)
        self.assertEqual(fake.calls[0]["timeout"], 45)
        session = self._assert_public_session()
        self.assertEqual(session["user_status"], "in_progress")
        self.assertTrue(session.get("interview_started_at"))
        self.assertEqual(session["current_main_id"], "q1")
        self.assertEqual(session["asked_main_ids"], ["q1"])
        self.assertGreaterEqual(session["remaining_seconds"], 1798)
        self.assertLessEqual(session["remaining_seconds"], 1800)
        self.assertEqual(session["current_question"], FIRST_QUESTION)

    def test_first_failure_does_not_enter_in_progress(self):
        self._start()
        fake = _fake_stream(FIRST_QUESTION, error="unavailable")
        events = self._stream("first", fake)
        self.assertEqual(events[0][0], "meta")
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["message"], interview_chat.MSG_FIRST_FAILED)
        session = backend.get_store("user").interview_session()
        self.assertEqual(session["user_status"], "preparing")
        self.assertIsNone(session.get("interview_started_at"))
        self.assertEqual(session.get("asked_main_ids") or [], [])
        self.assertNotEqual(session.get("user_status"), "in_progress")

    def test_vague_answer_next_is_followup_same_main(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        reply = self._reply(VAGUE_ANSWER)
        self.assertTrue(reply["need_next"])
        self.assertFalse(reply["end_available"])
        fake = _fake_stream(FOLLOWUP_QUESTION)
        events = self._stream("next", fake)
        self.assertEqual(events[0][1]["move"], "followup")
        session = backend.get_store("user").interview_session()
        self.assertEqual(session["current_main_id"], "q1")
        self.assertEqual(session["followup_count"], 1)
        self.assertEqual(session["asked_main_ids"], ["q1"])
        user = json.loads(fake.calls[0]["user"])
        self.assertEqual(user["move"], "followup")
        self.assertEqual(user["stem_intent"], "内部意图1")

    def test_followup_stops_after_three_and_goes_next_main(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        for index in range(3):
            reply = self._reply(VAGUE_ANSWER)
            self.assertTrue(reply["need_next"], msg=f"followup {index} should continue")
            events = self._stream("next", _fake_stream(f"追问{index + 1}：请把结果说具体。"))
            self.assertEqual(events[0][1]["move"], "followup")
            session = backend.get_store("user").interview_session()
            self.assertEqual(session["current_main_id"], "q1")
            self.assertEqual(session["followup_count"], index + 1)
        reply = self._reply(VAGUE_ANSWER)
        self.assertTrue(reply["need_next"])
        events = self._stream("next", _fake_stream(NEXT_MAIN_QUESTION))
        self.assertEqual(events[0][1]["move"], "main")
        session = backend.get_store("user").interview_session()
        self.assertEqual(session["current_main_id"], "q2")
        self.assertEqual(session["followup_count"], 0)
        self.assertEqual(session["asked_main_ids"], ["q1", "q2"])

    def test_materials_force_missing_kind_on_next_main(self):
        jingyan = backend.interview_material_upload({
            "mode": "user",
            "kind": "jingyan",
            "body": "测试面经：候选人被问过一次需求评审里如何取舍范围。",
        })
        knowledge = backend.interview_material_upload({
            "mode": "user",
            "kind": "knowledge",
            "body": "测试岗位知识：该岗位要推动一次活动报名漏斗改版。",
        })
        self._start(
            {"material_ids": [jingyan["id"], knowledge["id"]]},
            kinds=["resume_probe", "resume_probe", "business_scenario", "resume_probe"],
        )
        fake_first = _fake_stream(FIRST_QUESTION)
        self._stream("first", fake_first)
        self._reply(SPECIFIC_ANSWER)
        fake_next = _fake_stream(NEXT_MAIN_QUESTION)
        events = self._stream("next", fake_next)
        self.assertEqual(events[0][1]["move"], "main")
        user = json.loads(fake_next.calls[0]["user"])
        self.assertEqual(user["kind"], "business_scenario")
        session = backend.get_store("user").interview_session()
        asked = {item["id"]: item["kind"] for item in session["blueprint"]["main_questions"] if item["id"] in session["asked_main_ids"]}
        self.assertIn("resume_probe", asked.values())
        self.assertEqual(session["current_kind"], "business_scenario")

    def test_blank_reply_is_400(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        with self.assertRaises(backend.ApiError) as ctx:
            self._reply("  ")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_EMPTY_ANSWER)
        session = backend.get_store("user").interview_session()
        self.assertEqual(session["user_status"], "in_progress")
        self.assertEqual(len([row for row in session["turns"] if row.get("role") == "candidate"]), 0)

    def test_reply_while_incomplete_is_409(self):
        self._start()
        events = self._stream("first", _fake_stream(FIRST_QUESTION, fail_after=4))
        self.assertEqual(events[-1][0], "error")
        with self.assertRaises(backend.ApiError) as ctx:
            self._reply(SPECIFIC_ANSWER)
        self.assertEqual(ctx.exception.status, 409)

    def test_reply_success_shape_has_no_ten_question_count(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        result = self._reply(SPECIFIC_ANSWER)
        self.assertIn("remaining_seconds", result)
        self.assertIn("end_available", result)
        self.assertIn("need_next", result)
        self.assertTrue(result["need_next"])
        self.assertFalse(result["end_available"])
        _hidden_in(result)
        self.assertNotIn("target_answers", result)

    def test_end_rejected_before_gate(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        with self.assertRaises(backend.ApiError) as ctx:
            backend.interview_end({"mode": "user"})
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_END_LOCKED)

    def test_time_up_allows_current_answer_then_blocks_next(self):
        self._start({"duration_minutes": 20})
        self._stream("first", _fake_stream(FIRST_QUESTION))
        store = backend.get_store("user")
        session = store.interview_session()
        started = dt.datetime.now(dt.timezone.utc).astimezone() - dt.timedelta(minutes=20, seconds=2)
        session["interview_started_at"] = started.isoformat(timespec="seconds")
        store.set_interview_session(session)
        result = self._reply(SPECIFIC_ANSWER)
        self.assertTrue(result["end_available"])
        self.assertFalse(result["need_next"])
        self.assertTrue(result["time_up"])
        self.assertEqual(result["remaining_seconds"], 0)
        self.assertEqual(result["user_status"], "ready_to_end")
        with self.assertRaises(backend.ApiError) as ctx:
            self._stream("next", _fake_stream(NEXT_MAIN_QUESTION))
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.message, interview_chat.MSG_TIME_UP)

    def test_plan_complete_sets_end_available_without_time_up(self):
        self._start(kinds=["resume_probe", "resume_probe"])
        self._stream("first", _fake_stream(FIRST_QUESTION))
        first_reply = self._reply(SPECIFIC_ANSWER)
        self.assertTrue(first_reply["need_next"])
        self._stream("next", _fake_stream(NEXT_MAIN_QUESTION))
        result = self._reply(SPECIFIC_ANSWER)
        self.assertTrue(result["end_available"])
        self.assertFalse(result["need_next"])
        self.assertFalse(result["time_up"])
        self.assertEqual(result["user_status"], "ready_to_end")
        self.assertGreater(result["remaining_seconds"], 0)
        # Stub the debrief model call to fail, so the test never depends on a local API key.
        def _unavailable(*_args, **_kwargs):
            raise interview_chat.DebriefGenerationError("unavailable")

        with patch.object(backend, "_complete_interview_debrief", _unavailable):
            with self.assertRaises(backend.ApiError) as ctx:
                backend.interview_end({"mode": "user"})
        self.assertEqual(ctx.exception.status, 503)

    def test_half_sentence_keeps_text_and_retry_does_not_advance(self):
        self._start()
        self._stream("first", _fake_stream(FIRST_QUESTION))
        self._reply(VAGUE_ANSWER)
        asked_before = list(backend.get_store("user").interview_session()["asked_main_ids"])
        followup_before = backend.get_store("user").interview_session()["followup_count"]
        events = self._stream("next", _fake_stream(FOLLOWUP_QUESTION, fail_after=6))
        self.assertEqual(events[-1][0], "error")
        self.assertEqual(events[-1][1]["message"], interview_chat.MSG_INCOMPLETE)
        session = backend.get_store("user").interview_session()
        partial = "".join(data["text"] for name, data in events if name == "token")
        self.assertEqual(session["current_question"], partial)
        self.assertTrue(session["turns"][-1]["incomplete"])
        self.assertEqual(session["asked_main_ids"], asked_before)
        self.assertEqual(session["followup_count"], followup_before)
        retry = self._stream("retry", _fake_stream(FOLLOWUP_QUESTION))
        self.assertEqual(retry[-1][0], "done")
        session = backend.get_store("user").interview_session()
        self.assertEqual(session["current_main_id"], "q1")
        self.assertEqual(session["followup_count"], followup_before + 1)
        self.assertEqual(session["asked_main_ids"], asked_before)
        self.assertFalse(session["turns"][-1]["incomplete"])

    def test_real_stream_is_not_used_for_fake_paths(self):
        def forbidden(*_args, **_kwargs):
            raise AssertionError("must not call the real paid stream")

        self._start()
        with patch.object(backend, "_stream_interview_question", forbidden):
            fake = _fake_stream(FIRST_QUESTION)
            with patch.object(backend, "_stream_interview_question", fake):
                events = _collect(backend.interview_stream_events({"mode": "user", "intent": "first"}))
        self.assertEqual(events[-1][0], "done")


class InterviewStreamHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="iv-http-")
        cls.web = patch.object(backend, "WEB_DIR", Path(cls.tmp.name))
        cls.web.start()
        _seed_isolated_store()
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
        cls.web.stop()
        cls.tmp.cleanup()

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

    def test_http_sse_first_question_and_blank_reply(self):
        complete = _fake_complete(_plan())
        fake = _fake_stream(FIRST_QUESTION)
        with patch.object(backend, "interview_ai_configured", return_value=True), patch.object(
            backend, "_complete_interview_plan", complete
        ), patch.object(backend, "_stream_interview_question", fake):
            status, _, raw = self.request(
                "POST",
                "/api/action",
                {"action": "interview-start", "mode": "user", "round": "tech", "duration_minutes": 20},
            )
            self.assertEqual(status, 200)
            start = json.loads(raw.decode("utf-8"))
            self.assertEqual(start["user_status"], "preparing")
            status, headers, raw = self.request(
                "POST",
                "/api/interview/stream",
                {"mode": "user", "intent": "first", "session_id": start["id"]},
            )
            self.assertEqual(status, 200)
            self.assertIn("text/event-stream", headers.get("Content-Type", ""))
            events = _parse_sse(raw)
            self.assertEqual(events[0][0], "meta")
            self.assertEqual(events[0][1]["session_id"], start["id"])
            self.assertNotIn("blueprint", json.dumps(events, ensure_ascii=False))
            self.assertEqual(events[-1][0], "done")
            status, _, raw = self.request(
                "POST",
                "/api/action",
                {"action": "interview-reply", "mode": "user", "answer": "   "},
            )
            self.assertEqual(status, 400)
            body = json.loads(raw.decode("utf-8"))
            self.assertEqual(body["error"], interview_chat.MSG_EMPTY_ANSWER)


if __name__ == "__main__":
    unittest.main()
