"""Owner-scoped, checkpointed workbench agent. Business writes require approval."""

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
import re
import uuid
from urllib.parse import urlsplit

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing import TypedDict

from interview_hub.career_store import CareerRecords
from interview_hub.store import ConflictError, NotFoundError
from .career import digest
from .model_adapter import ModelError
from .workbench_contracts import INPUTS, Decision, Recommendations, ApplicationDraft, DraftReview, Attachment
from .workbench_catalog import BUSINESS_TOOLS, CAPABILITIES


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def redact(value):
    """Only professional data reaches the model, including free-text inputs."""
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items() if key.lower() not in {
            "private_profile", "basic", "phone", "email", "wechat", "links", "token", "authorization",
            "credentials", "api_key", "access_token", "secret", "device_code", "source_quote"}}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[已隐藏联系方式]", value)
        value = re.sub(r"(?i)(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{8,}|(?:api[_ -]?key|token|password|密钥|微信)\s*[:：=]\s*\S+", "[已隐藏敏感信息]", value)
    return value


class GraphState(TypedDict, total=False):
    data: dict
    decision: dict
    approval: dict
    route: str


class WorkbenchWorkflow:
    def __init__(self, repo, agent, saver, *, career=None, token="", mode="demo", notes=None):
        self.repo, self.agent, self.career, self.token, self.mode = repo, agent, career, token, mode
        self.notes = notes
        self.records = CareerRecords(repo.store.db_path, repo.owner)
        self.tasks, self.locks = {}, {}
        self.live_text, self.signals, self.versions = {}, {}, {}
        for row in self.records.list("wb_conversation"):
            if row["status"] in {"queued", "running", "committing", "stopping"}:
                row.update(status="failed" if row["status"] == "committing" else "waiting_input", error_code="process_interrupted")
                if row.get("material_run") and row["material_run"]["status"] in {"queued", "preparing", "validating", "saving"}:
                    row["material_run"].update(status="failed", error_code="process_interrupted",
                                               message="服务重启中断了整理；原材料已保留，可重新整理。")
                self.emit(row, "interrupted", "服务已重启，已完成结果保留；请继续或重试。")
                self.put(row)
        graph = StateGraph(GraphState)
        for name in ("decide", "execute", "approval_gate", "commit"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "decide")
        graph.add_conditional_edges("decide", lambda s: s["route"], {"execute": "execute", "end": END})
        graph.add_conditional_edges("execute", lambda s: s["route"],
                                    {"decide": "decide", "approval": "approval_gate", "end": END})
        graph.add_edge("approval_gate", "commit")
        graph.add_edge("commit", END)
        self.graph = graph.compile(checkpointer=saver)

    async def close(self):
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)

    def put(self, data):
        data["updated_at"] = now()
        self.records.put("wb_conversation", data["id"], data, replace=True)
        self.versions[data["id"]] = self.versions.get(data["id"], 0) + 1
        self.notify(data["id"])

    def notify(self, sid):
        for signal in self.signals.get(sid, ()):
            signal.set()

    def text_callback(self, data, stage):
        sid, run_id, message_id = data["id"], data["run_id"], "text_" + uuid.uuid4().hex
        async def receive(text):
            self.live_text[sid] = {"id": message_id, "run_id": run_id, "stage": stage, "text": redact(text)}
            self.notify(sid)
        return receive

    async def model_decide(self, stage, value, data):
        if hasattr(self.agent, "decide_stream"):
            return await self.agent.decide_stream(stage, value, self.text_callback(data, stage))
        return await self.agent.decide(stage, value)

    def preserve_partial(self, data, state):
        partial = self.live_text.pop(data["id"], None)
        if partial and partial["text"]:
            data["messages"].append({"role": "assistant", "text": partial["text"], "state": state})

    async def stream(self, sid, after=0):
        signal = asyncio.Event()
        self.signals.setdefault(sid, set()).add(signal)
        version, previous, status = -1, None, None
        def frame(kind, payload, cursor=None):
            return (f"id: {cursor}\n" if cursor is not None else "") + f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        try:
            while True:
                signal.clear()
                current_version = self.versions.get(sid, 0)
                if version != current_version:
                    data = self.get(sid)
                    view = self.view(data)
                    yield frame("snapshot", {"events": [e for e in data["events"] if e["cursor"] > after], "view": view}, view["cursor"])
                    version, after, status = current_version, view["cursor"], view["status"]
                    previous = view["streaming_message"]
                else:
                    current = deepcopy(self.live_text.get(sid))
                    if current != previous:
                        if current and previous and current["id"] == previous["id"] and current["text"].startswith(previous["text"]):
                            yield frame("text_delta", {"id": current["id"], "run_id": current["run_id"],
                                "offset": len(previous["text"]), "delta": current["text"][len(previous["text"]):]})
                        else:
                            yield frame("text_reset", {"streaming_message": current})
                        previous = current
                if status not in {"queued", "running", "committing", "stopping"}:
                    yield frame("settled", {})
                    return
                try:
                    await asyncio.wait_for(signal.wait(), 15)
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            self.signals[sid].discard(signal)
            if not self.signals[sid]:
                self.signals.pop(sid)

    def get(self, sid):
        return self.records.get("wb_conversation", sid)

    def lock(self, sid):
        return self.locks.setdefault(sid, asyncio.Lock())

    def config(self, data):
        return {"configurable": {"thread_id": f"{self.repo.owner}:workbench:{data['id']}:{data['run_id']}"}, "recursion_limit": 64}

    def emit(self, data, kind, message, **extra):
        data["events"].append({"cursor": len(data["events"]) + 1, "type": kind, "message": message,
                               "run_id": data.get("run_id"), "at": now(), **extra})

    def workspace_progress(self, data):
        """生成当前会话关联工作区的只读进度摘要，供对话主线引导与前端建议卡片使用。"""
        source = data.get("source") or {}
        profile = source.get("private_profile") or {}
        job, material = self.selected(data)
        materials = self.materials(public=True)
        artifacts = data.get("artifacts") or []
        saved_versions = data.get("saved_versions") or []
        profile_confirmed = bool(profile.get("truth_confirmed"))
        has_profile_name = bool((profile.get("basic") or {}).get("name"))
        job_count = int(source.get("job_count", len(source.get("jobs") or [])))
        material_count = len(materials)
        has_resume = any(a.get("kind") == "resume" for a in artifacts)
        has_greeting = any(a.get("kind") == "greeting" for a in artifacts)
        pending_queue_count = int(source.get("approval_queue_count", 0))
        mail_count = len(source.get("mails") or [])
        interview_count = len(source.get("interviews") or [])
        if not profile_confirmed or not has_profile_name:
            next_step = "先导入简历或填写个人资料（至少填写真实姓名并确认）"
        elif job_count == 0:
            next_step = "还没有目标岗位，可直接在对话中粘贴 JD 录入，或打开平台采集向导"
        elif material_count == 0:
            next_step = "还没有已确认的项目或工作经历，可在对话里上传/粘贴经历材料，或核验 GitHub 项目"
        elif not job or not material:
            next_step = "请从已有岗位和已确认经历中各选定一项，随后即可生成定制简历与招呼语"
        elif not has_resume:
            next_step = "目标岗位与经历已就绪，可直接生成定制简历与招呼语草稿"
        elif not saved_versions:
            next_step = "已有最新草稿，可继续微调、核对保存正式简历版本，或同步招呼语到发送队列"
        else:
            next_step = "简历版本已保存，可复核并同步招呼语投递，或基于该简历开始模拟面试"
        return {
            "profile_confirmed": profile_confirmed,
            "has_profile_name": has_profile_name,
            "job_count": job_count,
            "selected_job": bool(job),
            "material_count": material_count,
            "materials": [{"material_id": m["material_id"], "name": m.get("name") or "已确认经历"} for m in materials[:10]],
            "selected_material": bool(material),
            "artifact_count": len(artifacts),
            "has_resume_artifact": has_resume,
            "has_greeting_artifact": has_greeting,
            "saved_version_count": len(saved_versions),
            "pending_queue_count": pending_queue_count,
            "mail_count": mail_count,
            "interview_count": interview_count,
            "recommended_next_step": next_step,
        }

    def guidance(self, data, progress):
        """基于当前真实进度生成可在对话流直接点击的 GUI/LUI 协同引导动作。"""
        if data.get("status") in {"queued", "running", "committing", "stopping", "waiting_approval"}:
            return []
        actions = []
        if not progress["profile_confirmed"] or not progress["has_profile_name"]:
            actions = [
                {"id": "guide_profile_import", "label": "上传简历自动提取资料", "kind": "capability", "capability": "profile_import", "primary": True},
                {"id": "guide_profile_form", "label": "手动填写并确认资料", "kind": "capability", "capability": "profile"},
                {"id": "guide_overview", "label": "让助手梳理当前进度", "kind": "prompt", "text": "帮我查看当前工作区进度，并告诉我第一步该怎么准备"},
            ]
        elif progress["job_count"] == 0:
            actions = [
                {"id": "guide_paste_jd", "label": "在对话中粘贴 JD 录入", "kind": "compose", "prefill": "请帮我录入这个目标岗位 JD：\n", "placeholder": "把公司、岗位名称和 JD 正文粘贴到这里，发给助手即可自动解析入库…", "primary": True},
                {"id": "guide_collect_jobs", "label": "打开平台采集向导", "kind": "capability", "capability": "collect"},
                {"id": "guide_jobs_form", "label": "打开岗位池表单", "kind": "capability", "capability": "jobs"},
            ]
        elif progress["material_count"] == 0:
            actions = [
                {"id": "guide_material_chat", "label": "在对话里提交项目经历", "kind": "material", "primary": True},
                {"id": "guide_github", "label": "连接 GitHub 核验项目", "kind": "capability", "capability": "github"},
                {"id": "guide_exp_details", "label": "按类型录入经历", "kind": "capability", "capability": "experience_details"},
            ]
        elif not progress["selected_job"] or not progress["selected_material"]:
            if not progress["selected_job"]:
                actions.append({"id": "guide_recommend_jobs", "label": "让助手推荐 3 个匹配岗位", "kind": "prompt", "text": "从已有岗位中结合我的资料推荐 3 个最匹配的岗位，并说明理由和缺口", "primary": True})
                actions.append({"id": "guide_select_job", "label": "去岗位池选择岗位", "kind": "capability", "capability": "jobs"})
            if not progress["selected_material"]:
                actions.append({"id": "guide_pick_material", "label": "列出已确认经历供选择", "kind": "prompt", "text": "列出我已确认的项目经历，帮我选定一份用于准备申请材料", "primary": progress["selected_job"]})
                actions.append({"id": "guide_add_material", "label": "补充新项目经历", "kind": "material"})
        elif not progress["has_resume_artifact"]:
            actions = [
                {"id": "guide_draft_app", "label": "生成定制简历与招呼语草稿", "kind": "prompt", "text": "为当前选定的岗位和已确认经历生成定制简历与招呼语草稿", "primary": True},
                {"id": "guide_job_detail", "label": "查看岗位详情与匹配差距", "kind": "prompt", "text": "查看当前目标岗位的详细要求，并对比我的已确认经历"},
            ]
        elif not progress["saved_version_count"]:
            actions = [
                {"id": "guide_save_resume", "label": "保存当前最新简历版本", "kind": "prompt", "text": "请帮我保存当前最新简历版本", "primary": True},
                {"id": "guide_revise_draft", "label": "微调简历要点或招呼语", "kind": "compose", "prefill": "请帮我把简历和招呼语调整一下：", "placeholder": "说明想调整的重点、表达或语气…"},
                {"id": "guide_review_greeting", "label": "核对并同步招呼语", "kind": "capability", "capability": "queue"},
            ]
        else:
            saved_id = (data.get("saved_versions") or [])[-1]["resume_version_id"]
            actions = [
                {"id": "guide_sync_delivery", "label": "复核并发送招呼语", "kind": "capability", "capability": "queue", "primary": True},
                {"id": "guide_version_interview", "label": "基于这份简历模拟面试", "kind": "prompt", "text": f"基于简历版本 {saved_id} 开始一场模拟面试"},
                {"id": "guide_export_pdf", "label": "导出 / 打印简历 PDF", "kind": "capability", "capability": "resume"},
            ]
        last_ui = (data.get("ui_actions") or [])[-1:]
        if last_ui and last_ui[0].get("run_id") == data.get("run_id"):
            cap = last_ui[0].get("capability")
            if cap and not any(a.get("capability") == cap for a in actions):
                label = dict((r[0], r[1]) for r in CAPABILITIES).get(cap, "对应表单")
                actions.insert(0, {"id": f"guide_ui_{cap}", "label": f"打开「{label}」", "kind": "capability", "capability": cap})
        return actions[:4]

    def view(self, data):
        progress = self.workspace_progress(data)
        return {key: deepcopy(data.get(key)) for key in ("id", "title", "mode", "status", "run_id", "job_id",
            "material_id", "messages", "artifacts", "recommendations", "pending", "saved_versions",
            "error_code", "updated_at", "material_run", "resume_version_id", "interview_id", "business_results", "ui_actions")} | {"cursor": len(data["events"]),
                "materials": self.materials(public=True), "generation": self.agent.generation,
                # 会话创建时的模型与当前设置不同：引擎不再接受新消息，前端据此改为新建会话。
                "model_changed": bool(data.get("generation")) and data.get("generation") != self.agent.generation,
                "streaming_message": deepcopy(self.live_text.get(data["id"])),
                "progress": progress, "guidance": self.guidance(data, progress)}

    def create(self, title):
        data = {"id": "wb_" + uuid.uuid4().hex, "title": title, "mode": self.mode,
                "status": "idle", "messages": [], "artifacts": [], "recommendations": [],
                "pending": None, "saved_versions": [], "events": [], "processed": {}, "approvals": {},
                "job_id": None, "material_id": None, "run_id": None, "source": {},
                "generation": self.agent.generation}
        self.put(data)
        return self.view(data)

    def listing(self):
        return [{key: row.get(key) for key in ("id", "title", "mode", "status", "updated_at")}
                for row in self.records.list("wb_conversation")]

    def overview(self):
        def all_records(kind):
            rows, offset = [], 0
            while True:
                page = self.records.list(kind, offset=offset)
                rows.extend(page)
                if len(page) < 100:
                    return rows
                offset += 100
        rows = all_records("wb_conversation")
        return {"materials": self.materials(public=True),
                "versions": [{k: r.get(k) for k in ("resume_version_id", "created_at", "job_snapshot")}
                             for r in all_records("resume")],
                "tasks": [{"id": r["id"], "title": r["title"], "status": r["status"],
                           "capability": "application", "conversation_id": r["id"]}
                          for r in rows if r["status"] in {"queued", "running", "committing", "stopping"}],
                "pending": [{"id": r["pending"]["id"], "title": r["title"], "capability": "application", "conversation_id": r["id"]}
                            for r in rows if r.get("pending")],
                "results": [{"id": a["id"], "title": r["title"], "kind": "简历草稿" if a["kind"] == "resume" else "招呼语草稿",
                             "capability": "application", "conversation_id": r["id"], "artifact_id": a["id"]}
                            for r in rows[:10] for a in r.get("artifacts", [])[-2:]]}

    def validate_context(self, data):
        job, material = self.selected(data)
        if data.get("job_id") and job is None or data.get("material_id") and material is None:
            raise ValueError("Unknown context reference")
        if data.get("resume_version_id"):
            self.records.get("resume", data["resume_version_id"])
        if data.get("interview_id") and data["interview_id"] != data["source"].get("interview_session", {}).get("id"):
            self.repo.context(data["interview_id"])

    def greeting_for_sync(self, sid, artifact_id, source):
        data = self.get(sid)
        data["source"] = deepcopy(source)
        self.validate_context(data)
        artifact = next((a for a in data["artifacts"] if a["id"] == artifact_id and a["kind"] == "greeting"), None)
        latest = next((a for a in reversed(data["artifacts"]) if a["kind"] == "greeting"), None)
        if not artifact or artifact != latest or artifact["binding"] != self.binding(data):
            raise ConflictError("Greeting source changed; regenerate the draft")
        return {"job_id": data["job_id"], "text": artifact["text"], "revision": artifact["revision"]}

    async def context(self, sid, context, source):
        async with self.lock(sid):
            data = self.get(sid)
            if sid in self.tasks and not self.tasks[sid].done():
                raise ConflictError("Stop the current task before switching context")
            previous = self.binding(data)
            data["source"] = deepcopy(source)
            for key, value in context.model_dump(exclude_none=True).items():
                data[key] = value or None
            self.validate_context(data)
            if data.get("pending") and previous != self.binding(data):
                data["approvals"][data["pending"]["id"]] = "invalidated"
                data.update(pending=None, status="waiting_input")
            self.put(data)
            return self.view(data)

    def materials(self, public=False):
        rows, offset = [], 0
        while True:
            page = self.repo.store.list_materials(self.repo.owner, limit=100, offset=offset)
            rows.extend(row["payload"] for row in page)
            if len(page) < 100:
                break
            offset += 100
        rows = [row for row in rows if row.get("resume_version_id") is None and row.get("is_demo") == (self.mode == "demo")
                and row.get("claims") and all(c.get("personal_contribution") == "confirmed" for c in row["claims"])]
        if public:
            return [{"material_id": m["material_id"], "name": m.get("project_name") or m.get("source_repository"),
                     "claims": [{"claim_id": c["claim_id"], "text": c["text"]} for c in m["claims"]]} for m in rows]
        return rows

    def selected(self, data):
        job = next((j for j in data["source"].get("jobs", []) if j["id"] == data.get("job_id")), None)
        material = next((m for m in self.materials() if m["material_id"] == data.get("material_id")), None)
        return job, material

    def binding(self, data):
        job, material = self.selected(data)
        extra = {key: data[key] for key in ("resume_version_id", "interview_id") if data.get(key)}
        return fingerprint({"job": job, "material": material,
                            "profile": data["source"].get("private_profile"), "generation": self.agent.generation, **extra})

    async def turn(self, sid, event, source, attachment=None, *, retry_run=None):
        async with self.lock(sid):
            data = self.get(sid)
            payload = attachment.model_dump(exclude_none=True) if attachment else event.model_dump()
            key, hashed = payload["event_id"], fingerprint(payload)
            old = data["processed"].get(key)
            if old:
                if old != hashed:
                    raise ConflictError("Event payload cannot change")
                return self.view(data)
            if retry_run and (data.get("material_run", {}).get("run_id") != retry_run
                              or data["material_run"]["status"] not in {"failed", "stopped"}
                              or data.get("pending")):
                raise ConflictError("Material retry is stale; review the current result")
            if sid in self.tasks and not self.tasks[sid].done():
                raise ConflictError("One active run per conversation")
            if data["generation"] != self.agent.generation:
                raise ConflictError("Create a new conversation for another model")
            if attachment and not attachment.model_consent:
                raise ValueError("Confirm model processing first")
            if attachment:
                if bool(attachment.text.strip()) == bool(attachment.material_id):
                    raise ValueError("Choose material text or one existing material")
                if attachment.material_id:
                    material = next((m for m in self.materials() if m["material_id"] == attachment.material_id), None)
                    if self.mode != "user" or attachment.kind != "experience" or material is None:
                        raise ValueError("Choose a confirmed material from this workspace")
                    # Only confirmed personal statements become input, not team/source-code claims.
                    payload["text"] = "\n".join(c["text"] for c in material["claims"])
                    if len(payload["text"]) > 20000:
                        raise ValueError("Selected material exceeds the text limit")
                    payload["name"] = attachment.name.strip() or str(material.get("project_name") or material.get("source_repository") or "已有项目")[:120]
                    payload["source_material_sha256"] = fingerprint(material)
            data["source"] = deepcopy(source)
            if not attachment:
                links = data.setdefault("note_links", {})
                for match in re.findall(r"https://[^\s<>\"'，。；、（）【】]+", event.text):
                    url = match.rstrip('.,;!?)')
                    host = urlsplit(url).hostname or ""
                    if host in {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.com", "www.xhslink.com"}:
                        links["note_link_" + fingerprint(url)[:10]] = url
                data["note_links"] = dict(list(links.items())[-10:])
                if event.job_id is not None:
                    data["job_id"] = event.job_id or None
                if event.material_id is not None:
                    data["material_id"] = event.material_id or None
                for field in ("resume_version_id", "interview_id"):
                    if getattr(event, field) is not None:
                        data[field] = getattr(event, field) or None
                self.validate_context(data)
            if data.get("pending"):
                data["approvals"][data["pending"]["id"]] = "invalidated"
                if data.get("material_run", {}).get("status") == "waiting_approval":
                    data["material_run"].update(status="invalidated", message="要求已变化，请重新整理并核对。")
            data.update(pending=None, status="queued", error_code=None, steps=0, observations=[],
                        run_id="run_" + uuid.uuid4().hex, attachment=payload if attachment else None, business_calls={})
            if attachment:
                data["material_attachment"] = deepcopy(payload)
                data["material_run"] = {"run_id": data["run_id"], "kind": attachment.kind,
                    "name": payload.get("name", ""), "role": payload.get("role", ""),
                    "status": "queued", "message": "材料已收到，等待整理。"}
            self.live_text.pop(sid, None)
            data["messages"].append({"role": "user", "text": "补充材料：" + attachment.kind if attachment else event.text})
            data["processed"][key] = hashed
            self.emit(data, "queued", "任务已受理")
            self.put(data)
            self.tasks[sid] = asyncio.create_task(self.run(sid))
            return self.view(data)

    async def retry_material(self, sid, event_id, run_id, source):
        data = self.get(sid)
        if self.mode != "user" or not data.get("material_attachment"):
            raise ConflictError("No retained material to retry; submit the source again")
        payload = {k: v for k, v in data["material_attachment"].items() if k in Attachment.model_fields}
        payload["event_id"] = event_id
        if payload.get("material_id"):
            payload["text"] = ""
        return await self.turn(sid, None, source, Attachment.model_validate(payload), retry_run=run_id)

    def material_progress(self, data, status, message, **extra):
        if status in {"failed", "stopped"}:
            extra["failed_at"] = data["material_run"]["status"]
        data["material_run"].update(status=status, message=message, **extra)
        self.emit(data, "material_" + status, message)
        self.put(data)

    async def run(self, sid, resume=None):
        data = self.get(sid)
        try:
            config = self.config(data)
            snapshot = await self.graph.aget_state(config) if resume is not None else None
            value = None if snapshot and snapshot.next == ("commit",) else Command(resume=resume) if resume is not None else {"data": data}
            await self.graph.ainvoke(value, config)
        except asyncio.CancelledError:
            data = self.get(sid)
            self.preserve_partial(data, "stopped")
            data.update(status="stopped", pending=None)
            if data.get("material_run", {}).get("run_id") == data["run_id"]:
                self.material_progress(data, "stopped", "已停止整理，原材料已保留，可重新整理。")
            self.emit(data, "stopped", "已停止；已完成的草稿和保存结果保留。")
            self.put(data)
        except Exception as error:
            data = self.get(sid)
            self.preserve_partial(data, "failed")
            data.update(status="failed", error_code=error.code if isinstance(error, ModelError) else "invalid_tool_or_result")
            if data.get("material_run", {}).get("run_id") == data["run_id"]:
                code = data["error_code"]
                reason = {"model_timeout": "模型响应超时", "model_transport_failed": "连接模型服务失败",
                    "invalid_model_decision": "模型结果未通过格式、原文引用或事实校验",
                    "material_validation_failed": "整理内容未通过原文引用或事实校验",
                    "model_output_truncated": "模型输出不完整", "invalid_model_stream": "模型返回的数据不完整",
                    "missing_model_credential": "模型凭据尚未配置"}.get(code, "本次整理或保存未完成")
                if code.startswith("provider_http_"):
                    reason = "模型服务返回错误（HTTP " + code.removeprefix("provider_http_") + "）"
                self.material_progress(data, "failed", reason + "；原材料已保留。请检查后重试。", error_code=code)
            self.emit(data, "failed", "执行未完成，已完成结果保留；请修改要求或重试。")
            self.put(data)

    async def stop(self, sid):
        async with self.lock(sid):
            data = self.get(sid)
            task = self.tasks.get(sid)
            if data["status"] == "committing" and task and not task.done():
                # A submitted domain write cannot be undone by cancelling its HTTP acknowledgement.
                await asyncio.gather(task, return_exceptions=True)
                return self.view(self.get(sid))
            if task and not task.done():
                data["status"] = "stopping"
                self.emit(data, "stopping", "正在停止当前请求")
                self.put(data)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                data = self.get(sid)
                if data["status"] == "stopping":
                    data.update(status="stopped", pending=None)
                    self.emit(data, "stopped", "已停止；已完成结果保留。")
                    self.put(data)
            else:
                if data.get("pending"):
                    data["approvals"][data["pending"]["id"]] = "rejected"
                data.update(status="stopped", pending=None)
                if data.get("material_run", {}).get("run_id") == data["run_id"]:
                    self.material_progress(data, "stopped", "已停止，整理预览与原材料保留。")
                self.put(data)
            return self.view(self.get(sid))

    async def approve(self, sid, request, source):
        async with self.lock(sid):
            data = self.get(sid)
            previous = data["approvals"].get(request.approval_id)
            if previous in {"approved", "rejected"}:
                if previous != ("approved" if request.approved else "rejected"):
                    raise ConflictError("Approval decision is immutable")
                if data.get("approval_in_flight") != request.model_dump():
                    raise ConflictError("Approval payload is immutable")
                return self.view(data)
            if sid in self.tasks and not self.tasks[sid].done():
                if data["status"] == "waiting_approval":
                    # The preview is visible before the interrupt checkpoint finishes flushing.
                    await asyncio.shield(self.tasks[sid])
                    data = self.get(sid)
                elif data.get("approval_in_flight") == request.model_dump():
                    return self.view(data)
                else:
                    raise ConflictError("A decision is already executing")
            pending = data.get("pending")
            if not pending or pending["id"] != request.approval_id or data["status"] not in {"waiting_approval", "failed"}:
                raise ConflictError("Approval is stale")
            if request.claim_ids is not None and (pending["kind"] != "confirm_material" or not request.claim_ids
                    or not set(request.claim_ids).issubset(pending["payload"]["claim_ids"])):
                raise ValueError("Select known project claims explicitly")
            recovering_profile = pending["kind"] == "save_profile" and data["status"] == "failed" and data.get("approval_in_flight") == request.model_dump()
            if not recovering_profile:
                data["source"] = deepcopy(source)
            if pending["binding"] != self.binding(data):
                data["approvals"][pending["id"]] = "invalidated"
                data.update(pending=None, status="waiting_input")
                self.put(data)
                raise ConflictError("Source changed; regenerate the preview")
            data["approval_in_flight"] = request.model_dump()
            data["status"] = "queued"
            self.put(data)
            self.tasks[sid] = asyncio.create_task(self.run(sid, request.model_dump()))
            return self.view(data)

    def finish(self, data, message, status="completed"):
        self.live_text.pop(data["id"], None)
        data["status"] = status
        data["messages"].append({"role": "assistant", "text": redact(message)})
        self.emit(data, status, redact(message))
        self.put(data)
        return {"data": data, "route": "end"}

    async def decide(self, state):
        data = deepcopy(state["data"])
        data["status"] = "running"
        self.emit(data, "deciding", "正在选择下一步")
        self.put(data)
        if data["steps"] >= 12:
            return self.finish(data, "本轮已达到 12 次工具调用，已有结果保留；可继续任务。", "waiting_input")
        if data.get("attachment"):
            return {"data": data, "decision": {"action": "attachment", "arguments": {}}, "route": "execute"}
        text = data["messages"][-1]["text"]
        if text.strip().startswith("/面经"):
            if self.mode != "user" or self.notes is None:
                return self.finish(data, "面经收藏和订阅仅在我的 user 模式开放。", "waiting_input")
            try:
                message = await self.notes.command(text)
            except (ValueError, NotFoundError, ConflictError):
                message = "面经操作未完成：请检查链接、周期（1至168小时）或编号；输入 /面经 查看用法。"
            return self.finish(data, message)
        job, material = self.selected(data)
        progress = self.workspace_progress(data)
        decision = Decision.model_validate(await self.model_decide("workbench_decide", redact({
            "messages": [m for m in data["messages"] if not m.get("state")][-12:], "job": job, "material_id": data.get("material_id"),
            "profile_confirmed": progress["profile_confirmed"],
            "workspace_progress": progress,
            "artifacts": [{"id": a["id"], "kind": a["kind"], "revision": a["revision"]} for a in data["artifacts"][-2:]],
            "tools": list(INPUTS), "capabilities": [{"id": r[0], "label": r[1]} for r in CAPABILITIES],
            "resume_version_id": data.get("resume_version_id"), "interview_id": data.get("interview_id"),
            "note_link_references": list(data.get("note_links", {})),
            "observations": data["observations"]}), data)).model_dump(exclude_none=True)
        if decision["action"] in {"ask", "reply"}:
            return self.finish(data, decision["message"] or "请补充本次求职目标。",
                               "waiting_input" if decision["action"] == "ask" else "completed")
        if decision["action"] in {"draft_application", "revise_application"} and any(
                item["tool"] in {"draft_application", "revise_application"} and item["result"].get("artifacts")
                for item in data["observations"]):
            return self.finish(data, "简历和招呼语草稿已准备，请核对内容；需要调整时可继续提出修改，保存正式版本仍需确认。")
        INPUTS[decision["action"]].model_validate(decision["arguments"])
        return {"data": data, "decision": decision, "route": "execute"}

    async def execute(self, state):
        data, decision = deepcopy(state["data"]), state["decision"]
        action, args = decision["action"], decision["arguments"]
        data["steps"] += 1
        self.emit(data, "tool_started", "正在执行 " + action, tool=action)
        self.put(data)
        result = await self.tool(data, action, args)
        self.live_text.pop(data["id"], None)
        data["observations"].append({"tool": action, "result": redact(result)})
        self.emit(data, "tool_completed", "已完成 " + action, tool=action)
        if data.get("pending"):
            data["status"] = "waiting_approval"
            self.emit(data, "waiting_approval", "请核对具体内容后确认")
            self.put(data)
            return {"data": data, "route": "approval"}
        if result.get("needs_input"):
            return self.finish(data, result["needs_input"], "waiting_input")
        self.put(data)
        return {"data": data, "route": "decide"}

    def pending(self, data, kind, preview, payload):
        data["pending"] = {"id": "approval_" + uuid.uuid4().hex, "kind": kind,
                           "binding": self.binding(data), "preview": preview, "payload": payload}

    async def approval_gate(self, state):
        # This node has no side effects before interrupt; resume executes it again.
        decision = interrupt({"type": "workbench_approval", "approval": state["data"]["pending"]})
        return {"approval": decision}

    async def commit(self, state):
        data = self.get(state["data"]["id"])
        pending, approval = data["pending"], state["approval"]
        if pending is None or pending["id"] != approval["approval_id"] or pending["binding"] != self.binding(data):
            raise ConflictError("Stale commit")
        if not approval["approved"]:
            data["approvals"][pending["id"]] = "rejected"
            data["pending"] = None
            if data.get("material_run", {}).get("run_id") == data["run_id"]:
                self.material_progress(data, "rejected", "本次预览未保存，仍可查看；可修改原文后重新整理。")
            return self.finish(data, "已拒绝本次提交，现有资料和正式版本未修改。")
        if self.mode != "user" or self.career is None:
            raise ValueError("Demo cannot commit personal data")
        data["status"] = "committing"
        if data.get("material_run", {}).get("run_id") == data["run_id"]:
            self.material_progress(data, "saving", "正在保存你确认的内容。")
        self.emit(data, "committing", "正在提交已确认的内容")
        self.put(data)
        if pending["kind"] == "save_resume":
            artifact = next(a for a in data["artifacts"] if a["id"] == pending["payload"]["artifact_id"])
            if artifact["binding"] != self.binding(data):
                raise ConflictError("Draft source changed")
            base = self.career.draft({"material_id": data["material_id"], "profile": data["source"]["private_profile"]})
            draft = {**base, "markdown": artifact["text"], "job_snapshot": artifact["job_snapshot"],
                     "markdown_sha256": fingerprint(artifact["text"]), "workbench_artifact_id": artifact["id"],
                     "generation": artifact["generation"], "source_map": artifact["source_map"], "semantic_review": artifact["review"]}
            draft["markdown_sha256"] = hashlib.sha256(draft["markdown"].encode()).hexdigest()
            draft["draft_id"] = digest({k: v for k, v in draft.items() if k != "draft_id"}, "draft_")
            self.career.records.put("draft", draft["draft_id"], draft)
            version = self.career.save_version(draft["draft_id"], True)
            data["saved_versions"].append({"resume_version_id": version["resume_version_id"], "artifact_id": artifact["id"]})
            message = "简历正式版本已保存：" + version["resume_version_id"]
        elif pending["kind"] == "confirm_material":
            project = self.career.records.get("project", pending["payload"]["project_id"])
            if fingerprint(project) != pending["payload"]["project_hash"]:
                raise ConflictError("Project statements changed")
            selected = approval["claim_ids"] if approval.get("claim_ids") is not None else pending["payload"]["claim_ids"]
            if not selected or not set(selected).issubset(pending["payload"]["claim_ids"]):
                raise ValueError("Unknown claims")
            result = self.career.confirm(pending["payload"]["project_id"], {"claim_ids": selected, "confirmed": True})
            data["material_id"] = result["material_id"]
            message = "这些经历已确认并保存，可以用来生成简历和招呼语。"
        elif pending["kind"] == "save_profile":
            profile = {**pending["payload"]["profile"], "truth_confirmed": True}
            async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
                response = await client.post("http://127.0.0.1:" + os.getenv("OFFERPILOT_WORKBENCH_PORT", "8766") + "/api/workbench-agent/internal/profile",
                    headers={"Authorization": "Bearer " + self.token},
                    json={"mode": self.mode, "operation_id": pending["id"],
                          "expected": fingerprint(data["source"]["private_profile"]), "profile": profile})
                if response.status_code != 200:
                    raise ConflictError("Profile changed or could not be saved")
                saved = response.json()["profile"]
            data["source"]["private_profile"] = saved
            data["source"]["profile"] = redact(saved)
            message = "确认后的个人资料已保存，可继续选择项目材料。"
        else:
            raise ValueError("Unknown commit type")
        data["approvals"][pending["id"]] = "approved"
        data["pending"] = None
        if data.get("material_run", {}).get("run_id") == data["run_id"]:
            self.material_progress(data, "confirmed", message, material_id=data.get("material_id"))
        return self.finish(data, message)

    async def tool(self, data, action, args):
        source = data["source"]
        if action == "open_workspace_tool":
            ui = {"id": "ui_" + uuid.uuid4().hex, "run_id": data.get("run_id"), "capability": args["capability"]}
            data.setdefault("ui_actions", []).append(ui)
            label = dict((r[0], r[1]) for r in CAPABILITIES).get(args["capability"], "对应操作区")
            return {"needs_input": f"已在工作区为你打开「{label}」，完成操作后可直接在对话里告诉我继续下一步。", "ui_action": ui}
        if action in BUSINESS_TOOLS:
            if action in {"collect_note", "subscribe_note"}:
                link = data.get("note_links", {}).get(args["url"])
                if not link:
                    return {"needs_input": "请粘贴你要收藏或订阅的单条小红书笔记链接。"}
                args = {**args, "url": link}
            signature = fingerprint({"action": action, "args": args})
            if signature in data.setdefault("business_calls", {}):
                return data["business_calls"][signature]
            operation_id = "wb_" + fingerprint({"conversation": data["id"], "run": data["run_id"], "signature": signature})
            if BUSINESS_TOOLS[action][2] == "write":
                data["status"] = "committing"
                self.emit(data, "committing", "正在提交业务操作，请等待真实结果")
                self.put(data)
            port = int(os.getenv("OFFERPILOT_WORKBENCH_PORT", "8766"))
            async with httpx.AsyncClient(trust_env=False, timeout=150) as client:
                response = await client.post(f"http://127.0.0.1:{port}/api/workbench/internal/business",
                    headers={"Authorization": "Bearer " + self.token},
                    json={"mode": self.mode, "tool": action, "arguments": args, "operation_id": operation_id})
            if response.status_code != 200:
                return {"needs_input": response.json().get("error", "业务未完成，请在工作区查看状态后继续。")}
            value = response.json()
            result = value["result"]
            data["source"] = value["source"]
            if result.get("ui_action"):
                data.setdefault("ui_actions", []).append({"id": "ui_" + uuid.uuid4().hex, "run_id": data.get("run_id"), **result["ui_action"]})
            else:
                data.setdefault("business_results", []).append({"id": operation_id, "tool": action,
                    "title": BUSINESS_TOOLS[action][0], "result": result, "created_at": now()})
                data["business_results"] = data["business_results"][-40:]
            data["business_calls"][signature] = result
            return result
        if action == "attachment":
            attachment = data.pop("attachment")
            if self.mode != "user" or self.career is None:
                return {"needs_input": "演示模式不接收真实材料，请切换到我的 user。"}
            if attachment["kind"] == "profile":
                from .resume_profile import extract_profile
                self.material_progress(data, "preparing", "正在从简历提取个人资料，完成后请核对。")
                result = await extract_profile(self.agent, redact(attachment["text"]))
                profile = {**source["private_profile"], **result["profile"],
                           "basic": {**source["private_profile"].get("basic", {}),
                                     **({"name": attachment["name"]} if attachment["name"] else {})}}
                self.pending(data, "save_profile", profile, {"profile": profile})
                self.material_progress(data, "waiting_approval", "资料提取成功，请核对后保存。")
                return {"proposal": "profile", "warnings": result["warnings"]}
            if not attachment["name"] or not attachment["role"]:
                return {"needs_input": "请填写经历名称和目标岗位，再提交经历材料。"}
            self.material_progress(data, "preparing", "正在生成项目背景、岗位匹配方向和核心贡献。")
            async def validating():
                self.material_progress(data, "validating", "模型已返回，正在校验原文引用、数字和职责表述。")
            before = set(self.career.tasks)
            project = await self.career.prepare_experience({"kind": "project", "name": attachment["name"],
                "role": attachment["role"], "context": "用户自主补充的经历材料", "contribution": redact(attachment["text"])[:4000],
                "source_text": redact(attachment["text"]), "confirmed": True, "model_consent": True},
                on_text=self.text_callback(data, "prepare_experience"), on_validating=validating)
            await asyncio.gather(*(set(self.career.tasks) - before))
            project = self.career.records.get("project", project["project_id"])
            if project["status"] != "ready":
                raise ModelError(project.get("error_code", "experience_preparation_failed"))
            if attachment.get("material_id"):
                project.update(source_material_id=attachment["material_id"],
                               source_material_sha256=attachment["source_material_sha256"])
                self.career.records.put("project", project["project_id"], project, replace=True)
            ids = [c["claim_id"] for c in project["claims"]]
            preview = {k: deepcopy(project.get(k, "")) for k in ("summary", "project_overview", "positioning", "claims")}
            preview.update(name=attachment["name"], role=attachment["role"], evidence=deepcopy(project["evidence"]))
            self.pending(data, "confirm_material", preview,
                         {"project_id": project["project_id"], "claim_ids": ids, "project_hash": fingerprint(project)})
            self.material_progress(data, "waiting_approval", f"整理成功，生成 {len(ids)} 条核心贡献；请逐条核对后保存。",
                                   project_id=project["project_id"], preview=preview)
            return {"proposal": "material"}
        if action == "workspace_summary":
            return {"jobs": source.get("job_count", 0), "coverage": source.get("coverage"),
                    "materials": len(self.materials()), "profile_confirmed": source.get("profile", {}).get("truth_confirmed", False),
                    "hr_records": len(source.get("mails", [])), "interview_records": len(source.get("interviews", []))}
        if action == "professional_profile":
            return source.get("profile", {})
        if action == "materials":
            return {"items": self.materials(public=True)}
        if action == "resume_versions":
            return {"items": [{k: r.get(k) for k in ("resume_version_id", "job_snapshot", "created_at")}
                              for r in self.records.list("resume")]}
        if action in {"hr_records", "interview_records", "task_status"}:
            key = {"hr_records": "mails", "interview_records": "interviews", "task_status": "tasks"}[action]
            return {"items": source.get(key, [])}
        if action == "job_detail":
            job = next((j for j in source.get("jobs", []) if j["id"] == args["job_id"]), None)
            if job is None:
                raise ValueError("Unknown job")
            return job
        if action in {"search_jobs", "recommend_jobs"}:
            query, city = args.get("query", "").lower(), args.get("city", "")
            jobs = [j for j in source.get("jobs", []) if (not query or query in json.dumps(j, ensure_ascii=False).lower())
                    and (not city or city in str(j.get("city", "")))]
            if not jobs:
                return {"needs_input": "已有岗位中未找到符合条件的结果。可调整条件，或前往求职主线录入/采集岗位。"}
            candidates = jobs[:30]
            if action == "search_jobs":
                return {"items": candidates[:args.get("limit", 3)], "matched": len(jobs)}
            candidates = [j for j in candidates if not j.get("risk", {}).get("blocks_queue")]
            if not candidates:
                return {"needs_input": "符合条件的候选岗位均被现有风险规则拦截，请核实或选择其他岗位。"}
            result = Recommendations.model_validate(await self.model_decide("workbench_recommend", redact({
                "candidates": candidates, "profile": source.get("profile"), "limit": args.get("limit", 3)}), data)).model_dump()
            by_id = {j["id"]: j for j in candidates}
            if len({r["job_id"] for r in result["items"]}) != len(result["items"]) or any(r["job_id"] not in by_id for r in result["items"]):
                raise ValueError("Unknown recommendation reference")
            data["recommendations"] = [{**r, "job": by_id[r["job_id"]]} for r in result["items"][:args.get("limit", 3)]]
            return {"items": data["recommendations"], "coverage": source.get("coverage"), "matched": len(jobs), "reviewed_candidates": len(candidates)}
        if action in {"draft_application", "revise_application"}:
            return await self.draft(data, args)
        if action == "request_save":
            artifact = next((a for a in data["artifacts"] if a["id"] == args["artifact_id"] and a["kind"] == "resume"), None)
            latest = next((a for a in reversed(data["artifacts"]) if a["kind"] == "resume"), None)
            if artifact is None or artifact != latest or artifact["binding"] != self.binding(data):
                raise ValueError("Only the current source-bound revision may be saved")
            if self.mode != "user":
                return {"needs_input": "演示草稿不能保存为个人简历版本。"}
            self.pending(data, "save_resume", {"artifact_id": artifact["id"], "revision": artifact["revision"], "text": artifact["text"]},
                         {"artifact_id": artifact["id"]})
            return {"proposal": "save_resume"}
        raise ValueError("Tool is not allowed")

    async def draft(self, data, args):
        job, material = self.selected(data)
        profile = data["source"].get("private_profile", {})
        if not job:
            return {"needs_input": "请先选择一个目标岗位。"}
        if not material:
            return {"needs_input": "请选择已确认材料，或在当前对话上传/粘贴经历并确认。"}
        if not profile.get("truth_confirmed") or not profile.get("basic", {}).get("name"):
            return {"needs_input": "请补充个人资料并确认真实性，至少填写姓名。"}
        previous = next((a for a in reversed(data["artifacts"]) if a["kind"] == "resume"), None)
        previous_greeting = next((a for a in reversed(data["artifacts"]) if a["kind"] == "greeting"), None)
        claims = material["claims"]
        value = ApplicationDraft.model_validate(await self.model_decide("workbench_draft", redact({
            "job": job, "confirmed_claims": claims, "instruction": args.get("instruction", ""),
            "profile": data["source"].get("profile"), "previous_bullets": previous.get("bullets") if previous else None}), data)).model_dump()
        if value["new_facts"]:
            return {"needs_input": "以下内容需要补充原始材料并确认，当前草稿未修改：" + "；".join(value["new_facts"])}
        by_id = {c["claim_id"]: c for c in claims}
        for text, refs in [(b["text"], b["claim_ids"]) for b in value["bullets"]] + [(value["greeting"], value["greeting_claim_ids"])]:
            if not refs or not set(refs).issubset(by_id):
                raise ValueError("Unknown claim reference")
            support = "\n".join(by_id[ref]["text"] for ref in refs)
            numbers = lambda s: set(re.findall(r"\d+(?:[.,]\d+)*(?:\s*(?:%|％|倍|万|亿))?", s))
            if not numbers(text).issubset(numbers(support)) or redact(text) != text:
                raise ValueError("Unsupported numeric claim or contact data")
            if any(word in text and word not in support for word in ("主导", "独立", "牵头")):
                raise ValueError("Responsibility escalation")
        review = DraftReview.model_validate(await self.agent.decide("workbench_review", redact({
            "confirmed_claims": claims, "job": job, "draft": value}))).model_dump()
        if not review["supported"] or review["issues"]:
            return {"needs_input": "草稿的语义核对未通过，原草稿保留：" + "；".join(review["issues"] or ["证据支持仍需核对"])}
        if self.career is None:
            raise ValueError("Personal draft service is unavailable")
        base = self.career.draft({"material_id": material["material_id"], "profile": profile})
        original_lines = {"- " + (c.get("pillar", "") + "：" if material.get("project_name") and c.get("pillar") else "") + c["text"] for c in claims}
        lines, inserted = [], False
        for line in base["markdown"].splitlines():
            if line in original_lines:
                if not inserted:
                    lines.extend("- " + b["text"] for b in value["bullets"])
                    inserted = True
            else:
                lines.append(line)
        if not inserted:
            raise ValueError("Source draft structure changed")
        markdown = "\n".join(lines).strip() + "\n"
        revision = 1 + sum(a["kind"] == "resume" for a in data["artifacts"])
        shared = {"revision": revision, "binding": self.binding(data), "job_snapshot": {**deepcopy(job), "role": job.get("title", ""), "jd": job.get("raw_text", "")},
                  "material_id": material["material_id"], "generation": deepcopy(self.agent.generation),
                  "review": {**review, "scope": "model_semantic_check_pending_human_review"}, "created_at": now()}
        data["artifacts"].extend([
            {**shared, "id": "artifact_" + uuid.uuid4().hex, "kind": "resume", "text": markdown,
             "bullets": value["bullets"], "source_map": value["bullets"],
             "diff": "\n".join(difflib.unified_diff((previous["text"] if previous else base["markdown"]).splitlines(), markdown.splitlines(), fromfile="修改前", tofile="当前草稿", lineterm=""))},
            {**shared, "id": "artifact_" + uuid.uuid4().hex, "kind": "greeting", "text": value["greeting"],
             "source_map": value["greeting_claim_ids"], "delivery_status": "not_synced_not_sent",
             "diff": "\n".join(difflib.unified_diff((previous_greeting["text"] if previous_greeting else "").splitlines(),
                 value["greeting"].splitlines(), fromfile="修改前", tofile="当前草稿", lineterm=""))}])
        return {"artifacts": [{"id": a["id"], "kind": a["kind"], "revision": revision} for a in data["artifacts"][-2:]],
                "notice": "草稿已准备，事实来源与差异可查看；语义仍待人工复核，未发送。"}
