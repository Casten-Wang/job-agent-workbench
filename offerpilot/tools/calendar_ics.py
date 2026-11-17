#!/usr/bin/env python3
"""Generate an RFC 5545 .ics event from an extracted mail time.

No timezone database or third-party dependency is used. A naive event time is
interpreted as Asia/Shanghai local time (fixed UTC+08:00, correct for all
dates China currently uses), converted to UTC, and emitted with a ``Z``
suffix. An input with an explicit offset is converted to UTC as well. The
UID and event times are deterministic; DTSTAMP records generation time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True


def _escape_text(value: str) -> str:
    """Escape ICS TEXT content, including control characters and line breaks."""
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(ch if ch >= " " or ch == "\n" else " " for ch in value)
    return (
        value.replace("\\", r"\\")
        .replace("\n", r"\n")
        .replace(";", r"\;")
        .replace(",", r"\,")
    )


def _fold(line: str) -> str:
    """Fold one ICS content line at UTF-8 byte boundaries per RFC 5545."""
    if len(line.encode("utf-8")) <= 75:
        return line
    pieces: list[str] = []
    current = ""
    limit = 75
    for ch in line:
        candidate = current + ch
        if current and len(candidate.encode("utf-8")) > limit:
            pieces.append(current)
            current = " " + ch
            limit = 74
        else:
            current = candidate
    if current:
        pieces.append(current)
    return "\r\n".join(pieces)


def make_ics(
    event_time: str,
    summary: str,
    duration_minutes: int = 60,
    timezone: str = "Asia/Shanghai",
    meeting_link: str | None = None,
) -> dict[str, Any]:
    if not event_time:
        return {"ok": False, "error": "missing-event-time"}
    if timezone != "Asia/Shanghai":
        return {"ok": False, "error": "unsupported-timezone", "timezone": timezone}
    if isinstance(duration_minutes, bool) or not isinstance(duration_minutes, int) or not 1 <= duration_minutes <= 1440:
        return {"ok": False, "error": "invalid-duration"}
    try:
        start = dt.datetime.fromisoformat(event_time)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": "invalid-event-time", "detail": str(exc)}
    local_offset = dt.timezone(dt.timedelta(hours=8))
    if start.tzinfo is None:
        start = start.replace(tzinfo=local_offset)
    start_utc = start.astimezone(dt.timezone.utc)
    end_utc = start_utc + dt.timedelta(minutes=duration_minutes)
    uid_seed = event_time + "|" + str(summary)
    uid = hashlib.sha256(uid_seed.encode("utf-8")).hexdigest()[:24] + "@offerpilot.local"
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Job Agent//Interview Calendar//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"SUMMARY:{_escape_text(summary)}",
    ]
    if meeting_link:
        lines.append(f"DESCRIPTION:{_escape_text(meeting_link)}")
    lines += ["END:VEVENT", "END:VCALENDAR", ""]
    ics = "\r\n".join(_fold(line) if line else line for line in lines)
    return {
        "ok": True,
        "timezone": timezone,
        "uid": uid,
        "start_utc": start_utc.strftime("%Y%m%dT%H%M%SZ"),
        "end_utc": end_utc.strftime("%Y%m%dT%H%M%SZ"),
        "ics": ics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate an offline .ics file from a parsed interview time")
    parser.add_argument("--time", required=True, help="local ISO time, e.g. 2026-11-20T14:30:00")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--link")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = make_ics(args.time, args.summary, args.minutes, meeting_link=args.link)
    if result["ok"]:
        Path(args.out).write_text(result["ics"], encoding="utf-8")
    print(json.dumps({"ok": result["ok"], "out": args.out if result["ok"] else None, **{k: v for k, v in result.items() if k != "ics"}}, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
