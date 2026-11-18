#!/usr/bin/env python3
"""Local hard-rule filter for pasted job descriptions (TASK-03).

This module is pure Python 3 standard library.  It treats JD text as untrusted
data: it never evaluates it, follows instructions embedded in it, opens a
network connection, invokes an LLM, or submits anything.  Every default value
(cities, excluded terms, title keywords, salary floor, score thresholds,
normalizer, warning/reason codes) is read from ``tools/config.json``.

The public entry point is :func:`apply_hard_filters`, which returns a JSON-safe
dictionary with ``hard_filter``, ``warnings``, ``salary_parse``, ``title_match``
and ``fingerprint``.  ``jd_intake.py`` uses it to assemble the final record;
tests import it directly to verify the rules.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
_ZERO_WIDTH_RE = re.compile("[​‌‍﻿]")
_WHITESPACE_RE = re.compile(r"\s+")
_MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")

# The same legal-suffix list used by tools/precheck.py.  Kept here as behavior
# (not a configurable default) so cross-platform fingerprints agree even when
# filters.py is imported without precheck on sys.path.
_CJK_LEGAL_SUFFIXES = tuple(
    sorted(
        ("股份有限公司", "有限责任公司", "有限公司", "公司", "株式会社", "有限会社"),
        key=len,
        reverse=True,
    )
)
_LATIN_SUFFIX_PATTERNS = sorted(
    {
        "incorporated",
        "corporation",
        "company",
        "limited",
        "gmbh",
        "kgaa",
        "sarl",
        "eurl",
        "llc",
        "llp",
        "plc",
        "apc",
        "inc",
        "corp",
        "ltd",
        "lp",
        "pc",
        "ag",
        "mbh",
        "ug",
        "sas",
        "snc",
        "scs",
        "sca",
        "sa",
        "spa",
        "srl",
        "ltda",
        "saa",
        "sl",
        "sll",
        "slu",
        "bv",
        "nv",
        "cv",
        "ab",
        "as",
        "oy",
        "oyj",
        "kf",
        "sf",
        "aps",
        "se",
        "jsc",
        "pjsc",
        "zao",
        "ooo",
        "doo",
        "kft",
        "rt",
        "zrt",
        "pty",
        "pte",
        "pvt",
        "sdn",
        "bhd",
        "co",
        r"co\.?,?\s*ltd\.?",
        r"pty\.?\s*ltd\.?",
        r"pte\.?\s*ltd\.?",
        r"pvt\.?\s*ltd\.?",
        r"s\.a\.r\.l\.?",
        r"s\.a\.s\.?",
        r"s\.a\.?",
        r"b\.v\.?",
        r"n\.v\.?",
        r"k\.k\.?",
    },
    key=len,
    reverse=True,
)
_LATIN_SUFFIX_RE = re.compile(
    r"(?:[,\s，]+(?:" + "|".join(_LATIN_SUFFIX_PATTERNS) + r")\.?\s*[.,;:]*)$",
    re.IGNORECASE,
)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the single source of truth for all configurable defaults."""

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    return json.loads(config_path.read_text(encoding="utf-8"))


def _base_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return _ZERO_WIDTH_RE.sub("", text).strip()


def _collapse_whitespace(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def normalize_title(value: Any) -> str:
    """Case-fold, width-normalize, and collapse whitespace in a title."""

    return _collapse_whitespace(_base_text(value).casefold())


def normalize_city(value: Any) -> str:
    """Case-fold, width-normalize, and collapse whitespace in a city."""

    return _collapse_whitespace(_base_text(value).casefold())


def _strip_cjk_legal_suffixes(value: str) -> str:
    text = value.strip(" \t\r\n,，.。;；:：")
    while True:
        for suffix in _CJK_LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].strip(" \t\r\n,，.。;；:：")
                break
        else:
            return text


def normalize_company(value: Any) -> str:
    """Remove common legal suffixes, case-fold, and remove whitespace."""

    text = _collapse_whitespace(_base_text(value).casefold())
    text = _strip_cjk_legal_suffixes(text)
    previous = None
    while text and text != previous:
        previous = text
        text = _LATIN_SUFFIX_RE.sub("", text)
        text = text.strip(" \t\r\n,，.。;；:：")
    return _WHITESPACE_RE.sub("", text).strip(" \t\r\n,，.。;；:：")


def compute_fingerprint(
    company: Any, title: Any, city: Any, config: dict[str, Any] | None = None
) -> str:
    """sha256(normalize(company)|normalize(title)|normalize(city)) from config."""

    cfg = config if config is not None else load_config()
    spec = cfg["fingerprint"]
    normalizers = {
        "company": normalize_company,
        "title": normalize_title,
        "city": normalize_city,
    }
    values = {"company": company, "title": title, "city": city}
    key = spec["separator"].join(
        normalizers[field](values[field]) for field in spec["fields"]
    )
    if spec["algorithm"] != "sha256":
        raise ValueError(f"unsupported fingerprint algorithm: {spec['algorithm']!r}")
    return hashlib.sha256(key.encode(spec["encoding"])).hexdigest()


def _to_amount(number: float, unit: str, salary_cfg: dict[str, Any]) -> int | None:
    if unit in salary_cfg["k_units"]:
        number *= float(salary_cfg["k_multiplier"])
    result = round(number)
    # Guard against corrupt configuration rather than silently guessing.
    if result < 0:
        return None
    return result


def parse_salary(
    value: Any,
    config: dict[str, Any] | None = None,
    salary_max_hint: Any = None,
    explicit_numeric: bool = False,
) -> dict[str, Any]:
    """Parse explicit salary text only; never guess an unparsable value.

    Supported: ``15k-25k``, ``15000-25000``, ``15K~25K 元/月``, ``面议``
    (seen as explicit negotiable text), and a single explicit numeric amount.
    ``explicit_numeric=True`` is used only for an explicitly labeled
    ``salary_min`` marker: the label itself supplies the salary context, so a
    bare number is not a guess.  ``salary_max_hint`` is only used to supply an
    upper bound when a lower bound was declared; it never creates a lower bound.
    """

    cfg = config if config is not None else load_config()
    salary_cfg = cfg["salary"]
    text = _collapse_whitespace(_base_text(value))
    result: dict[str, Any] = {
        "status": "unparsable",
        "text": text or None,
        "salary_min": None,
        "salary_max": None,
        "reason": None,
    }
    if not text:
        return result

    lowered = text.casefold()
    for marker in salary_cfg["unparsable_markers"]:
        if _base_text(marker).casefold() in lowered:
            result["reason"] = "explicit-negotiable"
            return result

    range_re = re.compile(salary_cfg["range_pattern"])
    match = range_re.search(text)
    if match:
        low = _to_amount(
            float(match.group("min")), match.group("min_unit") or "", salary_cfg
        )
        high = _to_amount(
            float(match.group("max")), match.group("max_unit") or "", salary_cfg
        )
        if low is None or high is None:
            result["reason"] = "invalid-amount"
            return result
        # A unit on either side applies to both sides: "15-25k" means 15k-25k.
        if (match.group("min_unit") or match.group("max_unit")) and (
            not match.group("min_unit") or not match.group("max_unit")
        ):
            unit = match.group("min_unit") or match.group("max_unit") or ""
            low = _to_amount(float(match.group("min")), unit, salary_cfg)
            high = _to_amount(float(match.group("max")), unit, salary_cfg)
            if low is None or high is None:
                result["reason"] = "invalid-amount"
                return result
        if low > high:
            result["reason"] = "invalid-range"
            return result
        result.update(
            {
                "status": "parsed",
                "salary_min": low,
                "salary_max": high,
            }
        )
        return result

    amount_re = re.compile(salary_cfg["amount_pattern"])
    match = amount_re.search(text)
    if match and (
        explicit_numeric or _has_explicit_salary_unit(text, match, salary_cfg)
    ):
        amount = _to_amount(
            float(match.group("amount")), match.group("unit") or "", salary_cfg
        )
        if amount is None:
            result["reason"] = "invalid-amount"
            return result
        hint_text = _collapse_whitespace(_base_text(salary_max_hint))
        hint_match = amount_re.search(hint_text) if hint_text else None
        high = amount
        if hint_match and explicit_numeric:
            candidate = _to_amount(
                float(hint_match.group("amount")),
                hint_match.group("unit") or "",
                salary_cfg,
            )
            if candidate is not None and candidate >= amount:
                high = candidate
        result.update(
            {
                "status": "parsed",
                "salary_min": amount,
                "salary_max": high,
            }
        )
        return result

    result["reason"] = "no-recognized-salary-pattern"
    return result


def _has_explicit_salary_unit(
    text: str, match: re.Match[str], salary_cfg: dict[str, Any]
) -> bool:
    """Require a unit for a bare number so arbitrary JD numbers are not salaries."""

    if match.group("unit") in salary_cfg["k_units"]:
        return True
    return bool(re.search(r"元|/月|薪|工资|salary", text, re.IGNORECASE))


# 紧挨在排除词前面的否定说法：「非外包」「无需驻场」「不接受单休」「拒绝外包」。
_NEGATION_PREFIXES = ("非", "无", "无需", "不", "不是", "不接受", "不需要", "没有", "拒绝", "杜绝")
_NEGATION_WINDOW = max(len(prefix) for prefix in _NEGATION_PREFIXES)


def _has_unnegated_term(text: str, term: str) -> bool:
    """True when ``term`` occurs at least once without a negation right before it."""

    start = text.find(term)
    while start != -1:
        before = text[max(0, start - _NEGATION_WINDOW):start]
        if not any(before.endswith(prefix) for prefix in _NEGATION_PREFIXES):
            return True
        start = text.find(term, start + 1)
    return False


def _searchable_text(fields: dict[str, Any]) -> str:
    parts = []
    for key in ("company", "title", "city", "source_channel", "contact", "raw_text"):
        value = fields.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).casefold()


def apply_hard_filters(
    fields: dict[str, Any], config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply every rule in TASK-03 section 2 and return a JSON-safe result.

    ``fields`` must already be extracted by ``jd_intake.parse_jd_text``.
    The function is deterministic and has no side effects beyond reading the
    config file when one is not supplied.
    """

    cfg = config if config is not None else load_config()
    codes = cfg["warning_codes"]
    reason_codes = cfg["reason_codes"]
    warnings: list[dict[str, Any]] = []
    reasons: list[dict[str, Any]] = []

    company = fields.get("company")
    title = fields.get("title")
    city = fields.get("city")
    salary_text = fields.get("salary_text")
    declared_min_text = fields.get("declared_salary_min")
    declared_max_text = fields.get("declared_salary_max")
    declared_min = (
        parse_salary(declared_min_text, cfg, declared_max_text, explicit_numeric=True)
        if declared_min_text
        else None
    )
    declared_max = (
        parse_salary(declared_max_text, cfg, explicit_numeric=True)
        if declared_max_text
        else None
    )

    def warning(code: str, message: str, **extra: Any) -> None:
        item = {"code": code, "message": message}
        item.update(extra)
        warnings.append(item)

    def reject(code: str, message: str, **extra: Any) -> None:
        item = {"code": code, "message": message}
        item.update(extra)
        reasons.append(item)

    # Missing core identity fields are warnings, not invented values.
    if not normalize_company(company):
        warning(codes["missing_company"], "公司字段缺失，未猜测公司名")
    if not normalize_title(title):
        warning(codes["missing_title"], "岗位字段缺失，未猜测岗位名")

    # City: allowed list is from config.  An empty city passes with a warning.
    city_text = _collapse_whitespace(_base_text(city))
    if not city_text:
        warning(
            codes["city_missing"],
            "城市为空，按默认策略放行并记 warning",
            field="city",
        )
    else:
        targets = [_base_text(item).casefold() for item in cfg["target_cities"]]
        normalized_city = city_text.casefold()
        if not any(target and target in normalized_city for target in targets):
            reject(
                reason_codes["city_not_allowed"],
                f"城市不在目标城市列表：{city_text}",
                field="city",
                value=city_text,
            )

    # Salary: parse explicitly, never guess.  Unparsable passes with a warning.
    # An explicitly labeled salary_min marker is the source of truth; a
    # salary_max marker alone never creates a lower bound.
    if declared_min is not None and declared_min["salary_min"] is not None:
        salary_result = declared_min
    else:
        salary_result = parse_salary(salary_text, cfg)
    salary_min = salary_result["salary_min"]
    salary_max = salary_result["salary_max"]
    if (
        declared_max is not None
        and declared_max["salary_min"] is not None
        and salary_min is not None
        and declared_max["salary_min"] >= salary_min
    ):
        salary_max = declared_max["salary_min"]
    if salary_result["status"] != "parsed" or salary_min is None:
        warning(
            codes["salary_unparsable"],
            "薪资无法解析，按默认策略放行并记 warning，不猜测",
            field="salary",
            text=salary_result["text"],
            parse_reason=salary_result["reason"],
        )
    else:
        threshold = int(cfg["salary"]["min_threshold"])
        if salary_min < threshold:
            reject(
                reason_codes["salary_below_min"],
                f"薪资下限 {salary_min} 低于配置阈值 {threshold}",
                field="salary_min",
                value=salary_min,
                threshold=threshold,
            )

    # Excluded terms are hard rejects.  Search only trusted extracted fields
    # plus raw_text as *data*: a match is quoted, never interpreted.
    searchable = _searchable_text(fields)
    for term in cfg["excluded_terms"]:
        term_text = _base_text(term).casefold()
        if term_text and _has_unnegated_term(searchable, term_text):
            reject(
                reason_codes["excluded_term"],
                f"命中硬性排除词：{term}",
                field="jd_text",
                term=term,
            )

    # Direction keywords are advisory only; section 2 does not make them a
    # rejection rule.  Substring match because e.g. "高级产品经理" contains
    # "产品经理".  Avoid double-counting when one keyword contains another.
    title_text = _base_text(title).casefold()
    matched_keywords = []
    unmatched_keywords = []
    for keyword in cfg["title_keywords"]:
        keyword_text = _base_text(keyword).casefold()
        if keyword_text and keyword_text in title_text:
            matched_keywords.append(keyword)
        else:
            unmatched_keywords.append(keyword)
    if not matched_keywords:
        warning(
            codes["title_direction"],
            "岗位名称未命中配置中的岗位方向关键词（仅提示，不作为硬性拒绝）",
            field="title",
            keywords=list(cfg["title_keywords"]),
        )

    fingerprint = compute_fingerprint(company, title, city, cfg)
    status = "reject" if reasons else "pass"
    return {
        "hard_filter": {
            "status": status,
            "pass": status == "pass",
            "reasons": reasons,
        },
        "warnings": warnings,
        "salary_parse": {
            "status": salary_result["status"],
            "text": salary_result["text"],
            "reason": salary_result["reason"],
            "salary_min": salary_min,
            "salary_max": salary_max,
            "threshold": int(cfg["salary"]["min_threshold"]),
        },
        "title_match": {
            "matched": matched_keywords,
            "unmatched": unmatched_keywords,
        },
        "fingerprint": fingerprint,
    }
