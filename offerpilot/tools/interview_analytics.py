#!/usr/bin/env python3
"""Aggregate weakness tags from local debrief JSON cards. No charts, no PII."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task05.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def summarize(debriefs: list[dict[str, Any]], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    allowed = set(cfg["weakness_tags"])
    counts: Counter[str] = Counter()
    card_count = 0
    missing = 0
    for item in debriefs:
        if not isinstance(item, dict):
            continue
        card_count += 1
        tags = item.get("weakness_tags")
        if not isinstance(tags, list):
            missing += 1
            continue
        seen = set()
        for tag in tags:
            label = str(tag)
            if label in allowed and label not in seen:
                counts[label] += 1
                seen.add(label)
    return {
        "engine": "offline-deterministic-aggregation",
        "debrief_count": card_count,
        "cards_missing_weakness_tags": missing,
        "weakness_tag_counts": {tag: counts[tag] for tag in cfg["weakness_tags"]},
        "high_frequency_tags": [tag for tag in cfg["weakness_tags"] if counts[tag] >= 2],
        "note": "Labels are explicitly marked evidence signals, not inferred evaluations; no chart is drawn.",
    }


def load_debriefs(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    rows = payload if isinstance(payload, list) else payload.get("debriefs")
    if not isinstance(rows, list):
        raise ValueError("input must be an array or {debriefs: [...]}")
    return [row for row in rows if isinstance(row, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline weakness-tag aggregation")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        result = summarize(load_debriefs(args.input))
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
