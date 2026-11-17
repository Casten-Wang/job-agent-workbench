#!/usr/bin/env python3
"""Offline JD intake: pasted text -> structured JSON (TASK-03).

CLI:
    python3 -I tools/jd_intake.py --input <file.md> --out <file.json> --id <stable-id>

The input file is untrusted data.  It is read as UTF-8 text and parsed only
with explicit ``label: value`` markers listed in tools/config.json.  No shell,
eval, exec, import of JD content, network call, LLM call, or application
submission is performed.  Text that looks like an instruction to an agent is
quoted verbatim in ``input_anomalies`` and never acted on.

Output is standard JSON with the required fields:
    id, is_job_post, fingerprint, hard_filter, warnings, analytics,
    company, title, city, salary_min, salary_max, source_channel,
    posted_at, contact, raw_text
plus ``salary_text``, ``salary_parse``, ``title_match`` and
``input_anomalies`` as explicit audit data.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# ``python3 -I`` does not add the script's directory to sys.path.  Make the
# sibling modules importable without touching PYTHONPATH or installing any
# package.  Only these known local modules are imported.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

import filters  # noqa: E402  (local module, path set above)
from filters import load_config  # noqa: E402

FIELDS = (
    "company",
    "title",
    "city",
    "salary_min",
    "salary_max",
    "source_channel",
    "posted_at",
    "contact",
    "raw_text",
)


def _collapse(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _marker_map(config: dict[str, Any]) -> dict[str, str]:
    """Marker text -> canonical field name, longest marker first."""

    mapping: dict[str, str] = {}
    for field, labels in config["jd_markers"].items():
        if not isinstance(labels, list):
            continue
        for label in labels:
            key = _collapse(str(label)).casefold()
            mapping.setdefault(key, field)
    return mapping


def _parse_labeled_lines(
    text: str, markers: dict[str, str]
) -> dict[str, str]:
    """Parse only lines with an explicit ``marker: value`` shape.

    Both ASCII ``:`` and full-width ``：`` are accepted.  Markdown emphasis on
    the label is ignored; a value is copied as text, never interpreted.
    """

    found: dict[str, str] = {}
    # Longest first so "公司名称" wins over "公司".
    alternatives = sorted((re.escape(key) for key in markers), key=len, reverse=True)
    if not alternatives:
        return found
    line_re = re.compile(
        r"^\s*(?:[-*+]\s+)?(?:[*_`]+\s*)?("
        + "|".join(alternatives)
        + r")\s*(?:[*_`]+\s*)?[:：]\s*(.*?)\s*$",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        match = line_re.match(line)
        if not match:
            continue
        field = markers[match.group(1).casefold()]
        value = _collapse(match.group(2))
        value = value.strip("`").strip()
        if value and field not in found:
            found[field] = value
    return found


def _detect_anomalies(
    text: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Quote suspicious instruction-like lines as data; execute nothing."""

    patterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in config["input_anomaly_patterns"]["patterns"]
    ]
    anomalies: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                anomalies.append(
                    {
                        "line": index,
                        "pattern": pattern.pattern,
                        "quote": line.strip()[:500],
                        "action": "quoted_as_untrusted_data_not_executed",
                    }
                )
                break
    return anomalies


def _is_job_post(
    labeled: dict[str, str], config: dict[str, Any]
) -> bool | None:
    explicit = labeled.get("is_job_post")
    if explicit is not None:
        yes_values = {
            str(value).casefold()
            for value in config["jd_markers"]["job_post_yes_values"]
        }
        return explicit.casefold() in yes_values
    required = config["jd_markers"]["is_job_post_require_fields"]
    if all(labeled.get(field) for field in required):
        return True
    return None


def _clean_int(value: Any) -> int | None:
    """Only accept an already-parsed integer; never convert free text."""

    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_jd_text(
    text: str, stable_id: str, config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Parse one pasted JD into the TASK-03 structured record."""

    cfg = config if config is not None else load_config()
    labeled = _parse_labeled_lines(text, _marker_map(cfg))
    anomalies = _detect_anomalies(text, cfg)
    is_job_post = _is_job_post(labeled, cfg)

    # Explicit salary_min/salary_max markers and the human-facing salary range
    # or negotiable marker are all passed to filters.py as data; that module
    # owns all salary parsing and never infers a missing lower bound.
    salary_min_marker = labeled.get("salary_min")
    salary_max_marker = labeled.get("salary_max")
    salary_text = labeled.get("salary")

    raw_fields: dict[str, Any] = {
        "company": labeled.get("company"),
        "title": labeled.get("title"),
        "city": labeled.get("city"),
        "source_channel": labeled.get("source_channel"),
        "posted_at": labeled.get("posted_at"),
        "contact": labeled.get("contact"),
        "raw_text": text,
        "salary_text": salary_text,
        "declared_salary_min": salary_min_marker,
        "declared_salary_max": salary_max_marker,
    }
    filter_result = filters.apply_hard_filters(raw_fields, cfg)

    salary_min = filter_result["salary_parse"]["salary_min"]
    salary_max = filter_result["salary_parse"]["salary_max"]

    warnings = list(filter_result["warnings"])
    if is_job_post is False:
        warnings.append(
            {
                "code": cfg["warning_codes"]["not_job_post"],
                "message": "显式标记表明该文本不是岗位记录；仍按原样结构化，不做自动丢弃",
                "field": "is_job_post",
            }
        )
    if anomalies:
        warnings.append(
            {
                "code": "input-anomalies-quoted",
                "message": "检测到疑似指令样文本，已原样摘录，未执行",
                "count": len(anomalies),
            }
        )

    analytics_cfg = cfg["analytics"]
    analytics = {
        "Source_Channel": labeled.get(
            analytics_cfg["Source_Channel"]["source_field"]
        ),
        "Rejection_Reason": analytics_cfg["Rejection_Reason"]["initial"],
        "LLM_Rewrite_Edited_Flag": analytics_cfg["LLM_Rewrite_Edited_Flag"]["initial"],
    }

    record: dict[str, Any] = {
        "id": stable_id,
        "is_job_post": is_job_post,
        "fingerprint": filter_result["fingerprint"],
        "hard_filter": filter_result["hard_filter"],
        "warnings": warnings,
        "analytics": analytics,
        "company": raw_fields["company"],
        "title": raw_fields["title"],
        "city": raw_fields["city"],
        "salary_min": _clean_int(salary_min),
        "salary_max": _clean_int(salary_max),
        "source_channel": raw_fields["source_channel"],
        "posted_at": raw_fields["posted_at"],
        "contact": raw_fields["contact"],
        "raw_text": text,
        # Audit-only fields: keep the original salary wording and parse detail.
        "salary_text": salary_text,
        "salary_parse": filter_result["salary_parse"],
        "title_match": filter_result["title_match"],
        "input_anomalies": anomalies,
    }
    # All nine spec fields are present, with None for anything not marked.
    missing = [field for field in FIELDS if field not in record]
    if missing:
        raise RuntimeError(f"internal contract error, missing fields: {missing}")
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Offline JD intake. Parse explicitly labeled pasted text, apply "
            "config-driven hard filters, and write one JSON record. No network, "
            "no LLM scoring, no submission, no credential handling."
        )
    )
    parser.add_argument("--input", required=True, help="path to pasted JD .md/.txt")
    parser.add_argument("--out", required=True, help="path for the output JSON")
    parser.add_argument("--id", required=True, dest="stable_id", help="stable record id")
    parser.add_argument(
        "--config",
        help="optional alternate config path (defaults to tools/config.json)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        text = Path(args.input).read_text(encoding="utf-8-sig")
        cfg = load_config(args.config) if args.config else load_config()
        record = parse_jd_text(text, args.stable_id, cfg)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError, KeyError, RuntimeError) as exc:
        parser.error(f"cannot process JD input: {exc}")
    print(
        json.dumps(
            {
                "out": str(Path(args.out)),
                "id": record["id"],
                "fingerprint": record["fingerprint"],
                "hard_filter": record["hard_filter"]["status"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
