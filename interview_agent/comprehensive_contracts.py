"""综合模拟面试服务的严格契约模型与阶段数据结构（v1.1）。"""

from typing import Any, Literal
from pydantic import Field, field_validator, model_validator

from .models import StrictModel


SourceLabel = Literal[
    "FACT_CANDIDATE_CONFIRMED",
    "FACT_USER_SUPPLIED_UNVERIFIED",
    "REF_COMPANY_OR_JINGYAN",
    "EVIDENCE_SESSION_ANSWER",
]
RoleFamily = Literal["engineering", "algorithm", "product_biz", "general"]
InterviewRound = Literal["first", "second", "manager", "hr", "comprehensive"]
DurationMinutes = Literal[20, 30, 45, 60]
InputChannel = Literal["text", "asr_transcript"]
TurnCommand = Literal[
    "pause",
    "resume",
    "skip",
    "force_skip",
    "request_hint",
    "open_book",
    "ai_assisted",
    "clarify_case",
    "correct_contribution",
    "correct_version",
    "finish",
    "early_terminate",
    "retry",
]
ControlCommandsWithoutText = frozenset(
    {
        "pause",
        "resume",
        "skip",
        "force_skip",
        "request_hint",
        "open_book",
        "ai_assisted",
        "finish",
        "early_terminate",
        "retry",
    }
)
ExternalRefScope = Literal[
    "company_official",
    "company_jingyan",
    "similar_role_other_company",
    "web_supplement",
]

IdentifierStr = str
BoundedText = str


class JobContextInput(StrictModel):
    """目标岗位快照输入。"""

    job_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    jd: str = Field(default="", max_length=20000)
    risk_signals: list[str] = Field(default_factory=list, max_length=20)
    mandatory_conditions: list[str] = Field(default_factory=list, max_length=20)


class ExternalReferenceInput(StrictModel):
    """本地持续维护的外部面经或岗位知识条目。"""

    ref_id: str = Field(min_length=1, max_length=120)
    kind: Literal["jingyan", "knowledge"] = "jingyan"
    scope: ExternalRefScope = "company_jingyan"
    company: str = Field(default="", max_length=200)
    role: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    source_url: str = Field(default="", max_length=1000)


class StartComprehensiveInterview(StrictModel):
    """发起综合模拟面试的请求契约。"""

    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    role_family: RoleFamily = "engineering"
    round: InterviewRound = "comprehensive"
    duration_minutes: DurationMinutes = 30
    job_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    job_snapshot: JobContextInput | None = None
    jd_text: str = Field(default="", max_length=20000)
    resume_version_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    project_ids: list[str] = Field(default_factory=list, max_length=20)
    knowledge_snapshot_ids: list[str] = Field(default_factory=list, max_length=20)
    note_ids: list[str] = Field(default_factory=list, max_length=30)
    external_materials: list[ExternalReferenceInput] = Field(default_factory=list, max_length=30)
    profile_snapshot: dict[str, Any] | None = None
    loop_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    previous_session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")
    cold_start_mode: Literal["strict", "warmup_if_empty"] = "strict"

    @field_validator("project_ids", "knowledge_snapshot_ids", "note_ids")
    @classmethod
    def valid_id_list(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = item.strip()
            if not text or len(text) > 120:
                raise ValueError("列表中的标识格式无效")
            if text not in seen:
                seen.add(text)
                cleaned.append(text)
        return cleaned


class ComprehensiveTurn(StrictModel):
    """综合模拟面试单轮用户提交输入。"""

    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    text: str = Field(default="", max_length=12000)
    command: TurnCommand | None = None
    input_channel: InputChannel = "text"

    @model_validator(mode="after")
    def validate_text_or_command(self) -> "ComprehensiveTurn":
        if self.command in ControlCommandsWithoutText:
            return self
        if not self.text.strip():
            raise ValueError("请填写回答内容或指定有效控制指令")
        return self


class ComprehensiveStreamRequest(StrictModel):
    """SSE 流式获取考官下一句的请求契约。"""

    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    intent: Literal["first", "next", "retry"]


class ComprehensiveDrillRequest(StrictModel):
    """复盘后单缺口重练请求契约。"""

    event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    question_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(default="", max_length=12000)


class BriefClaim(StrictModel):
    """冻结简报中的单条候选人项目或经历陈述。"""

    claim_id: str = Field(min_length=1, max_length=120)
    project_id: str = Field(default="", max_length=120)
    project_name: str = Field(default="", max_length=200)
    pillar: str = Field(default="", max_length=100)
    text: str = Field(min_length=1, max_length=500)
    boundary: str = Field(default="", max_length=300)
    risk: str = Field(default="", max_length=300)
    evidence_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False
    source_label: SourceLabel = "FACT_USER_SUPPLIED_UNVERIFIED"


class BriefProject(StrictModel):
    """冻结简报中的项目与知识库覆盖摘要。"""

    project_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["github", "manual"] = "github"
    repository: str = Field(default="", max_length=200)
    source_commit: str = Field(default="", max_length=120)
    project_snapshot_id: str = Field(default="", max_length=120)
    knowledge_snapshot_id: str = Field(default="", max_length=120)
    available_source_kinds: list[str] = Field(default_factory=list)
    coverage_status: str = Field(default="none", max_length=60)
    coverage_complete: bool = False
    has_ocr_units: bool = False
    summary: str = Field(default="", max_length=2000)
    contribution_statement: str = Field(default="", max_length=4000)
    claims: list[BriefClaim] = Field(default_factory=list)
    source_label: SourceLabel = "FACT_USER_SUPPLIED_UNVERIFIED"


class BriefExperience(StrictModel):
    """脱敏后的个人履历条目。"""

    kind: Literal["internship", "work", "project", "education"]
    title: str = Field(min_length=1, max_length=300)
    period: str = Field(default="", max_length=100)
    summary: str = Field(default="", max_length=2000)
    source_label: SourceLabel = "FACT_USER_SUPPLIED_UNVERIFIED"


class SourceConflict(StrictModel):
    """同一项目在简历版本、项目档案与个人资料间的口径差异。"""

    project_name: str = Field(min_length=1, max_length=200)
    primary_source: str = Field(min_length=1, max_length=80)
    secondary_source: str = Field(min_length=1, max_length=80)
    reason: Literal["metric_mismatch", "role_or_summary_mismatch"]
    detail: str = Field(min_length=1, max_length=600)


class ExternalRefItem(StrictModel):
    """冻结的外部岗位、面经或收藏笔记条目。"""

    ref_id: str = Field(min_length=1, max_length=120)
    kind: Literal["jingyan", "knowledge", "xhs_note"]
    scope: ExternalRefScope
    title: str = Field(default="", max_length=300)
    body: str = Field(min_length=1, max_length=8000)
    source_url: str = Field(default="", max_length=1000)
    source_label: Literal["REF_COMPANY_OR_JINGYAN"] = "REF_COMPANY_OR_JINGYAN"


class LoopAgendaItem(StrictModel):
    """来自历史复盘或 Mock Loop 上一轮的待复测议题。"""

    agenda_id: str = Field(min_length=1, max_length=120)
    origin_session_id: str = Field(min_length=1, max_length=120)
    priority: Literal["high", "normal"] = "normal"
    topic: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    claim_id: str = Field(default="", max_length=120)


class InterviewBrief(StrictModel):
    """开场前冻结的综合模拟面试双侧全量快照（不可变）。"""

    schema_version: Literal[1] = 1
    brief_id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    created_at: str = Field(min_length=1, max_length=80)
    role_family: RoleFamily
    round: InterviewRound
    duration_minutes: DurationMinutes
    loop_id: str | None = None
    previous_session_id: str | None = None
    resume_version_id: str | None = None
    resume_binding: Literal["immutable_version", "profile_fallback", "warmup_only"]
    resume_markdown_excerpt: str = Field(default="", max_length=8000)
    has_project_evidence: bool = True
    generic_role: bool = False
    job: JobContextInput
    candidate_summary: str = Field(default="", max_length=2000)
    skills: list[str] = Field(default_factory=list)
    experiences: list[BriefExperience] = Field(default_factory=list)
    projects: list[BriefProject] = Field(default_factory=list)
    knowledge_snapshot_ids: list[str] = Field(default_factory=list)
    external_references: list[ExternalRefItem] = Field(default_factory=list)
    source_conflicts: list[SourceConflict] = Field(default_factory=list)
    history_agenda: list[LoopAgendaItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BlueprintQuestion(StrictModel):
    """服务端内部考纲主问题（绝不下发前端）。"""

    question_id: str = Field(min_length=1, max_length=80)
    section_id: str = Field(min_length=1, max_length=80)
    origin_type: Literal[
        "self_intro_hook",
        "fundamental_probe",
        "coding_or_debug",
        "resume_deep_dive",
        "repo_verification",
        "jd_scenario",
        "case_study",
        "pressure_challenge",
        "history_retest",
        "candidate_qa",
        "overflow_backup",
    ]
    focus: str = Field(min_length=1, max_length=300)
    claim_id: str = Field(default="", max_length=120)
    knowledge_snapshot_id: str = Field(default="", max_length=120)
    preferred_source_kind: Literal["source_text", "document_text", "user_supplied"] | None = None
    is_overflow: bool = False


class BlueprintSection(StrictModel):
    """服务端内部考纲板块配比。"""

    section_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    weight_percent: int = Field(ge=5, le=80)
    max_followups: int = Field(default=2, ge=0, le=3)
    requires_clarify: bool = False
    requires_code_box: bool = False


class Blueprint(StrictModel):
    """服务端内部动态考纲。"""

    brief_id: str = Field(min_length=1, max_length=120)
    sections: list[BlueprintSection] = Field(min_length=1, max_length=8)
    main_questions: list[BlueprintQuestion] = Field(min_length=1, max_length=12)
    overflow_questions: list[BlueprintQuestion] = Field(default_factory=list, max_length=4)


class BlueprintQuestionFocus(StrictModel):
    question_id: str = Field(min_length=1, max_length=80)
    focus: str = Field(min_length=1, max_length=300)


class BlueprintDraft(StrictModel):
    """模型定制考察点；完整考纲及证据绑定由服务端保留。"""

    questions: list[BlueprintQuestionFocus] = Field(min_length=1, max_length=16)


class SilentRetrievalQuery(StrictModel):
    """后台按需知识库检索指令。"""

    should_retrieve: bool = False
    queries: list[str] = Field(default_factory=list, max_length=3)
    source_kind: Literal["source_text", "document_text", "user_supplied"] | None = None


class NextMoveDecision(StrictModel):
    """考官在回答后的下一步路由与追问/转场决策。"""

    move: Literal[
        "follow_up",
        "scaffold",
        "challenge",
        "advance_topic",
        "use_overflow",
        "candidate_qa",
        "ready_to_end",
    ]
    detected_gaps: list[
        Literal[
            "vague_scenario",
            "we_only",
            "no_metric",
            "no_tradeoff",
            "success_only",
            "contradiction",
        ]
    ] = Field(default_factory=list)
    used_scaffold: bool = False
    derivation_signal: Literal["none", "guided_success", "guided_failed"] = "none"
    oral_new_fact: str = Field(default="", max_length=500)
    interviewer_prompt: str = Field(min_length=1, max_length=2000)

    @field_validator("derivation_signal", mode="before")
    @classmethod
    def _normalize_derivation(cls, value: Any) -> Any:
        if value is None:
            return "none"
        text = str(value).strip().lower()
        if text in {"", "null", "na", "n/a", "untriggered", "false", "no", "not_triggered"}:
            return "none"
        return text

    @field_validator("oral_new_fact", mode="before")
    @classmethod
    def _normalize_oral_fact(cls, value: Any) -> str:
        return "" if value is None else str(value)[:500]


class DimensionScore(StrictModel):
    """带原文直接证据的维度评分。"""

    dimension_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=120)
    weight: float = Field(gt=0, le=1)
    score: int | None = Field(default=None, ge=1, le=5)
    evidence_insufficient: bool = False
    evidence_quotes: list[str] = Field(default_factory=list)
    missing_evidence: str = Field(default="", max_length=400)
    comment: str = Field(min_length=1, max_length=800)

    @field_validator("score", mode="before")
    @classmethod
    def _normalize_zero_score(cls, value: Any) -> Any:
        if value == 0 or value == "":
            return None
        return value


class RedFlagItem(StrictModel):
    """面评红线或加分信号。"""

    severity: Literal["red_flag", "hire_bar_signal"]
    category: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=500)
    evidence_quote: str = Field(default="", max_length=500)

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        if text in {"red_flag", "high", "medium", "warning", "critical", "flag", "risk"}:
            return "red_flag"
        if text in {"hire_bar_signal", "low", "positive", "signal", "strength", "bonus", "good"}:
            return "hire_bar_signal"
        return value


class ResumeAlignmentDraft(StrictModel):
    """绑定 claim_id 与知识库引用的简历对齐草稿（不自动改写简历）。"""

    claim_id: str = Field(default="", max_length=120)
    action: Literal[
        "keep_verified",
        "enrich_highlight",
        "needs_evidence_or_downgrade",
        "resolve_conflict",
    ]
    rationale: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(default_factory=list)
    answer_quote: str = Field(default="", max_length=500)
    confirmation_status: Literal["pending_user_confirmation"] = "pending_user_confirmation"

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, value: Any) -> Any:
        text = str(value or "").strip().lower()
        aliases = {
            "keep": "keep_verified",
            "verified": "keep_verified",
            "enrich": "enrich_highlight",
            "highlight": "enrich_highlight",
            "add": "enrich_highlight",
            "downgrade": "needs_evidence_or_downgrade",
            "needs_evidence": "needs_evidence_or_downgrade",
            "verify": "needs_evidence_or_downgrade",
            "conflict": "resolve_conflict",
            "resolve": "resolve_conflict",
        }
        return aliases.get(text, value)


class ImprovementTask(StrictModel):
    """带完成条件与变式复测的跨轮补强任务。"""

    task_id: str = Field(min_length=1, max_length=120)
    claim_id: str = Field(default="", max_length=120)
    gap_type: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=500)
    completion_criteria: str = Field(min_length=1, max_length=400)
    retest_prompt: str = Field(min_length=1, max_length=400)
    completed: bool = False


class ComprehensiveDebrief(StrictModel):
    """综合模拟面试结束后的不可变双轨复盘报告。"""

    session_id: str = Field(min_length=1, max_length=120)
    brief_id: str = Field(min_length=1, max_length=120)
    readiness: Literal["ready", "almost_ready", "needs_practice", "insufficient_evidence"]
    readiness_reason: str = Field(min_length=1, max_length=400)
    early_terminated: bool = False
    not_an_offer: Literal[True] = True
    dimensions: list[DimensionScore] = Field(min_length=1, max_length=6)
    red_flags_and_signals: list[RedFlagItem] = Field(default_factory=list)
    top_priority_fix: str = Field(min_length=1, max_length=500)
    qa_review_summary: str = Field(default="", max_length=600)
    resume_suggestions: list[ResumeAlignmentDraft] = Field(default_factory=list)
    improvement_tasks: list[ImprovementTask] = Field(default_factory=list)
    drill_question_ids: list[str] = Field(default_factory=list, max_length=3)
    applied_to_resume: Literal[False] = False


class DrillFeedback(StrictModel):
    """单缺口重练（Drill）单次反馈。"""

    question_id: str = Field(min_length=1, max_length=100)
    attempt: int = Field(ge=1)
    switched_perspective: bool = False
    target_gap: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=1000)
    added_evidence: str = Field(default="", max_length=500)
    remaining_gap: str = Field(default="", max_length=500)
    recast_example: str = Field(default="", max_length=1500)
