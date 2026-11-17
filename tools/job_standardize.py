#!/usr/bin/env python3
"""Standardize one local job row into the product's ``job.standard`` view.

Read-only and deterministic: it reads fields already stored on the job row and
returns a new dict. It never edits the row, never guesses a missing value and
never calls the network. Missing source data becomes ``None``.

The standard view is the single shape the UI reads for "what the posting
says": title, location, responsibilities, must-have / nice-to-have
requirements, salary and start, hiring status, source platform and the
source's update time.

Derivation rules
----------------
- ``responsibilities`` / ``nice_to_have`` come only from sections of the
  posting's ``raw_text`` (岗位职责/职位描述, 加分项/优先条件). No section means
  ``None``.
- ``must_have`` prefers the already-scored ``mandatory_conditions`` (the set
  the match score was computed against). Only when that list is absent does it
  fall back to the 任职要求 section of ``raw_text``.
- Placeholder strings written by the workbench ("未填写", "未填写公司",
  "未填写岗位") are treated as missing, never shown as data.
- ``source_platform`` accepts an explicit platform, else the known platform
  names in ``source_channel``; "manual_paste" is a source, not a platform, so
  it yields ``None``.
- ``source_updated_at`` uses an explicit update time when present and falls
  back to ``posted_at`` (the timestamp the source showed for the posting).
"""

from __future__ import annotations

import re
import sys
from typing import Any

sys.dont_write_bytecode = True

PLACEHOLDER_VALUES = {
    "",
    "未填写",
    "未填写公司",
    "未填写岗位",
    "未知",
    "暂无",
    "none",
    "null",
}
KNOWN_PLATFORMS = ("boss", "zhilian", "51job", "liepin")

# Longest headings first so "任职要求" wins over "任职".
_SECTION_HEADINGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "responsibilities",
        (
            "岗位职责",
            "工作职责",
            "职位职责",
            "职责描述",
            "工作内容",
            "岗位内容",
            "你将负责",
            "职位描述",
            "岗位描述",
        ),
    ),
    (
        "must_have",
        (
            "任职要求",
            "岗位要求",
            "任职资格",
            "职位要求",
            "任职条件",
            "基本要求",
            "你需要具备",
            "我们希望你",
        ),
    ),
    (
        "nice_to_have",
        ("加分项", "加分条件", "优先条件", "优先考虑", "nice to have", "preferred"),
    ),
)

_BULLET_RE = re.compile(r"^\s*(?:[-*•·●○▪◦]|\d{1,2}[.、)）]|[（(]\d{1,2}[)）])\s*")
_SPACE_RE = re.compile(r"\s+")
_MAX_ITEM_CHARS = 500


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # pragma: no cover - exotic objects
        return ""


def _clean(value: Any) -> str | None:
    """Collapse whitespace and map workbench placeholders to ``None``."""

    text = _SPACE_RE.sub(" ", _text(value)).strip()
    return None if text.casefold() in PLACEHOLDER_VALUES else text


def _heading(line: str) -> tuple[str | None, str | None]:
    """Return ``(section, inline_content)`` when *line* is a section heading."""

    candidate = _BULLET_RE.sub("", line).strip().strip("【】[]#").strip()
    lowered = candidate.casefold()
    for section, words in _SECTION_HEADINGS:
        for word in words:
            if not lowered.startswith(word.casefold()):
                continue
            rest = candidate[len(word):]
            # A heading is the bare keyword or keyword + colon + content.
            # "岗位要求相关文档编写" must stay body text, not become a heading.
            if not rest:
                return section, None
            if rest[0] in "：:":
                inline = rest[1:].strip()
                return section, inline or None
            if rest[0].isspace():
                inline = rest.strip()
                if len(candidate) <= len(word) + 12:
                    return section, inline or None
    return None, None


def _append(items: list[str], value: str) -> None:
    text = _SPACE_RE.sub(" ", value).strip()
    if len(text) < 2:
        return
    if len(text) > _MAX_ITEM_CHARS:
        text = text[:_MAX_ITEM_CHARS].rstrip()
    if text not in items:
        items.append(text)


def split_sections(raw_text: Any) -> dict[str, list[str] | None]:
    """Split a pasted posting into responsibilities / requirements sections.

    Returns ``None`` for a section the posting does not contain. Lines are
    kept as data: no rewriting, summarizing or inference.
    """

    buckets: dict[str, list[str]] = {key: [] for key, _ in _SECTION_HEADINGS}
    current: str | None = None
    for raw_line in _text(raw_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section, inline = _heading(line)
        if section:
            current = section
            if inline:
                _append(buckets[section], inline)
            continue
        if current:
            _append(buckets[current], _BULLET_RE.sub("", line))
    return {key: (values or None) for key, values in buckets.items()}


def _mandatory_conditions(job: dict[str, Any]) -> list[str] | None:
    rows = job.get("mandatory_conditions")
    if not isinstance(rows, list):
        return None
    conditions: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        condition = _clean(row.get("condition"))
        if condition and condition not in conditions:
            conditions.append(condition)
    return conditions or None


def _salary(job: dict[str, Any]) -> str | None:
    text = _clean(job.get("salary_text")) or _clean(job.get("salary_label"))
    if text:
        return text
    low, high = job.get("salary_min"), job.get("salary_max")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        if not isinstance(low, bool) and not isinstance(high, bool):
            return f"{int(low) // 1000}–{int(high) // 1000}k"
    return None


def salary_and_start(job: dict[str, Any]) -> dict[str, str | None] | None:
    """Salary wording plus the job's stated start/onboarding time, if any.

    ``posted_at`` is *not* used here: the posting date is not a start date.
    """

    salary = _salary(job)
    start = None
    for key in ("start", "start_date", "onboard_at", "availability"):
        start = _clean(job.get(key))
        if start:
            break
    if salary is None and start is None:
        return None
    return {"salary": salary, "start": start}


def source_platform(job: dict[str, Any]) -> str | None:
    explicit = _clean(job.get("source_platform"))
    if explicit:
        return explicit.lower()
    channel = _clean(job.get("source_channel"))
    if channel and channel.lower() in KNOWN_PLATFORMS:
        return channel.lower()
    return None


def source_updated_at(job: dict[str, Any]) -> str | None:
    # 只认平台给出的时间。本地的 updated_at / created_at 是入库或评分写入时间，不能冒充来源时间。
    explicit = _clean(job.get("source_updated_at"))
    if explicit:
        return explicit
    # 岗位自动化导入的行（带 offerpilot_id）：运行时库不提供平台发布时间，
    # 旧版导入把入库时间写进了 posted_at，所以这类行的 posted_at 不可信，返回 None。
    if job.get("offerpilot_id"):
        return None
    return _clean(job.get("posted_at")) or None


def standardize_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return the read-only ``job.standard`` view for one job row."""

    job = job if isinstance(job, dict) else {}
    sections = split_sections(job.get("raw_text"))
    return {
        "title": _clean(job.get("title")),
        "location": _clean(job.get("city")),
        "responsibilities": sections["responsibilities"],
        "must_have": _mandatory_conditions(job) or sections["must_have"],
        "nice_to_have": sections["nice_to_have"],
        "salary_and_start": salary_and_start(job),
        "hiring_status": _clean(job.get("hiring_status")),
        "source_platform": source_platform(job),
        "source_updated_at": source_updated_at(job),
    }


def main() -> int:  # pragma: no cover - convenience entry point
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Print the standard view of one local job JSON")
    parser.add_argument("--job", required=True, help="job row or {\"jobs\": [...]} JSON")
    args = parser.parse_args()
    payload = json.loads(Path(args.job).read_text(encoding="utf-8-sig"))
    row = payload["jobs"][0] if isinstance(payload, dict) and payload.get("jobs") else payload
    print(json.dumps(standardize_job(row), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
