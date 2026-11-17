#!/usr/bin/env python3
"""Build the local application dossier for one job row (read-only).

``job.dossier`` has exactly five parts:

- ``analysis_card``: a factual card assembled from the existing score fields
  (fit score, confidence and risk stay separate; conditions are grouped by
  their recorded status). ``None`` when the row has no analysis at all.
- ``resume_variant``: an existing ``add-variant`` id. It is the job's explicit
  ``resume_variant`` when present, else a saved variant whose project name
  equals the job title (case-insensitive, whitespace-collapsed). A loose
  "contains" match could attach the wrong variant, so it is not used. Never a
  new variant, never a guessed id.
- ``greeting``: the job's stored greeting draft when there is one, otherwise a
  draft from the existing :mod:`greeting` generator when ``cv_text`` is
  available. Anything containing a phone number, email, WeChat handle, QQ or
  link is rejected (CLAUDE.md §5): the field is ``None`` and the checklist
  says so. No message is sent by this module.
- ``checklist``: human steps before applying, derived from the same facts.
- ``recommended_action``: one of ``skip`` / ``hold`` / ``collect_more`` /
  ``generate_greeting`` / ``review_and_send``.

``job.traceability`` is a list with one entry per must-have requirement:
``{requirement, project_evidence, source}``. Evidence is the profile
project/experience summary that shares domain terms with the requirement,
with whitespace collapsed and clipped to ``MAX_EVIDENCE_CHARS``; no wording is
added or paraphrased. When nothing matches, both ``project_evidence`` and
``source`` are ``None``.

No network access, no external service, no mutation.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

import greeting as greeting_module  # noqa: E402
import job_match  # noqa: E402
import job_standardize  # noqa: E402

MAX_EVIDENCE_CHARS = 240

# Contact shapes that must never appear in a generated draft.
_CONTACT_PATTERNS = (
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),  # CN mobile
    re.compile(r"(?<!\d)0\d{2,3}[- ]?\d{7,8}(?!\d)"),  # landline
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"(?:微信|wechat|weixin|vx|v信|威信|加我)\s*[:：]?\s*\S+", re.IGNORECASE),
    re.compile(r"(?:qq|扣扣)\s*[:：]?\s*\d{5,}", re.IGNORECASE),
    re.compile(r"https?://|www\.", re.IGNORECASE),
)

# Domain terms used only for read-only evidence matching. Generic words such as
# "经验" or "产品" are deliberately absent: they match everything and prove
# nothing.
_MATCH_TERMS = tuple(
    term.casefold()
    for term in (
        "需求分析", "需求调研", "用户调研", "用户访谈", "产品设计", "产品原型",
        "原型设计", "交互设计", "用户体验", "可用性测试", "信息架构", "功能架构",
        "需求文档", "流程图", "数据分析", "数据监控", "上线", "迭代", "增长",
        "留存", "小程序", "移动端", "电商", "供应链", "订单", "结算", "支付",
        "项目管理", "跨部门", "跨团队", "运营", "图像处理", "视频", "VR", "AI",
        "机器学习", "大模型", "Axure", "Visio", "Mindmanager", "PRD", "B2B",
        "B端", "CRM", "ERP", "SaaS", "APP", "H5", "UI",
    )
)


def _term_in(term: str, text: str) -> bool:
    """Match one vocabulary term with a boundary check for Latin terms.

    Plain substring matching would let "AI" hit "email" and "UI" hit "build";
    CJK terms have no word boundaries and stay substring matches.
    """

    if term.isascii():
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        return re.search(pattern, text) is not None
    return term in text


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # pragma: no cover - exotic objects
        return ""


def _normalized(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).casefold()


def contains_contact(text: Any) -> bool:
    """True when *text* carries a phone, email, IM handle or link."""

    value = _text(text)
    return any(pattern.search(value) for pattern in _CONTACT_PATTERNS)


def analysis_card(job: dict[str, Any]) -> dict[str, Any] | None:
    """Group the existing analysis fields; ``None`` when there is none."""

    job = job or {}
    conditions = job.get("mandatory_conditions")
    rows = [row for row in conditions if isinstance(row, dict)] if isinstance(conditions, list) else []
    score = job_match.fit_score(job)
    hiring = _text(job.get("hiring_status")).strip() or None
    mandatory_status = _text(job.get("mandatory_status")).strip() or None
    if score is None and not rows and not hiring and not mandatory_status:
        return None

    grouped: dict[str, list[str]] = {"已满足": [], "待确认": [], "明确不满足": []}
    for row in rows:
        condition = _text(row.get("condition")).strip()
        status = _text(row.get("status")).strip()
        if condition and status in grouped and condition not in grouped[status]:
            grouped[status].append(condition)
    return {
        "company": _text(job.get("company")).strip() or None,
        "title": _text(job.get("title")).strip() or None,
        "city": _text(job.get("city")).strip() or None,
        "fit_score": score,
        "fit_confidence": job_match.fit_confidence(job),
        "risk_level": job_match.risk_level(job),
        "mandatory_status": mandatory_status,
        "hiring_status": hiring,
        "score_coverage": job.get("score_coverage"),
        "score_reason": _text(job.get("score_reason")).strip() or None,
        "satisfied": grouped["已满足"],
        "pending": grouped["待确认"],
        "gaps": grouped["明确不满足"],
    }


def resume_variant_id(job: dict[str, Any], variants: list[dict[str, Any]] | None = None) -> str | None:
    """An existing saved variant id, or ``None``. Never creates a variant."""

    explicit = _text((job or {}).get("resume_variant")).strip()
    if explicit:
        return explicit
    title = re.sub(r"\s+", " ", _normalized((job or {}).get("title"))).strip()
    if not title:
        return None
    for row in variants or []:
        if not isinstance(row, dict):
            continue
        variant_id = _text(row.get("id")).strip()
        project = re.sub(r"\s+", " ", _normalized(row.get("project"))).strip()
        if variant_id and project and project == title:
            return variant_id
    return None


def greeting_draft(job: dict[str, Any], cv_text: str | None = None) -> str | None:
    """Stored draft first, else the existing greeter's output; contact-free only."""

    job = job or {}
    stored = job.get("greeting")
    if isinstance(stored, dict):
        stored = stored.get("greeting")
    text = _text(stored).strip()
    if text:
        return text if not contains_contact(text) else None
    if not cv_text:
        return None
    try:
        result = greeting_module.make_greeting(job, cv_text)
    except Exception:
        return None
    text = _text((result or {}).get("greeting")).strip()
    if not text or contains_contact(text):
        return None
    return text


def _unsatisfied_count(job: dict[str, Any]) -> int:
    rows = job.get("mandatory_conditions")
    if not isinstance(rows, list):
        return 0
    return sum(
        1
        for row in rows
        if isinstance(row, dict) and _text(row.get("status")).strip() == "明确不满足"
    )


def _checklist(
    job: dict[str, Any],
    card: dict[str, Any] | None,
    variant: str | None,
    greeting_text: str | None,
) -> list[str]:
    items = ["核对岗位标准信息：标题、地点、薪资与更新时间"]
    hiring = _text(job.get("hiring_status")).strip().lower()
    if card is None or hiring in ("", "unknown"):
        items.append("确认岗位仍在招聘、发布时间仍然有效")
    mandatory_status = _text(job.get("mandatory_status")).strip()
    gaps = _unsatisfied_count(job)
    if mandatory_status == "unsatisfied" or gaps:
        items.append(f"必备条件有 {gaps} 项明确不满足：投递前确认是否仍要尝试")
    elif mandatory_status in ("pending", "unknown") or (
        mandatory_status in (None, "") and job.get("mandatory_conditions")
    ):
        items.append("逐条核对必备条件，待确认项先补齐证据")
    risk = job_match.risk_level(job)
    if risk == "high":
        items.append("来源或招聘状态存在高风险信号：投递前人工核实")
    elif risk == "medium":
        items.append("来源或招聘状态待核实，避免投递已失效岗位")
    if greeting_text:
        items.append("复核招呼语，确认不含联系方式后再发送")
    else:
        items.append("生成招呼语草稿并复核（当前没有可用草稿）")
    if variant:
        items.append(f"确认简历变体 {variant} 与岗位匹配")
    else:
        items.append("为岗位准备定制简历变体")
    items.append("发送前在审批队列人工确认")
    return items


def _recommended_action(
    job: dict[str, Any],
    card: dict[str, Any] | None,
    greeting_text: str | None,
) -> str:
    hiring = _text(job.get("hiring_status")).strip().lower()
    if hiring == "closed":
        return "skip"
    if _text(job.get("mandatory_status")).strip() == "unsatisfied" or _unsatisfied_count(job):
        return "hold"
    if job_match.risk_level(job) == "high":
        return "hold"
    if card is None or job_match.fit_score(job) is None:
        return "collect_more"
    if not greeting_text:
        return "generate_greeting"
    return "review_and_send"


def build_dossier(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    variants: list[dict[str, Any]] | None = None,
    cv_text: str | None = None,
) -> dict[str, Any]:
    """Return the read-only application dossier for one job row."""

    job = job if isinstance(job, dict) else {}
    card = analysis_card(job)
    variant = resume_variant_id(job, variants)
    greeting_text = greeting_draft(job, cv_text)
    return {
        "analysis_card": card,
        "resume_variant": variant,
        "greeting": greeting_text,
        "checklist": _checklist(job, card, variant, greeting_text),
        "recommended_action": _recommended_action(job, card, greeting_text),
    }


def _profile_entries(profile: dict[str, Any] | None) -> list[tuple[str, dict[str, Any], str]]:
    profile = profile if isinstance(profile, dict) else {}
    entries: list[tuple[str, dict[str, Any], str]] = []
    for key in ("projects", "experiences"):
        rows = profile.get(key)
        if not isinstance(rows, list):
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            parts = [
                _text(row.get(field))
                for field in ("name", "company", "role", "title", "summary")
            ]
            entries.append((f"profile.{key}[{index}]", row, _normalized(" ".join(parts))))
    return entries


def _evidence(row: dict[str, Any]) -> str | None:
    if _text(row.get("name")).strip():
        heading = _text(row.get("name")).strip()
    else:
        heading = " ".join(
            part for part in (_text(row.get("company")).strip(), _text(row.get("title")).strip()) if part
        )
    summary = re.sub(r"\s+", " ", _text(row.get("summary"))).strip()
    if heading and summary:
        text = f"{heading}：{summary}"
    elif heading or summary:
        text = heading or summary
    else:
        return None
    return text[:MAX_EVIDENCE_CHARS].rstrip() or None


def build_traceability(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Map each must-have requirement to verbatim profile evidence, or nulls."""

    standard = job_standardize.standardize_job(job if isinstance(job, dict) else {})
    requirements = standard.get("must_have") or []
    entries = _profile_entries(profile)
    result: list[dict[str, Any]] = []
    for requirement in requirements:
        needle = _normalized(requirement)
        best: tuple[int, str, dict[str, Any]] | None = None
        for source, row, haystack in entries:
            matched = sum(
                1 for term in _MATCH_TERMS if _term_in(term, needle) and _term_in(term, haystack)
            )
            if matched and (best is None or matched > best[0]):
                best = (matched, source, row)
        if best is None:
            result.append({"requirement": requirement, "project_evidence": None, "source": None})
        else:
            result.append(
                {
                    "requirement": requirement,
                    "project_evidence": _evidence(best[2]),
                    "source": best[1],
                }
            )
    return result
