"""Personal career routes. Only this module may bridge user mode to port 18748."""

import base64
import re
from urllib.parse import urlencode

import backend
from career_agent_runtime import service_request

ID = r"[A-Za-z0-9_-]{1,100}"


def export_template(query):
    from resume_layout import template_name
    if query.get("mode") != "user" or set(query) - {"mode", "template"}:
        raise backend.ApiError("简历导出参数无效")
    try:
        return template_name(query.get("template", "professional"))
    except ValueError as error:
        raise backend.ApiError(str(error)) from None


def pdf_document(path, query):
    match = re.fullmatch(rf"/api/career-user/resumes/({ID})/pdf", path)
    if not match:
        raise backend.ApiError("PDF 导出参数无效")
    template = export_template(query)
    version = upstream("GET", "/v1/career/resumes/" + match.group(1))
    try:
        from resume_pdf import render_pdf
        return render_pdf(version['markdown'], role=version.get('job_snapshot', {}).get('role', ''), template=template)
    except ImportError:
        raise backend.ApiError("请安装 requirements-offerpilot.txt 中的 PDF 导出依赖后重启服务", 503) from None
    except ValueError as error:
        raise backend.ApiError(str(error), 503) from None


def print_document(path, query):
    match = re.fullmatch(rf"/api/career-user/resumes/({ID})/print", path)
    if not match:
        raise backend.ApiError("打印参数无效")
    template = export_template(query)
    version = upstream("GET", "/v1/career/resumes/" + match.group(1))
    from resume_layout import print_html
    return print_html(version["markdown"], role=version.get("job_snapshot", {}).get("role", ""), template=template)


def upstream(method, path, payload=None):
    return service_request(18748, "OFFERPILOT_CAREER_USER_TOKEN", method, path, payload)


def dispatch(method, path, query, payload=None):
    payload = dict(payload or {})
    query = dict(query)
    if query.pop("mode", None) != "user" or payload.pop("mode", "user") != "user":
        raise backend.ApiError("个人项目仅在我的 user 模式开放", 400)
    suffix = path.removeprefix("/api/career-user")
    if suffix.startswith("/notes/"):
        operation = suffix.removeprefix("/notes")
        if method == "GET" and operation in {"/subscriptions", "/self-check"} and not query:
            return upstream("GET", "/v1/notes" + operation), 200
        if method == "GET" and operation == "/inbox" and not set(query) - {"limit", "offset"}:
            return upstream("GET", "/v1/notes/inbox" + ("?" + urlencode(query) if query else "")), 200
        if method == "GET" and re.fullmatch(rf"/items/{ID}", operation) and not query:
            return upstream("GET", "/v1/notes" + operation), 200
        if method == "GET" and re.fullmatch(rf"/subscriptions/{ID}/runs", operation) and not set(query) - {"limit"}:
            return upstream("GET", "/v1/notes" + operation + ("?" + urlencode(query) if query else "")), 200
        if method == "POST" and operation in {"/collect", "/subscriptions"} and not query:
            return upstream("POST", "/v1/notes" + operation, payload), 201 if operation == "/subscriptions" else 200
        if (method == "POST" and not query and not payload
                and re.fullmatch(rf"/(?:subscriptions/{ID}/(?:pause|resume)|inbox/{ID}/read)", operation)):
            return upstream("POST", "/v1/notes" + operation, {}), 200
        raise backend.ApiError("面经接口参数无效", 400)
    if suffix.startswith("/knowledge/"):
        operation = suffix.removeprefix("/knowledge")
        if method == "GET" and operation == "/sources" and not set(query) - {"limit", "offset"}:
            return {"ok": True, **upstream("GET", "/v1/knowledge/sources" + ("?" + urlencode(query) if query else ""))}, 200
        if method == "POST" and operation in {"/sources", "/warmup", "/search"} and not query:
            status = 200 if operation == "/search" else 202
            return {"ok": True, **upstream("POST", "/v1/knowledge" + operation, payload)}, status
        if method == "GET" and re.fullmatch(rf"/snapshots/{ID}/context", operation) and not query:
            return {"ok": True, **upstream("GET", "/v1/knowledge" + operation)}, 200
        raise backend.ApiError("知识库接口参数无效", 400)
    if method == "POST" and suffix == "/experience-text" and not query:
        if set(payload) != {"filename", "content_base64"}:
            raise backend.ApiError("请选择完整的经历或作品集文字文件")
        from profile_import import extract_resume_text, MAX_BYTES
        filename, encoded = payload["filename"], payload["content_base64"]
        if not isinstance(filename, str) or not filename or len(filename) > 255 or not isinstance(encoded, str) or len(encoded) > 7 * 1024 * 1024:
            raise backend.ApiError("文件参数无效；文件不能超过 5 MB")
        try:
            content = base64.b64decode(encoded, validate=True)
            if len(content) > MAX_BYTES:
                raise ValueError("文件不能超过 5 MB")
            text = extract_resume_text(filename, content)
            if len(text) > 20000:
                raise ValueError("单段经历材料请精简至 20000 字符以内")
        except ValueError as error:
            raise backend.ApiError(str(error)) from None
        return {"ok": True, "text": text}, 200
    if method == "POST" and suffix == "/experience-import" and not query:
        return {"ok": True, **upstream("POST", "/v1/career/experience-import", payload)}, 202
    if method == "GET" and suffix == "/github/status" and not query:
        return {"ok": True, **upstream("GET", "/v1/career/github/status")}, 200
    if method == "POST" and suffix in {"/github/config", "/github/start", "/github/poll", "/github/disconnect"} and not query:
        return {"ok": True, **upstream("POST", "/v1/career" + suffix, payload)}, 200
    if method == "GET" and suffix in {"/github/repositories", "/github/tree", "/github/file"}:
        allowed = {"page"} if suffix.endswith("repositories") else {"repository", "page"} if suffix.endswith("tree") else {"repository", "commit", "path"}
        if set(query) - allowed:
            raise backend.ApiError("仓库读取参数无效")
        return {"ok": True, **upstream("GET", "/v1/career" + suffix + "?" + urlencode(query))}, 200
    if suffix == "/projects" and not query and method in {"GET", "POST"}:
        return {"ok": True, **upstream(method, "/v1/career/projects", payload if method == "POST" else None)}, 202 if method == "POST" else 200
    if re.fullmatch(rf"/projects/{ID}(?:/confirm)?", suffix) and not query:
        allowed = "POST" if suffix.endswith("/confirm") else "GET"
        if method == allowed:
            return {"ok": True, **upstream(method, "/v1/career" + suffix, payload if method == "POST" else None)}, 200
    if method == "POST" and suffix == "/resume-drafts" and not query:
        if set(payload) not in ({"session_id"}, {"material_id"}):
            raise backend.ApiError("简历预览参数无效")
        profile = backend.profile_public(backend.get_store("user").profile())
        if not profile.get("truth_confirmed") or not profile.get("basic", {}).get("name"):
            raise backend.ApiError("请先在个人资料填写姓名并确认资料事实，再生成简历预览")
        payload["profile"] = profile
        return {"ok": True, **upstream("POST", "/v1/career/resume-drafts", payload)}, 201
    if method == "POST" and re.fullmatch(rf"/resume-drafts/{ID}/save", suffix) and not query:
        return {"ok": True, **upstream("POST", "/v1/career" + suffix, payload)}, 201
    if method == "GET" and (suffix == "/resumes" or re.fullmatch(rf"/resumes/{ID}", suffix)) and not query:
        return {"ok": True, **upstream("GET", "/v1/career" + suffix)}, 200
    if method == "POST" and suffix == "/interviews" and not query:
        if set(payload) != {"material_id", "session_id", "interview_mode"}:
            raise backend.ApiError("面试参数无效")
        data = {"material_id": payload["material_id"], "session_id": payload["session_id"],
                "mode": payload.get("interview_mode", "resume_readiness")}
        if not re.fullmatch(r"opuser_[A-Za-z0-9_-]{1,64}", str(data["session_id"])):
            raise backend.ApiError("个人会话 id 无效")
        # Target is read from a server-owned frozen material, never from a browser JD override.
        context = upstream("GET", f"/v1/career/materials/{data['material_id']}/evidence")
        data["target"] = context["target"]
        view = upstream("POST", "/v1/career/interviews", data)
        return {"ok": True, "view": view, "evidence": context["evidence"]}, 201
    match = re.fullmatch(r"/interviews/(opuser_[A-Za-z0-9_-]{1,64})(?:/(turns|recap))?", suffix)
    if match and not query:
        session_id, operation = match.groups()
        if method == "GET" and operation == "recap":
            return {"ok": True, "recap": upstream("GET", f"/v1/sessions/{session_id}/recap")["payload"]}, 200
        if method == "GET" and operation is None or method == "POST" and operation == "turns":
            view = upstream(method, f"/v1/interviews/{session_id}" + ("/turns" if operation else ""), payload if method == "POST" else None)
            plan = upstream("GET", f"/v1/sessions/{session_id}/question-plan")["payload"]
            context = upstream("GET", f"/v1/career/materials/{plan['material_id']}/evidence")
            if view.get("is_demo") is not False:
                raise backend.ApiError("个人与演示会话不能混用", 403)
            return {"ok": True, "view": view, "evidence": context["evidence"]}, 200
    raise backend.ApiError("未找到个人项目操作", 404)
