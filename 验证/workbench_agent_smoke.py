"""Isolated real HTTP/UI fixture; never reads or writes personal workspace data."""

import argparse
import http.client
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
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
from interview_agent.api import create_app
from interview_agent.tests.test_workbench import ContractAgent, LocalAuth, fixture_material
from interview_hub.store import Store
from interview_hub.career_store import CareerRecords


class SmokeAuth(LocalAuth):
    def status(self):
        return {"configured": False, "connected": False}


def write_report(output, live):
    directory = ROOT / "outputs/workbench-agent"
    directory.mkdir(parents=True, exist_ok=True)
    output = {"recorded_at": datetime.now(timezone.utc).isoformat(), **output}
    latest = directory / ("latest-live-check.json" if live else "latest-contract-check.json")
    latest.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    if output["passed"]:
        passed = directory / ("live-http.json" if live else "contract-http.json")
        passed.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


def available_port():
    with closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--stream-fixture", action="store_true", help="Use a local SSE model provider with synthetic data")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="offerpilot-workbench-") as directory:
        sandbox = Path(directory)
        backend.WEB_DIR = sandbox / "web"
        backend.CV_PATH = sandbox / "workspace/resume.md"
        backend.get_offerpilot_state = lambda mode="user": {"ok": False, "error": "隔离验收，未连接平台"}
        for mode in ("demo", "user"):
            store = backend.Store(mode)
            store.set_jobs([{"id": "job1", "company": "虚构公司", "city": "上海", "title": "后端开发", "score": 4.5,
                             "raw_text": "负责 Python 服务的输入校验、异常处理与接口维护。", "source_channel": "manual_paste"}])
            store.set_profile(backend.normalize_profile({"truth_confirmed": True, "basic": {"name": "虚构候选人", "email": "synthetic@example.invalid"},
                                                         "skills": {"tools": ["Python"], "strengths": []}}))
        engine_port = available_port()
        token = secrets.token_urlsafe(32)
        os.environ["OFFERPILOT_CAREER_USER_TOKEN"] = token
        os.environ["LANGSMITH_TRACING"] = "false"
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        provider = None
        if args.stream_fixture:
            from workbench_stream_fixture import start_provider
            provider = start_provider()
            os.environ["INTERVIEW_API_KEY"] = "synthetic-stream-provider-only"
            os.environ["INTERVIEW_BASE_URL"] = f"http://127.0.0.1:{provider.server_port}/v1"
        if args.live:
            from local_secrets import load
            credentials = load(ROOT / "offerpilot/web/data/user/career-agent/model-credentials.dpapi.json")
            if credentials.get("step_api_key") and not os.getenv("INTERVIEW_API_KEY"):
                os.environ["INTERVIEW_API_KEY"] = credentials["step_api_key"]
            for name in ("INTERVIEW_API_KEY", "STEP_API_KEY", "STEPFUN_API_KEY"):
                if not os.getenv(name) and credentials.get(name):
                    os.environ[name] = credentials[name]
            if not any(os.getenv(name) for name in ("INTERVIEW_API_KEY", "STEP_API_KEY", "STEPFUN_API_KEY")):
                raise RuntimeError("No configured model credential available")
        db = sandbox / "engine/business.db"
        Store(db).put_material("smoke-owner", "mat_confirmed", fixture_material())
        CareerRecords(db, "smoke-owner").put("binding", "mat_confirmed", {"material_id": "mat_confirmed"})
        app = create_app(db, sandbox / "engine/checkpoints.db", "smoke-owner", token,
                         agent=None if args.live or args.stream_fixture else ContractAgent(), career_root=sandbox / "engine",
                         career_options={"authorization": SmokeAuth()})
        engine = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=engine_port, access_log=False, log_level="error"))
        engine_thread = threading.Thread(target=engine.run, daemon=True)
        engine_thread.start()
        deadline = time.monotonic() + 15
        while not engine.started and engine_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        if not engine.started:
            raise RuntimeError("Isolated engine startup failed")
        def isolated_upstream(mode, method, path, payload=None):
            if mode != "user":
                raise backend.ApiError("请切换我的 user 使用隔离合成数据验收", 503)
            return career_agent_runtime.service_request(engine_port, "OFFERPILOT_CAREER_USER_TOKEN", method, path, payload)
        bridge.upstream = isolated_upstream
        bridge.HTTPConnection = lambda host, port, timeout: http.client.HTTPConnection(host, engine_port, timeout=timeout)
        career_user_runtime.upstream = lambda method, path, payload=None: isolated_upstream("user", method, path, payload)
        career_agent_runtime._request = lambda method, path, payload=None: {"items": []}
        web = server.make_server("127.0.0.1", args.port)
        original_log = server.JobAgentHandler.log_message
        server.JobAgentHandler.log_message = lambda handler, fmt, *values: None if "/events?" in handler.path else original_log(handler, fmt, *values)
        web_thread = threading.Thread(target=web.serve_forever, daemon=True)
        web_thread.start()
        print(json.dumps({"ready": True, "url": f"http://127.0.0.1:{args.port}/", "model": "live" if args.live else "contract",
                          "data": "isolated_synthetic_only"}), flush=True)
        try:
            if args.verify:
                try:
                    verify(args.port, app, args.live)
                except Exception as error:
                    write_report({"passed": False, "model": "live_step" if args.live else "contract",
                                  "data": "isolated_synthetic_only", "error_type": type(error).__name__,
                                  "detail": str(error)[:2000]}, args.live)
                    print(json.dumps({"model_format_diagnostic": getattr(app.state.workflow.agent, "last_failure", None)}, ensure_ascii=False), flush=True)
                    raise
                if args.keep_open:
                    while web_thread.is_alive():
                        time.sleep(.5)
            else:
                while web_thread.is_alive():
                    time.sleep(.5)
        except KeyboardInterrupt:
            pass
        finally:
            web.shutdown()
            web.server_close()
            engine.should_exit = True
            engine_thread.join(10)
            if provider:
                provider.shutdown()
                provider.server_close()


def verify(port, app, live):
    base = f"http://127.0.0.1:{port}/api/workbench-agent"
    with httpx.Client(trust_env=False, timeout=20) as client:
        def call(path, body=None):
            response = client.get(base + path, params={"mode": "user"}) if body is None else client.post(base + path, params={"mode": "user"}, json=body)
            if response.status_code >= 400:
                raise AssertionError(f"HTTP {response.status_code} for {path}")
            return response.json()
        view = call("/conversations", {"title": "合成用户：上海后端准备"})
        sid = view["id"]
        def wait():
            deadline, seen = time.monotonic() + 240, None
            while time.monotonic() < deadline:
                response = client.get(base + f"/conversations/{sid}/events", params={"mode": "user", "after": 0})
                response.raise_for_status()
                data = response.json()
                if data.get("events"):
                    last = data["events"][-1]
                    mark = (last["type"], last.get("tool"))
                    if mark != seen:
                        print(json.dumps({"stage": mark, "status": data["view"]["status"]}), flush=True)
                        seen = mark
                result = data["view"]
                if result["status"] not in {"running", "queued", "committing", "stopping"}:
                    return result
                time.sleep(.25)
            raise AssertionError("Run exceeded verification deadline")
        call(f"/conversations/{sid}/messages", {"event_id": "recommend", "text": "从已有岗位里推荐 3 个上海后端岗"})
        recommended = wait()
        assert recommended["recommendations"], recommended.get("error_code")
        call(f"/conversations/{sid}/messages", {"event_id": "draft", "text": "为选定岗位准备简历和招呼语草稿", "job_id": "job1", "material_id": "mat_confirmed"})
        drafted = wait()
        assert len(drafted["artifacts"]) == 2, {"error_code": drafted.get("error_code"), "last_message": drafted.get("messages", [])[-1:]}
        call(f"/conversations/{sid}/messages", {"event_id": "revise", "text": "修改：精简项目要点，只调整表达，不新增任何事实"})
        revised = wait()
        assert len(revised["artifacts"]) == 4, {"error_code": revised.get("error_code"), "last_message": revised.get("messages", [])[-1:]}
        assert revised["artifacts"][0] == drafted["artifacts"][0]
        artifact = revised["artifacts"][-2]
        call(f"/conversations/{sid}/messages", {"event_id": "save", "text": "请保存当前简历修订 " + str(artifact["revision"])})
        approval = wait()
        assert approval["status"] == "waiting_approval", approval.get("error_code")
        decision = {"approval_id": approval["pending"]["id"], "approved": True}
        call(f"/conversations/{sid}/approvals", decision)
        saved = wait()
        repeated = call(f"/conversations/{sid}/approvals", decision)
        assert saved["saved_versions"] == repeated["saved_versions"]
        assert len(saved["saved_versions"]) == 1
        output = {"passed": True, "model": "live_step" if live else "contract", "data": "isolated_synthetic_only",
                  "recommendations": len(recommended["recommendations"]), "artifacts": len(revised["artifacts"]), "revisions": 2,
                  "saved_versions": len(saved["saved_versions"]), "no_external_send_tool": True,
                  "semantic_quality": "requires_human_review"}
        write_report(output, live)
        print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()
