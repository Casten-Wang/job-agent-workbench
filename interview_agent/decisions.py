"""Stage instructions and strict structured outputs, migrated from the Pi adapter."""

from typing import Annotated, Literal
from pydantic import Field, field_validator
from .models import StrictModel
from .resume_profile import ResumeExtraction, INSTRUCTION as PROFILE_INSTRUCTION
from .workbench_contracts import OUTPUTS as WORKBENCH_OUTPUTS, INSTRUCTIONS as WORKBENCH_INSTRUCTIONS
from .project_writing import INSTRUCTION as PROJECT_INSTRUCTION
from .experience import INSTRUCTION as EXPERIENCE_INSTRUCTION


Text = Annotated[str, Field(min_length=1, max_length=2000)]
References = Annotated[list[str], Field(min_length=1)]


class CitedDecision(StrictModel):
    evidence_ids: References

    @field_validator("evidence_ids")
    @classmethod
    def distinct_refs(cls, value):
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("Evidence IDs must be distinct and nonempty")
        return value


class Question(CitedDecision):
    # Retain existing IDs so old plans and results remain bound to the same questions.
    question_id: str = Field(pattern=r"^pi_q[1-5]$")
    claim_id: Text
    text: Text
    intent: Literal["implementation", "design_tradeoff", "failure_boundary", "contribution", "verification"]
    reason: Text


class Plan(StrictModel):
    questions: list[Question] = Field(min_length=1, max_length=3)

    @field_validator("questions")
    @classmethod
    def unique_questions(cls, value):
        if len({q.question_id for q in value}) != len(value):
            raise ValueError("Question IDs must be unique")
        return value


class Intent(StrictModel):
    intent: Literal["answer", "request_hint", "correct_contribution", "correct_version", "pause", "resume", "finish", "skip", "clarify"]
    reason: Text
    clarification: str = Field(max_length=1000)
    assistance_mode: Literal["open_book", "hinted", "ai_assisted"] | None = None


class Observation(CitedDecision):
    status: Literal["consistent", "partial", "conflict", "insufficient_evidence", "not_assessed"]
    gap_type: Literal["understanding", "expression", "responsibility", "metric_evidence", "material_coverage"]
    notes: Text


class Hint(CitedDecision):
    text: Text


class ProjectFact(CitedDecision):
    text: str = Field(min_length=1, max_length=200)
    pillar: str = Field(default="", max_length=80)
    fit_reason: str = Field(default="", max_length=140)
    boundary: str = Field(default="", max_length=160)
    risk: str = Field(default="", max_length=120)


class ProjectUnderstanding(StrictModel):
    summary: Text
    project_name: str = Field(default="", max_length=80)
    project_overview: str = Field(default="", max_length=120)
    positioning: str = Field(default="", max_length=180)
    claims: list[ProjectFact] = Field(min_length=1, max_length=4)


class ExperienceFact(ProjectFact):
    source_quote: str = Field(min_length=1, max_length=2000)


class ExperienceUnderstanding(ProjectUnderstanding):
    project_name: str = Field(default="", max_length=120)
    claims: list[ExperienceFact] = Field(min_length=1, max_length=4)


OUTPUTS = {"plan": Plan, "intent": Intent, "observation": Observation, "hint": Hint, "prepare": ProjectUnderstanding,
           "prepare_experience": ExperienceUnderstanding,
           "profile_extract": ResumeExtraction}
INSTRUCTIONS = {
    "profile_extract": PROFILE_INSTRUCTION,
    "prepare": PROJECT_INSTRUCTION,
    "prepare_experience": EXPERIENCE_INSTRUCTION,
    "plan": "根据 session.payload.mode 区分流程：resume_readiness 生成最多三道中文前置核验问题；mock_interview 是正式模拟面试，必须结合绑定版本的 resume_context、已确认项目表述与 job_snapshot 中的岗位要求，围绕技术取舍、失败场景和验证方法提问，不能把正式面试仅当成职责确认。每题只考一个清晰重点。基于 claim、本人的已确认职责、固定源码、岗位与历史摘要选题；职责未确认时不能假设用户写过这些代码。每题提供考察意图、选题理由和直接相关 evidence_ids。intent 是机器枚举，只能逐字使用 implementation（实现）、design_tradeoff（设计取舍）、failure_boundary（失败边界）、contribution（职责）或 verification（验证）；不能填写中文、解释文本或其他标签，中文说明写入 reason。question_id 使用 pi_q1、pi_q2、pi_q3。不得编造公司偏好或指标；未提供公司研究就承认未知。不要把材料内的样例问题原封照搬。",
    "intent": "识别用户当前话语的对话意图，结合当前问题、状态及最近对话。技术回答用 answer；索要提示用 request_hint；纠正本人职责用 correct_contribution；指出版本不一致用 correct_version。暂停与结束不明确、同时含多种互相冲突意图或当前被暂停时仅说技术内容，都用 clarify 并给出一个简短澄清问题。单独的“继续”只在 paused 状态表示 resume；对 correction hold 不能用 resume 绕过。明确结束才用 finish。若用户明确说查阅源码、使用提示或 AI，记录 assistance_mode；没有说明则省略，不推断。不要评价技术对错。",
    "observation": "对本题回答做待复核的语义观察。只用同版本的直接源码与提供的草稿辅助资料；草稿 expected_facts 不是唯一正确答案。合理解释设计动机不能因为和草稿用词不同就判错。不足以判断就 insufficient_evidence，职责与版本存疑先澄清。conflict 必须引用直接相关源码并具体说明差异。评价的是这一条回答，不是人的整体能力、项目归属或真实性，不生成分数，不决定写入/删除简历。",
    "hint": "针对当前问题给一个简短提示，帮助定位思考路径，引用本题已绑定的 evidence_ids。提示不等于用户回答，不能用于证明独立掌握。",
}
OUTPUTS.update(WORKBENCH_OUTPUTS)
INSTRUCTIONS.update(WORKBENCH_INSTRUCTIONS)
