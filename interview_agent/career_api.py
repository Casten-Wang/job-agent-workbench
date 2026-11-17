"""Routes installed only on the separate personal career service."""

import asyncio
from fastapi import HTTPException
from github_source.github_api import GitHubError
from .models import StartInterview


def install_career_routes(app, repo):
    def service():
        return app.state.career

    @app.post("/v1/career/profile-import")
    async def profile_import(data: dict):
        if set(data) != {"text"}:
            raise ValueError("Expected resume text only")
        from .resume_profile import extract_profile
        return await extract_profile(app.state.workflow.agent, data["text"])

    @app.exception_handler(GitHubError)
    async def github_error(request, error):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": str(error)})

    @app.get("/v1/career/github/status")
    async def github_status():
        return await asyncio.to_thread(service().auth.status)

    @app.post("/v1/career/github/config")
    async def github_config(data: dict):
        if set(data) != {"client_id"}:
            raise ValueError("Expected a public OAuth client ID")
        return await asyncio.to_thread(service().auth.configure, data["client_id"])

    @app.post("/v1/career/github/start")
    async def github_start():
        return await asyncio.to_thread(service().auth.start)

    @app.post("/v1/career/github/poll")
    async def github_poll(data: dict):
        if set(data) != {"ticket"}:
            raise ValueError("Invalid device authorization request")
        return await asyncio.to_thread(service().auth.poll, data["ticket"])

    @app.post("/v1/career/github/disconnect")
    async def github_disconnect():
        return await asyncio.to_thread(service().auth.disconnect)

    @app.get("/v1/career/github/repositories")
    async def github_repositories(page: int = 1):
        return await asyncio.to_thread(service().repositories, page)

    @app.get("/v1/career/github/tree")
    async def github_tree(repository: str, page: int = 1):
        return await asyncio.to_thread(service().tree, repository, page)

    @app.get("/v1/career/github/file")
    async def github_file(repository: str, commit: str, path: str):
        return await asyncio.to_thread(service().file, repository, commit, path)

    @app.get("/v1/career/projects")
    async def projects():
        return {"items": service().records.list("project")}

    @app.post("/v1/career/projects", status_code=202)
    async def prepare_project(data: dict):
        return await service().prepare(data)

    @app.post("/v1/career/experience-import", status_code=202)
    async def prepare_experience(data: dict):
        return await service().prepare_experience(data)

    @app.get("/v1/career/projects/{project_id}")
    async def project(project_id: str):
        return service().records.get("project", project_id)

    @app.post("/v1/career/projects/{project_id}/confirm")
    async def confirm_project(project_id: str, data: dict):
        if set(data) != {"claim_ids", "confirmed"}:
            raise ValueError("Invalid contribution confirmation")
        return service().confirm(project_id, data)

    @app.get("/v1/career/materials")
    async def user_materials():
        from interview_hub.server import public_material
        return {"items": [public_material(row) for row in repo.store.list_materials(repo.owner)
                          if row["payload"].get("is_demo") is False]}

    @app.get("/v1/career/materials/{material_id}/evidence")
    async def evidence(material_id: str):
        material = repo.store.get_material(repo.owner, material_id)["payload"]
        if material.get("is_demo") is not False:
            raise HTTPException(403)
        return {"evidence": material["evidence"], "source_repository": material["source_repository"],
                "source_commit": material["source_commit"], "target": material.get("target", {})}

    @app.post("/v1/career/interviews", status_code=201)
    async def interview(data: StartInterview):
        material = repo.store.get_material(repo.owner, data.material_id)["payload"]
        if material.get("is_demo") is not False:
            raise ValueError("Personal service only accepts personal materials")
        if data.mode == "mock_interview":
            version = service().records.get("resume", material.get("resume_version_id"))
            if (version["source_commit"] != material["source_commit"]
                    or version["claim_ids"] != [c["claim_id"] for c in material["claims"]]):
                raise ValueError("Resume version does not match interview material")
        if data.target != material.get("target", {}):
            raise ValueError("Target must match the frozen project/job snapshot")
        return await app.state.workflow.start(data)

    @app.post("/v1/career/resume-drafts", status_code=201)
    async def resume_draft(data: dict):
        if set(data) not in ({"session_id", "profile"}, {"material_id", "profile"}):
            raise ValueError("Invalid draft input")
        return service().draft(data)

    @app.post("/v1/career/resume-drafts/{draft_id}/save", status_code=201)
    async def resume_save(draft_id: str, data: dict):
        if set(data) != {"confirmed"}:
            raise ValueError("Confirm the reviewed draft")
        return service().save_version(draft_id, data["confirmed"])

    @app.get("/v1/career/resumes")
    async def resumes():
        fields = ("resume_version_id", "created_at", "markdown_sha256", "source_commit", "job_snapshot", "session_id")
        return {"items": [{k: row[k] for k in fields} for row in service().records.list("resume")]}

    @app.get("/v1/career/resumes/{version_id}")
    async def resume_version(version_id: str):
        version = service().records.get("resume", version_id)
        if version.get("interview_material_id"):
            return version
        material = repo.store.get_material(repo.owner, version["material_id"])["payload"]
        from .career import digest
        interview_material = {**material, "resume_version_id": version_id}
        material_id = digest(interview_material, "mat_")
        return {**version, "interview_material_id": material_id}
