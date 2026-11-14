#!/usr/bin/env python3
"""Dry-run-only Feishu Bitable/calendar adapter.

No HTTP client, credential value, or real personal information is used. When
the environment variables named in config_task04.json are absent, the module
returns the exact structured payload it would send, marked ``dry_run: true``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task04.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _credential_status(config: dict[str, Any] | None = None) -> dict[str, bool]:
    cfg = config or load_config()
    return {name: bool(os.environ.get(name)) for name in cfg["env_vars"].values()}


def _sync_payload(row: dict[str, Any]) -> dict[str, Any]:
    allowed = ("job_id", "company", "title", "status", "score", "source_channel", "updated_at")
    return {key: row.get(key) for key in allowed if key in row}


def sync_job(row: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    status = _credential_status(cfg)
    payload = _sync_payload(row)
    result = {
        "target": "feishu_bitable",
        "dry_run": True,
        "credentials_present": status,
        "payload": payload,
        "note": "No HTTP request is implemented. Real integration requires a user-provided adapter and explicit confirmation.",
    }
    if all(status.values()):
        result["note"] += " Credential names are present, but this offline build still performs no HTTP request."
    return result


def create_calendar_event(event: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    status = _credential_status(cfg)
    allowed = ("summary", "start_time", "end_time", "timezone", "meeting_link")
    payload = {key: event.get(key) for key in allowed if key in event}
    return {
        "target": "feishu_calendar",
        "dry_run": True,
        "credentials_present": status,
        "payload": payload,
        "note": "Offline dry-run; prefer calendar_ics.py for a portable .ics file.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline Feishu dry-run adapter")
    parser.add_argument("--kind", choices=("job", "event"), required=True)
    parser.add_argument("--input", required=True, help="local JSON object")
    args = parser.parse_args(argv)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    result = sync_job(payload) if args.kind == "job" else create_calendar_event(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
