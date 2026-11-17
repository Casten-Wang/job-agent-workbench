"""Same-origin bridge to the isolated public-project interview service."""

from functools import lru_cache
import http.client
import json
import os
from pathlib import Path
import re

from backend import ApiError

AGENT_PORT = 18747
MATERIAL_ID = "mat_6c05373d57d03a107d49806c"
SOURCE_COMMIT = "672971d66a2ef9f85151e53283113f33d642dabd"
FIXTURE = Path(__file__).resolve().parents[1] / "examples/career-agent/itsdangerous-material.json"
SESSION_ID = re.compile(r"opdemo_[A-Za-z0-9_-]{1,64}\Z")
EVENT_ID = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
COMMANDS = {"request_hint", "open_book", "ai_assisted", "skip", "pause", "resume", "finish", "retry",
            "correct_contribution", "correct_version"}


@lru_cache(maxsize=1)
def public_fixture():
    material = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if (material.get("material_id") != MATERIAL_ID or material.get("is_demo") is not True
            or material.get("source_commit") != SOURCE_COMMIT or material.get("resume_version_id") is not None):
        raise ApiError("公开样例版本不匹配", 503)
    return material


def _request(method, path, payload=None):
    return service_request(AGENT_PORT, "OFFERPILOT_CAREER_AGENT_TOKEN", method, path, payload)


def service_request(port, token_env, method, path, payload=None):
    token = os.environ.get(token_env, "")
    if len(token) < 20:
        raise ApiError("项目核验服务未启动，请使用公开样例启动脚本", 503)
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=150)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        connection.request(method, path, body=body, headers={"Authorization": "Bearer " + token,
                           "Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ApiError("项目核验服务响应过大", 502)
        if response.status >= 400:
            messages = {400: "材料或会话绑定无效", 401: "项目核验服务连接配置不匹配",
                        404: "样例会话尚不存在，请重新开始核验", 409: "会话状态冲突，请刷新后重试未完成操作",
                        422: "答题请求格式无效", 502: "模型调用未完成，可重试或结束保存待复核记录"}
            message = messages.get(response.status, "项目核验服务暂不可用")
            if response.status == 502:
                try:
                    code = json.loads(raw).get("code")
                except (ValueError, AttributeError):
                    code = None
                model_errors = {"provider_http_401": "模型密钥无效，请更新本机配置后重启",
                                "provider_http_403": "模型服务拒绝访问，请核对账号与模型权限",
                                "provider_http_429": "模型服务限流，请稍后重试同一轮核验",
                                "model_transport_failed": "模型网络连接失败，请检查网络后重试",
                                "model_timeout": "模型响应超时，请重试同一轮核验",
                                "invalid_model_decision": "模型响应未通过格式校验，请重试同一轮核验"}
                if isinstance(code, str):
                    message = model_errors.get(code, message)
            if response.status == 400 and token_env == "OFFERPILOT_CAREER_USER_TOKEN":
                # Only our known GitHubError texts are actionable; never relay arbitrary provider bodies.
                try:
                    safe_error = json.loads(raw).get("error", "")
                    if isinstance(safe_error, str) and safe_error.startswith(("GitHub ", "请先连接 GitHub", "请输入 GitHub", "这里需要公开", "首次连接需要", "授权请求已失效", "无法读取本机 GitHub", "已收到授权")) and len(safe_error) <= 200:
                        message = safe_error
                except (ValueError, AttributeError):
                    pass
            raise ApiError(message,
                           response.status if response.status in {400, 404, 409, 422, 502} else 503)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Expected object")
        return data
    except (OSError, http.client.HTTPException):
        raise ApiError("项目核验服务连接中断，请刷新恢复同一会话", 503) from None
    except (ValueError, UnicodeError):
        raise ApiError("项目核验服务响应格式异常", 502) from None
    finally:
        connection.close()


def _check_plan(session_id):
    plan = _request("GET", f"/v1/sessions/{session_id}/question-plan").get("payload", {})
    if (plan.get("material_id") != MATERIAL_ID or plan.get("source_commit") != SOURCE_COMMIT
            or plan.get("project_snapshot_id") != public_fixture()["project_snapshot_id"]):
        raise ApiError("只允许访问当前公开样例会话", 403)


def _view(value):
    if value.get("is_demo") is not True:
        raise ApiError("只允许访问公开样例", 403)
    ids = (value.get("question") or {}).get("evidence_ids", [])
    evidence = [e for e in public_fixture()["evidence"] if e["evidence_id"] in ids]
    return {"ok": True, "view": value, "evidence": evidence}


def dispatch(method, path, query, payload=None):
    payload = payload or {}
    if set(query) - {"mode"} or query.get("mode", "demo") != "demo" or payload.get("mode", "demo") != "demo":
        raise ApiError("公开样例仅在演示 demo 模式开放", 400)
    if method == "GET" and path == "/api/resume-agent/materials":
        rows = _request("GET", "/v1/materials").get("items", [])
        rows = [row for row in rows if row.get("material_id") == MATERIAL_ID
                and row.get("source_commit") == SOURCE_COMMIT and row.get("is_demo") is True]
        return {"ok": True, "items": rows, "public_demo": True}, 200
    if method == "POST" and path == "/api/interview-agent/sessions":
        if set(payload) - {"mode", "session_id"}:
            raise ApiError("公开样例不接收个人资料或自定义材料")
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not SESSION_ID.fullmatch(session_id):
            raise ApiError("样例会话 id 无效")
        value = _request("POST", "/v1/interviews", {"session_id": session_id, "material_id": MATERIAL_ID,
                         "mode": "resume_readiness", "target": {"role": "初级后端", "round": "公开项目核验演示"}})
        return _view(value), 201
    match = re.fullmatch(r"/api/interview-agent/sessions/(opdemo_[A-Za-z0-9_-]{1,64})(?:/(turns|recap))?", path)
    if not match:
        raise ApiError("未找到项目核验操作", 404)
    session_id, operation = match.groups()
    if method == "POST" and operation == "turns":
        if set(payload) - {"mode", "event_id", "text", "command"}:
            raise ApiError("答题请求包含未知字段")
        if not isinstance(payload.get("event_id"), str) or not EVENT_ID.fullmatch(payload["event_id"]):
            raise ApiError("答题事件 id 无效")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ApiError("请输入 1–12000 字的回答")
        command = payload.get("command")
        if command is not None and (not isinstance(command, str) or command not in COMMANDS):
            raise ApiError("面试操作无效")
        _check_plan(session_id)
        event = {key: payload[key] for key in ("event_id", "text", "command") if key in payload}
        return _view(_request("POST", f"/v1/interviews/{session_id}/turns", event)), 200
    if method == "GET" and operation is None:
        _check_plan(session_id)
        return _view(_request("GET", f"/v1/interviews/{session_id}")), 200
    if method == "GET" and operation == "recap":
        _check_plan(session_id)
        recap = _request("GET", f"/v1/sessions/{session_id}/recap").get("payload", {})
        if recap.get("material_id") != MATERIAL_ID or recap.get("is_demo") is not True:
            raise ApiError("复盘不属于当前公开样例", 403)
        return {"ok": True, "recap": recap}, 200
    raise ApiError("未找到项目核验操作", 404)
