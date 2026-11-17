#!/usr/bin/env python3
"""Three independent match signals for one job row (read-only).

The product intentionally keeps these apart — they are never merged into one
number:

- ``fit_score``: the workbench's documented 0–100 document-match score. It is
  copied from the existing ``score`` field; values outside 0–100 are not
  rescaled or guessed, they become ``None``.
- ``fit_confidence``: how much resume evidence supports the requirements the
  score was computed on. Rule: take every row of ``mandatory_conditions`` and
  weight it by evidence —
  * 1.0 evidence recorded and status settled (``已满足`` / ``明确不满足``)
  * 0.5 evidence recorded but status still ``待确认``
  * 0.25 evidence recorded with an unrecognized status
  * 0.0 no evidence recorded
  and average the weights. With no ``mandatory_conditions`` at all, fall back
  to the posting's ``score_coverage`` (clamped to 0–1). No data means ``None``.
- ``risk_level``: ``low`` / ``medium`` / ``high`` from provenance and hiring
  status only:
  * ``high`` when the posting is closed, or when it carries no source at all
  * ``medium`` when the source is not one of the four supported platforms
    (for example a manual paste), or the hiring status is missing/unknown
  * ``low`` only when a supported platform and ``hiring_status == not_closed``
  * ``None`` when neither signal exists

No network access, no external dependency, no LLM call, no mutation.
"""

from __future__ import annotations

import sys
from typing import Any

sys.dont_write_bytecode = True

KNOWN_PLATFORMS = ("boss", "zhilian", "51job", "liepin")
SETTLED_STATUSES = ("已满足", "明确不满足")
PENDING_STATUSES = ("待确认",)


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:  # pragma: no cover - exotic objects
        return ""


def fit_score(job: dict[str, Any]) -> int | float | None:
    raw = (job or {}).get("score")
    # Only stored numbers count. Strings are not coerced: "80" from a hand-edited
    # file is treated as missing rather than silently accepted.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    if value < 0 or value > 100:
        return None
    return int(value) if value.is_integer() else round(value, 1)


def fit_confidence(job: dict[str, Any]) -> float | None:
    rows = (job or {}).get("mandatory_conditions")
    weights: list[float] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            status = _text(row.get("status")).strip()
            evidence = _text(row.get("evidence")).strip()
            if not evidence:
                weights.append(0.0)
            elif status in SETTLED_STATUSES:
                weights.append(1.0)
            elif status in PENDING_STATUSES:
                weights.append(0.5)
            else:
                weights.append(0.25)
    if weights:
        return round(sum(weights) / len(weights), 2)
    coverage = (job or {}).get("score_coverage")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        return None
    value = float(coverage)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return round(min(max(value, 0.0), 1.0), 2)


def risk_level(job: dict[str, Any]) -> str | None:
    job = job or {}
    hiring = _text(job.get("hiring_status")).strip().lower()
    source = (
        _text(job.get("source_platform")).strip()
        or _text(job.get("source_channel")).strip()
    ).lower()
    if not hiring and not source:
        return None
    if hiring == "closed":
        return "high"
    if not source:
        return "high"
    if source not in KNOWN_PLATFORMS:
        return "medium"
    if hiring == "not_closed":
        return "low"
    return "medium"


def match_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return the three separate match signals for one job row."""

    return {
        "fit_score": fit_score(job),
        "fit_confidence": fit_confidence(job),
        "risk_level": risk_level(job),
    }
