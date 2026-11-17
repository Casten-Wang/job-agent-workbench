#!/usr/bin/env python3
"""Text mock-interview planning, streaming questions, debrief, and drill.

Planning builds an internal InterviewPlan. Streaming asks one interviewer
question at a time. Debrief and drill are non-streaming JSON calls. Callers
inject `complete` / `stream` so tests can use a fake model without touching
a paid API. This module does not fall back to canned stems or write a
tailored resume.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Callable

_TOOLS_DIR = Path(__file__).resolve().parent
PROMPT_PATH = _TOOLS_DIR / "prompts" / "interview-plan-system.txt"
CHAT_PROMPT_PATH = _TOOLS_DIR / "prompts" / "interview-chat-system.txt"
DEBRIEF_PROMPT_PATH = _TOOLS_DIR / "prompts" / "interview-debrief-system.txt"
DRILL_PROMPT_PATH = _TOOLS_DIR / "prompts" / "interview-drill-system.txt"
PLAN_TIMEOUT_SECONDS = 45
CHAT_TIMEOUT_SECONDS = 45
DEBRIEF_TIMEOUT_SECONDS = 60
DRILL_TIMEOUT_SECONDS = 45
MATERIAL_MODEL_LIMIT = 4_000
ROUNDS = ("hr", "business", "tech", "manager")
DURATIONS = (20, 30)
ROUND_LABELS = {
    "hr": "HR",
    "business": "业务专业",
    "tech": "技术口述",
    "manager": "主管",
}
QUESTION_KINDS = ("resume_probe", "business_scenario")
MSG_NO_RESUME = "请先在个人资料里填写实习或项目，再开始面试。"
MSG_ROUND_DURATION = "请选择 HR、业务专业、技术口述或主管，以及 20 或 30 分钟。"
MSG_AI_MISSING = (
    "尚未配置外部 AI，无法开始文字面试。请到内嵌 OfferPilot 配置里填写密钥或模型名；"
    "密钥只保存在本机配置或环境变量中，不会写入代码仓库。"
)
MSG_PLAN_FAILED = (
    "还不能开始：准备本轮提问时外部 AI 暂时不可用或已超时。没有进入这场面试。"
)
MSG_MATERIAL_EMPTY = "请粘贴面经或岗位知识正文"
MSG_EMPTY_ANSWER = "请填写回答"
MSG_QUESTION_INCOMPLETE = "这一问还没说完，请等面试官说完后再回答。"
MSG_TIME_UP = "时长已到，请结束面试。"
MSG_END_LOCKED = "计划问完或时长用完后才能结束。"
MSG_DEBRIEF_UNAVAILABLE = (
    "复盘没有生成：外部 AI 暂时不可用或已超时。回答仍在，可以再点结束。未写入定制简历。"
)
MSG_DRILL_LOCKED = "结束并生成复盘后才能重练。"
MSG_DRILL_ITEM = "请选择要重练的题目。"
MSG_DRILL_UNAVAILABLE = "重练没有生成：外部 AI 暂时不可用或已超时。"
READINESS_LEVELS = ("ready", "almost_ready", "needs_practice", "insufficient_evidence")
CONFIDENCE_LEVELS = ("high", "medium", "low")
EVIDENCE_MISSING = "证据不足"
FILL_REAL_NUMBER = "请补充真实数字"
EVIDENCE_NOTE = "分数只依据本场回答；修改点未写入定制简历；不表示录用"
DRILL_STATUSES = ("debriefed", "drilling")
ADJACENT_PROMPT_PREFIX = "换个角度："
_OFFER_RE = re.compile(r"会被录取|拿到\s*Offer|拿到\s*offer|通过面试|录用结论|\bOffer\b|\boffer\b")
_ARABIC_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_COMPANY_RE = re.compile(r"[A-Za-z][A-Za-z0-9.&-]{1,}|(?:[\u4e00-\u9fff]{2,12}(?:公司|集团|科技))")
MSG_FIRST_FAILED = (
    "面试官第一问没有生成：外部 AI 暂时不可用或已超时。尚未开始这场面试。"
)
MSG_INCOMPLETE = (
    "这一问没有说完：外部 AI 中断或超时。已出现的半句仍保留，标明未完成，不计入本轮进度。"
    "可以重试。你已提交的回答还在。"
)
MSG_INTENT = "请指定 first、next 或 retry。"
MSG_NO_SESSION = "没有进行中的面试。"
MSG_PLAN_DONE = "计划主问题已问完，请结束面试。"
MATERIAL_KINDS = ("jingyan", "knowledge")
STREAM_INTENTS = ("first", "next", "retry")
GAP_VAGUE = "含糊场景"
GAP_WE = "我们"
GAP_NO_NUMBER = "无数字"
GAP_NO_TRADEOFF = "无取舍"
GAP_SUCCESS_ONLY = "只成功"
GAP_CONTRADICTION = "矛盾"
CompleteFn = Callable[[str, str, float], str]
StreamFn = Callable[[str, str, float], Iterator[str]]


class PlanGenerationError(Exception):
    """Planning failed before a session should be written."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class StreamGenerationError(Exception):
    """Question streaming failed; callers must not fall back to canned stems."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class DebriefGenerationError(Exception):
    """Debrief JSON failed; the session must stay ready_to_end."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


class DrillGenerationError(Exception):
    """Drill JSON failed; do not invent a canned recast."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def load_plan_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_chat_system_prompt() -> str:
    return CHAT_PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_debrief_system_prompt() -> str:
    return DEBRIEF_PROMPT_PATH.read_text(encoding="utf-8").strip()


def load_drill_system_prompt() -> str:
    return DRILL_PROMPT_PATH.read_text(encoding="utf-8").strip()


def parse_round(value: Any) -> str:
    text = str(value or "").strip()
    if text not in ROUNDS:
        raise ValueError(MSG_ROUND_DURATION)
    return text


def parse_duration(value: Any) -> int:
    if value in (None, ""):
        return 30
    if isinstance(value, bool) or value not in DURATIONS:
        raise ValueError(MSG_ROUND_DURATION)
    return int(value)


def profile_has_internship_or_project(profile: dict[str, Any] | None) -> bool:
    profile = profile or {}
    for row in profile.get("experiences") or []:
        if isinstance(row, dict) and (row.get("company") or row.get("title") or row.get("summary")):
            return True
    for row in profile.get("projects") or []:
        if isinstance(row, dict) and (row.get("name") or row.get("role") or row.get("summary")):
            return True
    return False


def resume_evidence_text(profile: dict[str, Any] | None) -> str:
    """Internship and project facts only; no phone, email, WeChat, or links."""
    profile = profile or {}
    lines: list[str] = []
    for row in profile.get("experiences") or []:
        if not isinstance(row, dict):
            continue
        head = " · ".join(part for part in (row.get("company"), row.get("title")) if part)
        summary = str(row.get("summary") or "").strip()
        if head or summary:
            lines.append(f"实习/工作：{head}。{summary}".strip())
    for row in profile.get("projects") or []:
        if not isinstance(row, dict):
            continue
        head = " · ".join(part for part in (row.get("name"), row.get("role")) if part)
        summary = str(row.get("summary") or "").strip()
        if head or summary:
            lines.append(f"项目：{head}。{summary}".strip())
    return "\n".join(lines)


def build_rules_text(round_key: str, duration_minutes: int, generic_role: bool) -> str:
    label = ROUND_LABELS[round_key]
    text = f"本场是{label}、{duration_minutes}分钟。一次一问，过程中不点评，结束后复盘。"
    if generic_role:
        text = "本轮是通用岗位模拟。" + text
    return text[:120]


def public_session(session: dict[str, Any]) -> dict[str, Any]:
    """Drop blueprint and other internal planning fields from an API payload."""
    blocked = {
        "blueprint",
        "competencies",
        "evidence_map",
        "main_questions",
        "stem_intent",
        "interview_started_at",
        "current_main_id",
        "followup_count",
        "jd",
        "material_ids",
        "job_id",
        "jingyan_is_not_official",
        "asked_main_ids",
        "pending",
        "question_complete",
        "current_move",
        "current_kind",
        "gap_labels",
        "last_answer",
        "drill_state",
        "debrief_id",
        "debrief_card",
    }
    return {key: value for key, value in session.items() if key not in blocked}


def _parse_plan_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise PlanGenerationError("invalid")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise PlanGenerationError("invalid")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise PlanGenerationError("invalid") from exc
    if not isinstance(value, dict):
        raise PlanGenerationError("invalid")
    return value


def _clean_competencies(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "").strip()
        label = str(item.get("label") or "").strip()
        try:
            weight = float(item.get("weight"))
        except (TypeError, ValueError):
            continue
        if not ident or not label or weight != weight or weight < 0:
            continue
        rows.append({"id": ident, "label": label, "weight": weight})
    return rows


def _clean_evidence_map(raw: Any, resume_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        competency_id = str(item.get("competency_id") or "").strip()
        span = str(item.get("resume_span") or "").strip()
        if not competency_id or not span:
            continue
        if span not in resume_text:
            continue
        rows.append({"competency_id": competency_id, "resume_span": span})
    return rows


def _clean_main_questions(raw: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "").strip()
        kind = str(item.get("kind") or "").strip()
        stem = str(item.get("stem_intent") or "").strip()
        if not ident or kind not in QUESTION_KINDS or not stem:
            continue
        rows.append({"id": ident, "kind": kind, "stem_intent": stem})
    return rows


def _planner_user_payload(
    *,
    round_key: str,
    duration_minutes: int,
    resume_text: str,
    jd_text: str,
    materials: list[dict[str, Any]],
) -> str:
    packed_materials = []
    for item in materials:
        kind = str(item.get("kind") or "")
        body = str(item.get("body") or "")[:MATERIAL_MODEL_LIMIT]
        row: dict[str, Any] = {"kind": kind, "body": body}
        if kind == "jingyan":
            row["jingyan_is_not_official"] = True
        packed_materials.append(row)
    payload = {
        "round": round_key,
        "duration_minutes": duration_minutes,
        "resume": resume_text,
        "jd": jd_text[:MATERIAL_MODEL_LIMIT],
        "materials": packed_materials,
    }
    return json.dumps(payload, ensure_ascii=False)


def plan_interview(
    *,
    round_key: str,
    duration_minutes: int,
    resume_text: str,
    jd_text: str = "",
    materials: list[dict[str, Any]] | None = None,
    complete: CompleteFn,
) -> dict[str, Any]:
    """Call the planning model and return a server-only InterviewPlan."""
    materials = materials or []
    has_materials = bool(jd_text.strip() or materials)
    system_prompt = load_plan_system_prompt()
    user_text = _planner_user_payload(
        round_key=round_key,
        duration_minutes=duration_minutes,
        resume_text=resume_text,
        jd_text=jd_text,
        materials=materials,
    )
    try:
        raw = complete(system_prompt, user_text, PLAN_TIMEOUT_SECONDS)
    except PlanGenerationError:
        raise
    except TimeoutError as exc:
        raise PlanGenerationError("timeout") from exc
    except Exception as exc:
        raise PlanGenerationError("unavailable") from exc
    parsed = _parse_plan_json(raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False))
    questions = _clean_main_questions(parsed.get("main_questions"))
    if not questions:
        raise PlanGenerationError("invalid")
    kinds = {item["kind"] for item in questions}
    if has_materials:
        if "resume_probe" not in kinds or "business_scenario" not in kinds:
            raise PlanGenerationError("invalid")
    elif any(item["kind"] != "resume_probe" for item in questions):
        raise PlanGenerationError("invalid")
    return {
        "competencies": _clean_competencies(parsed.get("competencies")),
        "evidence_map": _clean_evidence_map(parsed.get("evidence_map"), resume_text),
        "main_questions": questions,
    }


_VAGUE_RE = re.compile(r"大概|可能吧|还行|挺好的|差不多|之类|随便|感觉|好像")
_NUMBER_RE = re.compile(r"\d|[零二三四五六七八九十百千万亿两]|百分")
_TRADEOFF_RE = re.compile(r"取舍|权衡|放弃|选择|砍掉|优先|代价|折中")
_SUCCESS_RE = re.compile(r"成功|顺利|达成|拿下")
_FAILURE_RE = re.compile(r"失败|受阻|问题|困难|踩坑|没做成|风险")
_CONTRA_POS_RE = re.compile(r"全部|一直都|都没问题|都很顺利")
_CONTRA_NEG_RE = re.compile(r"但是|不过|然而|其实有问题|其实失败")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).astimezone()


def parse_started_at(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def remaining_seconds(session: dict[str, Any], now: dt.datetime | None = None) -> int:
    duration = int(session.get("duration_minutes") or 30)
    started = parse_started_at(session.get("interview_started_at"))
    if started is None:
        return max(0, duration * 60)
    current = now or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    elapsed = (current - started).total_seconds()
    return max(0, int(duration * 60 - elapsed))


def apply_timing(session: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    session["remaining_seconds"] = remaining_seconds(session, now)
    return session


def detect_answer_gaps(answer: str) -> list[str]:
    text = str(answer or "").strip()
    labels: list[str] = []
    if len(text) < 12 or _VAGUE_RE.search(text):
        labels.append(GAP_VAGUE)
    stripped_we = text.replace("我们", "")
    if "我们" in text and "我" not in stripped_we:
        labels.append(GAP_WE)
    if not _NUMBER_RE.search(text):
        labels.append(GAP_NO_NUMBER)
    if not _TRADEOFF_RE.search(text):
        labels.append(GAP_NO_TRADEOFF)
    if _SUCCESS_RE.search(text) and not _FAILURE_RE.search(text):
        labels.append(GAP_SUCCESS_ONLY)
    if _CONTRA_POS_RE.search(text) and _CONTRA_NEG_RE.search(text):
        labels.append(GAP_CONTRADICTION)
    return labels


def main_questions(session: dict[str, Any]) -> list[dict[str, str]]:
    blueprint = session.get("blueprint") if isinstance(session.get("blueprint"), dict) else {}
    rows = blueprint.get("main_questions") if isinstance(blueprint, dict) else None
    return [row for row in rows or [] if isinstance(row, dict)]


def asked_main_ids(session: dict[str, Any]) -> list[str]:
    rows = session.get("asked_main_ids")
    if not isinstance(rows, list):
        return []
    return [str(item) for item in rows if str(item)]


def session_has_materials(session: dict[str, Any]) -> bool:
    jd = str(session.get("jd") or "").strip()
    material_ids = session.get("material_ids") or []
    return bool(jd or material_ids)


def first_question_decision(session: dict[str, Any]) -> dict[str, Any]:
    questions = main_questions(session)
    if not questions:
        raise StreamGenerationError("invalid")
    item = questions[0]
    return {
        "move": "main",
        "kind": item["kind"],
        "main_id": item["id"],
        "stem_intent": item.get("stem_intent") or "",
        "gap_labels": [],
    }


def _force_missing_kind(session: dict[str, Any], remaining: list[dict[str, str]]) -> dict[str, str]:
    nxt = dict(remaining[0])
    if not session_has_materials(session):
        return nxt
    completed_kinds = {
        str(item.get("kind") or "")
        for item in main_questions(session)
        if str(item.get("id") or "") in set(asked_main_ids(session))
    }
    missing = [kind for kind in QUESTION_KINDS if kind not in completed_kinds]
    if not missing:
        return nxt
    prefer = missing[0]
    found = next((item for item in remaining if item.get("kind") == prefer), None)
    if found:
        return dict(found)
    nxt["kind"] = prefer
    for item in main_questions(session):
        if item.get("id") == nxt["id"]:
            item["kind"] = prefer
            break
    return nxt


def decide_next_move(session: dict[str, Any], last_answer: str) -> dict[str, Any] | None:
    questions = main_questions(session)
    if not questions:
        return None
    current_id = str(session.get("current_main_id") or "")
    followup_count = int(session.get("followup_count") or 0)
    gaps = detect_answer_gaps(last_answer)
    current = next((item for item in questions if item.get("id") == current_id), None)
    if current and followup_count < 3 and gaps:
        return {
            "move": "followup",
            "kind": current.get("kind") or "resume_probe",
            "main_id": current_id,
            "stem_intent": current.get("stem_intent") or "",
            "gap_labels": gaps,
        }
    asked = set(asked_main_ids(session))
    remaining = [item for item in questions if item.get("id") not in asked]
    if not remaining:
        return None
    nxt = _force_missing_kind(session, remaining)
    return {
        "move": "main",
        "kind": nxt.get("kind") or "resume_probe",
        "main_id": nxt["id"],
        "stem_intent": nxt.get("stem_intent") or "",
        "gap_labels": [],
    }


def should_end_after_answer(session: dict[str, Any], answer: str) -> bool:
    questions = main_questions(session)
    asked = set(asked_main_ids(session))
    all_asked = bool(questions) and all(str(item.get("id") or "") in asked for item in questions)
    followup_count = int(session.get("followup_count") or 0)
    more_followup = followup_count < 3 and bool(detect_answer_gaps(answer))
    return all_asked and not more_followup


def awaiting_answer(session: dict[str, Any]) -> bool:
    if not session.get("question_complete"):
        return False
    turns = session.get("turns") or []
    if not turns:
        return False
    last = turns[-1]
    return isinstance(last, dict) and last.get("role") == "interviewer" and not last.get("incomplete")


def last_candidate_answer(session: dict[str, Any]) -> str:
    turns = session.get("turns") or []
    for row in reversed(turns):
        if isinstance(row, dict) and row.get("role") == "candidate":
            return str(row.get("text") or "")
    return str(session.get("last_answer") or "")


def stream_error_message(intent: str, user_status: str) -> str:
    if intent == "first" or user_status == "preparing":
        return MSG_FIRST_FAILED
    return MSG_INCOMPLETE


def chat_user_payload(
    session: dict[str, Any],
    decision: dict[str, Any],
    resume_text: str = "",
    materials: list[dict[str, Any]] | None = None,
) -> str:
    packed = []
    for item in materials or []:
        kind = str(item.get("kind") or "")
        body = str(item.get("body") or "")[:MATERIAL_MODEL_LIMIT]
        row: dict[str, Any] = {"kind": kind, "body": body}
        if kind == "jingyan":
            row["jingyan_is_not_official"] = True
        packed.append(row)
    payload = {
        "round": session.get("round"),
        "move": decision.get("move"),
        "kind": decision.get("kind"),
        "stem_intent": decision.get("stem_intent"),
        "probe": decision.get("gap_labels") or [],
        "materials": packed,
        "resume": resume_text[:MATERIAL_MODEL_LIMIT],
        "last_answer": last_candidate_answer(session),
        "followup_count": int(session.get("followup_count") or 0),
        "gap_labels": decision.get("gap_labels") or [],
        "jd": str(session.get("jd") or "")[:MATERIAL_MODEL_LIMIT],
    }
    return json.dumps(payload, ensure_ascii=False)


def iter_question_tokens(system_prompt: str, user_text: str, stream: StreamFn, timeout: float = CHAT_TIMEOUT_SECONDS) -> Iterator[str]:
    try:
        yielded = False
        for piece in stream(system_prompt, user_text, timeout):
            text = str(piece or "")
            if not text:
                continue
            yielded = True
            yield text
        if not yielded:
            raise StreamGenerationError("empty")
    except StreamGenerationError:
        raise
    except TimeoutError as exc:
        raise StreamGenerationError("timeout") from exc
    except Exception as exc:
        raise StreamGenerationError("unavailable") from exc


def _replace_or_append_interviewer_turn(session: dict[str, Any], text: str, incomplete: bool) -> None:
    turns = list(session.get("turns") or [])
    last = turns[-1] if turns else None
    if isinstance(last, dict) and last.get("role") == "interviewer" and last.get("incomplete"):
        last["text"] = text
        last["incomplete"] = incomplete
        turns[-1] = last
    else:
        turns.append({"role": "interviewer", "text": text, "incomplete": incomplete})
    session["turns"] = turns


def save_incomplete_question(session: dict[str, Any], decision: dict[str, Any], text: str, intent: str) -> None:
    if text:
        _replace_or_append_interviewer_turn(session, text, True)
        session["current_question"] = text
    session["question_complete"] = False
    session["pending"] = {
        "intent": intent,
        "move": decision.get("move"),
        "kind": decision.get("kind"),
        "main_id": decision.get("main_id"),
        "stem_intent": decision.get("stem_intent"),
        "gap_labels": decision.get("gap_labels") or [],
        "text": text,
        "incomplete": True,
    }


def commit_stream_done(session: dict[str, Any], decision: dict[str, Any], text: str, now: dt.datetime | None = None) -> None:
    current = now or _now()
    _replace_or_append_interviewer_turn(session, text, False)
    if decision.get("move") == "followup":
        session["followup_count"] = int(session.get("followup_count") or 0) + 1
        session["current_main_id"] = decision.get("main_id") or session.get("current_main_id")
    else:
        asked = asked_main_ids(session)
        main_id = str(decision.get("main_id") or "")
        if main_id and main_id not in asked:
            asked.append(main_id)
        session["asked_main_ids"] = asked
        session["current_main_id"] = main_id
        session["followup_count"] = 0
        if session_has_materials(session):
            for item in main_questions(session):
                if item.get("id") == main_id and decision.get("kind"):
                    item["kind"] = decision["kind"]
                    break
    if not session.get("interview_started_at"):
        session["interview_started_at"] = current.isoformat(timespec="seconds")
        session["user_status"] = "in_progress"
    session["current_question"] = text
    session["current_move"] = decision.get("move")
    session["current_kind"] = decision.get("kind")
    session["question_complete"] = True
    session["pending"] = None
    apply_timing(session, current)


def pending_decision(session: dict[str, Any]) -> dict[str, Any] | None:
    pending = session.get("pending")
    if not isinstance(pending, dict) or not pending.get("move"):
        return None
    return {
        "move": pending.get("move"),
        "kind": pending.get("kind") or "resume_probe",
        "main_id": pending.get("main_id"),
        "stem_intent": pending.get("stem_intent") or "",
        "gap_labels": pending.get("gap_labels") or [],
    }


def encode_sse(event: str, data: dict[str, Any]) -> bytes:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def conversation_text(session: dict[str, Any]) -> str:
    parts: list[str] = []
    for row in session.get("turns") or []:
        if isinstance(row, dict):
            text = str(row.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def candidate_facts_text(session: dict[str, Any], answer: str = "") -> str:
    parts: list[str] = []
    for row in session.get("turns") or []:
        if isinstance(row, dict) and row.get("role") == "candidate":
            text = str(row.get("text") or "").strip()
            if text:
                parts.append(text)
    extra = str(answer or "").strip()
    if extra:
        parts.append(extra)
    return "\n".join(parts)


def _parse_model_json(raw: Any, error_cls: type) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    text = (raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)).strip()
    if not text:
        raise error_cls("invalid")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise error_cls("invalid")
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise error_cls("invalid") from exc
    if not isinstance(value, dict):
        raise error_cls("invalid")
    return value


def _strip_offer_language(text: str) -> str:
    cleaned = _OFFER_RE.sub("", str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _arabic_numbers(text: str) -> set[str]:
    return set(_ARABIC_NUM_RE.findall(text or ""))


def sanitize_recast(recast: str, source: str) -> str:
    """Keep only facts already spoken. Missing numbers become the fixed phrase."""
    original = str(recast or "").strip()
    if not original:
        return ""
    source = str(source or "")
    allowed_nums = _arabic_numbers(source)
    had_invented_number = False
    pieces: list[str] = []
    cursor = 0
    for match in _ARABIC_NUM_RE.finditer(original):
        pieces.append(original[cursor:match.start()])
        token = match.group(0)
        if token in allowed_nums:
            pieces.append(token)
        else:
            had_invented_number = True
        cursor = match.end()
    pieces.append(original[cursor:])
    text = "".join(pieces)
    for match in list(_COMPANY_RE.finditer(text))[::-1]:
        name = match.group(0)
        if name in FILL_REAL_NUMBER or name in source:
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", name):
            continue
        text = text[:match.start()] + text[match.end():]
    for match in list(re.finditer(r"[\u4e00-\u9fff]{3,}", text))[::-1]:
        token = match.group(0)
        if token in FILL_REAL_NUMBER or token in source:
            continue
        text = text[:match.start()] + text[match.end():]
    text = _strip_offer_language(text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"。{2,}", "。", text).strip(" ，、；")
    needs_fill = had_invented_number or (not allowed_nums and bool(_arabic_numbers(original)))
    if not allowed_nums:
        leftover = [num for num in _arabic_numbers(text) if num not in _arabic_numbers(FILL_REAL_NUMBER)]
        for num in leftover:
            text = text.replace(num, "")
            needs_fill = True
    if needs_fill and FILL_REAL_NUMBER not in text:
        text = (text.rstrip("。") + "。" if text.strip("。 ") else "") + FILL_REAL_NUMBER
    return re.sub(r"[ \t]{2,}", " ", text).strip(" ，、")


def _one_gap(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return _strip_offer_language(text.splitlines()[0].split("；")[0].strip())
        return ""
    text = str(value or "").strip()
    if not text:
        return ""
    return _strip_offer_language(text.splitlines()[0].split("；")[0].strip())


def _answered_pairs(session: dict[str, Any]) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    pending_q = ""
    for row in session.get("turns") or []:
        if not isinstance(row, dict):
            continue
        role = row.get("role")
        text = str(row.get("text") or "").strip()
        if role == "interviewer" and text and not row.get("incomplete"):
            pending_q = text
        elif role == "candidate" and text and pending_q:
            pairs.append({"question": pending_q, "answer": text})
            pending_q = ""
    return pairs


def _plan_competencies(session: dict[str, Any]) -> list[dict[str, Any]]:
    blueprint = session.get("blueprint") if isinstance(session.get("blueprint"), dict) else {}
    rows = blueprint.get("competencies") if isinstance(blueprint, dict) else None
    return [row for row in rows or [] if isinstance(row, dict) and str(row.get("id") or "").strip()]


def evidence_in_transcript(evidence: str, transcript: str) -> bool:
    span = str(evidence or "").strip()
    if not span:
        return False
    return span in (transcript or "")


def _clean_score_row(item: dict[str, Any], competency: dict[str, Any], transcript: str) -> dict[str, Any]:
    evidence = str(item.get("evidence") or "").strip()
    if not evidence_in_transcript(evidence, transcript):
        evidence = ""
    missing = _strip_offer_language(str(item.get("missing") or "").strip())
    score_raw = item.get("score")
    score: int | None
    try:
        score = int(score_raw) if score_raw is not None and str(score_raw).strip() != "" else None
    except (TypeError, ValueError):
        score = None
    if evidence == "":
        score = None
        if EVIDENCE_MISSING not in missing:
            missing = EVIDENCE_MISSING if not missing else f"{missing}；{EVIDENCE_MISSING}"
    elif score is None or score < 1 or score > 5:
        score = None
        if EVIDENCE_MISSING not in missing:
            missing = EVIDENCE_MISSING if not missing else f"{missing}；{EVIDENCE_MISSING}"
    confidence = str(item.get("confidence") or "").strip()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "low" if score is None else "medium"
    try:
        weight = float(competency.get("weight") if competency.get("weight") is not None else item.get("weight"))
    except (TypeError, ValueError):
        weight = 0.0
    return {
        "competency_id": str(competency.get("id") or item.get("competency_id") or "").strip(),
        "label": str(competency.get("label") or item.get("label") or "").strip(),
        "score": score,
        "weight": weight,
        "evidence": evidence,
        "missing": missing,
        "confidence": confidence,
    }


def validate_debrief_card(raw: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DebriefGenerationError("invalid")
    transcript = conversation_text(session)
    facts = candidate_facts_text(session)
    readiness = str(raw.get("readiness") or "").strip()
    if readiness not in READINESS_LEVELS:
        raise DebriefGenerationError("invalid")
    reason = _strip_offer_language(str(raw.get("reason") or "").strip())
    if not reason:
        raise DebriefGenerationError("invalid")
    model_scores = raw.get("scores") if isinstance(raw.get("scores"), list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for item in model_scores:
        if isinstance(item, dict) and str(item.get("competency_id") or "").strip():
            by_id[str(item.get("competency_id")).strip()] = item
    competencies = _plan_competencies(session)
    if not competencies:
        competencies = [
            item for item in model_scores
            if isinstance(item, dict) and str(item.get("competency_id") or "").strip()
        ]
    if not competencies:
        raise DebriefGenerationError("invalid")
    scores = [_clean_score_row(by_id.get(str(row.get("id") or row.get("competency_id") or ""), row), row, transcript) for row in competencies]
    reviews: list[dict[str, str]] = []
    model_reviews = raw.get("reviews") if isinstance(raw.get("reviews"), list) else []
    pairs = _answered_pairs(session)
    for index, pair in enumerate(pairs):
        item = model_reviews[index] if index < len(model_reviews) and isinstance(model_reviews[index], dict) else {}
        reviews.append({
            "question": str(item.get("question") or pair["question"]),
            "answer": str(item.get("answer") or pair["answer"]),
            "comment": _strip_offer_language(str(item.get("comment") or "").strip()),
            "suggested_structure": sanitize_recast(str(item.get("suggested_structure") or ""), facts),
        })
    if not reviews and model_reviews:
        for item in model_reviews:
            if not isinstance(item, dict):
                continue
            reviews.append({
                "question": str(item.get("question") or ""),
                "answer": str(item.get("answer") or ""),
                "comment": _strip_offer_language(str(item.get("comment") or "").strip()),
                "suggested_structure": sanitize_recast(str(item.get("suggested_structure") or ""), facts),
            })
    priority = _strip_offer_language(str(raw.get("priority_fix") or "").strip())
    if not priority:
        raise DebriefGenerationError("invalid")
    edit_points: list[dict[str, str]] = []
    for item in raw.get("resume_edit_points") or []:
        if not isinstance(item, dict):
            continue
        suggestion = _strip_offer_language(str(item.get("suggestion") or "").strip())
        evidence = str(item.get("evidence") or "").strip()
        if not suggestion or not evidence_in_transcript(evidence, transcript):
            continue
        edit_points.append({"suggestion": suggestion, "evidence": evidence})
    drill_items: list[dict[str, str]] = []
    for index, item in enumerate(raw.get("drill_items") or [], start=1):
        if not isinstance(item, dict):
            continue
        question = str(item.get("question") or "").strip()
        gap = _one_gap(item.get("gap"))
        if not question or not gap:
            continue
        ident = str(item.get("id") or "").strip() or f"drill-{index}"
        drill_items.append({"id": ident, "question": question, "gap": gap})
        if len(drill_items) >= 3:
            break
    if not drill_items:
        raise DebriefGenerationError("invalid")
    return {
        "readiness": readiness,
        "reason": reason,
        "scores": scores,
        "reviews": reviews,
        "priority_fix": priority,
        "resume_edit_points": edit_points,
        "drill_items": drill_items,
        "not_an_offer": True,
        "evidence_note": EVIDENCE_NOTE,
    }


def debrief_user_payload(session: dict[str, Any]) -> str:
    blueprint = session.get("blueprint") if isinstance(session.get("blueprint"), dict) else {}
    payload = {
        "round": session.get("round"),
        "duration_minutes": session.get("duration_minutes"),
        "competencies": _plan_competencies(session),
        "evidence_map": blueprint.get("evidence_map") if isinstance(blueprint, dict) else [],
        "turns": [
            {"role": row.get("role"), "text": str(row.get("text") or "")}
            for row in session.get("turns") or []
            if isinstance(row, dict)
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def generate_debrief(session: dict[str, Any], complete: CompleteFn) -> dict[str, Any]:
    system_prompt = load_debrief_system_prompt()
    user_text = debrief_user_payload(session)
    try:
        raw = complete(system_prompt, user_text, DEBRIEF_TIMEOUT_SECONDS)
    except DebriefGenerationError:
        raise
    except TimeoutError as exc:
        raise DebriefGenerationError("timeout") from exc
    except Exception as exc:
        raise DebriefGenerationError("unavailable") from exc
    parsed = _parse_model_json(raw, DebriefGenerationError)
    return validate_debrief_card(parsed, session)


def session_drill_items(session: dict[str, Any]) -> list[dict[str, str]]:
    card = session.get("debrief_card")
    if isinstance(card, dict) and isinstance(card.get("drill_items"), list):
        return [row for row in card["drill_items"] if isinstance(row, dict)]
    return []


def find_drill_item(session: dict[str, Any], item_id: str) -> dict[str, str] | None:
    wanted = str(item_id or "").strip()
    if not wanted:
        return None
    for row in session_drill_items(session):
        if str(row.get("id") or "") == wanted:
            return {
                "id": str(row.get("id") or ""),
                "question": str(row.get("question") or ""),
                "gap": str(row.get("gap") or ""),
            }
    return None


def drill_user_payload(session: dict[str, Any], item: dict[str, str], answer: str, attempt: int) -> str:
    payload = {
        "item_id": item.get("id"),
        "question": item.get("question"),
        "gap": item.get("gap"),
        "answer": answer,
        "attempt": attempt,
        "original_prompt": item.get("question"),
        "facts": candidate_facts_text(session, answer),
        "round": session.get("round"),
    }
    return json.dumps(payload, ensure_ascii=False)


def adjacent_prompt(original: str) -> str:
    text = str(original or "").strip()
    if not text:
        return ADJACENT_PROMPT_PREFIX.strip()
    if text.startswith(ADJACENT_PROMPT_PREFIX):
        return text
    return ADJACENT_PROMPT_PREFIX + text


def apply_drill_attempt(session: dict[str, Any], item: dict[str, str], model: dict[str, Any], answer: str) -> dict[str, Any]:
    item_id = str(item.get("id") or "")
    state = dict(session.get("drill_state") or {}) if isinstance(session.get("drill_state"), dict) else {}
    current = dict(state.get(item_id) or {}) if isinstance(state.get(item_id), dict) else {}
    attempt = int(current.get("attempt") or 0) + 1
    original = str(current.get("prompt") or item.get("question") or "").strip()
    model_prompt = str(model.get("prompt") or "").strip()
    if not original:
        original = model_prompt
    if attempt >= 4:
        prompt = model_prompt if model_prompt and model_prompt != original else adjacent_prompt(original)
    else:
        if not current.get("prompt") and model_prompt:
            original = model_prompt
        prompt = original
    recast = ""
    if str(answer or "").strip():
        recast = sanitize_recast(str(model.get("recast") or ""), candidate_facts_text(session, answer))
    current["attempt"] = attempt
    current["prompt"] = original
    state[item_id] = current
    session["drill_state"] = state
    session["user_status"] = "drilling"
    result = {
        "item_id": item_id,
        "gap": _one_gap(model.get("gap")) or _one_gap(item.get("gap")),
        "prompt": prompt,
        "attempt": attempt,
    }
    if recast:
        result["recast"] = recast
    return result


def generate_drill(
    session: dict[str, Any],
    item: dict[str, str],
    answer: str,
    complete: CompleteFn | None,
) -> dict[str, Any]:
    answer_text = str(answer or "").strip()
    if not answer_text:
        return apply_drill_attempt(session, item, {"gap": item.get("gap"), "prompt": item.get("question")}, "")
    if complete is None:
        raise DrillGenerationError("unavailable")
    state = session.get("drill_state") if isinstance(session.get("drill_state"), dict) else {}
    current = state.get(item.get("id")) if isinstance(state, dict) else None
    attempt = int((current or {}).get("attempt") or 0) + 1
    system_prompt = load_drill_system_prompt()
    user_text = drill_user_payload(session, item, answer_text, attempt)
    try:
        raw = complete(system_prompt, user_text, DRILL_TIMEOUT_SECONDS)
    except DrillGenerationError:
        raise
    except TimeoutError as exc:
        raise DrillGenerationError("timeout") from exc
    except Exception as exc:
        raise DrillGenerationError("unavailable") from exc
    parsed = _parse_model_json(raw, DrillGenerationError)
    return apply_drill_attempt(session, item, parsed, answer_text)
