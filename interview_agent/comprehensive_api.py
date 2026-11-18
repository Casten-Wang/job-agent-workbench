"""综合模拟面试 HTTP & SSE 路由注册。"""

from __future__ import annotations

import re

from fastapi import Body
from starlette.responses import PlainTextResponse, StreamingResponse

from .comprehensive_contracts import (
    ComprehensiveDrillRequest,
    ComprehensiveStreamRequest,
    ComprehensiveTurn,
    StartComprehensiveInterview,
)
from .models import StrictModel

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")


class FinishComprehensiveRequest(StrictModel):
    """手动结束综合模拟面试的可选请求体。"""

    early: bool = False


def _session_id(value: str) -> str:
    if not _ID_RE.fullmatch(value or ""):
        raise ValueError("Invalid comprehensive interview session identifier")
    return value


def install_comprehensive_routes(app) -> None:
    """将综合模拟面试全部端点挂载到 FastAPI 应用。"""

    def workflow():
        return app.state.comprehensive

    @app.post("/v1/comprehensive-interviews", status_code=201)
    async def create_comprehensive(request: StartComprehensiveInterview):
        return await workflow().start(request)

    @app.get("/v1/comprehensive-interviews/{session_id}")
    async def get_comprehensive(session_id: str):
        return await workflow().get(_session_id(session_id))

    @app.post("/v1/comprehensive-interviews/{session_id}/stream")
    async def stream_comprehensive(session_id: str, request: ComprehensiveStreamRequest):
        sid = _session_id(session_id)
        await workflow().get(sid)
        return StreamingResponse(
            workflow().stream_events(sid, request),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/comprehensive-interviews/{session_id}/turns")
    async def turn_comprehensive(session_id: str, request: ComprehensiveTurn):
        return await workflow().turn(_session_id(session_id), request)

    @app.post("/v1/comprehensive-interviews/{session_id}/finish")
    async def finish_comprehensive(
        session_id: str,
        request: FinishComprehensiveRequest | None = Body(default=None),
    ):
        early = bool(request.early) if request is not None else False
        return await workflow().finish(_session_id(session_id), early=early)

    @app.get("/v1/comprehensive-interviews/{session_id}/recap")
    async def recap_comprehensive(session_id: str):
        return await workflow().recap(_session_id(session_id))

    @app.get("/v1/comprehensive-interviews/{session_id}/export")
    async def export_comprehensive(session_id: str, format: str = "json"):
        data = await workflow().export_markdown(_session_id(session_id))
        if format == "markdown":
            return PlainTextResponse(
                data["markdown"],
                media_type="text/markdown; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{data["filename"]}"'},
            )
        return data

    @app.post("/v1/comprehensive-interviews/{session_id}/drill")
    async def drill_comprehensive(session_id: str, request: ComprehensiveDrillRequest):
        return await workflow().drill(_session_id(session_id), request)
