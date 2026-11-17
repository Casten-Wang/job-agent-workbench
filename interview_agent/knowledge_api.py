"""Knowledge routes, usable with the career app or without any model runtime."""

import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from github_source.github_api import GitHubError

from interview_hub.store import ConflictError, NotFoundError
from .knowledge import KnowledgeService


def install_knowledge_routes(app):
    def service():
        return app.state.knowledge

    @app.post("/v1/knowledge/sources", status_code=202)
    async def register(data: dict):
        return service().register(data)

    @app.post("/v1/knowledge/warmup", status_code=202)
    async def warmup(data: dict):
        if data:
            raise ValueError("Warmup takes an empty object")
        return await service().warmup()

    @app.get("/v1/knowledge/sources")
    async def sources(limit: int = 20, offset: int = 0):
        return await asyncio.to_thread(service().list_sources, limit, offset)

    @app.get("/v1/knowledge/snapshots/{snapshot_id}/context")
    async def context(snapshot_id: str):
        return await asyncio.to_thread(service().context, snapshot_id)

    @app.post("/v1/knowledge/search")
    async def search(data: dict):
        return await asyncio.to_thread(service().search, data)


def create_knowledge_app(business_db, owner, token, root, **options):
    if not owner or not isinstance(token, str) or len(token) < 20:
        raise ValueError("A local owner and a service token of at least 20 characters are required")

    @asynccontextmanager
    async def lifespan(app):
        service = KnowledgeService(business_db, owner, root, **options)
        app.state.knowledge = service
        try:
            await service.warmup()
            yield
        finally:
            await service.close()

    bearer = HTTPBearer(auto_error=False)

    async def authorized(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        supplied = credentials.credentials if credentials else ""
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            raise HTTPException(401, detail="unauthorized")

    app = FastAPI(title="Local Project Knowledge", version="1.0", lifespan=lifespan,
                  dependencies=[Depends(authorized)])
    install_knowledge_routes(app)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    for error_type, status, message in ((NotFoundError, 404, "not_found"),
            (ConflictError, 409, "knowledge_not_ready"), (ValueError, 400, "invalid_knowledge_request"),
            (GitHubError, 400, "invalid_repository_or_authorization"),
            (RequestValidationError, 422, "invalid_request")):
        def handler(code, text):
            async def respond(request, error):
                return JSONResponse(status_code=code, content={"error": text})
            return respond
        app.add_exception_handler(error_type, handler(status, message))

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "local_project_knowledge", "model_required": False}

    return app


def main():
    import argparse
    import uvicorn
    parser = argparse.ArgumentParser(description="Model-free local project knowledge service")
    parser.add_argument("--root", type=Path, required=True, help="Existing personal career runtime directory")
    parser.add_argument("--owner", default="offerpilot-personal")
    parser.add_argument("--port", type=int, default=18748)
    args = parser.parse_args()
    token = os.environ.get("OFFERPILOT_CAREER_USER_TOKEN", "")
    if len(token) < 20:
        parser.error("Set OFFERPILOT_CAREER_USER_TOKEN to a service token of at least 20 characters")
    uvicorn.run(create_knowledge_app(args.root / "interview.db", args.owner, token, args.root),
                host="127.0.0.1", port=args.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
