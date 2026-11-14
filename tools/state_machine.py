#!/usr/bin/env python3
"""Local application state machine with an append-only JSONL ledger."""

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

CONFIG_PATH = _TOOLS_DIR / "config_task04.json"
DEFAULT_LOG = _TOOLS_DIR / "data" / "status-log.jsonl"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def transition(
    job_id: str,
    from_state: str,
    to_state: str,
    config: dict[str, Any] | None = None,
    log_path: str | Path | None = None,
    note: str = "",
) -> dict[str, Any]:
    cfg = config or load_config()
    allowed = cfg["transitions"].get(from_state)
    if from_state not in cfg["states"] or to_state not in cfg["states"]:
        return {"ok": False, "error": "unknown-state", "from": from_state, "to": to_state}
    if allowed is None or to_state not in allowed:
        return {"ok": False, "error": "illegal-transition", "from": from_state, "to": to_state}
    event = {
        "job_id": job_id,
        "from": from_state,
        "to": to_state,
        "note": note,
        "recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
    }
    target = Path(log_path or DEFAULT_LOG)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"ok": True, "event": event, "log": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Append one validated application-state transition")
    parser.add_argument("--id", required=True)
    parser.add_argument("--from", dest="from_state", required=True)
    parser.add_argument("--to", dest="to_state", required=True)
    parser.add_argument("--note", default="")
    parser.add_argument("--log", default=str(DEFAULT_LOG))
    args = parser.parse_args(argv)
    result = transition(args.id, args.from_state, args.to_state, log_path=args.log, note=args.note)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
