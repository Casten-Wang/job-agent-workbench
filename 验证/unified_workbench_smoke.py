"""Isolated HTTP/UI fixture for the unified shell; platform sends go to a local sink."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "offerpilot/web"), str(ROOT / "offerpilot/tools")]

import httpx
import uvicorn
import backend
import server
import career_user_runtime
import career_agent_runtime
import workbench_agent_runtime as bridge
import workbench_runtime
from interview_agent.api import create_app
from interview_agent.tests.test_workbench import ContractAgent, LocalAuth, fixture_material
from interview_hub.store import Store
from interview_hub.career_store import CareerRecords
from workbench_agent_smoke import available_port


class FixtureAgent(ContractAgent):
    async def decide(self, stage, value):
        if stage == "workbench_decide":
            text = value["messages"][-1]["text"]
            if "只收藏" in text:
                if any(o["tool"] == "collect_note" for o in value["observations"]):
                    return {"action": "reply", "arguments": {}, "message": "面经已收藏，可以在工作区阅读。"}
                return {"action": "collect_note", "arguments": {"url": value["note_link_references"][-1]}}
            if "只生成题单" in text:
                if value["observations"]:
                    return {"action": "reply", "arguments": {}, "message": "题单已生成。"}
                return {"action": "build_worksheet", "arguments": {"jd": "Python 后端", "minutes": 30}}
        return await super().decide(stage, value)


class FixtureAuth(LocalAuth):
    def status(self):
        return {"configured": False, "connected": False}


class FixtureCollector:
    def fetch(self, url):
        return {"ok": True, "reason": "success", "title": "虚构面经", "author": "虚构作者", "content": "只用于隔离测试的输入校验面经。", "images": []}


class Platform:
    def __init__(self, sink):
        self.sink, self.task = sink, None
        self.greeting = "您好，我参与过输入校验，希望了解这个岗位。"

    def state(self, mode="user"):
        return {"ok": True, "embedded": True, "base_url": "embedded://offerpilot", "task": self.task,
                "ai": {"configured": True}, "resume": {"available": True}, "preferences": {}, "capabilities": {}}

    def greetings(self, ids):
        return {"ok": True, "greetings": [{"id": i, "greeting": self.greeting, "selection": "edited", "ready": True, "reviewed": True, "status": "ready"} for i in ids]}

    def send(self, ids):
        response = httpx.post(f"http://127.0.0.1:{self.sink.server_port}/receive", json={"ids": ids, "greeting": self.greeting}, trust_env=False)
        response.raise_for_status()
        self.task = {"id": "fixture-delivery", "mode": "deliver", "status": "running"}
        return {"task": self.task}

    def sync(self, job_id, text):
        self.greeting = text
        return {"ok": True, "message": "已同步，尚未发送。"}


def wait_conversation(client, sid):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        response = client.get(f"/api/workbench-agent/conversations/{sid}?mode=user")
        response.raise_for_status()
        value = response.json()
        if value["status"] not in {"queued", "running", "committing", "stopping"}:
            if value["status"] in {"failed", "stopped"}:
                raise AssertionError("conversation did not complete: " + str(value.get("error_code")))
            return value
        time.sleep(.15)
    raise AssertionError("conversation timed out")


def verify(port, sink):
    evidence = []
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=180) as client:
        def call(method, path, payload=None):
            response = client.request(method, path, json=payload)
            response.raise_for_status()
            return response.json()
        overview = call("GET", "/api/workbench/overview?mode=user")
        assert overview["counts"]["jobs"] == 1 and len(overview["capabilities"]) == 23
        evidence.append("overview and complete tool directory")
        sid = call("POST", "/api/workbench-agent/conversations?mode=user", {"title": "虚构后端申请验收"})["id"]
        call("POST", f"/api/workbench-agent/conversations/{sid}/context?mode=user", {"job_id": "job1", "material_id": "mat_confirmed"})
        call("POST", f"/api/workbench-agent/conversations/{sid}/messages?mode=user", {"event_id": "prepare", "text": "为当前目标岗位准备简历和招呼语草稿"})
        draft = wait_conversation(client, sid)
        assert len(draft["artifacts"]) >= 2
        evidence.append("button context to generated application artifacts")
        call("POST", f"/api/workbench-agent/conversations/{sid}/messages?mode=user", {"event_id": "save", "text": "请保存当前最新简历版本"})
        preview = wait_conversation(client, sid)
        assert preview["pending"]["kind"] == "save_resume"
        approval = {"approval_id": preview["pending"]["id"], "approved": True}
        call("POST", f"/api/workbench-agent/conversations/{sid}/approvals?mode=user", approval)
        saved = wait_conversation(client, sid)
        version = saved["saved_versions"][-1]["resume_version_id"]
        pdf = client.get(f"/api/career-user/resumes/{version}/pdf?mode=user&template=professional")
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        evidence.append("explicit save approval and real PDF export")
        call("POST", f"/api/workbench-agent/conversations/{sid}/messages?mode=user", {"event_id": "note", "text": "只收藏这条面经 https://www.xiaohongshu.com/explore/5f0000000000000000000001?xsec_token=synthetic"})
        notes = wait_conversation(client, sid)
        assert any(r["tool"] == "collect_note" for r in notes["business_results"])
        evidence.append("natural-language note collection through actual local APIs")
        body = {"tool": "subscribe_note", "arguments": {"url": "https://www.xiaohongshu.com/explore/5f0000000000000000000001", "interval_hours": 24, "keywords": []}, "operation_id": "subscribe-once"}
        subscription = call("POST", "/api/workbench/actions?mode=user", body)
        assert call("POST", "/api/workbench/actions?mode=user", body)["id"] == subscription["id"]
        for operation in ("pause_note_subscription", "resume_note_subscription"):
            call("POST", "/api/workbench/actions?mode=user", {"tool": operation, "arguments": {"subscription_id": subscription["id"]}, "operation_id": operation})
        evidence.append("subscription creation, pause, resume and duplicate receipt")
        greeting = next(a for a in reversed(saved["artifacts"]) if a["kind"] == "greeting")
        call("POST", "/api/workbench/confirmed-action?mode=user", {"action": "sync-greeting", "arguments": {"conversation_id": sid, "artifact_id": greeting["id"]}, "operation_id": "sync-reviewed"})
        send_preview = call("POST", "/api/workbench/delivery-preview?mode=user", {"ids": ["job1"]})
        assert send_preview["items"][0]["greeting"] == greeting["text"]
        send = {"action": "offerpilot-deliver", "arguments": {"ids": ["job1"], "confirm": "确认发送本批 1 条", "risk_acknowledged": True, "binding": send_preview["binding"]}, "operation_id": "send-once"}
        result = call("POST", "/api/workbench/confirmed-action?mode=user", send)
        assert call("POST", "/api/workbench/confirmed-action?mode=user", send) == result
        assert len(sink.received) == 1
        assert sink.received[0]["greeting"] == greeting["text"]
        evidence.append("reviewed draft to local send sink exactly once")
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8784)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    class Sink(BaseHTTPRequestHandler):
        def do_POST(self):
            self.server.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            raw = b'{"ok":true}'
            self.send_response(200);self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
        def log_message(self, *values):
            pass
    sink = ThreadingHTTPServer(("127.0.0.1", 0), Sink);sink.received=[]
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    platform = Platform(sink)
    with tempfile.TemporaryDirectory(prefix="offerpilot-unified-") as directory:
        sandbox = Path(directory)
        backend.WEB_DIR = sandbox / "web";backend.CV_PATH = sandbox / "resume.md"
        backend.get_offerpilot_state = platform.state
        backend.get_offerpilot_jobs = lambda mode: {"ok": True, "jobs": [], "count": 0}
        backend.offerpilot_runtime.get_greetings = platform.greetings
        backend.offerpilot_runtime.start_deliver_task = platform.send
        backend.offerpilot_runtime.save_reviewed_greeting = platform.sync
        for mode in ("user", "demo"):
            store = backend.Store(mode)
            store.set_jobs([{"id": "job1", "company": "虚构公司", "title": "后端开发", "city": "上海", "score": 4.5,
                             "raw_text": "负责 Python 输入校验与失败处理。", "source_channel": "boss", "offerpilot_id": "fixture-vendor-job"}])
            store.set_queue([{"id": "job1", "company": "虚构公司", "title": "后端开发", "score": 4.5, "status": "approved"}])
            store.set_profile(backend.normalize_profile({"truth_confirmed": True, "basic": {"name": "虚构候选人", "email": "synthetic@example.invalid"},
                "summary": "参与实现输入校验与失败处理，仅用于隔离合成验收。", "skills": {"tools": ["Python"]}}))
        os.environ["OFFERPILOT_WORKBENCH_PORT"] = str(args.port)
        os.environ["LANGSMITH_TRACING"] = "false"
        if args.live:
            from local_secrets import load
            key = load(ROOT / "offerpilot/web/data/user/career-agent/model-credentials.dpapi.json").get("step_api_key")
            if not key:
                raise RuntimeError("No local model credential available")
            os.environ["INTERVIEW_API_KEY"] = key
        db = sandbox / "engine/business.db"
        Store(db).put_material("fixture-owner", "mat_confirmed", fixture_material())
        CareerRecords(db, "fixture-owner").put("binding", "mat_confirmed", {"material_id": "mat_confirmed"})
        token = secrets.token_urlsafe(32);os.environ["OFFERPILOT_CAREER_USER_TOKEN"] = token
        engine_port = available_port()
        app = create_app(db, sandbox / "engine/checkpoints.db", "fixture-owner", token, agent=None if args.live else FixtureAgent(),
                         career_root=sandbox / "engine", career_options={"authorization": FixtureAuth()})
        engine = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=engine_port, access_log=False, log_level="error"))
        thread = threading.Thread(target=engine.run, daemon=True);thread.start()
        deadline = time.monotonic() + 20
        while not engine.started and thread.is_alive() and time.monotonic() < deadline:time.sleep(.05)
        if not engine.started:raise RuntimeError("Isolated engine did not start")
        app.state.note_subscriptions.collector = FixtureCollector()
        def upstream(mode, method, path, payload=None):
            if mode != "user":raise backend.ApiError("隔离验收请使用我的资料模式", 503)
            return career_agent_runtime.service_request(engine_port, "OFFERPILOT_CAREER_USER_TOKEN", method, path, payload)
        bridge.upstream = upstream
        bridge.HTTPConnection = lambda host, port, timeout: http.client.HTTPConnection(host, engine_port, timeout=timeout)
        career_user_runtime.upstream = lambda method,path,payload=None:upstream("user",method,path,payload)
        career_agent_runtime._request = lambda method,path,payload=None:{"items": []}
        web = server.make_server("127.0.0.1", args.port)
        threading.Thread(target=web.serve_forever, daemon=True).start()
        output = ROOT / "outputs/unified-workbench";output.mkdir(parents=True,exist_ok=True)
        print(json.dumps({"ready": True, "url": f"http://127.0.0.1:{args.port}/", "model": "live" if args.live else "protocol", "data": "isolated_synthetic_only"}),flush=True)
        try:
            if args.verify:
                result={"passed": False, "model": "live" if args.live else "protocol", "recorded_at": datetime.now(timezone.utc).isoformat()}
                try:result.update(checks=verify(args.port,sink),passed=True)
                finally:(output / ("live-http.json" if args.live else "protocol-http.json")).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                print(json.dumps(result,ensure_ascii=False),flush=True)
            if args.keep_open:
                while True:time.sleep(.5)
        except KeyboardInterrupt:
            pass
        finally:
            web.shutdown();web.server_close();engine.should_exit=True;thread.join(timeout=15);sink.shutdown();sink.server_close()


if __name__ == "__main__":
    main()
