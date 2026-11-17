"""Confirmed GitHub experience to frozen resumes, with optional interview APIs."""

import asyncio
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import re
import uuid
from urllib.parse import quote

from github_source.authorization import GitHubAuthorization
from github_source.github_api import GitHubClient, GitHubError, parse_repository
from github_source.ingest import ingest
from interview_hub.career_store import CareerRecords
from interview_hub.recap import validate_result
from interview_hub.store import ConflictError, NotFoundError
from .model_adapter import ModelError
from .project_evidence import project_evidence
from .project_writing import writing_issues
from .experience import freeze_experience, experience_issues


def digest(value, prefix):
    return prefix + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def bounded(value, name, limit, *, required=True):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError(f"Invalid {name}")
    return value.strip()


class CareerService:
    def __init__(self, repository, agent, root, *, authorization=None, client_factory=None):
        self.repo, self.agent, self.root = repository, agent, Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.auth = authorization or GitHubAuthorization(self.root)
        self.records = CareerRecords(repository.store.db_path, repository.owner)
        self.client_factory = client_factory or (lambda: GitHubClient(token=self.auth.token()))
        self.tasks = set()
        self.knowledge = None
        for project in self.records.list("project"):
            if project["status"] == "preparing":
                project.update(status="failed", error="上次整理被中断，请核对材料后重试" if project.get("source_type") == "manual" else "上次准备被中断，请重新选择项目")
                self.records.put("project", project["project_id"], project, replace=True)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.auth.close()

    def repositories(self, page):
        if not 1 <= page <= 10000:
            raise ValueError("Invalid repository page")
        client = self.client_factory()
        rows = client.get_json("/user/repos", {"visibility": "all", "affiliation": "owner,collaborator,organization_member",
                                              "sort": "updated", "direction": "desc", "per_page": 50, "page": page})
        if not isinstance(rows, list):
            raise GitHubError("GitHub 仓库列表格式异常")
        fields = ("id", "full_name", "private", "fork", "description", "language", "default_branch", "updated_at", "html_url")
        return {"items": [{key: item.get(key) for key in fields} for item in rows], "page": page,
                "next_page": page + 1 if len(rows) == 50 else None}

    def tree(self, repository, page):
        parse_repository(repository)
        if not 1 <= page <= 10000:
            raise ValueError("Invalid file page")
        client = self.client_factory()
        resolved = client.resolve_repository(repository)
        owner, name = resolved["repository"]["full_name"].split("/")
        rows = client.get_tree(owner, name, resolved["tree_sha"])
        selected = rows[(page - 1) * 200:page * 200]
        return {"repository": f"{owner}/{name}", "source_commit": resolved["commit_sha"], "total": len(rows),
                "items": [{key: row.get(key) for key in ("path", "type", "size")} for row in selected],
                "next_page": page + 1 if page * 200 < len(rows) else None}

    def file(self, repository, commit, path):
        owner, name = parse_repository(repository)
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit) or any(p in {"", ".", ".."} for p in path.split("/")) or "\\" in path:
            raise ValueError("Invalid source file reference")
        item = self.client_factory().get_json(f"/repos/{owner}/{name}/contents/{quote(path, safe='/')}", {"ref": commit})
        if item.get("type") != "file" or item.get("encoding") != "base64" or item.get("size", 0) > 256 * 1024:
            raise ValueError("Preview supports text files up to 256 KiB")
        try:
            text = base64.b64decode(item["content"]).decode("utf-8")
        except (ValueError, UnicodeError, KeyError):
            raise ValueError("Source file is not UTF-8 text") from None
        return {"path": path, "text": text[:30000], "truncated": len(text) > 30000, "source_commit": commit}

    async def prepare(self, data):
        if set(data) - {"repository", "role", "jd", "contribution", "confirmed", "model_consent"}:
            raise ValueError("Unknown project fields")
        owner, name = parse_repository(data.get("repository"))
        role = bounded(data.get("role"), "role", 200)
        contribution = bounded(data.get("contribution"), "contribution", 4000)
        jd = bounded(data.get("jd", ""), "jd", 15000, required=False)
        if data.get("confirmed") is not True or data.get("model_consent") is not True:
            raise ValueError("Confirm contribution and source sharing before preparing project")
        self.auth.token()
        project_id = "project_" + uuid.uuid4().hex
        project = {"project_id": project_id, "repository": f"{owner}/{name}", "role": role, "jd": jd,
                   "contribution": contribution, "contribution_confirmation": "user_self_report",
                   "status": "preparing", "phase": "正在读取项目内容", "is_demo": False}
        self.records.put("project", project_id, project)
        task = asyncio.create_task(self._prepare(project))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return project

    async def prepare_experience(self, data, *, on_text=None, on_validating=None):
        value, sha, evidence = freeze_experience(data)
        project_id = "project_" + uuid.uuid4().hex
        project = {"project_id": project_id, "source_type": "manual", "repository": value["name"],
                   "source_commit": sha, "project_snapshot_id": f"experience:{sha}", "experience": value,
                   "role": value["role"], "jd": value["jd"], "contribution": value["contribution"],
                   "contribution_confirmation": "user_self_report", "evidence": evidence,
                   "status": "preparing", "phase": "整理本人经历与补充材料", "is_demo": False}
        self.records.put("project", project_id, project)
        task = asyncio.create_task(self._prepare(project, on_text=on_text, on_validating=on_validating))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return project

    async def _prepare(self, project, *, on_text=None, on_validating=None):
        try:
            manual = project.get("source_type") == "manual"
            if manual:
                evidence = project["evidence"]
                project.update(coverage={"read_fragments": len(evidence)})
            else:
                directory, manifest = await asyncio.to_thread(ingest, self.client_factory(), project["repository"],
                                                             self.root / "sources", max_files=250)
                evidence = await asyncio.to_thread(project_evidence, directory, manifest)
                project.update(phase="正在整理项目经历", source_commit=manifest["commit_sha"],
                               repository=manifest["repository"],
                               project_snapshot_id=f"github:{manifest['repository_id']}:{manifest['commit_sha']}",
                               coverage={"downloaded": sum(e["status"] == "downloaded" for e in manifest["files"]),
                                         "read_fragments": len(evidence), "exclusions": manifest.get("coverage", {}).get("exclusion_reasons", {})})
            if not evidence:
                raise ValueError("No readable project evidence")
            self.records.put("project", project["project_id"], project, replace=True)
            if self.knowledge is not None:
                self.knowledge.register({"project_id": project["project_id"]})
            # Short, request-local IDs prevent the model from mistyping hashes.
            # Map them back exactly before persisting any source references.
            references = {f"E{i}": item["evidence_id"] for i, item in enumerate(evidence, 1)}
            model_evidence = [{**item, "evidence_id": key} for key, item in zip(references, evidence)]
            request = {"repository": project["repository"], "source_commit": project["source_commit"],
                       "role": project["role"], "jd": project["jd"], "contribution": project["contribution"], "evidence": model_evidence}
            if manual:
                request["experience"] = {k: project["experience"][k] for k in ("kind", "name", "organization", "position", "start", "end")}
            if manual and on_text is not None and hasattr(self.agent, "decide_stream"):
                understood = await self.agent.decide_stream("prepare_experience", request, on_text)
            else:
                understood = await self.agent.decide("prepare_experience" if manual else "prepare", request)
            if on_validating is not None:
                await on_validating()
            if writing_issues(understood) or manual and experience_issues(understood, model_evidence):
                raise ValueError("Project prose contains internal source details")
            for item in understood["claims"]:
                item["evidence_ids"] = [references[ref] for ref in item["evidence_ids"]]
            known = {e["evidence_id"] for e in evidence}
            claims = []
            for item in understood["claims"]:
                if not item["evidence_ids"] or not set(item["evidence_ids"]).issubset(known):
                    raise ValueError("Project fact cites unrelated evidence")
                item["text"] = re.sub(r"\s+", " ", item["text"]).strip()
                if len(item["text"]) > 200:
                    raise ValueError("Project fact is not concise enough for a resume bullet")
                if not manual and re.search(r"\d+(?:\.\d+)?\s*(?:%|倍|万元|万用户|万次)", item["text"]):
                    raise ValueError("Unsupported project outcome metric")
                if not item.get("pillar"):
                    item["pillar"] = "核心贡献" if manual else "工程实现"
                claims.append({**item, "claim_id": digest({"commit": project["source_commit"], **item}, "claim_"),
                               "personal_contribution": "unconfirmed"})
            project.update(status="ready", phase="请逐条确认本人负责的工作", summary=understood["summary"],
                           project_name=understood.get("project_name", ""), project_overview=understood.get("project_overview", ""),
                           positioning=understood.get("positioning", ""),
                           claims=claims, evidence=evidence)
            if manual:
                project["project_name"] = project["experience"]["name"]
        except asyncio.CancelledError:
            project.update(status="failed", error="准备已中断，请重新选择项目")
            raise
        except (GitHubError, ValueError, KeyError, OSError, RuntimeError) as error:
            code = error.code if isinstance(error, ModelError) else "material_validation_failed" if project.get("source_commit") else "source_read_failed"
            logging.getLogger(__name__).warning("Career preparation failed: %s; format=%s", code, getattr(self.agent, "last_failure", None))
            message = ("原始经历已保留，整理未完成；请核对原文后重试。" if project.get("source_type") == "manual" else
                       "源码快照已保存，经历表述整理未完成。可直接重试，无需重新授权；不会据此评价能力。" if project.get("source_commit") else "源码读取未完成，请检查 GitHub 授权与网络后重试。")
            project.update(status="failed", error=message, error_code=code)
        finally:
            self.records.put("project", project["project_id"], project, replace=True)

    def confirm(self, project_id, data):
        project = self.records.get("project", project_id)
        selected = data.get("claim_ids")
        if (project["status"] != "ready" or data.get("confirmed") is not True or not isinstance(selected, list)
                or not selected or any(not isinstance(x, str) for x in selected) or len(selected) != len(set(selected))):
            raise ValueError("Confirm project claims first")
        claims = [{**claim, "personal_contribution": "confirmed"} for claim in project["claims"] if claim["claim_id"] in selected]
        if len(claims) != len(selected):
            raise ValueError("Unknown project claims")
        evidence_ids = {ref for claim in claims for ref in claim["evidence_ids"]}
        material = {"schema_version": 1, "is_demo": False, "resume_version_id": None,
                    "source_commit": project["source_commit"], "source_repository": project["repository"],
                    "project_snapshot_id": project["project_snapshot_id"], "claims": claims,
                    "evidence": [e for e in project["evidence"] if e["evidence_id"] in evidence_ids],
                    "questions": [{"question_id": f"source_q{i}", "claim_id": c["claim_id"],
                                   "text": f"请结合源码解释：{c['text']}", "evidence_ids": c["evidence_ids"],
                                   "expected_facts": []} for i, c in enumerate(claims, 1)],
                    "contribution_statement": project["contribution"], "contribution_confirmation": "user_self_report",
                    "target": {"role": project["role"]}, "job_snapshot": {"role": project["role"], "jd": project["jd"]},
                    "warnings": ["个人职责由用户确认；仓库存在与提交记录不证明独立完成。", "仅读取已声明范围，未执行仓库代码。"]}
        if project.get("project_name") and project.get("project_overview"):
            material.update(project_name=project["project_name"], project_overview=project["project_overview"])
        if project.get("source_type") == "manual":
            material.update(source_type="manual", experience=deepcopy(project["experience"]), project_name=project["experience"]["name"],
                            warnings=["经历与附件来自用户提供，未经独立核验。", "作品集链接仅作引用，未自动访问或验证。"])
            for question in material["questions"]:
                question["text"] = question["text"].replace("结合源码", "结合原始经历")
        if project.get("source_material_id"):
            material.update(source_material_id=project["source_material_id"],
                            source_material_sha256=project["source_material_sha256"])
        material_id = digest(material, "mat_")
        material["material_id"] = material_id
        validate_result(material, {"answers": [], "observations": []})
        self.repo.store.put_material(self.repo.owner, material_id, material)
        # Identical confirmed facts can be prepared more than once. Preserve
        # the first binding instead of conflicting with a new preparation id.
        try:
            self.records.get("binding", material_id)
        except NotFoundError:
            self.records.put("binding", material_id, {"project_id": project_id, "material_id": material_id})
        return {"material_id": material_id}

    def draft(self, data):
        session_id = data.get("session_id")
        if data.get("material_id"):
            material_id = bounded(data["material_id"], "material", 100)
            material = self.repo.store.get_material(self.repo.owner, material_id)["payload"]
            if (material.get("is_demo") is not False or material.get("resume_version_id") is not None
                    or not material.get("claims") or any(c.get("personal_contribution") != "confirmed" for c in material["claims"])):
                raise ValueError("Use confirmed personal project material")
            self.records.get("binding", material_id)
            recap = {"resume_suggestions": [], "needs_review": [], "not_assessed": []}
            assessment_status = "not_assessed"
        else:
            session_id = bounded(session_id, "session", 100)
            session, material, plan = self.repo.context(session_id)
            if material.get("is_demo") or session["state"] != "completed" or session["payload"]["mode"] != "resume_readiness":
                raise ValueError("Complete a personal project readiness session first")
            result = self.repo.store.get_result(self.repo.owner, session_id)["payload"]
            if result.get("corrections"):
                raise ConflictError("Resolve contribution or version corrections with new material first")
            recap = self.repo.store.get_recap(self.repo.owner, session_id)["payload"]
            assessment_status = "interview_observations_available"
        profile = data.get("profile")
        if not isinstance(profile, dict) or profile.get("truth_confirmed") is not True:
            raise ValueError("Confirm profile facts before creating resume")
        basic = profile.get("basic", {})
        name = bounded(basic.get("name"), "candidate name", 100)
        lines = [f"# {name}", ""]
        contacts = [str(basic.get(k) or "").strip() for k in ("phone", "email", "city")]
        if basic.get("wechat"):
            contacts.append("微信：" + str(basic["wechat"]).strip())
        if basic.get("links"):
            contacts.append(str(basic["links"]).strip())
        if any(contacts):
            lines += [" | ".join(c for c in contacts if c), ""]
        if profile.get("summary"):
            lines += ["## 个人简介", "", str(profile["summary"]), ""]
        experience = material.get("experience", {})
        section = "实习与工作经历" if experience.get("kind") in {"internship", "work"} else "作品集" if experience.get("kind") == "portfolio" else "项目经历"
        def experience_lines():
            title = " · ".join(filter(None, (experience.get("organization"), experience.get("position")))) if section == "实习与工作经历" else ""
            result = [f"### {title or material.get('project_name') or material['source_repository']}", ""]
            if experience:
                detail = [" - ".join(filter(None, (experience.get("start"), experience.get("end"))))]
                if title and experience["name"] != title:
                    detail.append(experience["name"])
                if section != "实习与工作经历":
                    detail.extend(filter(None, (experience.get("organization"), experience.get("position"))))
                if any(detail):
                    result += [" · ".join(filter(None, detail)), ""]
            if material.get("project_overview"):
                result += [material["project_overview"], ""]
            result += [f"- {claim.get('pillar', '') + '：' if material.get('project_name') and claim.get('pillar') else ''}{claim['text']}"
                       for claim in material["claims"]]
            if experience.get("portfolio_url"):
                result += ["", "作品集：" + experience["portfolio_url"]]
            elif material.get("source_type") != "manual" and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", material["source_repository"]):
                result += ["", "项目链接：https://github.com/" + material["source_repository"]]
            return result
        for title, key, heading_keys in (("教育背景", "education", ("school", "major", "degree")),
                                         ("实习与工作经历", "experiences", ("company", "title"))):
            if profile.get(key) or title == section:
                lines += [f"## {title}", ""]
                for row in profile.get(key, []):
                    if title == section and all(row.get(field, "") == experience.get(other, "") for field, other in
                                               (("company", "organization"), ("title", "position"), ("start", "start"), ("end", "end"))):
                        continue
                    lines += ["### " + " · ".join(str(row.get(k) or "") for k in heading_keys),
                              " - ".join(str(row.get(k) or "") for k in ("start", "end")), str(row.get("summary") or ""), ""]
                if title == section:
                    lines += experience_lines()
        if section != "实习与工作经历":
            lines += [f"## {section}", ""] + experience_lines()
        selected_names = {str(value).strip().casefold() for value in
                          (material.get("project_name", ""), material["source_repository"], experience.get("name", "")) if value}
        other_projects = [row for row in profile.get("projects", []) if row.get("name")
                          and str(row["name"]).strip().casefold() not in selected_names]
        if other_projects:
            if section != "项目经历":
                lines += ["", "## 项目经历", ""]
            for row in other_projects:
                lines += ["", "### " + " · ".join(str(row.get(k) or "") for k in ("name", "role") if row.get(k)),
                          " - ".join(str(row.get(k) or "") for k in ("start", "end") if row.get(k)),
                          str(row.get("summary") or ""), ""]
        skills = profile.get("skills", {})
        if skills.get("tools") or skills.get("strengths"):
            lines += ["", "## 技能", "", "、".join(skills.get("tools", []) + skills.get("strengths", []))]
        markdown = "\n".join(lines).strip() + "\n"
        value = {"session_id": session_id, "material_id": material["material_id"], "source_commit": material["source_commit"],
                 "project_snapshot_id": material["project_snapshot_id"], "profile_snapshot": deepcopy(profile),
                 "job_snapshot": material["job_snapshot"], "claim_ids": [c["claim_id"] for c in material["claims"]],
                 "contribution_statement": material["contribution_statement"],
                 "markdown": markdown, "markdown_sha256": hashlib.sha256(markdown.encode()).hexdigest(),
                 "review_notes": recap["resume_suggestions"], "needs_review": recap["needs_review"],
                 "not_assessed_count": len(recap["not_assessed"]), "assessment_status": assessment_status,
                 "generation_basis": "source_evidence_and_user_confirmed_facts", "is_demo": False}
        if material.get("source_type") == "manual":
            value.update(source_type="manual", generation_basis="user_supplied_material_and_confirmed_facts")
        draft_id = digest(value, "draft_")
        value["draft_id"] = draft_id
        return self.records.put("draft", draft_id, value)

    def save_version(self, draft_id, confirmed):
        if confirmed is not True:
            raise ValueError("Review and confirm resume before saving")
        draft = self.records.get("draft", draft_id)
        version_id = digest(draft, "resume_")
        try:
            existing = self.records.get("resume", version_id)
            original = self.repo.store.get_material(self.repo.owner, draft["material_id"])["payload"]
            old_material_id = digest({**original, "resume_version_id": version_id}, "mat_")
            return {**existing, "interview_material_id": existing.get("interview_material_id", old_material_id)}
        except NotFoundError:
            pass
        version = {**draft, "resume_version_id": version_id, "confirmed": True,
                   "created_at": datetime.now(timezone.utc).isoformat(),
                   "confirmation_scope": "User confirmed profile and project statements; no interview assessment" if draft.get("assessment_status") == "not_assessed"
                   else "User confirmed profile, project statements and readiness limitations"}
        original = self.repo.store.get_material(self.repo.owner, draft["material_id"])["payload"]
        profile = draft["profile_snapshot"]
        professional = {key: deepcopy(profile.get(key)) for key in ("education", "experiences", "projects", "skills", "summary")}
        material = {**original, "resume_version_id": version_id,
                    "resume_context": {"professional_profile": professional,
                                       "project_statements": [c["text"] for c in original["claims"]]}}
        if draft.get("workbench_artifact_id"):
            material["job_snapshot"] = deepcopy(draft["job_snapshot"])
            material["target"] = {"role": draft["job_snapshot"]["role"]}
        material_id = digest(material, "mat_")
        material["material_id"] = material_id
        self.repo.store.put_material(self.repo.owner, material_id, material)
        self.records.put("binding", material_id, {"material_id": material_id, "resume_version_id": version_id})
        version["interview_material_id"] = material_id
        return self.records.put("resume", version_id, version)
