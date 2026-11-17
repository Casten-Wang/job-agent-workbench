"""Owner-bound private note APIs; credentials and owner never come from input."""

import asyncio
from fastapi import Query
from pydantic import Field
from .models import StrictModel


class CollectNote(StrictModel):
    url: str = Field(min_length=1, max_length=4096)


class SubscribeNote(CollectNote):
    interval_hours: int = Field(default=24, ge=1, le=168)
    keywords: list[str] = Field(default_factory=list, max_length=10)


def install_note_routes(app):
    def service():
        return app.state.note_subscriptions

    @app.post("/v1/notes/collect")
    async def collect(data: CollectNote):
        return await asyncio.to_thread(service().collect, data.url)

    @app.get("/v1/notes/subscriptions")
    async def subscriptions():
        return {"items": service().listing()}

    @app.post("/v1/notes/subscriptions", status_code=201)
    async def subscribe(data: SubscribeNote):
        return service().create(data.url, data.interval_hours, data.keywords)

    @app.post("/v1/notes/subscriptions/{key}/pause")
    async def pause(key: str):
        return service().enable(key, False)

    @app.post("/v1/notes/subscriptions/{key}/resume")
    async def resume(key: str):
        return service().enable(key, True)

    @app.get("/v1/notes/subscriptions/{key}/runs")
    async def runs(key: str, limit: int = Query(30, ge=1, le=100)):
        return service().runs(key, limit)

    @app.get("/v1/notes/inbox")
    async def inbox(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
        return service().inbox(limit, offset)

    @app.post("/v1/notes/inbox/{key}/read")
    async def read(key: str):
        return service().read(key)

    @app.get("/v1/notes/self-check")
    async def self_check():
        return await asyncio.to_thread(service().health)

    @app.get("/v1/notes/items/{key}")
    async def note(key: str):
        return service().note(key)
