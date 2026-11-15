#!/usr/bin/env python3
"""Daily contact-quota planner (pure function, read-only).

Given candidate jobs, the user's daily contact quota and the contact history,
it ranks which candidates to contact today and explains, in Chinese, why each
candidate was ranked or deferred. It skips high-risk postings, same-job
re-contacts inside a window, and companies that already have an interview /
written-test flow. It never reads or writes files and never sends anything.

No network access, no external dependency, no LLM call.
"""

from __future__ import annotations

import datetime
import math
import re
import sys
import unicodedata
from typing import Any

sys.dont_write_bytecode = True

_DATE_RE = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_RISK_ORDER = {"low": 0, "verify": 1}
_RISK_LABEL = {"low": "低", "verify": "需核实"}
_MIN_DATE = datetime.date.min


def _norm(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text).strip().lower()
    return re.sub(r"\s+", " ", text)


def _parse_date(value: Any) -> datetime.date | None:
    if value is None:
        return None
    match = _DATE_RE.match(unicodedata.normalize("NFKC", str(value)))
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _score(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _risk(value: Any) -> str:
    """Missing risk defaults to low; an unknown label is treated as verify."""

    if value is None or _norm(value) == "":
        return "low"
    level = _norm(value)
    return level if level in ("low", "verify", "high") else "verify"


def plan_contact_queue(
    candidates: list[dict],
    *,
    daily_quota: int,
    history: list[dict],
    today: datetime.date,
    window_days: int = 30,
    active_companies: set[str] | None = None,
) -> dict:
    """Rank today's contact candidates within the remaining daily quota."""

    history = [h for h in (history or []) if isinstance(h, dict)]
    try:
        quota = int(daily_quota)
    except (TypeError, ValueError):
        quota = 0

    contacted_today = 0
    recent_keys: set[tuple[str, str]] = set()
    for item in history:
        contacted = _parse_date(item.get("contacted_at"))
        if contacted is None:
            continue
        if contacted == today:
            contacted_today += 1
        days_ago = (today - contacted).days
        if 0 <= days_ago <= window_days:
            recent_keys.add((_norm(item.get("company")), _norm(item.get("title"))))

    active = {_norm(name) for name in (active_companies or set())}
    remaining = max(quota - contacted_today, 0)

    valid: list[dict] = []
    for cand in candidates or []:
        if isinstance(cand, dict) and _norm(cand.get("id")) != "" and cand.get("id") is not None:
            valid.append(cand)

    ranked: list[dict] = []
    deferred: list[dict] = []

    if remaining <= 0:
        deferred = [{"id": str(c["id"]), "reason": "今日额度已用完"} for c in valid]
        return {"remaining_quota": remaining, "ranked": ranked, "deferred": deferred}

    eligible: list[tuple[dict, float | None, str, datetime.date]] = []
    for cand in valid:
        cid = str(cand["id"])
        company = _norm(cand.get("company"))
        title = _norm(cand.get("title"))
        risk = _risk(cand.get("risk_level"))
        score = _score(cand.get("score"))
        if risk == "high":
            deferred.append({"id": cid, "reason": "风险等级高，不进入推荐队列"})
        elif (company, title) in recent_keys:
            deferred.append({"id": cid, "reason": f"近 {window_days} 天已沟通过同一岗位"})
        elif company and company in active:
            deferred.append({"id": cid, "reason": "同公司已有面试/笔试流程，默认降权"})
        elif score is None:
            deferred.append({"id": cid, "reason": "未评分，先人工判断"})
        else:
            posted = _parse_date(cand.get("posted_at")) or _MIN_DATE
            eligible.append((cand, score, risk, posted))

    eligible.sort(
        key=lambda row: (
            -(row[1] or 0.0),
            _RISK_ORDER.get(row[2], 1),
            -row[3].toordinal(),
            str(row[0]["id"]),
        )
    )

    for index, (cand, score, risk, _posted) in enumerate(eligible):
        cid = str(cand["id"])
        if index < remaining:
            rank = index + 1
            ranked.append(
                {
                    "id": cid,
                    "rank": rank,
                    "reason": f"评分 {score:g}，风险{_RISK_LABEL.get(risk, '需核实')}，排第 {rank}；今日额度 {remaining}",
                }
            )
        else:
            deferred.append({"id": cid, "reason": f"超出今日额度 {remaining}，顺延到下一批"})

    return {"remaining_quota": remaining, "ranked": ranked, "deferred": deferred}
