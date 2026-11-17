"""Real loopback HTTP -> FastAPI -> LangGraph -> direct Python model call."""

import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
import getpass
import sys

import httpx
import uvicorn

from interview_hub.materials import import_demo
from interview_hub.store import Store
from .api import create_app
from .model_adapter import ROOT


def main():
    if "--key-stdin" in sys.argv:
        os.environ["INTERVIEW_API_KEY"] = getpass.getpass("Step API key (hidden): ")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    directory = ROOT / "outputs/interview-agent" / f"live-{time.time_ns()}"
    directory.mkdir(parents=True)
    report_path = ROOT / "outputs/interview-agent/live-verification.json"
    report = {"ok": False, "status": "starting", "runtime": "python-httpx", "synthetic_answers": True, "real_user_assessment": False,
              "artifacts_directory": str(directory), "checks": {}}

    def save():
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        report_path.write_text(encoded, encoding="utf-8")
        (directory / "verification.json").write_text(encoded, encoding="utf-8")

    save()
    store = Store(directory / "interview.db")
    record = import_demo(store, "local-demo", ROOT / "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd",
        ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e/project/.ua",
        ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e/resume-readiness-demo.json")
    token = secrets.token_urlsafe(32)
    app = create_app(directory / "interview.db", directory / "checkpoints.db", "local-demo", token)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not server.started:
            raise RuntimeError("server_start_failed")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": "Bearer " + token},
                          timeout=140, trust_env=False) as client:
            health = client.get("/health")
            health.raise_for_status()
            report["generation"] = health.json()["generation"]
            report["checks"]["direct_python_executor"] = health.json()["model_executor"] == "python-httpx"
            report["status"] = "calling_plan"
            save()
            print("正在通过 FastAPI/LangGraph 验证真实出题…", flush=True)
            response = client.post("/v1/interviews", json={"session_id": "python_live", "material_id": record["material_id"],
                                                          "target": {"role": "初级后端", "round": "Python 迁移验证，合成回答"}})
            response.raise_for_status()
            opened = response.json()
            report["question_plan_id"] = opened["question_plan_id"]
            report["status"] = "calling_hint_intent_and_observation"
            save()
            print("正在验证提示、意图识别、逐题观察和复盘…", flush=True)
            hinted = client.post("/v1/interviews/python_live/turns", json={"event_id": "hint_1", "text": "/hint", "command": "request_hint"})
            hinted.raise_for_status()
            report["checks"]["hint_delivered"] = hinted.json()["message"].startswith("提示：")
            response = client.post("/v1/interviews/python_live/turns", json={"event_id": "answer_1",
                "text": "签名结果保留原消息，并附上计算得到的签名；消息本身没有被加密。验签会拆分并核对签名。"})
            response.raise_for_status()
            answer = response.json()
            report["checks"]["one_answer_assessed"] = answer["answered"] == 1 and not answer["pending_evaluation"]
            if not report["checks"]["one_answer_assessed"]:
                raise RuntimeError("required_observation_missing")
            for index in range(answer["total"] - 1):
                skipped = client.post("/v1/interviews/python_live/turns", json={"event_id": f"skip_{index}", "text": "/skip", "command": "skip"})
                skipped.raise_for_status()
            finished = client.post("/v1/interviews/python_live/turns", json={"event_id": "finish", "text": "/finish", "command": "finish"})
            finished.raise_for_status()
            recap = finished.json()["recap"]
            result = client.get("/v1/sessions/python_live/results").json()["payload"]
            report["checks"].update(
                completed=finished.json()["status"] == "completed",
                plan_binding=result["question_plan_id"] == recap["question_plan_id"] == opened["question_plan_id"],
                one_observation=len(result["observations"]) == 1,
                assistance_preserved=result["answers"][0]["assistance_mode"] == "hinted",
                no_resume_write=recap["applied_to_resume"] is False and recap["ability_verdict"] is None,
                checkpoint_persisted=(directory / "checkpoints.db").exists())
            report["example_recap"] = recap
            report["ok"] = all(report["checks"].values())
            report["status"] = "completed" if report["ok"] else "failed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = {"type": type(error).__name__, "http_status": getattr(getattr(error, "response", None), "status_code", None)}
        execution = getattr(getattr(app.state, "workflow", None), "agent", None)
        report["model_diagnostics"] = getattr(execution, "last_failure", None)
        if isinstance(error, httpx.HTTPStatusError):
            try:
                code = error.response.json().get("code")
                if isinstance(code, str) and len(code) <= 100 and code.replace("_", "").isalnum():
                    report["error"]["model_code"] = code
            except ValueError:
                pass
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        report["checks"]["server_stopped"] = not thread.is_alive()
        report["ok"] = report["ok"] and report["checks"]["server_stopped"]
        if "--key-stdin" in sys.argv:
            os.environ.pop("INTERVIEW_API_KEY", None)
        save()
    print(json.dumps({k: v for k, v in report.items() if k != "example_recap"}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
