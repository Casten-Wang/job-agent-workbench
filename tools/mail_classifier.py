#!/usr/bin/env python3
"""Offline, deterministic classification of job-search emails.

Input is either a local .eml file or a JSON object with from/subject/body/date/
message_id. Email text is untrusted data: it is never executed, and no network
or LLM call is made. Missing entities are returned as null, never guessed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import json
import re
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task04.json"

DATE_RE = re.compile(
    r"(?P<y>20\d{2})[-/年.]\s*(?P<m>\d{1,2})[-/月.]\s*(?P<d>\d{1,2})日?"
    r"(?:\s*(?P<h>\d{1,2})[:时]\s*(?P<min>\d{2})?)?"
)
UTC_DATE_RE = re.compile(r"(?P<h>\d{1,2}):(?P<min>\d{2})\s*(?P<zone>UTC|GMT|Z)\b", re.IGNORECASE)
LINK_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
INSTRUCTION_RE = re.compile(
    r"忽略[^\n]{0,30}(指令|约束|规则)|提交[^\n]{0,20}(申请|投递)|写入[^\n]{0,20}凭据"
    r"|ignore\s+(all\s+|any\s+|the\s+|previous\s+|above\s+)?(instructions?|rules?|constraints?)"
    r"|api[_ -]?key|password|credential|secret|\bsystem\s*:",
    re.IGNORECASE,
)
UNICODE_ESCAPE_RE = re.compile(
    r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})|\\x([0-9a-fA-F]{2})"
)
NEGATION_RE = re.compile(r"不含|没有|并非|不是|非")
SENTENCE_BOUNDARY_RE = re.compile(r"[。！？!?；;\n]")
COMPANY_RE = re.compile(r"(?:公司|企业|雇主)\s*[:：]\s*([^\n\r|]{1,80})")
TITLE_RE = re.compile(r"(?:岗位|职位)\s*[:：]\s*([^\n\r|]{1,80})")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _restore_unicode_escapes(text: str) -> str:
    """Decode literal \\uXXXX sequences produced by email's 7-bit CTE parser."""
    def replace(match: re.Match[str]) -> str:
        value = next(group for group in match.groups() if group is not None)
        try:
            return chr(int(value, 16))
        except (ValueError, OverflowError):
            return match.group(0)
    return UNICODE_ESCAPE_RE.sub(replace, text)


def parse_eml(text: str) -> dict[str, Any]:
    message = email.message_from_string(text)
    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode(part.get_content_charset() or "utf-8", "replace")
    else:
        body = str(message.get_payload() or "")
    return {
        "from": str(message.get("From") or ""),
        "subject": str(message.get("Subject") or ""),
        "body": _restore_unicode_escapes(body),
        "date": str(message.get("Date") or ""),
        "message_id": str(message.get("Message-ID") or ""),
    }


def load_mail(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("mail JSON must be an object")
        return payload
    return parse_eml(text)


def classify(mail: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    subject = str(mail.get("subject") or "")
    body = str(mail.get("body") or "")
    text = (subject + "\n" + body).casefold()

    def keyword_hits(keyword: str) -> int:
        lowered = str(keyword).casefold()
        count = 0
        start = 0
        while True:
            index = text.find(lowered, start)
            if index < 0:
                return count
            boundary = text.rfind("\n", 0, index)
            for stop in ("。", "！", "？", "!", "?", "；", ";"):
                found = text.rfind(stop, 0, index)
                if found > boundary:
                    boundary = found
            clause = text[boundary + 1 : index + len(lowered)]
            if not NEGATION_RE.search(clause):
                count += 1
            start = index + len(lowered)

    scores: dict[str, int] = {}
    for intent, keywords in cfg["intent_keywords"].items():
        if intent == "other":
            continue
        scores[intent] = sum(keyword_hits(word) for word in keywords)
    # Rejection language is more specific than a generic "interview" mention.
    if scores.get("rejection", 0):
        intent = "rejection"
    elif scores.get("offer", 0):
        intent = "offer"
    elif scores.get("interview_invite", 0):
        intent = "interview_invite"
    elif scores.get("assessment", 0):
        intent = "assessment"
    else:
        intent = "other"
    matched = scores.get(intent, 0)
    confidence = min(1.0, 0.6 + 0.15 * matched) if matched else 0.0

    date_match = DATE_RE.search(body) or DATE_RE.search(subject)
    event_time = None
    if date_match:
        parts = date_match.groupdict()
        hour = int(parts["h"] or 9)
        minute = int(parts["min"] or 0)
        if hour < 24 and minute < 60:
            try:
                local = dt.datetime(
                    int(parts["y"]), int(parts["m"]), int(parts["d"]),
                    hour, minute,
                )
            except ValueError:
                local = None
            if local is not None:
                # Explicit UTC/GMT clock text in the same mail means the date
                # is a UTC calendar date; convert to local Asia/Shanghai.
                utc_hint = UTC_DATE_RE.search(body) or UTC_DATE_RE.search(subject)
                if utc_hint and parts["h"] is None:
                    utc_hour = int(utc_hint.group("h"))
                    utc_minute = int(utc_hint.group("min"))
                    if utc_hour < 24:
                        local = local.replace(
                            hour=utc_hour,
                            minute=utc_minute,
                            tzinfo=dt.timezone.utc,
                        ).astimezone(dt.timezone(dt.timedelta(hours=8))).replace(tzinfo=None)
                event_time = local.isoformat(timespec="seconds")
    links = LINK_RE.findall(body + "\n" + subject)
    company_match = COMPANY_RE.search(body)
    title_match = TITLE_RE.search(body)
    anomalies = [
        {"quote": line.strip()[:500], "action": "quoted_as_untrusted_data_not_executed"}
        for line in (subject + "\n" + body).splitlines()
        if INSTRUCTION_RE.search(line)
    ]
    return {
        "intent": intent,
        "input_anomalies": anomalies,
        "confidence": round(confidence, 2),
        "event_time": event_time,
        "time_parse_status": "parsed" if event_time else "missing",
        "meeting_links": links[:5],
        "company": company_match.group(1).strip() if company_match else None,
        "title": title_match.group(1).strip() if title_match else None,
        "message_id": str(mail.get("message_id") or "") or None,
        "subject": subject,
        "scores": scores,
        "engine": "offline-deterministic-rules",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline classifier for local .eml/JSON mail samples")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", help="optional JSON output path")
    args = parser.parse_args(argv)
    record = classify(load_mail(args.input))
    output = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
