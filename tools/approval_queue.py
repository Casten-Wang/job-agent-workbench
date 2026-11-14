#!/usr/bin/env python3
"""Local approval queue with explicit confirmation.

Entries under 4.0 are dropped; 4.0–4.4 and >=4.5 are both queued as pending
until an explicit `--confirm <ids>` command. Approval never submits anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task06.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _TOOLS_DIR.parent / path


def load_queue(path: str | Path | None = None, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = config or load_config()
    target = _resolve(path or cfg["approval"]["queue_path"])
    if not target.is_file():
        return []
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    rows = payload if isinstance(payload, list) else payload.get("items")
    if not isinstance(rows, list):
        raise ValueError("approval queue must be an array or {items: [...]}")
    return [row for row in rows if isinstance(row, dict)]


def save_queue(rows: list[dict[str, Any]], path: str | Path | None = None, config: dict[str, Any] | None = None) -> Path:
    cfg = config or load_config()
    target = _resolve(path or cfg["approval"]["queue_path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)
    return target


def _score(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("score must be a number, not a boolean")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("score must be finite")
    return number


def _fingerprint(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "").strip() for key in ("id", "company", "title", "Source_Channel"))


def enqueue(
    jobs: list[dict[str, Any]],
    path: str | Path | None = None,
    config: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    rows = load_queue(path, cfg)
    existing = {_fingerprint(row) for row in rows}
    threshold = float(cfg["score"]["approval_min"])
    accepted: list[str] = []
    dropped: list[str] = []
    duplicate: list[str] = []
    stamp = (now or dt.datetime.now(dt.timezone.utc).astimezone()).isoformat()
    for job in jobs:
        job_id = str(job.get("id") or job.get("job_id") or "").strip()
        if not job_id:
            dropped.append("missing-id")
            continue
        try:
            score = _score(job.get("score"))
        except (TypeError, ValueError):
            dropped.append(job_id)
            continue
        if score < threshold:
            dropped.append(job_id)
            continue
        entry = {
            "id": job_id,
            "score": score,
            "company": str(job.get("company") or ""),
            "title": str(job.get("title") or ""),
            "status": cfg["approval"]["pending_status"],
            "Source_Channel": str(job.get("Source_Channel") or job.get("source_channel") or "unknown"),
            "created_at": stamp,
            "high_confidence": score >= float(cfg["score"]["high_threshold"]),
        }
        key = _fingerprint(entry)
        if key in existing:
            duplicate.append(job_id)
            continue
        existing.add(key)
        rows.append(entry)
        accepted.append(job_id)
    save_queue(rows, path, cfg)
    return {"accepted": accepted, "dropped": dropped, "duplicate": duplicate, "count": len(rows)}


def list_pending(
    date: str | None = None,
    path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cfg = config or load_config()
    rows = load_queue(path, cfg)
    pending = [row for row in rows if row.get("status") == cfg["approval"]["pending_status"]]
    if date:
        pending = [row for row in pending if str(row.get("created_at") or "").startswith(date)]
    return pending


def confirm(
    ids: list[str],
    path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    rows = load_queue(path, cfg)
    wanted = set(ids)
    confirmed = []
    for row in rows:
        if str(row.get("id")) in wanted:
            row["status"] = cfg["approval"]["approved_status"]
            row["approved_at"] = dt.datetime.now(dt.timezone.utc).astimezone().isoformat()
            confirmed.append(str(row["id"]))
    save_queue(rows, path, cfg)
    return {
        "confirmed": confirmed,
        "not_found": sorted(wanted - set(confirmed)),
        "status": "ready_for_manual_submission_only",
        "auto_submit": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local approval queue (no submission)")
    parser.add_argument("--input", help="local jobs JSON")
    parser.add_argument("--date", help="list pending entries for one YYYY-MM-DD")
    parser.add_argument("--confirm", nargs="*", help="explicit IDs to approve")
    parser.add_argument("--queue", help="optional queue path")
    args = parser.parse_args(argv)
    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
        jobs = payload if isinstance(payload, list) else payload.get("jobs", [])
        print(json.dumps(enqueue(jobs, args.queue), ensure_ascii=False, indent=2))
    elif args.confirm is not None:
        print(json.dumps(confirm(args.confirm, args.queue), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(list_pending(args.date, args.queue), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
