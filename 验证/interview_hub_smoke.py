"""Exercise the actual loopback API with public material and synthetic answers.

No interview engine, user answers or automatic correctness judgement are used.
The verification server is shut down; its SQLite records remain inspectable.
"""

import hashlib
import json
from pathlib import Path
import secrets
import sys
import threading
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from github_source.ingest import write_json
from interview_hub.materials import import_demo
from interview_hub.server import make_server
from interview_hub.store import Store


def main():
    output = ROOT / "outputs/interview-hub"
    snapshot = ROOT / "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd"
    ua = ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e/project/.ua"
    readiness = ua.parent.parent / "resume-readiness-demo.json"
    original_files = [snapshot / "manifest.json", ua / "knowledge-graph.json", ua / "code-lessons.json", readiness]
    original_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in original_files}
    store = Store(output / "interview.db")
    owner = "local-demo"
    imported = import_demo(store, owner, snapshot, ua, readiness)
    material = imported["payload"]
    material_id = imported["material_id"]
    token = secrets.token_urlsafe(32)
    server = make_server(store, owner, token, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = build_opener(ProxyHandler({}))
    url = f"http://127.0.0.1:{server.server_port}"
    trace = []

    def call(path, body=None, authorized=True):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + token
        request = Request(url + path, data=None if body is None else json.dumps(body).encode("utf-8"), headers=headers)
        try:
            response = client.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            data = json.load(response)
            trace.append({"method": "GET" if body is None else "POST", "path": path, "status": response.status})
            return response.status, data

    def expect(status, expected):
        if status != expected:
            raise AssertionError(f"Unexpected HTTP status: {status}, expected {expected}")

    def session(number):
        session_id = f"demo_round{number}_{material_id[-8:]}"
        status, record = call("/v1/sessions", {"session_id": session_id, "material_id": material_id,
            "mode": "resume_readiness", "target": {"company": "公开样例演示，非真实公司面试", "role": "初级后端", "round": f"合成第{number}轮"}})
        expect(status, 201)
        return record

    try:
        expect(call("/health", authorized=False)[0], 401)
        expect(call("/v1/materials")[0], 200)
        first = session(1)
        sid = first["session_id"]
        status, context = call(f"/v1/sessions/{sid}/context")
        expect(status, 200)
        write_json(output / "context-example.json", context)
        status, evaluator = call(f"/v1/sessions/{sid}/evaluation-context")
        expect(status, 200)
        questions = material["questions"]
        q1, q2, q3 = [q["question_id"] for q in questions]
        result = {"material_id": material_id, "source_commit": material["source_commit"],
            "project_snapshot_id": material["project_snapshot_id"], "resume_version_id": None,
            "session_id": sid, "is_synthetic": True,
            "summary": "合成验收输入，不是真实候选人的回答或评价。",
            "answers": [
                {"question_id": q1, "text": "返回原始消息、分隔符和签名，原文仍可见。", "assistance_mode": "independent"},
                {"question_id": q2, "text": "查阅了循环尝试密钥的实现，轮换细节仍需整理。", "assistance_mode": "open_book"},
                {"question_id": q3, "text": "", "skipped": True, "assistance_mode": "independent"}],
            "observations": [
                {"question_id": q1, "status": "consistent", "notes": "合成上游观察：用于验证一致反馈的保存。", "evidence_ids": questions[0]["evidence_ids"]},
                {"question_id": q2, "status": "partial", "gap_type": "understanding", "notes": "合成上游观察：用于验证补强任务，不代表真实能力缺口。", "evidence_ids": questions[1]["evidence_ids"]},
                {"question_id": q3, "status": "not_assessed", "notes": "合成跳过，保留未评估。", "evidence_ids": []}]}
        write_json(output / "result-request-example.json", result)
        wrong = {**result, "session_id": "another-session"}
        expect(call(f"/v1/sessions/{sid}/results", wrong)[0], 400)
        expect(call(f"/v1/sessions/{sid}/results", result)[0], 201)
        expect(call(f"/v1/sessions/{sid}/results", result)[0], 201)
        changed = {**result, "summary": "This would overwrite an existing final result"}
        expect(call(f"/v1/sessions/{sid}/results", changed)[0], 409)
        status, recap1 = call(f"/v1/sessions/{sid}/recap", {})
        if status not in {200, 201}:
            raise AssertionError("First-round recap was not saved")
        cached = call(f"/v1/sessions/{sid}/recap", {})
        expect(cached[0], 200)
        if recap1 != cached[1]:
            raise AssertionError("Repeated recap changed historical data")
        write_json(output / "recap-example.json", recap1)
        second = session(2)
        sid2 = second["session_id"]
        status, context2 = call(f"/v1/sessions/{sid2}/context")
        expect(status, 200)
        result2 = {**result, "session_id": sid2,
            "answers": [result["answers"][0], {"question_id": q2, "text": "合成第二轮的独立说明，非实际复测。", "assistance_mode": "independent"}, result["answers"][2]],
            "observations": [result["observations"][0], {"question_id": q2, "status": "consistent", "notes": "合成第二轮观察，不认证掌握。", "evidence_ids": questions[1]["evidence_ids"]}, result["observations"][2]]}
        expect(call(f"/v1/sessions/{sid2}/results", result2)[0], 201)
        status, recap2 = call(f"/v1/sessions/{sid2}/recap", {})
        if status not in {200, 201}:
            raise AssertionError("Second-round recap was not saved")
        status, history = call("/v1/history?claim_id=" + material["claims"][0]["claim_id"])
        expect(status, 200)
        write_json(output / "history-example.json", history)
        expect(call(f"/v1/sessions/{sid}/recap")[0], 200)
        reopened = Store(output / "interview.db").get_recap(owner, sid)
        p = recap1["payload"]
        checks = {"unauthenticated_call_rejected": trace[0]["status"] == 401,
            "interviewer_context_hides_expected_facts": all("expected_facts" not in q for q in context["material"]["questions"]),
            "evaluator_context_keeps_draft_evaluation_basis": "expected_facts" in evaluator["material"]["questions"][0],
            "wrong_session_rejected": any(t["path"].endswith("/results") and t["status"] == 400 for t in trace),
            "final_result_cannot_be_overwritten": any(t["status"] == 409 for t in trace),
            "recap_splits_observations_and_unassessed": len(p["what_went_well"]) == 1 and len(p["needs_review"]) == 1 and len(p["not_assessed"]) == 1,
            "improvement_has_material_action_criterion_and_retest": all(task["materials"] and task["action"] and task["completion_criterion"] and task["retest"]["prompt"] for task in p["improvement_tasks"]),
            "new_round_reads_first_round_history": sid in [row["session_id"] for row in context2["related_history"]],
            "old_round_context_does_not_import_later_feedback": sid2 not in [row["session_id"] for row in call(f"/v1/sessions/{sid}/context")[1]["related_history"]],
            "recap_survives_reopening_sqlite": reopened == recap1,
            "all_proposals_pending_and_no_ability_verdict": p["review_status"] == "pending_user_confirmation" and p["ability_verdict"] is None and not p["applied_to_resume"],
            "source_artifacts_unchanged": all(hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha for path, sha in original_hashes.items())}
        summary = {"scope": "real_loopback_HTTP_with_public_source_and_synthetic_interview_inputs", "material_id": material_id,
            "source_repository": material["source_repository"], "source_commit": material["source_commit"],
            "questions": len(questions), "evidence_items": len(material["evidence"]),
            "sessions": [sid, sid2], "first_recap": {"positives": len(p["what_went_well"]), "needs_review": len(p["needs_review"]),
                "not_assessed": len(p["not_assessed"]), "tasks": len(p["improvement_tasks"])},
            "checks": checks, "all_checks_passed": all(checks.values()),
            "interview_engine_executed": False, "real_candidate_answers_used": False,
            "verification_server_kept_running": False}
        write_json(output / "http-verification.json", summary)
        write_json(output / "http-trace.json", trace)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["all_checks_passed"] else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
