#!/usr/bin/env python3
"""Offline channel ROI, rejection reasons, and quarterly radar aggregation.

All inputs are local JSON/JSONL files. No network, no LLM, no drawing library,
and no personal identifiers are emitted: output contains only channels, reason
strings, quarter labels, and counts. Missing Rejection_Reason is reported as
``unknown`` rather than guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

DEFAULT_LOG = _TOOLS_DIR / "data" / "status-log.jsonl"
CONFIG_PATH = _TOOLS_DIR / "config_task04.json"
DATE_RE = re.compile(r"(20\d{2})[-/年.]\s*(0?[1-9]|1[0-2])[-/月.]\s*(0?[1-9]|[12]\d|3[01])")
APPLIED_STATES = frozenset({"已投递/已沟通", "笔试/测评", "一面", "二面/终面", "Offer", "淘汰"})
INTERVIEW_STATES = frozenset({"一面", "二面/终面"})
RADAR_AXES = (
    "投递数", "面试数", "Offer数", "逻辑漏洞", "量化不足",
    "STAR缺失", "业务理解", "表达冗余",
)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def load_status_log(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = Path(path or DEFAULT_LOG)
    if not target.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


def _first(record: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return None


def source_channel(record: dict[str, Any]) -> str:
    value = _first(record, ("Source_Channel", "source_channel", "Source Channel"))
    if value is None and isinstance(record.get("analytics"), dict):
        value = record["analytics"].get("Source_Channel")
    return str(value).strip() if value not in (None, "") else "unknown"


def rejection_reason(record: dict[str, Any]) -> str:
    value = _first(record, ("Rejection_Reason", "rejection_reason", "rejectionReason"))
    if value is None and isinstance(record.get("analytics"), dict):
        value = record["analytics"].get("Rejection_Reason")
    if value is None or str(value).strip() in {"", "null", "None"}:
        return "unknown"
    return str(value).strip()


def _quarter(record: dict[str, Any]) -> str:
    explicit = str(record.get("quarter") or "").strip()
    if re.fullmatch(r"20\d{2}Q[1-4]", explicit):
        return explicit
    for name in ("recorded_at", "updated_at", "created_at", "date", "posted_at"):
        match = DATE_RE.search(str(record.get(name) or ""))
        if match:
            year, month = int(match.group(1)), int(match.group(2))
            return f"{year}Q{(month - 1) // 3 + 1}"
    return "unknown"


def _id(record: dict[str, Any]) -> str:
    return str(_first(record, ("job_id", "id", "jobId")) or "unknown")


def _state(record: dict[str, Any]) -> str:
    return str(_first(record, ("status", "state", "to", "current_state")) or "")


def normalize_jobs(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        rows = payload["jobs"]
    else:
        raise ValueError("jobs input must be an array or an object with a jobs array")
    return [row for row in rows if isinstance(row, dict)]


def analyze(
    jobs: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    debriefs: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    events = events if events is not None else []
    debriefs = debriefs or []
    by_id = {_id(row): row for row in jobs}

    applied: dict[str, set[str]] = defaultdict(set)
    interview: dict[str, set[str]] = defaultdict(set)
    offer: dict[str, set[str]] = defaultdict(set)
    rejected: dict[str, set[str]] = defaultdict(set)
    reason_seen: dict[str, set[str]] = defaultdict(set)
    reason_unknown: dict[str, set[str]] = defaultdict(set)
    quarters_seen: set[str] = set()
    quarter_counts: dict[tuple[str, str], int] = defaultdict(int)

    def mark(channel: str, job_id: str, bucket: str, quarter: str) -> None:
        target = {"applied": applied, "interview": interview, "offer": offer}[bucket]
        quarters_seen.add(quarter)
        if job_id not in target[channel]:
            target[channel].add(job_id)
            quarter_counts[(quarter, bucket)] += 1

    def mark_reason(channel: str, job_id: str, reason: str) -> None:
        rejected[channel].add(job_id)
        reason_seen[channel].add(job_id)
        if reason == "unknown":
            reason_unknown[channel].add(job_id)

    for row in jobs:
        channel = source_channel(row)
        job_id = _id(row)
        state = _state(row)
        reason = rejection_reason(row)
        quarter = _quarter(row)
        if state in APPLIED_STATES or row.get("applied") is True:
            mark(channel, job_id, "applied", quarter)
        if state in INTERVIEW_STATES:
            mark(channel, job_id, "interview", quarter)
        if state == "Offer":
            mark(channel, job_id, "offer", quarter)
        if state == "淘汰" or reason != "unknown":
            mark_reason(channel, job_id, reason)

    for event in events:
        job_id = str(event.get("job_id") or "unknown")
        row = by_id.get(job_id, {})
        channel = source_channel(row)
        from_state = str(event.get("from") or "")
        to_state = str(event.get("to") or "")
        quarter = _quarter(event) if event.get("recorded_at") else _quarter(row)
        quarters_seen.add(quarter)
        if from_state in APPLIED_STATES or to_state in APPLIED_STATES:
            mark(channel, job_id, "applied", quarter)
        if from_state in INTERVIEW_STATES or to_state in INTERVIEW_STATES:
            mark(channel, job_id, "interview", quarter)
        if from_state == "Offer" or to_state == "Offer":
            mark(channel, job_id, "offer", quarter)
        if to_state == "淘汰":
            mark_reason(channel, job_id, rejection_reason(row))

    weakness: dict[tuple[str, str], int] = defaultdict(int)
    for debrief in debriefs:
        quarter = _quarter(debrief)
        quarters_seen.add(quarter)
        tags = debrief.get("weakness_tags") or []
        if not isinstance(tags, list):
            continue
        for tag in tags:
            label = str(tag)
            if label in RADAR_AXES:
                weakness[(quarter, label)] += 1

    all_channels = set(applied) | set(interview) | set(offer) | set(rejected)
    channel_rows = []
    for channel in sorted(all_channels):
        count_applied = len(applied[channel])
        count_interview = len(interview[channel])
        count_offer = len(offer[channel])
        channel_rows.append(
            {
                "Source_Channel": channel,
                "投递数": count_applied,
                "面试数": count_interview,
                "Offer数": count_offer,
                "淘汰数": len(rejected[channel]),
                "面试转化率": round(count_interview / count_applied, 3) if count_applied else 0.0,
                "Offer转化率": round(count_offer / count_applied, 3) if count_applied else 0.0,
                "Rejection_Reason_present": len(reason_seen[channel]),
                "Rejection_Reason_unknown": len(reason_unknown[channel]),
            }
        )

    radar_quarters: dict[str, dict[str, int]] = {}
    for quarter in sorted(quarters_seen):
        counts = {axis: 0 for axis in RADAR_AXES}
        counts["投递数"] = quarter_counts[(quarter, "applied")]
        counts["面试数"] = quarter_counts[(quarter, "interview")]
        counts["Offer数"] = quarter_counts[(quarter, "offer")]
        for axis in RADAR_AXES[3:]:
            counts[axis] = weakness[(quarter, axis)]
        radar_quarters[quarter] = counts

    return {
        "engine": "offline-deterministic-aggregation",
        "sync_sla_seconds": cfg["sync_sla_seconds"],
        "channels": channel_rows,
        "quarterly_radar": {
            "axes": list(RADAR_AXES),
            "quarters": radar_quarters,
            "note": "JSON only; no chart is drawn. Unknown quarter is reported separately.",
        },
        "limitations": [
            "Rejection_Reason missing is counted as unknown, never inferred.",
            "Quarter is derived from explicit local timestamps; absent timestamps use unknown.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline channel ROI and quarterly radar JSON")
    parser.add_argument("--jobs", required=True, help="local JSON array or {jobs: [...]}")
    parser.add_argument("--log", help="optional local status-log.jsonl")
    parser.add_argument("--debriefs", help="optional local JSON array of debrief cards")
    parser.add_argument("--out", help="optional output JSON path")
    args = parser.parse_args(argv)
    try:
        jobs = normalize_jobs(json.loads(Path(args.jobs).read_text(encoding="utf-8-sig")))
        events = load_status_log(args.log) if args.log else []
        debriefs: list[dict[str, Any]] = []
        if args.debriefs:
            payload = json.loads(Path(args.debriefs).read_text(encoding="utf-8-sig"))
            raw = payload if isinstance(payload, list) else payload.get("debriefs", [])
            debriefs = [item for item in raw if isinstance(item, dict)]
        result = analyze(jobs, events, debriefs)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
