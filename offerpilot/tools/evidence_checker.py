#!/usr/bin/env python3
"""Read-only check: does a generated text's numbers trace back to the
user's confirmed facts (resume/profile), or were they invented?

This module never edits, redacts, or censors the generated text. It only
reports which quantified claims in the text have no matching number in the
supplied fact source, so a human reviewer (or an upstream gate) can decide
whether to block, edit, or approve. "No evidence found" is reported
conservatively: a number is only flagged when it is a *quantified claim*
(number + unit/comparison word, the same heuristic used by
``tools/resume_quality.py``) and does not appear, under loose formatting,
anywhere in the fact text.

No network access, no external dependency, no LLM call.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

sys_dont_write_bytecode = True

# Reuse the same "number + unit/comparison word" window heuristic as
# tools/resume_quality.py so a bare id-like number (a year, a job id) is not
# treated as a quantified claim that needs evidence.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_QUANT_UNIT_RE = re.compile(
    r"(%|％|倍|人|份|次|天|周|小时|分钟|篇|条|个|名|元|万|k|K|降到?|提升|缩短|精简|减少|增加|提高)"
)
_YEAR_ONLY_RE = re.compile(r"(?<!\d)(20\d{2}|19\d{2})年?(?!\d)")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def _strip_number_formatting(number_text: str) -> str:
    """Collapse "1,000" / "1000.0" / "1000" to one comparable form."""

    cleaned = number_text.replace(",", "").replace("，", "")
    if cleaned.endswith(".0"):
        cleaned = cleaned[:-2]
    return cleaned


def _extract_quantified_claims(text: str) -> list[dict[str, Any]]:
    """Return each number in ``text`` that reads as a quantified claim."""

    claims: list[dict[str, Any]] = []
    for match in _NUMBER_RE.finditer(text):
        start, end = match.span()
        window = text[max(0, start - 4) : min(len(text), end + 4)]
        raw = match.group()
        if _YEAR_ONLY_RE.fullmatch(raw) and not _QUANT_UNIT_RE.search(window):
            continue
        if not _QUANT_UNIT_RE.search(window):
            continue
        claims.append(
            {
                "value": raw,
                "normalized_value": _strip_number_formatting(raw),
                "context": text[max(0, start - 10) : min(len(text), end + 10)],
            }
        )
    return claims


def _fact_numbers(fact_text: str) -> set[str]:
    """All numbers that appear anywhere in the fact source, normalized.

    Unlike claim extraction, this does not require a unit/comparison word
    next to the number in the fact text: the same figure may be phrased
    differently there (e.g. a table cell), and the goal is only to check
    whether the number itself is traceable, not to re-apply the quantified
    heuristic to the source.
    """

    return {
        _strip_number_formatting(match.group())
        for match in _NUMBER_RE.finditer(fact_text)
    }


def check_text_against_facts(generated_text: str, fact_text: str) -> dict[str, Any]:
    """Check ``generated_text``'s quantified claims against ``fact_text``.

    Returns:
      - ``claims``: every quantified claim found in ``generated_text``, each
        with ``has_evidence`` (bool) and its surrounding ``context``.
      - ``unsupported_claims``: the subset with no matching number in
        ``fact_text``; this is the list a caller should treat as a gate.
      - ``ok``: True only when there are zero unsupported claims. This is a
        read-only verdict for the caller to act on; this function never
        blocks, edits, or removes anything itself.
    """

    normalized_generated = _normalize(generated_text or "")
    normalized_facts = _normalize(fact_text or "")
    fact_numbers = _fact_numbers(normalized_facts)

    claims = _extract_quantified_claims(normalized_generated)
    for claim in claims:
        claim["has_evidence"] = claim["normalized_value"] in fact_numbers

    unsupported = [claim for claim in claims if not claim["has_evidence"]]
    return {
        "claims": claims,
        "unsupported_claims": unsupported,
        "ok": not unsupported,
    }
