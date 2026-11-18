"""Local workbench overview and explicit, receipted business adapters."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import uuid

import backend
import career_user_runtime
import workbench_agent_runtime

# 引擎包与综合面试实现在本仓库根目录。
ENGINE_ROOT = backend.ROOT
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
from interview_agent.workbench_catalog import BUSINESS_TOOLS, CAPABILITIES, validate_arguments

controller = None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def catalog(mode):
    personal = {"github", "knowledge", "notes", "experience", "experience_details", "settings"}
    return [{"id": key, "label": label, "group": group, "view": view, "anchor": anchor,
             "kind": kind, "available": mode == "user" or key not in personal,
             "reason": "仅在我的资料模式开放" if mode != "user" and key in personal else ""}
            for key, label, group, view, anchor, kind in CAPABILITIES]


def engine_get(mode, path):
    try:
        return workbench_agent_runtime.upstream(mode, "GET", path)
    except backend.ApiError:
        return None


def settings_status():
    return controller.status() if controller else {
        "configured": any(bool(os.getenv(k)) for k in ("INTERVIEW_API_KEY", "STEP_API_KEY", "STEPFUN_API_KEY")),
        "pending": False, "can_configure": False, "model": "step-5-preview",
        "message": "请使用项目启动器启动服务后配置模型。"}


def overview(mode):
    if mode != "user":
        raise backend.ApiError("工作台仅支持我的资料模式")
    store = backend.get_store(mode, seed_if_empty=False)
    jobs, queue, mails = store.jobs(), store.queue(), store.mails()
    profile = store.profile()
    model_setup = settings_status()
    runtime = backend.get_offerpilot_state(mode)
    engine = engine_get(mode, "/v1/workbench/overview")
    tasks = list((engine or {}).get("tasks", []))
    task = runtime.get("task")
    if isinstance(task, dict) and task.get("status") in {"queued", "running", "stopping"}:
        tasks.append({"id": task.get("id"), "title": "平台岗位任务", "status": task.get("status"), "capability": "collect"})
    session = store.interview_session()
    if backend._in_progress_interview(session):
        tasks.append({"id": session["id"], "title": "继续文字模拟面试", "capability": "interview",
                      "status": "ready_to_finish" if session.get("user_status") == "ready_to_end" else "active",
                      "interview_id": session["id"], "interview_kind": "legacy"})
    pending = list((engine or {}).get("pending", []))
    pending.extend({"id": str(row["id"]), "title": "待核对岗位", "capability": "queue"}
                   for row in queue if row.get("status") == "pending")
    materials = (engine or {}).get("materials", [])
    versions = (engine or {}).get("versions", [])
    results = [{"id": str(job["id"]), "title": str(job.get("company", "")) + " / " + str(job.get("title", "岗位")),
                "kind": "岗位", "capability": "jobs", "job_id": str(job["id"])} for job in jobs[-3:]]
    results += [{"id": row["resume_version_id"], "title": "简历 " + row["resume_version_id"], "kind": "简历版本",
                 "capability": "resume", "resume_version_id": row["resume_version_id"]} for row in versions[:5]]
    results += [{"id": row["material_id"], "title": row.get("name") or "已确认经历", "kind": "经历材料",
                 "capability": "experience", "material_id": row["material_id"]} for row in materials[:3]]
    results += [{"id": str(row.get("id", index)), "title": str(row.get("company") or "面试") + " 复盘", "kind": "面试复盘", "capability": "debrief"}
                for index, row in enumerate(store.debriefs()[-3:])]
    results += (engine or {}).get("results", [])[:8]
    receipts = store.root / "workbench-operations.db"
    if receipts.is_file():
        connection = sqlite3.connect(receipts.as_uri() + "?mode=ro", uri=True)
        try:
            if "tool" in {r[1] for r in connection.execute("PRAGMA table_info(operation)")}:
                for operation_id, tool, raw in connection.execute("SELECT id,tool,result FROM operation WHERE state='completed' ORDER BY created DESC LIMIT 20"):
                    if tool in {"collect_note", "subscribe_note", "build_worksheet", "export_workspace", "save_experience_variant"}:
                        result = json.loads(raw)
                        if result.get("ok") is not False:
                            results.append({"id": operation_id, "title": BUSINESS_TOOLS[tool][0], "kind": "已保存结果", "capability":
                                {"collect_note": "notes", "subscribe_note": "notes", "build_worksheet": "worksheet", "export_workspace": "data", "save_experience_variant": "variants"}[tool]})
        finally:
            connection.close()
    if pending:
        next_action = {"title": "先核对待确认内容", "capability": pending[0].get("capability", "application"), "conversation_id": pending[0].get("conversation_id")}
    elif tasks:
        next_action = {"title": "继续当前任务", **tasks[0]}
    elif mode == "user" and not profile.get("truth_confirmed") and not model_setup["configured"]:
        next_action = {"title": "连接模型，开始导入简历", "capability": "settings"}
    elif not profile.get("truth_confirmed"):
        next_action = {"title": "导入简历，建立你的求职资料", "capability": "profile_import"}
    elif not jobs:
        next_action = {"title": "粘贴一个目标岗位的 JD", "capability": "jobs"}
    elif engine is not None and not materials:
        next_action = {"title": "整理一段真实经历", "capability": "experience"}
    else:
        next_action = {"title": "为目标岗位准备申请材料", "capability": "application"}
    return {"ok": True, "mode": mode, "capabilities": catalog(mode), "next_action": next_action,
            "tasks": tasks, "pending": pending, "results": results, "materials": materials, "versions": versions,
            "interview_session": {k: session.get(k) for k in ("id", "user_status", "round")} if session else None,
            "counts": {"jobs": len(jobs), "materials": len(materials) if engine is not None else None,
                       "resumes": len(versions) if engine is not None else None, "mails": len(mails)},
            "setup": {"model": model_setup, "engine_connected": engine is not None,
                      "platform_connected": bool(runtime.get("ok")), "platform_error": runtime.get("error", "")},
            "partial": engine is None, "tool_labels": {name: spec[0] for name, spec in BUSINESS_TOOLS.items()}}


def _receipts(mode):
    root = backend.get_store(mode, seed_if_empty=False).root
    connection = sqlite3.connect(root / "workbench-operations.db", timeout=15)
    connection.execute("CREATE TABLE IF NOT EXISTS operation (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created REAL NOT NULL, tool TEXT NOT NULL DEFAULT '')")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        if "tool" not in {r[1] for r in connection.execute("PRAGMA table_info(operation)")}:
            connection.execute("ALTER TABLE operation ADD COLUMN tool TEXT NOT NULL DEFAULT ''")
    return connection


def execute(mode, name, arguments, operation_id):
    if mode != "user":
        raise backend.ApiError("工作台仅支持我的资料模式")
    try:
        args = validate_arguments(name, arguments)
    except ValueError as error:
        raise backend.ApiError(str(error)) from None
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", operation_id):
        raise backend.ApiError("操作编号无效")
    kind = BUSINESS_TOOLS[name][2]
    if kind in {"approval", "handoff"}:
        return handoff(mode, name, args)
    if kind == "read":
        return perform(mode, name, args)
    return execute_once(mode, name, args, operation_id, lambda: perform(mode, name, args))


def execute_once(mode, name, args, operation_id, operation):
    if not isinstance(operation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", operation_id):
        raise backend.ApiError("操作编号无效")
    signature = fingerprint({"name": name, "arguments": args, "mode": mode})
    connection = _receipts(mode)
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT fingerprint,state,result FROM operation WHERE id=?", (operation_id,)).fetchone()
            if row:
                if row[0] != signature:
                    raise backend.ApiError("同一操作编号不能变更内容", 409)
                if row[1] == "completed":
                    return json.loads(row[2])
                raise backend.ApiError("该操作已提交；请先查看真实状态，不能重复执行", 409)
            connection.execute("INSERT INTO operation (id,fingerprint,state,result,created,tool) VALUES (?,?,?,NULL,?,?)", (operation_id, signature, "started", time.time(), name))
        try:
            result = operation()
        except Exception:
            with connection:
                connection.execute("UPDATE operation SET state='unresolved' WHERE id=?", (operation_id,))
            raise
        with connection:
            connection.execute("UPDATE operation SET state='completed',result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), operation_id))
        return result
    finally:
        connection.close()


def delivery_preview(mode, ids):
    if mode != "user" or not isinstance(ids, list) or not 1 <= len(ids) <= 10 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise backend.ApiError("请明确选择最多十个真实岗位")
    store = backend.get_store(mode)
    jobs = {str(j["id"]): j for j in store.jobs()}
    queue = {str(j["id"]): j for j in store.queue()}
    if any(i not in jobs or queue.get(i, {}).get("status") != "approved" or not jobs[i].get("offerpilot_id") for i in ids):
        raise backend.ApiError("岗位或审批状态已变化，请重新选择", 409)
    greetings = backend.offerpilot_runtime.get_greetings([str(jobs[i]["offerpilot_id"]) for i in ids])
    by_id = {str(g["id"]): g for g in greetings.get("greetings", [])}
    items = []
    for job_id in ids:
        job = jobs[job_id]
        greeting = by_id.get(str(job["offerpilot_id"]), {})
        if not greeting.get("ready"):
            raise backend.ApiError("所选岗位还没有可复核的招呼语", 409)
        items.append({"job_id": job_id, "company": job.get("company"), "title": job.get("title"), "greeting": greeting.get("greeting")})
    binding = fingerprint({"jobs": [jobs[i] for i in ids], "queue": [queue[i] for i in ids],
                           "greetings": [by_id.get(str(jobs[i]["offerpilot_id"])) for i in ids], "profile": store.profile()})
    return {"ok": True, "items": items, "binding": binding}


def confirmed_action(mode, payload):
    if set(payload) != {"action", "arguments", "operation_id"} or not isinstance(payload["arguments"], dict):
        raise backend.ApiError("确认操作参数无效")
    action, args = payload["action"], payload["arguments"]
    allowed = {"save-profile": {"profile"}, "confirm": {"ids"},
               "sync-greeting": {"conversation_id", "artifact_id"},
               "offerpilot-deliver": {"ids", "confirm", "risk_acknowledged", "binding"},
               "offerpilot-start": {"mode", "data_mode", "confirm", "risk_acknowledged", "options"}}
    if not isinstance(action, str) or action not in allowed or set(args) - allowed[action]:
        raise backend.ApiError("未允许的确认操作")
    def commit():
        if action == "sync-greeting":
            if mode != "user" or set(args) != {"conversation_id", "artifact_id"} or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for v in args.values()):
                raise backend.ApiError("文案引用无效")
            draft = workbench_agent_runtime.upstream(mode, "POST",
                f"/v1/workbench/conversations/{args['conversation_id']}/artifacts/{args['artifact_id']}/greeting-preview",
                {"source": workbench_agent_runtime.workspace(mode)})
            store = backend.get_store(mode)
            job = next((j for j in store.jobs() if str(j["id"]) == draft["job_id"]), None)
            queued = next((r for r in store.queue() if str(r["id"]) == draft["job_id"] and r.get("status") == "approved"), None)
            if not job or not queued or not job.get("offerpilot_id"):
                raise backend.ApiError("请先把关联平台的目标岗位加入申请队列", 409)
            try:
                result = backend.offerpilot_runtime.save_reviewed_greeting(str(job["offerpilot_id"]), draft["text"])
            except (ValueError, KeyError) as error:
                raise backend.ApiError(str(error), 409) from None
            store.log("同步已核对的 Agent 文案", draft["job_id"] + "；尚未发送")
            return {**result, "job_id": draft["job_id"]}
        if action == "offerpilot-start":
            if args.get("data_mode") != mode:
                raise backend.ApiError("任务数据模式不一致")
            return backend.start_offerpilot_task(args)
        if action == "offerpilot-deliver":
            current = delivery_preview(mode, args.get("ids"))
            if not args.get("binding") or args["binding"] != current["binding"]:
                raise backend.ApiError("发送内容或资料已变化，请重新复核", 409)
            return backend.start_offerpilot_deliver({k: v for k, v in {**args, "mode": mode}.items() if k != "binding"})
        return {"save-profile": backend.save_profile, "confirm": backend.confirm_queue}[action]({**args, "mode": mode})
    return execute_once(mode, action, args, payload["operation_id"], commit)


def handoff(mode, name, args):
    # A model can request the existing review form; it cannot manufacture a human approval.
    if mode != "user" and name in {"collect_jobs", "review_delivery", "prepare_github_project"}:
        raise backend.ApiError("该操作仅在我的资料模式开放", 403)
    capability = {"approve_jobs": "queue", "review_delivery": "queue", "prepare_github_project": "github", "collect_jobs": "collect"}[name]
    return {"ok": True, "needs_input": "请在工作区核对并完成确认。", "ui_action": {
        "capability": capability, "operation": name, "values": args}}


def perform(mode, name, a):
    base = {"mode": mode, "data_mode": mode}
    if name == "record_job":
        return backend.parse_jd({**base, **a})
    if name == "import_job_json":
        return backend.import_jobs({**base, **a})
    if name == "collection_status":
        return {"ok": True, "state": backend.get_offerpilot_state(mode), "results": backend.get_offerpilot_jobs(mode)}
    if name == "stop_collection":
        return backend.stop_offerpilot_task(a["task_id"], mode)
    if name == "import_collected_jobs":
        return backend.import_offerpilot_jobs({**base, **a})
    if name == "enqueue_jobs":
        return backend.enqueue({**base, **a})
    if name == "prepare_greetings":
        return backend.start_offerpilot_greet({**base, **a})
    if name == "parse_hr_mail":
        return backend.parse_mail({**base, "subject": a["text"].splitlines()[0][:1000], "body": a["text"], "date": a["received_date"]})
    if name == "export_calendar":
        return backend.generate_ics({**base, "id": a["mail_id"]})
    if name == "build_worksheet":
        return backend.worksheet({**base, **a})
    if name == "start_mock_interview":
        current = backend.get_store(mode).interview_session()
        if backend._in_progress_interview(current):
            raise backend.ApiError("已有进行中的面试，请先继续或结束本场面试", 409)
        return backend.interview_start({**base, **a})
    if name in {"reply_mock_interview", "finish_mock_interview"}:
        current = backend.get_store(mode).interview_session()
        if not current or current.get("id") != a["session_id"]:
            raise backend.ApiError("面试会话已变化，请重新选择", 409)
        if name == "reply_mock_interview":
            return backend.interview_reply({**base, "session_id": a["session_id"], "text": a["text"]})
        return backend.interview_end({**base, "session_id": a["session_id"]})
    if name in {"export_resume_version", "start_version_interview", "reply_project_interview"}:
        if mode != "user":
            raise backend.ApiError("简历版本面试仅在我的资料模式开放", 403)
        if name == "reply_project_interview":
            session_id = a["session_id"]
            if not re.fullmatch(r"opuser_[A-Za-z0-9_-]{1,64}", session_id):
                raise backend.ApiError("个人面试会话编号无效")
            payload = {"event_id": uuid.uuid4().hex, "text": a["text"], **({"command": a["command"]} if a["command"] else {})}
            return career_user_runtime.dispatch("POST", f"/api/career-user/interviews/{session_id}/turns", {"mode": mode}, payload)[0]
        version_id = a["resume_version_id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", version_id):
            raise backend.ApiError("简历版本编号无效")
        version = career_user_runtime.dispatch("GET", "/api/career-user/resumes/" + version_id, {"mode": mode})[0]
        if name == "export_resume_version":
            if a["format"] not in {"pdf", "print"} or a["template"] not in {"professional", "classic"}:
                raise backend.ApiError("请选择 PDF 或打印，以及现有简历模板")
            return {"ok": True, "message": "已准备所选简历版本的导出链接。", "download_url":
                    f"/api/career-user/resumes/{version_id}/{a['format']}?mode=user&template={a['template']}"}
        version = version.get("version", version)
        return career_user_runtime.dispatch("POST", "/api/career-user/interviews", {"mode": mode},
            {"material_id": version["interview_material_id"], "session_id": "opuser_" + uuid.uuid4().hex,
             "interview_mode": "mock_interview"})[0]
    if name == "review_transcript":
        return backend.debrief({**base, "transcript": a["text"]})
    if name == "add_interview_question":
        return backend.add_bank_question({**base, **a})
    if name == "save_experience_variant":
        return backend.add_variant({**base, **a})
    if name == "push_preview":
        job = next((j for j in backend.get_store(mode).jobs() if str(j["id"]) == a["job_id"]), None)
        if not job:
            raise backend.ApiError("目标岗位不存在", 404)
        return backend.dry_run({**base, **job, "job_id": a["job_id"]})
    if name == "export_workspace":
        return backend.export_data(mode)
    routes = {
        "knowledge_sources": ("GET", "/knowledge/sources", {}),
        "search_project_knowledge": ("POST", "/knowledge/search", {**a, "top_k": 8}),
        "collect_note": ("POST", "/notes/collect", a),
        "subscribe_note": ("POST", "/notes/subscriptions", a),
        "note_subscriptions": ("GET", "/notes/subscriptions", {}),
        "note_inbox": ("GET", "/notes/inbox", {}),
        "note_self_check": ("GET", "/notes/self-check", {}),
    }
    for tool, field, prefix, suffix in (("pause_note_subscription", "subscription_id", "/notes/subscriptions/", "/pause"),
            ("resume_note_subscription", "subscription_id", "/notes/subscriptions/", "/resume"),
            ("read_note", "note_id", "/notes/items/", ""), ("mark_note_read", "message_id", "/notes/inbox/", "/read"),
            ("project_knowledge_context", "snapshot_id", "/knowledge/snapshots/", "/context")):
        if name == tool:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", a[field]):
                raise backend.ApiError("记录编号无效")
            routes[name] = ("GET" if name in {"read_note", "project_knowledge_context"} else "POST", prefix + a[field] + suffix, {})
    if name in routes:
        if mode != "user":
            raise backend.ApiError("个人知识库与面经仅在我的资料模式开放", 403)
        method, path, payload = routes[name]
        query = {"mode": mode, **({"offset": str(a["offset"]), "limit": "30"} if name == "note_inbox" else {})}
        if name == "knowledge_sources":
            query.update(offset=str(a.get("offset", 0)), limit="100")
        return career_user_runtime.dispatch(method, "/api/career-user" + path, query, payload)[0]
    raise backend.ApiError("该业务尚未接入", 404)


def internal(headers, payload):
    mode = payload.get("mode")
    token_name = {"user": "OFFERPILOT_CAREER_USER_TOKEN"}.get(mode)
    token = os.getenv(token_name, "") if token_name else ""
    if not token or not hmac.compare_digest(str(headers.get("Authorization", "")).encode(), ("Bearer " + token).encode()):
        raise backend.ApiError("内部调用未授权", 403)
    if set(payload) != {"mode", "tool", "arguments", "operation_id"}:
        raise backend.ApiError("内部业务参数无效")
    result = execute(mode, payload["tool"], payload["arguments"], payload["operation_id"])
    return {"result": result, "source": workbench_agent_runtime.workspace(mode)}


def dispatch(method, path, query, payload=None):
    mode = query.get("mode")
    if mode != "user" or set(query) != {"mode"}:
        raise backend.ApiError("工作台仅支持我的资料模式")
    payload = payload or {}
    if method == "GET" and path == "/api/workbench/overview":
        return overview(mode), 200
    if path == "/api/workbench/settings":
        if method == "GET":
            return {"ok": True, **settings_status()}, 200
        if method == "POST":
            raise backend.ApiError("模型密钥只能在「08 设置 › AI 接口设置」中配置", 400)
    if method == "POST" and path == "/api/workbench/actions" and set(payload) == {"tool", "arguments", "operation_id"}:
        return execute(mode, payload["tool"], payload["arguments"], payload["operation_id"]), 200
    if method == "POST" and path == "/api/workbench/delivery-preview" and set(payload) == {"ids"}:
        return delivery_preview(mode, payload["ids"]), 200
    if method == "POST" and path == "/api/workbench/confirmed-action":
        return confirmed_action(mode, payload), 200
    raise backend.ApiError("未找到工作台操作", 404)
