#!/usr/bin/env python3
"""Read-only, rule-based resume/experience-text quality hints (定制简历模块).

This module never generates, rewrites, or invents resume content. It only
inspects text the user already wrote (an experience variant, a pasted
paragraph) and reports *missing-structure hints*: whether a STAR-like
structure (background/problem/action/result) is present, whether a
quantified result is present, and whether an "AI 工具使用" skill line is
present. All three checks are heuristic and conservative: when unsure, the
check reports the weaker verdict (not found) rather than guessing a match
that is not clearly there, because a false "looks fine" is worse than an
extra reminder for a self-review tool.

No network access, no external dependency, no LLM call. Pure text
inspection with Python's standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

sys_dont_write_bytecode = True  # mirrors sibling tools' bytecode-avoidance intent

# STAR-ish section labels. Chinese projects in this repo commonly write
# "背景 / 问题 / 动作 / 结果" (see demo/demo-resume-001.md); we also accept
# the classic STAR English labels and a few common synonyms so a real user's
# resume isn't flagged just for using different words for the same structure.
_STAGE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "situation": ("背景", "情境", "场景", "situation", "context"),
    "task": ("问题", "任务", "目标", "task", "problem", "挑战"),
    "action": ("动作", "行动", "做法", "action", "我做了", "负责"),
    "result": ("结果", "成果", "产出", "result", "outcome", "效果"),
}

# A quantified result needs a number together with a unit/comparison cue so
# that a bare id-like number (e.g. "2026") is not mistaken for a result.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUANT_UNIT_RE = re.compile(
    r"(%|％|倍|人|份|次|天|周|小时|分钟|篇|条|个|名|元|万|k|K|降到?|提升|缩短|精简|减少|增加|提高)"
)
# A bare 4-digit year (2020-2099) next to typical date punctuation should not
# by itself count as a quantified result.
_YEAR_ONLY_RE = re.compile(r"(?<!\d)(20\d{2}|19\d{2})年?(?!\d)")

_AI_SKILL_HINT_RE = re.compile(r"AI\s*(工具|辅助|生成|技能)|人工智能工具|大模型(辅助|工具)")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _find_stage_hits(text: str) -> dict[str, bool]:
    folded = text.casefold()
    hits: dict[str, bool] = {}
    for stage, synonyms in _STAGE_SYNONYMS.items():
        hits[stage] = any(syn.casefold() in folded for syn in synonyms)
    return hits


def _has_quantified_result(text: str) -> bool:
    for match in _NUMBER_RE.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 4) : min(len(text), end + 4)]
        if _YEAR_ONLY_RE.fullmatch(match.group()) and not _QUANT_UNIT_RE.search(window):
            continue
        if _QUANT_UNIT_RE.search(window):
            return True
    return False


def _has_ai_skill_mention(text: str) -> bool:
    return bool(_AI_SKILL_HINT_RE.search(text))


def check_experience_text(text: str) -> dict[str, Any]:
    """Inspect one experience/variant text block and return hints only.

    Returns a dict with:
      - ``star_stages``: {situation, task, action, result} -> bool, which
        stage-like labels were found (heuristic, label-based, not semantic).
      - ``has_star_structure``: True only when at least 3 of the 4 stages
        are present, matching the four-part "背景-问题-动作-结果" convention
        used in this repo's demo resume.
      - ``has_quantified_result``: True when a number next to a unit or
        comparison word was found.
      - ``hints``: list of short, user-facing suggestions for what to add.
        Never rewrites or supplies the missing content; only names the gap.
    """

    normalized = _normalize(text or "")
    stages = _find_stage_hits(normalized)
    stage_count = sum(1 for present in stages.values() if present)
    has_star = stage_count >= 3
    has_quant = _has_quantified_result(normalized)

    hints: list[str] = []
    if not has_star:
        missing = [stage for stage, present in stages.items() if not present]
        label_map = {
            "situation": "背景",
            "task": "问题/目标",
            "action": "动作",
            "result": "结果",
        }
        missing_labels = "、".join(label_map[stage] for stage in missing)
        hints.append(f"建议补全「背景-问题-动作-结果」结构，当前缺少：{missing_labels}")
    if not has_quant:
        hints.append("建议补充一个量化结果（数字 + 单位/对比，例如比例、人数、次数、时长变化）")

    return {
        "star_stages": stages,
        "has_star_structure": has_star,
        "has_quantified_result": has_quant,
        "hints": hints,
    }


def check_skill_section(text: str) -> dict[str, Any]:
    """Inspect a skills section for an explicit AI-tool-usage line.

    Only reports presence/absence; never adds or suggests specific tool
    names, because that would be inventing a skill the user may not have.
    """

    normalized = _normalize(text or "")
    has_ai_skill = _has_ai_skill_mention(normalized)
    hints: list[str] = []
    if not has_ai_skill:
        hints.append("建议在技能区补充一条「AI 工具使用」说明，写清具体场景与人工核对方式")
    return {"has_ai_skill_mention": has_ai_skill, "hints": hints}
