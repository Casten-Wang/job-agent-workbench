"""Reliability boundaries: fail closed, fenced commits, restart and deduplication."""

import asyncio
import json
import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from fastapi.testclient import TestClient
from interview_agent.api import create_app
from interview_agent.note_subscriptions import NoteSubscriptions
from interview_agent.xhs_notes import NoteCollector, NoteFailure, SafeRedirect, checked_url, parse_note


ID = "0123456789abcdef01234567"
URL = "https://www.xiaohongshu.com/explore/" + ID + "?xsec_token=synthetic%2Btoken&xsec_source=pc_feed"
TOKEN = "synthetic-local-note-test-token"


def note(**changes):
    return {"noteId": ID, "title": "虚构后端面经", "desc": "第一行  Python\n第二行 {undefined NaN} \\\"",
            "tagList": [{"name": "面经"}], "user": {"nickName": "合成作者"},
            "imageList": [{"urlDefault": "https://example.invalid/cover.jpg"}], **changes}


def page(value=None):
    return "<html><script>window.__INITIAL_STATE__=" + json.dumps({"noteData": {"data": {"noteData": value or note()}}}, ensure_ascii=False) + ";</script></html>"


def good():
    return parse_note(page(), ID)


class FakeCollector:
    def __init__(self):
        self.value, self.calls = good(), []

    def fetch(self, url):
        self.calls.append(url)
        return dict(self.value)


class ParserTests(unittest.TestCase):
    def test_balanced_object_prose_tokens_and_line_breaks(self):
        value = parse_note(page(), ID)
        self.assertTrue(value["ok"])
        self.assertIn("第二行 {undefined NaN}", value["content"])
        self.assertIn("第一行 Python\n", value["content"])
        self.assertTrue(value["content"].endswith("#面经"))
        self.assertEqual(value["author"], "合成作者")
        raw = page().replace('"tagList":', '"missing":undefined,"nan":NaN,"m":new Map([]),"s":new Set([]),"tagList":')
        self.assertTrue(parse_note(raw, ID)["ok"])

    def test_invalid_and_empty_are_not_success(self):
        self.assertEqual(parse_note(page(note(noteId="f" * 24)), ID)["reason"], "id_mismatch")
        self.assertEqual(parse_note(page(note(desc=" \n ")), ID)["reason"], "empty_content")
        self.assertEqual(parse_note("window.__INITIAL_STATE__={", ID)["reason"], "parse_error")
        self.assertEqual(parse_note("window.__INITIAL_STATE__={\"noteData\":null}", ID)["reason"], "parse_error")

    def test_video_only_returns_cover(self):
        value = parse_note(page(note(type="video", imageList=[{"urlPre": "https://example.invalid/1"}, {"urlPre": "https://example.invalid/2"}])), ID)
        self.assertEqual(value["images"], ["https://example.invalid/1"])

    def test_url_and_redirect_allowlist(self):
        for url in ("http://127.0.0.1/", "https://xiaohongshu.com.evil.invalid/", "https://user@www.xiaohongshu.com/", "https://www.xiaohongshu.com:444/", "file:///etc/passwd"):
            with self.subTest(url=url), self.assertRaises(NoteFailure):
                checked_url(url)
        handler = SafeRedirect(lambda: None)
        with self.assertRaises(NoteFailure):
            handler.redirect_request(urllib.request.Request(URL), None, 302, "", {}, "https://localhost/private")

    def test_transport_query_headers_cookies_and_failure_classification(self):
        requests, handlers, gates = [], [], []

        class Response:
            def __init__(self, url, body):
                self.url, self.body = url, io.BytesIO(body.encode())
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def geturl(self):
                return self.url
            def read(self, size):
                return self.body.read(size)

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                if request.full_url.startswith("https://xhslink.com/"):
                    return Response(URL, "short")
                return Response(request.full_url, page() if "/explore/" in request.full_url else "home")

        def build(*args):
            handlers.extend(args)
            return Opener()

        collector = NoteCollector(lambda: gates.append(True))
        with patch("urllib.request.build_opener", build):
            self.assertTrue(collector.fetch("https://xhslink.com/a/synthetic")["ok"])
            self.assertEqual(requests[-1].full_url, URL)
            self.assertEqual(len(gates), 3)
            self.assertTrue(any(isinstance(h, urllib.request.HTTPCookieProcessor) for h in handlers))
            for request in requests:
                self.assertNotIn("Referer", request.headers)
                self.assertNotIn("Origin", request.headers)
                self.assertNotIn("Cookie", request.headers)
                self.assertIn("iPhone", request.headers["User-agent"])
            self.assertEqual(collector.fetch("https://www.xiaohongshu.com/")["reason"], "no_post_id")
        for code, reason in ((401, "need_login"), (403, "need_login"), (429, "rate_limited"), (404, "not_found"), (503, "unreachable")):
            with patch("urllib.request.OpenerDirector.open", side_effect=urllib.error.HTTPError(URL, code, "", {}, None)):
                self.assertEqual(collector.fetch(URL)["reason"], reason)
        with patch("urllib.request.OpenerDirector.open", side_effect=TimeoutError()):
            self.assertEqual(collector.fetch(URL)["reason"], "unreachable")


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.at = 10000.0
        self.collector = FakeCollector()
        self.service = NoteSubscriptions(self.temp.name, "alice", collector=self.collector, clock=lambda: self.at)

    def tearDown(self):
        self.temp.cleanup()

    def test_restart_dedup_trigger_source_and_read_receipt(self):
        job = self.service.create(URL, 1, ["Python"])
        self.service.tick()
        inbox = self.service.inbox()
        self.assertEqual(inbox["unread"], 1)
        message = inbox["items"][0]
        saved = self.service.note(message["note_id"])
        self.assertEqual(saved["source_url"], URL)
        restarted = NoteSubscriptions(self.temp.name, "alice", collector=self.collector, clock=lambda: self.at)
        self.at += 3600
        restarted.tick()
        self.assertEqual(restarted.inbox()["unread"], 1)
        self.collector.value = good() | {"content": "新的 Python 面经"}
        self.at += 3600
        restarted.tick()
        self.assertEqual(restarted.inbox()["unread"], 2)
        restarted.read(message["id"])
        restarted.read(message["id"])
        self.assertEqual(restarted.inbox()["unread"], 1)
        self.assertEqual(len(restarted.runs(job["id"])["items"]), 3)
        bob = NoteSubscriptions(self.temp.name, "bob", collector=self.collector)
        self.assertEqual(bob.inbox()["unread"], 0)

    def test_nonmatching_note_saved_without_notification(self):
        self.service.create(URL, 1, ["不存在的关键词"])
        self.service.tick()
        self.assertEqual(self.service.inbox()["unread"], 0)
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 1)

    def test_network_backoff_no_empty_note_and_login_pause(self):
        job = self.service.create(URL, 1)
        self.collector.value = {"ok": False, "reason": "unreachable"}
        self.service.tick()
        failed = self.service.get(job["id"])
        self.assertEqual(failed["next_run"], self.at + 7200)
        self.assertEqual(failed["enabled"], 1)
        self.service.tick()
        self.assertEqual(len(self.collector.calls), 1)
        self.at = failed["next_run"]
        self.collector.value = {"ok": False, "reason": "need_login"}
        self.service.tick()
        self.assertEqual(self.service.get(job["id"])["enabled"], 0)
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
        self.assertEqual(self.service.inbox()["items"][0]["kind"], "subscription_paused")

    def test_claim_fencing_crash_recovery_and_pause(self):
        job = self.service.create(URL)
        first = self.service.claim()
        self.assertIsNone(self.service.claim())
        self.at += 181
        second = self.service.claim()
        self.service.complete(first, good())
        self.assertEqual(self.service.inbox()["unread"], 0)
        self.service.complete(second, good())
        self.assertEqual(self.service.inbox()["unread"], 1)
        self.assertIn("interrupted", [r["reason"] for r in self.service.runs(job["id"])["items"]])
        self.service.enable(job["id"], True)
        third = self.service.claim()
        self.service.enable(job["id"], False)
        self.service.complete(third, good() | {"content": "late changed content"})
        self.assertEqual(self.service.inbox()["unread"], 1)

    def test_transaction_rolls_back_note_when_inbox_write_fails(self):
        self.service.create(URL)
        job = self.service.claim()
        with patch.object(self.service, "push", side_effect=RuntimeError("synthetic disk failure")):
            with self.assertRaises(RuntimeError):
                self.service.complete(job, good())
        with self.service.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM notes").fetchone()[0], 0)
        self.service.complete(job, good())
        self.assertEqual(self.service.inbox()["unread"], 1)

    def test_concurrent_workers_claim_once_and_shared_throttle(self):
        self.service.create(URL)
        peer = NoteSubscriptions(self.temp.name, "alice", collector=self.collector, clock=lambda: self.at)
        found = []
        threads = [threading.Thread(target=lambda s=s: found.append(s.claim())) for s in (self.service, peer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(job is not None for job in found), 1)
        with patch.object(self.service.stop, "wait", return_value=False) as wait1, patch.object(peer.stop, "wait", return_value=False) as wait2:
            self.service.request_gate()
            peer.request_gate()
        self.assertEqual(wait1.call_args.args[0], 0)
        self.assertEqual(wait2.call_args.args[0], 4)

    def test_three_parser_failures_pause_and_duplicate_create(self):
        job = self.service.create(URL, 1)
        self.assertEqual(self.service.create(URL, 1)["id"], job["id"])
        self.collector.value = {"ok": False, "reason": "parse_error"}
        for _ in range(3):
            self.service.tick()
            self.at = self.service.get(job["id"])["next_run"]
        self.assertEqual(self.service.get(job["id"])["enabled"], 0)

    def test_downtime_coalesces_no_catchup_storm(self):
        job = self.service.create(URL, 1)
        self.at += 30 * 86400
        self.service.tick()
        self.service.tick()
        self.assertEqual(len(self.collector.calls), 1)
        self.assertEqual(self.service.get(job["id"])["next_run"], self.at + 3600)

    def test_shutdown_interruption_does_not_increment_failures(self):
        job = self.service.create(URL)
        claimed = self.service.claim()
        self.service.complete(claimed, {"ok": False, "reason": "stopped"})
        self.assertEqual(self.service.get(job["id"])["failures"], 0)
        self.assertEqual(self.service.inbox()["unread"], 0)
        self.assertEqual(self.service.runs(job["id"])["items"][0]["reason"], "interrupted")
        self.assertIsNotNone(self.service.claim())

    def test_paused_schedule_can_be_changed_and_manual_work_is_serial(self):
        job = self.service.create(URL)
        self.service.enable(job["id"], False)
        changed = self.service.create(URL, 12, ["Python"])
        self.assertEqual(changed["id"], job["id"])
        self.assertEqual(changed["interval_hours"], 12)
        self.assertEqual(changed["enabled"], 1)
        self.service.tick_lock.acquire()
        try:
            self.assertEqual(self.service.collect(URL)["reason"], "collector_busy")
            self.assertEqual(len(self.collector.calls), 0)
        finally:
            self.service.tick_lock.release()

    def test_selfcheck_reports_database_failure_without_claiming_success(self):
        with patch.object(self.service, "db", side_effect=__import__('sqlite3').OperationalError("synthetic")):
            self.assertFalse(self.service.health()["ok"])
            self.assertFalse(self.service.health()["database_ok"])


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_schedule_actually_runs_and_stops(self):
        with tempfile.TemporaryDirectory() as temp:
            done = threading.Event()
            class Service(NoteSubscriptions):
                def complete(self, job, value):
                    super().complete(job, value)
                    done.set()
            service = Service(temp, "alice", collector=FakeCollector())
            service.create(URL)
            await service.start()
            try:
                self.assertTrue(await asyncio.to_thread(done.wait, 3))
                self.assertEqual(service.inbox()["unread"], 1)
                self.assertTrue(service.health()["ok"])
            finally:
                await service.close()
            self.assertTrue(service.task.done())


class NoModel:
    generation = {"provider": "test", "model": "no-model", "kind": "contract_test"}
    async def decide(self, *args):
        raise AssertionError("Explicit note commands must not call a model")


class LocalAuth:
    def close(self):
        pass


class HttpFlowTests(unittest.TestCase):
    def test_authenticated_api_command_selfcheck_restart_and_demo_isolation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def app(owner="alice", personal=True):
                return create_app(root / "business.db", root / "checkpoints.db", owner, TOKEN, NoModel(),
                    career_root=root / "career" if personal else None,
                    career_options={"authorization": LocalAuth()})
            headers = {"Authorization": "Bearer " + TOKEN}
            with patch("interview_agent.xhs_notes.NoteCollector.fetch", return_value=good()):
                with TestClient(app()) as client:
                    self.assertEqual(client.get("/v1/notes/inbox").status_code, 401)
                    self.assertEqual(client.post("/v1/notes/subscriptions", headers=headers, json={"url": "https://127.0.0.1/"}).status_code, 400)
                    self.assertEqual(client.post("/v1/notes/subscriptions", headers=headers, json={"url": URL, "interval_hours": 0}).status_code, 422)
                    saved = client.post("/v1/notes/collect", headers=headers, json={"url": URL}).json()
                    self.assertTrue(saved["ok"])
                    self.assertEqual(client.get("/v1/notes/items/" + saved["note_id"], headers=headers).json()["source_url"], URL)
                    inbox = client.get("/v1/notes/inbox", headers=headers).json()
                    self.assertEqual(inbox["unread"], 1)
                    self.assertEqual(client.get("/v1/notes/self-check", headers=headers).json()["database_ok"], True)
                    sid = client.post("/v1/workbench/conversations", headers=headers, json={}).json()["id"]
                    response = client.post(f"/v1/workbench/conversations/{sid}/messages", headers=headers,
                        json={"event": {"event_id": "sub1", "text": "/面经订阅 " + URL + " 24 Python"}, "source": {}})
                    self.assertEqual(response.status_code, 202)
                    # Wait for the actual task, not an arbitrary delay.
                    client.portal.call(asyncio.gather, *list(client.app.state.workbench.tasks.values()))
                    view = client.get(f"/v1/workbench/conversations/{sid}", headers=headers).json()
                    self.assertIn("订阅已保存", view["messages"][-1]["text"])
                    job = client.get("/v1/notes/subscriptions", headers=headers).json()["items"][0]
                    self.assertEqual(client.post(f"/v1/notes/subscriptions/{job['id']}/pause", headers=headers, json={}).json()["enabled"], 0)
                with TestClient(app()) as client:
                    self.assertEqual(client.get("/v1/notes/inbox", headers=headers).json()["unread"], 1)
                    self.assertEqual(client.get("/v1/notes/subscriptions", headers=headers).json()["items"][0]["enabled"], 0)
                with TestClient(app("bob")) as client:
                    self.assertEqual(client.get("/v1/notes/inbox", headers=headers).json()["unread"], 0)
                with TestClient(app(personal=False)) as client:
                    self.assertEqual(client.get("/v1/notes/inbox", headers=headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()
