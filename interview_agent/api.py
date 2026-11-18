"""Authenticated local FastAPI surface for Python-owned interview execution."""

from contextlib import asynccontextmanager
import hmac
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from interview_hub.server import identifier, public_material
from interview_hub.store import ConflictError, NotFoundError, Store
from .graph import InterviewWorkflow
from .models import StartInterview, Turn
from .model_adapter import ModelAdapter, ModelError
from .repository import Repository


def create_app(db_path, checkpoint_path, owner, token, agent=None, *, career_root=None, career_options=None):
    if not owner or not isinstance(token, str) or len(token) < 20:
        raise ValueError("A local owner and a service token of at least 20 characters are required")
    if Path(db_path).resolve() == Path(checkpoint_path).resolve():
        raise ValueError("Business records and runtime checkpoints use separate databases")
    repo = Repository(Store(db_path), owner)
    Path(checkpoint_path).parent.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app):
        execution = agent if agent is not None else await ModelAdapter().start()
        if getattr(execution, "managed", False):
            await execution.start()
        try:
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
                await saver.setup()
                app.state.workflow = InterviewWorkflow(repo, execution, saver)
                if career_root is not None:
                    from .career import CareerService
                    app.state.career = CareerService(repo, execution, career_root, **(career_options or {}))
                    from .knowledge import KnowledgeService
                    app.state.knowledge = KnowledgeService(db_path, owner, career_root,
                        authorization=app.state.career.auth, client_factory=app.state.career.client_factory)
                    app.state.career.knowledge = app.state.knowledge
                    await app.state.knowledge.warmup()
                    from .note_subscriptions import NoteSubscriptions
                    app.state.note_subscriptions = NoteSubscriptions(career_root, owner)
                from .workbench import WorkbenchWorkflow
                app.state.workbench = WorkbenchWorkflow(repo, execution, saver,
                    career=getattr(app.state, "career", None), token=token,
                    notes=getattr(app.state, "note_subscriptions", None),
                    mode="user" if career_root is not None else "demo")
                from .comprehensive_graph import ComprehensiveInterviewWorkflow
                app.state.comprehensive = ComprehensiveInterviewWorkflow(
                    repo,
                    execution,
                    saver,
                    knowledge=getattr(app.state, "knowledge", None),
                    notes=getattr(app.state, "note_subscriptions", None),
                )
                if getattr(execution, "managed", False):
                    execution.is_busy = lambda: any(not task.done() for task in list(app.state.workbench.tasks.values())) or any(
                        not task.done() for task in list(getattr(getattr(app.state, "career", None), "tasks", [])))
                try:
                    if career_root is not None:
                        await app.state.note_subscriptions.start()
                    yield
                finally:
                    await app.state.workbench.close()
                    if career_root is not None:
                        await app.state.note_subscriptions.close()
                        await app.state.knowledge.close()
                        await app.state.career.close()
        finally:
            if agent is None or getattr(execution, "managed", False):
                await execution.close()

    bearer = HTTPBearer(auto_error=False)

    async def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        supplied = credentials.credentials if credentials else ""
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, detail="unauthorized")

    app = FastAPI(title="Interview Agent Local", version="0.1.0", lifespan=lifespan, dependencies=[Depends(authorized)])
    from .workbench_api import install_workbench_routes
    install_workbench_routes(app)
    from .comprehensive_api import install_comprehensive_routes
    install_comprehensive_routes(app)
    if career_root is not None:
        from .career_api import install_career_routes
        install_career_routes(app, repo)
        from .knowledge_api import install_knowledge_routes
        install_knowledge_routes(app)
        from .note_api import install_note_routes
        install_note_routes(app)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, error):
        return JSONResponse(status_code=422, content={"error": "invalid_request"})

    @app.exception_handler(NotFoundError)
    async def missing(request, error):
        return JSONResponse(status_code=404, content={"error": "not_found"})

    @app.exception_handler(ConflictError)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"error": "state_or_version_conflict"})

    @app.exception_handler(ValueError)
    async def invalid_binding(request, error):
        return JSONResponse(status_code=400, content={"error": "invalid_binding_or_decision"})

    @app.exception_handler(ModelError)
    async def model_failure(request, error):
        logging.getLogger(__name__).warning("Interview model failure: %s; format=%s", error.code,
                                           getattr(app.state.workflow.agent, "last_failure", None))
        return JSONResponse(status_code=502, content={"error": "model_execution_failed", "code": error.code,
                                                    "retryable": True})

    @app.get("/health")
    async def health():
        return {"status": "ok", "scope": "local_single_owner_prototype", "orchestrator": "python-langgraph",
                "model_executor": "python-httpx", "generation": app.state.workflow.agent.generation}

    @app.get("/v1/materials")
    async def materials():
        return {"items": [public_material(row) for row in repo.store.list_materials(owner)]}

    @app.post("/v1/interviews", status_code=201)
    async def start(request: StartInterview):
        return await app.state.workflow.start(request)

    @app.get("/v1/interviews/{session_id}")
    async def current(session_id: str):
        return await app.state.workflow.get(identifier(session_id))

    @app.post("/v1/interviews/{session_id}/turns")
    async def turn(session_id: str, request: Turn):
        return await app.state.workflow.turn(identifier(session_id), request)

    @app.get("/v1/sessions/{session_id}/results")
    async def result(session_id: str):
        return repo.store.get_result(owner, identifier(session_id))

    @app.get("/v1/sessions/{session_id}/recap")
    async def recap(session_id: str):
        return repo.store.get_recap(owner, identifier(session_id))

    @app.get("/v1/sessions/{session_id}/question-plan")
    async def plan(session_id: str):
        return repo.store.get_plan(owner, identifier(session_id))

    @app.get("/v1/history")
    async def history(claim_id: str | None = None, limit: int = 20, offset: int = 0):
        if claim_id is not None:
            identifier(claim_id)
        return {"items": repo.store.history(owner, claim_id, limit, offset)}

    return app
