"""Same-origin workbench bridge. Never expose a generic action executor."""

import base64
import hashlib
import hmac
import http.client
from http.client import HTTPConnection
import json
import os
import re
import threading

import backend
from career_agent_runtime import service_request


ID = r"[A-Za-z0-9_-]{1,100}"
PROFILE_LOCK = threading.Lock()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def workspace(mode):
    """Read explicit domain records; snapshot() also syncs deliveries, so avoid it."""
    store = backend.get_store(mode)
    profile = backend.profile_public(store.profile())
    jobs = store.jobs()
    risks = backend._job_risk_map(jobs)
    fields = ("id", "company", "title", "city", "salary_text", "score", "source_channel", "raw_text", "posted_at")
    selected = [{**{k: row.get(k) for k in fields}, "risk": risks.get(str(row.get("id")), {})} for row in jobs[:200]]
    for row in selected:
        row["id"] = str(row["id"])
        row["raw_text"] = str(row.get("raw_text") or "")[:12000]
    professional = {key: profile.get(key) for key in ("education", "experiences", "projects", "skills", "summary",
                                                     "job_intent", "excluded_terms", "truth_confirmed")}
    runtime = backend.get_offerpilot_state(mode)
    task = runtime.get("task")
    tasks = [{k: task.get(k) for k in ("id", "mode", "status", "started_at", "finished_at")} ] if isinstance(task, dict) else []
    return {"private_profile": profile, "profile": professional, "jobs": selected, "job_count": len(jobs),
            "coverage": {"loaded_jobs": len(selected), "total_jobs": len(jobs), "complete": len(jobs) <= 200},
            "mails": [{"id": r.get("id"), "classification": r.get("classification"),
                       "subject": r.get("mail", {}).get("subject", ""),
                       "body": str(r.get("mail", {}).get("body", ""))[:4000]} for r in store.mails()[:30]],
            "interviews": [{k: r.get(k) for k in ("id", "company", "role", "weakness_tags", "summary")}
                           for r in store.debriefs()[:30]],
            "tasks": tasks, "approval_queue_count": len(store.queue()),
            "interview_session": {k: (store.interview_session() or {}).get(k) for k in ("id", "user_status")}}


def upstream(mode, method, path, payload=None):
    port, key = 18748, "OFFERPILOT_CAREER_USER_TOKEN"
    return service_request(port, key, method, path, payload)


def dispatch(method, path, query, payload=None):
    if os.environ.get("OFFERPILOT_WORKBENCH_AGENT_DISABLED") == "1":
        raise backend.ApiError("Agent 已关闭，可继续使用流程总览", 503)
    query, payload = dict(query), dict(payload or {})
    mode = query.pop("mode", None)
    if mode not in {"user"} or "mode" in payload or "source" in payload or "owner" in payload:
        raise backend.ApiError("工作台模式或请求字段无效")
    suffix = path.removeprefix("/api/workbench-agent")
    if suffix == "/conversations" and not query:
        if method == "GET":
            return upstream(mode, method, "/v1/workbench" + suffix), 200
        if method == "POST" and not set(payload) - {"title"}:
            return upstream(mode, method, "/v1/workbench" + suffix, payload), 201
    match = re.fullmatch(rf"/conversations/({ID})(?:/(messages|events|approvals|stop|attachments|retry-material|context))?", suffix)
    if not match:
        raise backend.ApiError("未找到工作台操作", 404)
    sid, operation = match.groups()
    target = "/v1/workbench/conversations/" + sid
    if method == "GET" and operation is None and not query:
        return upstream(mode, method, target), 200
    if method == "GET" and operation == "events" and not set(query) - {"after"}:
        after = str(query.get("after", "0"))
        if not re.fullmatch(r"\d{1,10}", after):
            raise backend.ApiError("事件游标无效")
        return upstream(mode, method, target + "/events?after=" + after), 200
    if method == "POST" and not query:
        if operation == "stop" and not payload:
            return upstream(mode, method, target + "/stop", {}), 200
        if operation == "retry-material" and mode == "user" and set(payload) == {"event_id", "run_id"}:
            if any(not isinstance(v, str) or not re.fullmatch(ID, v) for v in payload.values()):
                raise backend.ApiError("材料重试编号无效")
            return upstream(mode, method, target + "/retry-material", {**payload, "source": workspace(mode)}), 202
        if operation == "context" and payload and not set(payload) - {"job_id", "material_id", "resume_version_id", "interview_id"}:
            return upstream(mode, method, target + "/context", {"context": payload, "source": workspace(mode)}), 200
        if operation == "messages" and not set(payload) - {"event_id", "text", "job_id", "material_id", "resume_version_id", "interview_id"}:
            return upstream(mode, method, target + "/messages", {"event": payload, "source": workspace(mode)}), 202
        if operation == "approvals" and not set(payload) - {"approval_id", "approved", "claim_ids"}:
            return upstream(mode, method, target + "/approvals", {"decision": payload, "source": workspace(mode)}), 202
        if operation == "attachments" and mode == "user":
            allowed = {"event_id", "kind", "text", "name", "role", "model_consent", "filename", "content_base64", "material_id"}
            if set(payload) - allowed or payload.get("model_consent") is not True:
                raise backend.ApiError("请确认材料处理范围与模型授权")
            if "material_id" in payload:
                if (not isinstance(payload["material_id"], str) or not re.fullmatch(ID, payload["material_id"])
                        or payload.get("kind") != "experience" or set(payload) & {"text", "filename", "content_base64"}):
                    raise backend.ApiError("已有经历材料与新原文或文件请选择一种")
            if "filename" in payload or "content_base64" in payload:
                if payload.get("text"):
                    raise backend.ApiError("文件与粘贴文字请选择一种")
                from profile_import import extract_resume_text, MAX_BYTES
                encoded = payload.pop("content_base64", "")
                filename = payload.pop("filename", "")
                if not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024 or not isinstance(filename, str):
                    raise backend.ApiError("文件参数无效")
                try:
                    raw = base64.b64decode(encoded, validate=True)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("文件不能超过 5 MB")
                    payload["text"] = extract_resume_text(filename, raw)
                except ValueError as error:
                    raise backend.ApiError(str(error)) from None
            if "material_id" not in payload and (not isinstance(payload.get("text"), str) or not 1 <= len(payload["text"].strip()) <= 20000):
                raise backend.ApiError("请提供 1 至 20000 字符的材料")
            return upstream(mode, method, target + "/attachments", {"attachment": payload, "source": workspace(mode)}), 202
    raise backend.ApiError("工作台请求格式无效")


def stream_events(path, query, last_event_id=None):
    """Forward the fixed owner's SSE connection without polling or buffering."""
    if os.environ.get("OFFERPILOT_WORKBENCH_AGENT_DISABLED") == "1":
        raise backend.ApiError("Agent 已关闭，可继续使用流程总览", 503)
    if not re.fullmatch(rf"/api/workbench-agent/conversations/({ID})/stream", path):
        raise backend.ApiError("未找到工作台事件流", 404)
    query = dict(query)
    mode = query.pop("mode", None)
    if mode not in {"user"} or set(query) - {"after"}:
        raise backend.ApiError("工作台模式或请求字段无效")
    if last_event_id:
        if not re.fullmatch(r"\d{1,10}", last_event_id):
            raise backend.ApiError("事件游标无效")
        query["after"] = last_event_id
    after = str(query.get("after", "0"))
    if not re.fullmatch(r"\d{1,10}", after):
        raise backend.ApiError("事件游标无效")
    port, token_env = 18748, "OFFERPILOT_CAREER_USER_TOKEN"
    token = os.environ.get(token_env, "")
    if len(token) < 20:
        raise backend.ApiError("本机 Agent 尚未启动", 503)
    target = path.removeprefix("/api/workbench-agent")
    connection = HTTPConnection("127.0.0.1", port, timeout=150)
    try:
        connection.request("GET", "/v1/workbench" + target + "?after=" + after,
                           headers={"Authorization": "Bearer " + token, "Accept": "text/event-stream"})
        response = connection.getresponse()
        if response.status != 200:
            raise backend.ApiError("无法连接当前会话，请刷新后重试", response.status if response.status in {400, 404, 422} else 503)
        if not response.getheader("Content-Type", "").startswith("text/event-stream"):
            raise backend.ApiError("Agent 流式响应无效", 502)
        while True:
            line = response.readline(1024 * 1024 + 1)
            if not line:
                return
            if len(line) > 1024 * 1024:
                raise backend.ApiError("Agent 流式响应过大", 502)
            yield line
    except (OSError, http.client.HTTPException):
        raise backend.ApiError("Agent 连接已断开，可刷新恢复当前回复", 503) from None
    finally:
        connection.close()


def commit_profile(headers, payload):
    """Private callback from the approval node, never registered as an agent tool."""
    supplied = headers.get("Authorization", "")
    expected = os.environ.get("OFFERPILOT_CAREER_USER_TOKEN", "")
    if len(expected) < 20 or not hmac.compare_digest(supplied.encode(), ("Bearer " + expected).encode()):
        raise backend.ApiError("未授权的内部操作", 401)
    if (set(payload) != {"mode", "operation_id", "expected", "profile"} or payload["mode"] != "user"
            or not re.fullmatch(ID, str(payload["operation_id"]))):
        raise backend.ApiError("内部资料请求无效")
    with PROFILE_LOCK:
        store = backend.get_store("user")
        current = backend.profile_public(store.profile())
        receipt_file = store.root / "workbench-profile-commits.json"
        receipts = json.loads(receipt_file.read_text(encoding="utf-8")) if receipt_file.exists() else {}
        operation_id = payload["operation_id"]
        identity = fingerprint(payload)
        old = receipts.get(operation_id)
        if old and old["identity"] != identity:
            raise backend.ApiError("确认内容不可改写", 409)
        if old and old.get("result"):
            return old["result"]
        target = backend.normalize_profile(payload["profile"])
        clean = lambda p: {k: v for k, v in p.items() if k not in {"updated_at", "completeness", "has_content"}}
        def persist():
            temp = receipt_file.with_suffix(".tmp")
            temp.write_text(json.dumps(receipts, ensure_ascii=False), encoding="utf-8")
            temp.replace(receipt_file)
        if old and clean(current) == clean(target):
            result = {"ok": True, "profile": current}
            receipts[operation_id]["result"] = result
            persist()
            return result
        if fingerprint(current) != payload["expected"]:
            raise backend.ApiError("个人资料已变化，请重新核对", 409)
        receipts[operation_id] = {"identity": identity}
        persist()
        result = backend.save_profile({"mode": "user", "profile": payload["profile"]})
        receipts[operation_id]["result"] = result
        persist()
        return result
