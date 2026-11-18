"""Private engine API; the same-origin bridge owns workspace snapshots."""

from .models import StrictModel
from .workbench_contracts import NewConversation, UserEvent, Approval, Attachment, WorkspaceContext
from starlette.responses import StreamingResponse
from pydantic import Field


class TurnRequest(StrictModel):
    event: UserEvent
    source: dict


class ApprovalRequest(StrictModel):
    decision: Approval
    source: dict


class AttachmentRequest(StrictModel):
    attachment: Attachment
    source: dict


class MaterialRetryRequest(StrictModel):
    event_id: str = Field(min_length=1, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    source: dict


class ContextRequest(StrictModel):
    context: WorkspaceContext
    source: dict


class ArtifactSource(StrictModel):
    source: dict


def install_workbench_routes(app):
    def workflow():
        return app.state.workbench

    @app.get("/v1/workbench/overview")
    async def overview():
        from interview_hub.store import ConflictError, NotFoundError
        result = workflow().overview()
        repo, offset = workflow().repo, 0
        while True:
            rows = repo.store.list_sessions(repo.owner, state="in_progress", offset=offset)
            for row in rows:
                try:
                    view = await app.state.workflow.get(row["session_id"])
                    if view["status"] == "completed":
                        continue
                    status = view["status"]
                except (ConflictError, NotFoundError):
                    status = "waiting_input"
                role = row["payload"].get("target", {}).get("role", "项目")
                result["tasks"].append({"id": row["session_id"], "title": role + " 面试", "status": status,
                    "capability": "interview", "interview_id": row["session_id"], "interview_kind": "project"})
            if len(rows) < 100:
                break
            offset += 100
        recaps = [{"id": row["session_id"], "title": row["payload"].get("target", {}).get("role", "项目") + " 面试复盘",
                   "kind": "面试复盘", "capability": "interview", "interview_id": row["session_id"], "interview_kind": "project"}
                  for row in repo.store.list_sessions(repo.owner, state="completed", limit=5)]
        comprehensive = getattr(app.state, "comprehensive", None)
        if comprehensive is not None:
            for ci_row in comprehensive.records.list("ci_session", limit=10):
                ci_sid = ci_row.get("session_id")
                if not ci_sid:
                    continue
                role_label = ci_row.get("role") or ci_row.get("role_family") or "综合"
                try:
                    ci_view = await comprehensive.get(ci_sid)
                    ci_status = ci_view.get("status", "active")
                except (ConflictError, NotFoundError):
                    ci_status = "waiting_input"
                if ci_status in {"completed", "early_terminated"}:
                    recaps.insert(0, {"id": ci_sid, "title": f"{role_label} 综合模拟复盘", "kind": "综合复盘",
                                      "capability": "interview", "interview_id": ci_sid, "interview_kind": "comprehensive"})
                else:
                    result["tasks"].append({"id": ci_sid, "title": f"{role_label} 综合模拟面试", "status": ci_status,
                                            "capability": "interview", "interview_id": ci_sid, "interview_kind": "comprehensive"})
        result["results"] = recaps + result["results"]
        return result

    @app.get("/v1/workbench/conversations")
    async def conversations():
        return {"items": workflow().listing(), "materials": workflow().materials(public=True)}

    @app.post("/v1/workbench/conversations", status_code=201)
    async def create(request: NewConversation):
        return workflow().create(request.title)

    @app.get("/v1/workbench/conversations/{sid}")
    async def get(sid: str):
        return workflow().view(workflow().get(sid))

    @app.get("/v1/workbench/conversations/{sid}/events")
    async def events(sid: str, after: int = 0):
        if after < 0:
            raise ValueError("Invalid event cursor")
        data = workflow().get(sid)
        return {"events": [e for e in data["events"] if e["cursor"] > after], "view": workflow().view(data)}

    @app.get("/v1/workbench/conversations/{sid}/stream")
    async def stream(sid: str, after: int = 0):
        if not 0 <= after <= 9999999999:
            raise ValueError("Invalid event cursor")
        workflow().get(sid)
        return StreamingResponse(workflow().stream(sid, after), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/v1/workbench/conversations/{sid}/messages", status_code=202)
    async def message(sid: str, request: TurnRequest):
        return await workflow().turn(sid, request.event, request.source)

    @app.post("/v1/workbench/conversations/{sid}/context")
    async def context(sid: str, request: ContextRequest):
        return await workflow().context(sid, request.context, request.source)

    @app.post("/v1/workbench/conversations/{sid}/artifacts/{artifact_id}/greeting-preview")
    async def greeting_preview(sid: str, artifact_id: str, request: ArtifactSource):
        return workflow().greeting_for_sync(sid, artifact_id, request.source)

    @app.post("/v1/workbench/conversations/{sid}/attachments", status_code=202)
    async def attachment(sid: str, request: AttachmentRequest):
        return await workflow().turn(sid, None, request.source, request.attachment)

    @app.post("/v1/workbench/conversations/{sid}/approvals", status_code=202)
    async def approve(sid: str, request: ApprovalRequest):
        return await workflow().approve(sid, request.decision, request.source)

    @app.post("/v1/workbench/conversations/{sid}/retry-material", status_code=202)
    async def retry_material(sid: str, request: MaterialRetryRequest):
        return await workflow().retry_material(sid, request.event_id, request.run_id, request.source)

    @app.post("/v1/workbench/conversations/{sid}/stop")
    async def stop(sid: str):
        return await workflow().stop(sid)
