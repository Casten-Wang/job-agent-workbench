#!/usr/bin/env python3
"""Rule-based risk screen for a single job posting (read-only).

Looks for common red flags in a posting's text and metadata: agency
recruiters, fee / training-loan wording, "guaranteed" promises, an extremely
wide salary range, missing key fields, duplicate postings and stale postings.
It never edits the job and never calls out to anything. The caller decides
what to do with the result; ``blocks_queue`` only tells the approval queue
that the posting should not be pushed forward without a human looking at it.

No network access, no external dependency, no LLM call.
"""

from __future__ import annotations

import datetime
import re
import sys
import unicodedata
from typing import Any

sys.dont_write_bytecode = True

# Keyword lists (matched case-insensitively after NFKC normalization).
AGENCY_KEYWORDS = ["猎头", "中介", "代招", "我司代", "委托单位", "推荐费"]
FEE_KEYWORDS = [
    "培训贷",
    "培训费",
    "交费",
    "缴费",
    "押金",
    "押证",
    "押身份证",
    "收取",
    "办卡",
    "分期培训",
]
PROMISE_KEYWORDS = ["包分配", "包就业", "保就业", "包过", "保底高薪", "日入", "躺赚", "无责任底薪"]

SALARY_WIDE_RATIO = 3.0
STALE_DAYS = 60
MAX_EVIDENCE_CHARS = 40

_SALARY_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(k|千|万|w|元)?\s*[-~—–到至]\s*(\d+(?:\.\d+)?)\s*(k|千|万|w|元)?"
)
_UNIT_FACTOR = {"": 1.0, "元": 1.0, "k": 1000.0, "千": 1000.0, "万": 10000.0, "w": 10000.0}
_DATE_RE = re.compile(r"^\s*(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")


def _text(value: Any) -> str:
    """Coerce any value to a string; None becomes empty."""

    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # pragma: no cover - exotic objects
        return ""


def _normalize(value: Any) -> str:
    return unicodedata.normalize("NFKC", _text(value)).lower()


def _clip(text: str) -> str:
    return text[:MAX_EVIDENCE_CHARS]


def _first_keyword(text: str, keywords: list[str]) -> str:
    for keyword in keywords:
        if keyword.lower() in text:
            return keyword
    return ""


def _parse_salary_range(salary_text: str) -> tuple[float, float] | None:
    """Return (min, max) in yuan, or None when no range can be read."""

    match = _SALARY_RANGE_RE.search(salary_text)
    if not match:
        return None
    low_raw, low_unit, high_raw, high_unit = match.groups()
    # "8-30K": the low end borrows the unit written after the high end.
    low_unit = low_unit or high_unit or ""
    high_unit = high_unit or low_unit
    try:
        low = float(low_raw) * _UNIT_FACTOR[low_unit]
        high = float(high_raw) * _UNIT_FACTOR[high_unit]
    except (ValueError, KeyError):
        return None
    if low <= 0 or high <= 0:
        return None
    return low, high


def _parse_date(value: Any) -> datetime.date | None:
    match = _DATE_RE.match(_normalize(value))
    if not match:
        return None
    try:
        return datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _signal(code: str, severity: str, label: str, evidence: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "label": label, "evidence": _clip(evidence)}


def assess_job_risk(
    job: dict,
    *,
    duplicate_count: int = 0,
    today: datetime.date | None = None,
) -> dict:
    """Assess one job posting and return level, signals and ``blocks_queue``."""

    if not isinstance(job, dict):
        job = {}
    today = today or datetime.date.today()

    title = _text(job.get("title"))
    company = _text(job.get("company"))
    city = _text(job.get("city"))
    salary_text = _text(job.get("salary_text"))
    raw_text = _text(job.get("raw_text"))
    posted_at = job.get("posted_at")

    haystack = _normalize(" \n ".join([title, company, city, salary_text, raw_text]))
    signals: list[dict[str, str]] = []

    hit = _first_keyword(haystack, AGENCY_KEYWORDS)
    if hit:
        signals.append(_signal("agency_recruiter", "verify", "疑似猎头/中介代招", hit))

    hit = _first_keyword(haystack, FEE_KEYWORDS)
    if hit:
        signals.append(_signal("fee_or_training_loan", "high", "涉及收费/培训贷/押金", hit))

    hit = _first_keyword(haystack, PROMISE_KEYWORDS)
    if hit:
        signals.append(_signal("guaranteed_promise", "high", "含保证就业/高薪类承诺", hit))

    salary_norm = _normalize(salary_text)
    salary_range = _parse_salary_range(salary_norm)
    if salary_range is not None and salary_range[1] / salary_range[0] >= SALARY_WIDE_RATIO:
        match = _SALARY_RANGE_RE.search(salary_norm)
        signals.append(
            _signal(
                "salary_range_too_wide",
                "verify",
                "薪资区间过宽，上下限相差 3 倍以上",
                match.group(0) if match else salary_text,
            )
        )

    missing = [
        name
        for name, value in (("公司", company), ("岗位", title), ("城市", city))
        if not value.strip()
    ]
    if missing:
        signals.append(
            _signal("missing_key_info", "verify", "缺少关键信息", "缺少" + "、".join(missing))
        )

    try:
        dup = int(duplicate_count or 0)
    except (TypeError, ValueError):
        dup = 0
    if dup >= 1:
        signals.append(
            _signal("duplicate_posting", "verify", "岗位池内存在同公司同岗位的重复记录", f"重复 {dup} 条")
        )

    posted_date = _parse_date(posted_at)
    if posted_date is not None and (today - posted_date).days > STALE_DAYS:
        signals.append(
            _signal(
                "stale_posting",
                "verify",
                f"发布已超过 {STALE_DAYS} 天，可能已失效",
                _text(posted_at).strip(),
            )
        )

    if any(s["severity"] == "high" for s in signals):
        level = "high"
    elif signals:
        level = "verify"
    else:
        level = "low"
    return {"level": level, "signals": signals, "blocks_queue": level == "high"}
