"""Personal career routes. Only this module may bridge user mode to port 18748."""

import base64
import http.client
import json
import os
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


PROFILE_SECTIONS = ("experiences", "projects")


def profile_selection(payload):
    """Validate the checked profile entries sent by the resume page.

    Entries are addressed by (section, index) into the stored profile, so the
    browser never has to resend personal text and the server stays the source
    of truth.
    """
    items = payload.get("items")
    if not isinstance(items, list) or not items or len(items) > 20:
        raise backend.ApiError("请至少勾选一段经历或项目（最多 20 段）")
    selection, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"section", "index", "note"}:
            raise backend.ApiError("经历选择参数无效")
        section, index = item.get("section"), item.get("index")
        note = item.get("note") or ""
        if section not in PROFILE_SECTIONS or not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise backend.ApiError("经历选择参数无效")
        if not isinstance(note, str) or len(note) > 400:
            raise backend.ApiError("每段经历的补充说明请控制在 400 字以内")
        key = (section, index)
        if key in seen:
            continue
        seen.add(key)
        selection.append({"section": section, "index": index, "note": note.strip()})
    return selection


def profile_rows(profile, item):
    rows = profile.get(item["section"]) or []
    if item["index"] >= len(rows):
        raise backend.ApiError("所选经历已不在个人资料中，请刷新页面后重试", 409)
    row = rows[item["index"]]
    return row if isinstance(row, dict) else {}


def selected_profile(profile, items):
    """Keep only the checked entries, in the order the user arranged them."""
    order = {section: [] for section in PROFILE_SECTIONS}
    for item in profile_selection({"items": items}):
        order[item["section"]].append(profile_rows(profile, item))
    data = dict(profile)
    data.update(order)
    return data


def _row_heading(item, row):
    keys = ("company", "title") if item["section"] == "experiences" else ("name", "role")
    return " · ".join(str(row.get(key) or "").strip() for key in keys if str(row.get(key) or "").strip())


def experience_from_profile(profile, items, role, jd):
    """Compose one engine `experience-import` payload from checked profile rows.

    The first checked entry is the one the model rewrites into resume bullets;
    every checked entry still goes into the source text so claims stay grounded.
    """
    primary = items[0]
    row = profile_rows(profile, primary)
    summary = str(row.get("summary") or "").strip()
    note = primary["note"]
    if primary["section"] == "experiences":
        title = str(row.get("title") or "").strip()
        kind = "internship" if "实习" in title else "work"
        name = title or str(row.get("company") or "").strip()
        organization, position = str(row.get("company") or "").strip(), title
    else:
        kind = "project"
        name = str(row.get("name") or "").strip()
        organization, position = "", str(row.get("role") or "").strip()
    if not name:
        raise backend.ApiError("所选经历缺少名称，请先到个人资料补全")
    if not (summary or note):
        raise backend.ApiError("这段经历缺少说明，请在卡片里补充一句再生成")
    lines = []
    for item in items:
        current = profile_rows(profile, item)
        heading = _row_heading(item, current)
        period = " - ".join(part for part in (str(current.get("start") or "").strip(), str(current.get("end") or "").strip()) if part)
        label = "工作 / 实习经历" if item["section"] == "experiences" else "项目经历"
        lines.append(f"{label}：{heading}" + (f"（{period}）" if period else ""))
        body = str(current.get("summary") or "").strip()
        if body:
            lines.append(body)
        if item["note"]:
            lines.append("本人补充：" + item["note"])
        lines.append("")
    return {
        "kind": kind,
        "name": name[:120],
        "organization": organization[:120],
        "position": position[:120],
        "start": str(row.get("start") or "").strip()[:40],
        "end": str(row.get("end") or "").strip()[:40],
        "role": role,
        "jd": jd,
        "context": (summary or note)[:4000],
        "contribution": (summary or note)[:4000],
        "outcome": "",
        "source_text": "\n".join(lines).strip()[:20000],
        "portfolio_url": "",
        "confirmed": True,
        "model_consent": True,
    }


def _enrich_comprehensive_start(payload):
    """在本地服务端自动汇聚画像、已选岗位快照与同目标面经/知识，避免浏览器伪造或遗漏。"""
    enriched = dict(payload)
    try:
        store = backend.get_store("user")
    except Exception:
        return enriched
    if "profile_snapshot" not in enriched or not enriched["profile_snapshot"]:
        try:
            enriched["profile_snapshot"] = backend.profile_public(store.profile())
        except Exception:
            pass
    job_id = enriched.get("job_id")
    company = ""
    role = ""
    if isinstance(enriched.get("job_snapshot"), dict):
        company = str(enriched["job_snapshot"].get("company") or "")
        role = str(enriched["job_snapshot"].get("role") or "")
    try:
        snap = store.snapshot()
        jobs = snap.get("jobs") or []
    except Exception:
        jobs = []
    if job_id and (not enriched.get("job_snapshot")) and jobs:
        matched = next((j for j in jobs if str(j.get("id")) == str(job_id)), None)
        if matched:
            company = str(matched.get("company") or "")
            role = str(matched.get("title") or matched.get("role") or "")
            enriched["job_snapshot"] = {
                "job_id": str(matched.get("id")),
                "company": company,
                "role": role,
                "jd": str(matched.get("jd") or matched.get("description") or enriched.get("jd_text") or ""),
                "risk_signals": [],
                "mandatory_conditions": [],
            }
    if not enriched.get("external_materials"):
        try:
            materials = store.interview_materials() if hasattr(store, "interview_materials") else []
            ext = []
            for item in materials or []:
                if not isinstance(item, dict) or not item.get("body"):
                    continue
                item_co = str(item.get("company") or "")
                item_role = str(item.get("role") or "")
                if company and item_co and company.lower() not in item_co.lower():
                    continue
                ext.append(
                    {
                        "ref_id": str(item.get("id") or f"mat_{len(ext) + 1}")[:120],
                        "kind": "knowledge" if item.get("kind") == "knowledge" else "jingyan",
                        "scope": "company_jingyan" if item_co else "similar_role_other_company",
                        "company": item_co[:200],
                        "role": item_role[:200],
                        "title": str(item.get("title") or "")[:300],
                        "body": str(item.get("body") or "")[:8000],
                        "source_url": str(item.get("source_url") or "")[:1000],
                    }
                )
                if len(ext) >= 12:
                    break
            if ext:
                enriched["external_materials"] = ext
        except Exception:
            pass
    return enriched


def export_comprehensive_markdown(path, query):
    query = dict(query)
    if query.get("mode") != "user" or set(query) - {"mode", "format"}:
        raise backend.ApiError("综合面试导出参数无效", 400)
    match = re.fullmatch(rf"/api/career-user/comprehensive-interviews/({ID})/export", path)
    if not match:
        raise backend.ApiError("综合面试会话参数无效", 400)
    data = upstream("GET", f"/v1/comprehensive-interviews/{match.group(1)}/export")
    return str(data.get("markdown") or "").encode("utf-8"), str(data.get("filename") or f"mock-interview-{match.group(1)}.md")


def stream_comprehensive(path, query, payload=None):
    """代理综合模拟面试的 SSE 流式接口（逐帧透传 token 与 done/error）。"""
    payload = dict(payload or {})
    query = dict(query)
    if query.pop("mode", None) != "user" or payload.pop("mode", "user") != "user" or query:
        raise backend.ApiError("个人综合模拟面试仅在我的 user 模式开放", 400)
    match = re.fullmatch(rf"/api/career-user/comprehensive-interviews/({ID})/stream", path)
    if not match:
        raise backend.ApiError("综合面试流式参数无效", 400)
    token = os.environ.get("OFFERPILOT_CAREER_USER_TOKEN", "")
    if len(token) < 20:
        raise backend.ApiError("综合面试服务未启动：请先在本机启动服务后重试", 503)

    sid = match.group(1)
    connection = http.client.HTTPConnection("127.0.0.1", 18748, timeout=150)
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        connection.request(
            "POST",
            f"/v1/comprehensive-interviews/{sid}/stream",
            body=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        response = connection.getresponse()
        if response.status >= 400:
            connection.close()
            messages = {400: "流式参数无效", 404: "综合面试会话不存在", 409: "会话状态冲突或已结束", 422: "流式请求格式无效"}
            raise backend.ApiError(messages.get(response.status, "综合面试流式服务暂不可用"), response.status)

        def _iter_frames():
            try:
                buf = b""
                while True:
                    chunk = response.readline(64 * 1024)
                    if not chunk:
                        if buf:
                            yield buf
                        break
                    buf += chunk
                    if chunk in (b"\n", b"\r\n"):
                        yield buf
                        buf = b""
            finally:
                connection.close()

        gen = _iter_frames()
        first = next(gen, b"")
        yield first
        yield from gen
    except backend.ApiError:
        raise
    except (OSError, http.client.HTTPException):
        connection.close()
        raise backend.ApiError("综合面试流式连接中断，可点击重试恢复草稿", 503) from None


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
    if method == "POST" and suffix == "/profile-experience" and not query:
        if not {"items", "role"} <= set(payload) or set(payload) - {"items", "role", "jd", "confirmed", "model_consent"}:
            raise backend.ApiError("定制简历参数无效")
        if payload.get("confirmed") is not True or payload.get("model_consent") is not True:
            raise backend.ApiError("请勾选确认真实性并允许模型整理这份简历")
        role = payload.get("role")
        jd = payload.get("jd") or ""
        if not isinstance(role, str) or not role.strip() or len(role) > 200:
            raise backend.ApiError("请先选择或填写目标岗位")
        if not isinstance(jd, str) or len(jd) > 15000:
            raise backend.ApiError("岗位 JD 过长，请精简到 15000 字以内")
        items = profile_selection(payload)
        profile = backend.profile_public(backend.get_store("user").profile())
        if not profile.get("truth_confirmed") or not profile.get("basic", {}).get("name"):
            raise backend.ApiError("请先在个人资料填写姓名并确认资料事实，再生成简历")
        data = experience_from_profile(profile, items, role.strip(), jd)
        return {"ok": True, **upstream("POST", "/v1/career/experience-import", data)}, 202
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
        allowed = ({"session_id"}, {"material_id"}, {"session_id", "items"}, {"material_id", "items"})
        if set(payload) not in allowed:
            raise backend.ApiError("简历预览参数无效")
        profile = backend.profile_public(backend.get_store("user").profile())
        if not profile.get("truth_confirmed") or not profile.get("basic", {}).get("name"):
            raise backend.ApiError("请先在个人资料填写姓名并确认资料事实，再生成简历预览")
        if "items" in payload:
            # 定制简历页勾选的条目决定这份简历包含哪些经历；其余资料字段照常带入。
            profile = selected_profile(profile, payload.pop("items"))
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
    if suffix == "/comprehensive-interviews" and method == "POST" and not query:
        enriched = _enrich_comprehensive_start(payload)
        view = upstream("POST", "/v1/comprehensive-interviews", enriched)
        return {"ok": True, "view": view}, 201
    comp_match = re.fullmatch(
        rf"/comprehensive-interviews/({ID})(?:/(turns|finish|recap|export|drill))?",
        suffix,
    )
    if comp_match:
        sid, op = comp_match.groups()
        if op == "export" and method == "GET" and not (set(query) - {"format"}):
            fmt = query.get("format", "json")
            if fmt not in {"json", "markdown"}:
                raise backend.ApiError("导出格式仅支持 json 或 markdown", 400)
            return {"ok": True, **upstream("GET", f"/v1/comprehensive-interviews/{sid}/export?format={fmt}")}, 200
        if query:
            raise backend.ApiError("综合面试接口参数无效", 400)
        if op is None and method == "GET":
            return {"ok": True, "view": upstream("GET", f"/v1/comprehensive-interviews/{sid}")}, 200
        if op == "turns" and method == "POST":
            return {"ok": True, "view": upstream("POST", f"/v1/comprehensive-interviews/{sid}/turns", payload)}, 200
        if op == "finish" and method == "POST":
            return {"ok": True, "view": upstream("POST", f"/v1/comprehensive-interviews/{sid}/finish", payload or {})}, 200
        if op == "recap" and method == "GET":
            return {"ok": True, "recap": upstream("GET", f"/v1/comprehensive-interviews/{sid}/recap")}, 200
        if op == "drill" and method == "POST":
            return {"ok": True, "feedback": upstream("POST", f"/v1/comprehensive-interviews/{sid}/drill", payload)}, 200
        raise backend.ApiError("未找到综合面试操作", 404)
    raise backend.ApiError("未找到个人项目操作", 404)
