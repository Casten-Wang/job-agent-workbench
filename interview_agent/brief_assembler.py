"""综合模拟面试上下文装配器（确定性冻结本人与岗位全量信息）。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Any
import uuid

from interview_hub.career_store import CareerRecords
from interview_hub.store import ConflictError, NotFoundError

from .career import digest
from .comprehensive_contracts import (
    BriefClaim,
    BriefExperience,
    BriefProject,
    ExternalRefItem,
    InterviewBrief,
    JobContextInput,
    LoopAgendaItem,
    SourceConflict,
    StartComprehensiveInterview,
)
from .workbench import redact


_METRIC_RE = re.compile(r"\d+(?:[.,]\d+)*(?:\s*(?:%|％|倍|万|亿|ms|s|qps|tps))?", re.I)
_PRIVATE_PROFILE_KEYS = frozenset({"basic", "phone", "email", "wechat", "links", "credentials", "token"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s_\-·:：/]+", "", (name or "").strip().casefold())


def _extract_metrics(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m.lower()) for m in _METRIC_RE.findall(text or "") if m.strip()}


def _safe_text(value: Any, limit: int = 2000) -> str:
    text = redact(str(value or "")).strip()
    return text[:limit]


def _load_all_records(records: CareerRecords, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = records.list(kind, limit=100, offset=offset)
        rows.extend(page)
        if len(page) < 100:
            return rows
        offset += 100


class BriefAssembler:
    """将本人档案、简历版本、知识库、面经与历史轮次确定性装配为不可变 InterviewBrief。"""

    def __init__(self, repo, *, knowledge=None, notes=None, records: CareerRecords | None = None):
        self.repo = repo
        self.knowledge = knowledge
        self.notes = notes
        self.records = records or CareerRecords(repo.store.db_path, repo.owner)

    def _safe_profile_fields(self, raw_profile: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(raw_profile, dict):
            return {}
        cleaned = {
            k: v
            for k, v in raw_profile.items()
            if str(k).lower() not in _PRIVATE_PROFILE_KEYS
        }
        return redact(cleaned)

    def _extract_experiences(self, profile: dict[str, Any]) -> tuple[list[BriefExperience], list[str], str]:
        experiences: list[BriefExperience] = []
        for kind, key, heading_keys in (
            ("education", "education", ("school", "major", "degree")),
            ("internship", "experiences", ("company", "title")),
            ("project", "projects", ("name", "role")),
        ):
            for row in profile.get(key) or []:
                if not isinstance(row, dict):
                    continue
                title = " · ".join(str(row.get(k) or "").strip() for k in heading_keys if row.get(k))
                if not title:
                    continue
                period = " - ".join(str(row.get(k) or "").strip() for k in ("start", "end") if row.get(k))
                row_kind = "work" if kind == "internship" and str(row.get("kind") or "").lower() == "work" else kind
                experiences.append(
                    BriefExperience(
                        kind=row_kind,
                        title=_safe_text(title, 300),
                        period=_safe_text(period, 100),
                        summary=_safe_text(row.get("summary") or "", 2000),
                        source_label="FACT_USER_SUPPLIED_UNVERIFIED",
                    )
                )
        skills_obj = profile.get("skills") or {}
        skills: list[str] = []
        if isinstance(skills_obj, dict):
            for field in ("tools", "strengths"):
                for item in skills_obj.get(field) or []:
                    text = _safe_text(item, 80)
                    if text and text not in skills:
                        skills.append(text)
        elif isinstance(skills_obj, list):
            for item in skills_obj:
                text = _safe_text(item, 80)
                if text and text not in skills:
                    skills.append(text)
        summary = _safe_text(profile.get("summary") or "", 2000)
        return experiences, skills[:50], summary

    def _resolve_resume_version(
        self, resume_version_id: str | None
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not resume_version_id:
            return None, None
        version = self.records.get("resume", resume_version_id)
        material_id = version.get("interview_material_id") or version.get("material_id")
        material = None
        if material_id:
            try:
                material = self.repo.store.get_material(self.repo.owner, material_id)["payload"]
            except NotFoundError:
                material = None
        return version, material

    def _resolve_projects(
        self,
        project_ids: list[str],
        resume_version: dict[str, Any] | None,
        resume_material: dict[str, Any] | None,
    ) -> tuple[list[BriefProject], list[str]]:
        warnings: list[str] = []
        if project_ids:
            raw_projects = [self.records.get("project", pid) for pid in project_ids]
        else:
            raw_projects = [
                row
                for row in _load_all_records(self.records, "project")
                if row.get("status") == "ready"
            ][:20]

        confirmed_claim_ids = set((resume_version or {}).get("claim_ids") or [])
        if resume_material:
            for claim in resume_material.get("claims") or []:
                if claim.get("personal_contribution") == "confirmed" and claim.get("claim_id"):
                    confirmed_claim_ids.add(claim["claim_id"])

        brief_projects: list[BriefProject] = []
        for proj in raw_projects:
            pid = proj["project_id"]
            name = (
                proj.get("project_name")
                or (proj.get("experience") or {}).get("name")
                or proj.get("repository")
                or pid
            )
            claims: list[BriefClaim] = []
            for item in proj.get("claims") or []:
                cid = item.get("claim_id") or ""
                is_confirmed = (
                    item.get("personal_contribution") == "confirmed" or cid in confirmed_claim_ids
                )
                claims.append(
                    BriefClaim(
                        claim_id=cid or digest(item, "claim_"),
                        project_id=pid,
                        project_name=_safe_text(name, 200),
                        pillar=_safe_text(item.get("pillar") or "", 100),
                        text=_safe_text(item.get("text") or "", 500),
                        boundary=_safe_text(item.get("boundary") or "", 300),
                        risk=_safe_text(item.get("risk") or "", 300),
                        evidence_ids=list(item.get("evidence_ids") or []),
                        confirmed=is_confirmed,
                        source_label=(
                            "FACT_CANDIDATE_CONFIRMED"
                            if is_confirmed and proj.get("source_type") != "manual"
                            else "FACT_USER_SUPPLIED_UNVERIFIED"
                        ),
                    )
                )
            brief_projects.append(
                BriefProject(
                    project_id=pid,
                    name=_safe_text(name, 200),
                    source_type="manual" if proj.get("source_type") == "manual" else "github",
                    repository=_safe_text(proj.get("repository") or "", 200),
                    source_commit=str(proj.get("source_commit") or "")[:120],
                    project_snapshot_id=str(proj.get("project_snapshot_id") or "")[:120],
                    summary=_safe_text(proj.get("summary") or "", 2000),
                    contribution_statement=_safe_text(proj.get("contribution") or "", 4000),
                    claims=claims,
                    source_label=(
                        "FACT_CANDIDATE_CONFIRMED"
                        if any(c.confirmed for c in claims) and proj.get("source_type") != "manual"
                        else "FACT_USER_SUPPLIED_UNVERIFIED"
                    ),
                )
            )
        if resume_material and not any(
            p.project_snapshot_id == resume_material.get("project_snapshot_id")
            for p in brief_projects
        ):
            r_name = (
                resume_material.get("project_name")
                or (resume_material.get("experience") or {}).get("name")
                or resume_material.get("source_repository")
                or resume_material.get("material_id", "selected_resume_project")
            )
            r_claims = [
                BriefClaim(
                    claim_id=str(c.get("claim_id") or digest(c, "claim_")),
                    project_id=str(resume_material.get("material_id") or "resume_material"),
                    project_name=_safe_text(r_name, 200),
                    pillar=_safe_text(c.get("pillar") or "", 100),
                    text=_safe_text(c.get("text") or "", 500),
                    boundary=_safe_text(c.get("boundary") or "", 300),
                    risk=_safe_text(c.get("risk") or "", 300),
                    evidence_ids=list(c.get("evidence_ids") or []),
                    confirmed=c.get("personal_contribution") == "confirmed",
                    source_label=(
                        "FACT_CANDIDATE_CONFIRMED"
                        if c.get("personal_contribution") == "confirmed"
                        and resume_material.get("source_type") != "manual"
                        else "FACT_USER_SUPPLIED_UNVERIFIED"
                    ),
                )
                for c in resume_material.get("claims") or []
            ]
            brief_projects.insert(
                0,
                BriefProject(
                    project_id=str(resume_material.get("material_id") or "resume_material"),
                    name=_safe_text(r_name, 200),
                    source_type="manual" if resume_material.get("source_type") == "manual" else "github",
                    repository=_safe_text(resume_material.get("source_repository") or "", 200),
                    source_commit=str(resume_material.get("source_commit") or "")[:120],
                    project_snapshot_id=str(resume_material.get("project_snapshot_id") or "")[:120],
                    summary=_safe_text(resume_material.get("project_overview") or "", 2000),
                    contribution_statement=_safe_text(resume_material.get("contribution_statement") or "", 4000),
                    claims=r_claims,
                    source_label=(
                        "FACT_CANDIDATE_CONFIRMED"
                        if resume_material.get("source_type") != "manual"
                        else "FACT_USER_SUPPLIED_UNVERIFIED"
                    ),
                ),
            )
        if not brief_projects:
            warnings.append("当前未关联项目核验记录，场内将无法触发源码细节对比。")
        return brief_projects, warnings

    def _bind_knowledge(
        self,
        requested_snapshot_ids: list[str],
        projects: list[BriefProject],
    ) -> tuple[list[str], list[str]]:
        if self.knowledge is None:
            if requested_snapshot_ids:
                return [], ["项目知识库服务未启用，已忽略指定的知识快照。"]
            return [], []

        warnings: list[str] = []
        available_sources = self.knowledge.all_sources()
        by_project: dict[str, dict[str, Any]] = {}
        for src in available_sources:
            snap = src.get("snapshot_id")
            if not snap:
                continue
            for pid in src.get("project_ids") or []:
                by_project[pid] = src

        bound_ids: list[str] = list(requested_snapshot_ids)
        for proj in projects:
            if not proj.knowledge_snapshot_id and proj.project_id in by_project:
                proj.knowledge_snapshot_id = by_project[proj.project_id]["snapshot_id"]
            if proj.knowledge_snapshot_id and proj.knowledge_snapshot_id not in bound_ids:
                bound_ids.append(proj.knowledge_snapshot_id)

        verified_ids: list[str] = []
        proj_by_snap = {p.knowledge_snapshot_id: p for p in projects if p.knowledge_snapshot_id}
        for snap_id in bound_ids:
            try:
                ctx = self.knowledge.context(snap_id)
            except (NotFoundError, ConflictError):
                warnings.append(f"知识库快照 {snap_id} 尚未就绪或不存在，已跳过该快照检索绑定。")
                continue
            verified_ids.append(snap_id)
            cov = ctx.get("coverage") or {}
            kinds = ["source_text"]
            if cov.get("document_units", 0) > 0:
                kinds.append("document_text")
            target = proj_by_snap.get(snap_id)
            if target is not None:
                target.available_source_kinds = ["user_supplied"] if target.source_type == "manual" else kinds
                target.coverage_complete = bool(cov.get("complete"))
                target.coverage_status = "ready" if cov.get("complete") else "partial"
                target.has_ocr_units = bool(cov.get("document_ocr_units", 0) > 0)
                if target.has_ocr_units:
                    warnings.append(f"项目「{target.name}」包含 OCR 提取文档，场内引用时将标注待核对。")
        return verified_ids, warnings

    def _detect_source_conflicts(
        self,
        resume_version: dict[str, Any] | None,
        projects: list[BriefProject],
        experiences: list[BriefExperience],
    ) -> list[SourceConflict]:
        """按「选定简历版本 > 已确认项目材料 > 个人资料基础字段」检测同项目口径冲突。"""
        conflicts: list[SourceConflict] = []
        exp_by_name = {
            _normalize_name(exp.title.split("·")[0]): exp
            for exp in experiences
            if exp.kind in {"project", "internship", "work"} and exp.title
        }
        resume_claims_by_proj: dict[str, list[str]] = {}
        if resume_version:
            for proj in projects:
                key = _normalize_name(proj.name)
                texts = [c.text for c in proj.claims if c.confirmed]
                if texts:
                    resume_claims_by_proj[key] = texts

        for proj in projects:
            norm = _normalize_name(proj.name)
            if not norm:
                continue
            primary_label = "选定简历版本" if norm in resume_claims_by_proj else "已确认项目材料"
            primary_text = " ".join(resume_claims_by_proj.get(norm) or [c.text for c in proj.claims] or [proj.summary])
            primary_metrics = _extract_metrics(primary_text)
            exp = exp_by_name.get(norm)
            if exp is None:
                continue
            exp_metrics = _extract_metrics(exp.summary)
            if primary_metrics and exp_metrics and primary_metrics != exp_metrics:
                conflicts.append(
                    SourceConflict(
                        project_name=proj.name,
                        primary_source=primary_label,
                        secondary_source="个人资料基础字段",
                        reason="metric_mismatch",
                        detail=(
                            f"{primary_label}中的量化指标 {sorted(primary_metrics)} 与"
                            f"个人资料基础字段 {sorted(exp_metrics)} 不一致，将以{primary_label}为主口径。"
                        ),
                    )
                )
        return conflicts

    def _resolve_job_and_external_refs(
        self, request: StartComprehensiveInterview
    ) -> tuple[JobContextInput, bool, list[ExternalRefItem], list[str]]:
        warnings: list[str] = []
        base = request.job_snapshot
        company = _safe_text(base.company if base else "", 200)
        role = _safe_text(base.role if base else "", 200)
        jd_raw = request.jd_text.strip() or (base.jd.strip() if base else "")
        jd = _safe_text(jd_raw, 20000)
        job = JobContextInput(
            job_id=request.job_id or (base.job_id if base else None),
            company=company,
            role=role,
            jd=jd,
            risk_signals=[_safe_text(s, 300) for s in (base.risk_signals if base else [])],
            mandatory_conditions=[_safe_text(s, 300) for s in (base.mandatory_conditions if base else [])],
        )
        generic_role = not bool(company or role or jd)
        if generic_role:
            warnings.append("未提供目标岗位与 JD，本轮将作为通用岗位模拟，不使用其他公司面经。")

        refs: list[ExternalRefItem] = []
        for item in request.external_materials:
            if generic_role and item.scope == "similar_role_other_company":
                warnings.append(f"通用岗位模拟已过滤别家同类面经「{item.title or item.ref_id}」。")
                continue
            refs.append(
                ExternalRefItem(
                    ref_id=item.ref_id,
                    kind=item.kind,
                    scope=item.scope,
                    title=_safe_text(item.title, 300),
                    body=_safe_text(item.body, 8000),
                    source_url=str(item.source_url or "")[:1000],
                )
            )
        if request.note_ids:
            if self.notes is None:
                warnings.append("面经订阅服务未启用，已跳过收藏面经读取。")
            else:
                for nid in request.note_ids:
                    try:
                        note = self.notes.note(nid)
                    except NotFoundError:
                        warnings.append(f"未找到收藏面经 {nid}，已忽略。")
                        continue
                    refs.append(
                        ExternalRefItem(
                            ref_id=nid,
                            kind="xhs_note",
                            scope="company_jingyan" if company else "similar_role_other_company",
                            title=_safe_text(note.get("title") or nid, 300),
                            body=_safe_text(note.get("content") or "", 8000),
                            source_url=str(note.get("source_url") or "")[:1000],
                        )
                    )
        return job, generic_role, refs, warnings

    def _resolve_history_agenda(
        self,
        projects: list[BriefProject],
        previous_session_id: str | None,
    ) -> list[LoopAgendaItem]:
        agenda: list[LoopAgendaItem] = []
        seen: set[str] = set()
        if previous_session_id:
            try:
                prev_debrief = self.records.get("ci_debrief", previous_session_id)
                for task in prev_debrief.get("improvement_tasks") or []:
                    if task.get("completed"):
                        continue
                    aid = str(task.get("task_id") or digest(task, "ag_"))
                    if aid not in seen:
                        seen.add(aid)
                        agenda.append(
                            LoopAgendaItem(
                                agenda_id=aid,
                                origin_session_id=previous_session_id,
                                priority="high",
                                topic=_safe_text(task.get("retest_prompt") or task.get("action") or "", 500),
                                reason=f"Mock Loop 上一轮未闭环补强项（{task.get('gap_type', 'general')}）",
                                claim_id=str(task.get("claim_id") or "")[:120],
                            )
                        )
                for flag in prev_debrief.get("red_flags_and_signals") or []:
                    if flag.get("severity") != "red_flag":
                        continue
                    aid = digest({"prev": previous_session_id, "flag": flag}, "ag_")
                    if aid not in seen:
                        seen.add(aid)
                        agenda.append(
                            LoopAgendaItem(
                                agenda_id=aid,
                                origin_session_id=previous_session_id,
                                priority="high",
                                topic=_safe_text(flag.get("summary") or "", 500),
                                reason=f"Mock Loop 上一轮红线复核（{flag.get('category', 'risk')}）",
                            )
                        )
            except NotFoundError:
                pass

        for proj in projects:
            for claim in proj.claims:
                for row in self.repo.store.history(self.repo.owner, claim.claim_id, limit=5):
                    recap = row.get("recap")
                    if not recap:
                        continue
                    sid = row["session"]["session_id"]
                    for task in recap["payload"].get("improvement_tasks") or []:
                        tid = digest({"sid": sid, "task": task}, "ag_")
                        if tid in seen:
                            continue
                        seen.add(tid)
                        retest_info = task.get("retest") if isinstance(task.get("retest"), dict) else {}
                        agenda.append(
                            LoopAgendaItem(
                                agenda_id=tid,
                                origin_session_id=sid,
                                priority="normal",
                                topic=_safe_text(retest_info.get("prompt") or task.get("action") or "", 500),
                                reason=f"历史核验复盘待补强（{task.get('gap_type', 'understanding')}）",
                                claim_id=claim.claim_id,
                            )
                        )
                        if len(agenda) >= 10:
                            return agenda
        return agenda[:10]

    def assemble(self, request: StartComprehensiveInterview) -> InterviewBrief:
        """确定性装配并冻结综合模拟面试简报；若 session_id 已存在则校验不可变性。"""
        session_id = request.session_id or ("ci_" + uuid.uuid4().hex[:20])
        try:
            existing = self.records.get("ci_brief", session_id)
        except NotFoundError:
            existing = None

        resume_version, resume_material = self._resolve_resume_version(request.resume_version_id)
        raw_profile = request.profile_snapshot
        if raw_profile is None and resume_version is not None:
            raw_profile = resume_version.get("profile_snapshot")
        safe_profile = self._safe_profile_fields(raw_profile)
        experiences, skills, candidate_summary = self._extract_experiences(safe_profile)

        projects, proj_warnings = self._resolve_projects(
            request.project_ids, resume_version, resume_material
        )
        bound_snaps, kb_warnings = self._bind_knowledge(request.knowledge_snapshot_ids, projects)
        conflicts = self._detect_source_conflicts(resume_version, projects, experiences)
        job, generic_role, external_refs, job_warnings = self._resolve_job_and_external_refs(request)
        history_agenda = self._resolve_history_agenda(projects, request.previous_session_id)

        has_experiences = any(e.kind in {"internship", "work", "project"} for e in experiences)
        has_projects = bool(projects)
        has_project_evidence = has_experiences or has_projects
        warnings = proj_warnings + kb_warnings + job_warnings

        if not has_project_evidence:
            if request.cold_start_mode == "strict":
                raise ValueError("请先在个人资料或经历库中填写至少一段实习或项目，或开启基础热身模式。")
            resume_binding = "warmup_only"
            warnings.append("当前无个人实习或项目材料，已进入基础能力与行为热身模式，不编造项目经历。")
        elif resume_version is not None:
            resume_binding = "immutable_version"
        else:
            resume_binding = "profile_fallback"

        markdown_excerpt = ""
        if resume_version and resume_version.get("markdown"):
            markdown_excerpt = _safe_text(resume_version["markdown"], 8000)

        brief_core = {
            "session_id": session_id,
            "role_family": request.role_family,
            "round": request.round,
            "duration_minutes": request.duration_minutes,
            "loop_id": request.loop_id,
            "previous_session_id": request.previous_session_id,
            "resume_version_id": request.resume_version_id,
            "resume_binding": resume_binding,
            "resume_markdown_excerpt": markdown_excerpt,
            "has_project_evidence": has_project_evidence,
            "generic_role": generic_role,
            "job": job.model_dump(),
            "candidate_summary": candidate_summary,
            "skills": skills,
            "experiences": [e.model_dump() for e in experiences],
            "projects": [p.model_dump() for p in projects],
            "knowledge_snapshot_ids": bound_snaps,
            "external_references": [r.model_dump() for r in external_refs],
            "source_conflicts": [c.model_dump() for c in conflicts],
            "history_agenda": [a.model_dump() for a in history_agenda],
            "warnings": warnings,
        }
        brief_id = digest(brief_core, "brief_")
        if existing is not None:
            if existing.get("brief_id") != brief_id:
                raise ConflictError("Comprehensive interview brief is immutable")
            return InterviewBrief.model_validate(existing)
        brief = InterviewBrief.model_validate(
            {**brief_core, "brief_id": brief_id, "created_at": _utc_now()}
        )
        self.records.put("ci_brief", session_id, brief.model_dump())
        return brief
