#!/usr/bin/env python3
"""Convert a manually exported, static OfferPilot job-pool JSON into JD JSON.

This module is deliberately offline. It reads one local JSON file, normalizes
untrusted job data, and writes one local JSON file. It does not run OfferPilot,
connect to a browser, call a network service, submit an application, or handle
credentials. Every value from the export is data, including instruction-like
text; such text is preserved (after length/newline sanitation) and never acted
on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

SOURCE_CHANNEL = "offerpilot_manual_export"
FIELD_LIMITS = {
    "company": 160,
    "title": 160,
    "city": 80,
    "source_channel": 100,
    "posted_at": 100,
    "contact": 200,
    "raw_text": 15000,
    "url": 1000,
}
MAX_JOBS = 1000
MAX_SALARY = 10**9

# TASK-03 defaults, used only by the minimal fallback when tools/filters.py is
# unavailable. The adapter does not require config.json to exist.
TARGET_CITIES = ("上海", "长宁")
EXCLUDED_TERMS = ("外包", "驻场", "单休", "电销")
TITLE_KEYWORDS = ("AI产品经理", "商业分析师", "跨境电商", "产品经理", "数据分析")
SALARY_MIN_THRESHOLD = 15000.0

ZERO_WIDTH_RE = re.compile(r"[​‌‍﻿]")
WHITESPACE_RE = re.compile(r"\s+")
MARKDOWN_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
SALARY_RANGE_RE = re.compile(
    r"(?P<min>\d+(?:\.\d+)?)\s*(?P<min_unit>[kK千]?)\s*"
    r"(?:-|–|—|~|～|至|到)\s*"
    r"(?P<max>\d+(?:\.\d+)?)\s*(?P<max_unit>[kK千]?)"
)
SALARY_SINGLE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>[kK千]?)"
)

LEGAL_SUFFIXES = (
    "incorporated", "corporation", "company", "limited", "gmbh", "kgaa",
    "sarl", "eurl", "llc", "llp", "plc", "apc", "inc", "corp", "ltd",
    "lp", "pc", "ag", "mbh", "ug", "sas", "snc", "scs", "sca", "sa",
    "spa", "srl", "ltda", "saa", "sl", "sll", "slu", "bv", "nv", "cv",
    "ab", "as", "oy", "oyj", "kf", "sf", "aps", "se", "jsc", "pjsc",
    "zao", "ooo", "doo", "kft", "rt", "zrt", "pty", "pte", "pvt",
    "sdn", "bhd", "co",
)
CJK_LEGAL_SUFFIXES = (
    "股份有限公司", "有限责任公司", "有限公司", "公司",
    "株式会社", "有限会社",
)
_LATIN_SUFFIX_PATTERNS = sorted(
    {
        *(re.escape(suffix) for suffix in LEGAL_SUFFIXES),
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


class AdapterInputError(ValueError):
    """Raised when the manually supplied JSON does not have a supported shape."""


def clean_text(value: Any, limit: int) -> str | None:
    """Return a bounded, single-line-safe string without interpreting content.

    Instruction-like strings are retained as ordinary data. Only presentation
    characters that could break a Markdown table row and overlong content are
    removed. Missing values, empty strings, and non-scalar values become None.
    """

    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value)
    # Control characters and line breaks cannot be allowed into table cells.
    # U+0000 through U+001F and U+007F include CR/LF/TAB/NUL; C1 controls and
    # Unicode line/paragraph separators are also normalized to spaces.
    text = "".join(
        " " if (ord(ch) < 32 or 0x7F <= ord(ch) <= 0x9F or ch in "  ") else ch
        for ch in text
    )
    text = ZERO_WIDTH_RE.sub("", text)
    text = WHITESPACE_RE.sub(" ", text).strip()
    # Pipes are escaped for Markdown table cells. Formula-leading strings are
    # prefixed with an apostrophe for CSV-like consumers, after collapsing
    # leading whitespace; the underlying text remains present as data.
    text = text.replace("|", "\\|")
    if text.startswith(("=", "+", "-", "@")):
        text = "'" + text
    if not text:
        return None
    if len(text) > limit:
        text = text[:limit].rstrip()
    return text or None


def clean_nested_text(value: Any, limit: int = FIELD_LIMITS["raw_text"]) -> str | None:
    """Sanitize nested structured data by serializing it as opaque data."""

    if value is None or isinstance(value, (dict, list, tuple)):
        if value is None:
            return None
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            return None
    return clean_text(value, limit)


def _base_text(value: Any) -> str:
    """Mirror precheck._base_text for fingerprint normalization."""

    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return ZERO_WIDTH_RE.sub("", text).strip()


def _collapse_whitespace(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def _normalize_title_or_city(value: Any) -> str:
    return _collapse_whitespace(_base_text(value).casefold())


def _strip_cjk_legal_suffixes(value: str) -> str:
    text = value.strip(" \t\r\n,，.。;；:：")
    while True:
        for suffix in CJK_LEGAL_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)].strip(" \t\r\n,，.。;；:：")
                break
        else:
            return text


def _normalize_company(value: Any) -> str:
    text = _collapse_whitespace(_base_text(value).casefold())
    text = _strip_cjk_legal_suffixes(text)
    previous = None
    while text and text != previous:
        previous = text
        text = _LATIN_SUFFIX_RE.sub("", text)
        text = text.strip(" \t\r\n,，.。;；:：")
    return WHITESPACE_RE.sub("", text).strip(" \t\r\n,，.。;；:：")


def local_compute_fingerprint(company: Any, title: Any, city: Any) -> str:
    """Local equivalent of precheck.compute_fingerprint, including suffixes."""

    key = "|".join(
        (
            _normalize_company(company),
            _normalize_title_or_city(title),
            _normalize_title_or_city(city),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _load_precheck(tools_dir: Path | None = None):
    """Load precheck from the local tools directory, avoiding sys.path edits."""

    if tools_dir is None:
        tools_dir = Path(__file__).resolve().parent
    module_path = tools_dir / "precheck.py"
    if not module_path.is_file():
        return None, "precheck-module-missing"
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("_task07_precheck", module_path)
        if spec is None or spec.loader is None:
            return None, "precheck-import-failed"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = getattr(module, "compute_fingerprint", None)
        if not callable(function):
            return None, "precheck-fingerprint-missing"
        return function, None
    except Exception:  # untrusted/local module failure must not stop conversion
        return None, "precheck-import-failed"


def compute_fingerprint(company: Any, title: Any, city: Any) -> tuple[str, list[str]]:
    """Use precheck.compute_fingerprint when importable; else local fallback."""

    function, warning = _load_precheck()
    if function is not None:
        try:
            value = function(company, title, city)
            if isinstance(value, str) and value:
                local_value = local_compute_fingerprint(company, title, city)
                if value != local_value:
                    return local_value, ["precheck-fingerprint-mismatch-local-fallback"]
                return value, []
        except Exception:
            warning = "precheck-fingerprint-failed"
    return local_compute_fingerprint(company, title, city), [warning or "precheck-fingerprint-missing"]


def _first_present(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def _clean_salary_number(value: Any) -> int | float | None:
    """Accept finite JSON numbers and bounded numeric strings, without guessing."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = unicodedata.normalize("NFKC", value).strip().replace(",", "")
        if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
            return None
        number = float(text)
    else:
        return None
    if not math.isfinite(number) or number < 0 or number > MAX_SALARY:
        return None
    if number.is_integer():
        return int(number)
    return number


def _salary_unit_multiplier(text: str) -> float:
    """Return 1 for yuan/month, 1000 for K or 千; None when mixed/unknown."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    if re.search(r"[kK千]", normalized):
        return 1000.0
    if re.search(r"万", normalized):
        return 10000.0
    if re.fullmatch(r"[\d\s.,+\-~～–—至到元/月年月日]*", normalized):
        return 1.0
    return float("nan")


def _parse_salary_range(text: str) -> tuple[float, float] | None:
    """Parse only explicit numeric ranges; preserves no hidden assumptions."""

    normalized = unicodedata.normalize("NFKC", text).strip()
    if not normalized or "面议" in normalized or "negotiable" in normalized.casefold():
        return None
    multiplier = _salary_unit_multiplier(normalized)
    if math.isnan(multiplier):
        return None
    range_match = SALARY_RANGE_RE.search(normalized)
    if range_match:
        low = float(range_match.group("min"))
        high = float(range_match.group("max"))
        low *= 1000.0 if range_match.group("min_unit") else multiplier
        high *= 1000.0 if range_match.group("max_unit") else multiplier
        return (low, high) if low <= high else None
    single_match = SALARY_SINGLE_RE.search(normalized)
    if single_match:
        value = float(single_match.group("value"))
        value *= 1000.0 if single_match.group("unit") else multiplier
        return value, value
    return None


def _normalize_salary_bounds(
    record: dict[str, Any],
) -> tuple[int | float | None, int | float | None, str | None]:
    lower = _clean_salary_number(
        _first_present(record, ("salary_min", "min_salary", "salaryMin", "salary_lower"))
    )
    upper = _clean_salary_number(
        _first_present(record, ("salary_max", "max_salary", "salaryMax", "salary_upper"))
    )
    salary_text_value = _first_present(
        record, ("salary", "salary_text", "salaryText", "薪资", "salary_raw")
    )
    salary_text = clean_text(salary_text_value, FIELD_LIMITS["contact"])
    if lower is not None or upper is not None:
        if lower is not None and upper is not None and lower > upper:
            lower, upper = upper, lower
        return lower, upper, salary_text

    parsed = _parse_salary_range(salary_text or "")
    if parsed is None:
        return None, None, salary_text
    low, high = parsed
    return (
        int(low) if low.is_integer() else low,
        int(high) if high.is_integer() else high,
        salary_text,
    )


def normalize_record(value: Any, index: int) -> dict[str, Any]:
    """Normalize one untrusted job-pool entry into the standard JD shape."""

    warnings: list[str] = []
    if not isinstance(value, dict):
        value = {}
        warnings.append("record-not-object")

    company = clean_text(
        _first_present(value, ("company", "company_name", "companyName", "employer", "公司")),
        FIELD_LIMITS["company"],
    )
    title = clean_text(
        _first_present(
            value,
            ("title", "job_title", "jobTitle", "target_role", "targetRole", "position", "职位", "岗位"),
        ),
        FIELD_LIMITS["title"],
    )
    city = clean_text(
        _first_present(value, ("city", "work_city", "workCity", "location", "城市", "工作地点")),
        FIELD_LIMITS["city"],
    )
    salary_min, salary_max, salary_text = _normalize_salary_bounds(value)
    posted_at = clean_text(
        _first_present(
            value,
            ("posted_at", "postedAt", "publish_time", "publishTime", "created_at", "createdAt", "发布时间", "发布日期"),
        ),
        FIELD_LIMITS["posted_at"],
    )
    contact = clean_nested_text(
        _first_present(
            value,
            ("contact", "contacts", "hr", "hr_name", "hrName", "recruiter", "联系方式", "联系人"),
        ),
        FIELD_LIMITS["contact"],
    )
    url = clean_text(
        _first_present(value, ("url", "job_url", "jobUrl", "link", "岗位链接", "链接")),
        FIELD_LIMITS["url"],
    )
    raw_text = clean_nested_text(
        _first_present(
            value,
            ("raw_text", "rawText", "jd", "description", "job_description", "jobDescription", "JD", "岗位描述"),
        ),
        FIELD_LIMITS["raw_text"],
    )

    if company is None:
        warnings.append("company-missing")
    if title is None:
        warnings.append("title-missing")
    if city is None:
        warnings.append("city-missing")
    if salary_min is None:
        warnings.append("salary-min-missing")
    if salary_max is None:
        warnings.append("salary-max-missing")
    if salary_text is not None:
        warnings.append("salary-text-preserved-as-data")
    if posted_at is None:
        warnings.append("posted-at-missing")
    if contact is None:
        warnings.append("contact-missing")
    if raw_text is None:
        warnings.append("raw-text-missing")
    if url is None:
        warnings.append("url-missing")

    fingerprint, fingerprint_warnings = compute_fingerprint(company, title, city)
    warnings.extend(fingerprint_warnings)

    record: dict[str, Any] = {
        "company": company,
        "title": title,
        "city": city,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "source_channel": SOURCE_CHANNEL,
        "posted_at": posted_at,
        "contact": contact,
        "raw_text": raw_text,
        "url": url,
        "fingerprint": fingerprint,
    }
    # TASK-03 filters.parse_salary expects explicit text markers. Supply them
    # only to its adapter, never infer salary from arbitrary free text.
    filter_fields = dict(record)
    filter_fields["salary_text"] = salary_text
    if salary_min is not None:
        filter_fields["declared_salary_min"] = str(salary_min)
    if salary_max is not None:
        filter_fields["declared_salary_max"] = str(salary_max)
    hard_filter = evaluate_hard_filter(filter_fields)
    record["hard_filter"] = hard_filter
    warnings.extend(hard_filter.get("warnings", []))
    record["warnings"] = warnings
    record["analytics"] = {
        "Source_Channel": SOURCE_CHANNEL,
        "Rejection_Reason": hard_filter.get("reasons") or None,
        "LLM_Rewrite_Edited_Flag": False,
    }
    # The raw salary string and source index are kept outside the standard JD
    # fields as provenance; they are sanitized data, not execution directives.
    record["salary_text"] = salary_text
    record["source_index"] = index
    return record


def minimal_hard_filter(record: dict[str, Any]) -> dict[str, Any]:
    """Offline equivalent of TASK-03's documented hard rules."""

    reasons: list[str] = []
    warnings: list[str] = []
    searchable = " ".join(
        str(record.get(key) or "") for key in ("company", "title", "city", "raw_text")
    ).casefold()
    for term in EXCLUDED_TERMS:
        if term.casefold() in searchable:
            reasons.append(f"excluded-term:{term}")
    if record.get("city") is None:
        warnings.append("city-missing-pass-with-warning")
    else:
        city = str(record["city"])
        if not any(target in city for target in TARGET_CITIES):
            reasons.append("city-not-allowed")

    salary_min = record.get("salary_min")
    salary_max = record.get("salary_max")
    if salary_min is None and salary_max is None:
        warnings.append("salary-unparsable-pass-with-warning")
    else:
        upper = salary_max if salary_max is not None else salary_min
        try:
            if float(upper) < SALARY_MIN_THRESHOLD:
                reasons.append("salary-below-min")
        except (TypeError, ValueError):
            warnings.append("salary-unparsable-pass-with-warning")

    title = str(record.get("title") or "").casefold()
    if not any(keyword.casefold() in title for keyword in TITLE_KEYWORDS):
        warnings.append("title-direction-not-matched")

    return {
        "status": "reject" if reasons else "pass",
        "reasons": reasons,
        "warnings": warnings,
        "engine": "adapter-minimal-fallback",
    }


def evaluate_hard_filter(record: dict[str, Any]) -> dict[str, Any]:
    """Delegate to TASK-03 filters when safely callable, else fall back."""

    module_path = Path(__file__).resolve().parent / "filters.py"
    if not module_path.is_file():
        result = minimal_hard_filter(record)
        result["warnings"] = ["filters-module-missing"] + result["warnings"]
        return result
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location("_task07_filters", module_path)
        if spec is None or spec.loader is None:
            raise ImportError("no module spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function = None
        for name in ("apply_hard_filter", "apply_hard_filters", "hard_filter", "evaluate_hard_filter"):
            candidate = getattr(module, name, None)
            if callable(candidate):
                function = candidate
                break
        if function is None:
            raise AttributeError("no compatible filter function")
        raw = function(record)
        if not isinstance(raw, dict):
            raise TypeError("filter did not return a mapping")
        # TASK-03's apply_hard_filters returns a result envelope; support both
        # that shape and a flat {status, reasons, warnings} shape.
        decision = raw.get("hard_filter") if isinstance(raw.get("hard_filter"), dict) else raw
        status = str(decision.get("status") or decision.get("decision") or "").lower()
        if status not in {"pass", "reject"}:
            raise ValueError("filter returned an unknown status")
        reasons = decision.get("reasons", [])
        if not isinstance(reasons, list):
            reasons = [reasons]
        warning_items = raw.get("warnings") if isinstance(raw.get("warnings"), list) else []
        result = {
            "status": status,
            "reasons": [
                clean_text(
                    reason.get("code") if isinstance(reason, dict) else reason,
                    240,
                )
                or str(reason)
                for reason in reasons
            ],
            "warnings": [
                clean_text(
                    warning.get("code") if isinstance(warning, dict) else warning,
                    240,
                )
                or str(warning)
                for warning in warning_items
            ],
            "engine": "task03-filters",
        }
        return result
    except Exception:
        result = minimal_hard_filter(record)
        result["warnings"] = [
            "filters-module-unavailable-fallback"
        ] + result["warnings"]
        return result


def load_jobs(payload: Any) -> list[Any]:
    """Accept a list or {'jobs': [...]}; reject other shapes explicitly."""

    if isinstance(payload, list):
        jobs = payload
    elif isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        jobs = payload["jobs"]
    elif isinstance(payload, dict) and all(
        isinstance(payload.get(key), list) for key in ("data", "items", "results") if key in payload
    ):
        for key in ("data", "items", "results"):
            if isinstance(payload.get(key), list):
                jobs = payload[key]
                break
        else:
            raise AdapterInputError("expected a JSON array or an object containing jobs")
    else:
        raise AdapterInputError("expected a JSON array or an object containing jobs")
    if len(jobs) > MAX_JOBS:
        raise AdapterInputError(f"too many jobs: {len(jobs)} > {MAX_JOBS}")
    return jobs


def convert_payload(payload: Any) -> dict[str, Any]:
    """Convert the parsed export into the adapter's output contract."""

    jobs = load_jobs(payload)
    records = [normalize_record(job, index) for index, job in enumerate(jobs)]
    return {
        "source_channel": SOURCE_CHANNEL,
        "count": len(records),
        "jobs": records,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline converter for a manually exported OfferPilot job-pool JSON. "
            "Reads static local data only; never runs collection, delivery, "
            "browser control, or credential handling."
        )
    )
    parser.add_argument("--input", required=True, help="manually exported JSON file")
    parser.add_argument("--out", required=True, help="normalized JSON output file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.out)
    try:
        if input_path.resolve() == output_path.resolve():
            parser.error("--input and --out must refer to different files")
        payload = json.loads(input_path.read_text(encoding="utf-8-sig"))
        result = convert_payload(payload)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, json.JSONDecodeError, AdapterInputError) as exc:
        parser.error(f"cannot convert {str(input_path)!r}: {exc}")
    print(f"normalized {result['count']} jobs from {str(input_path)} to {str(output_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
