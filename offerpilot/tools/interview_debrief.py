#!/usr/bin/env python3
"""Extract a deterministic, evidence-bounded mock-interview debrief card.

Transcript text is untrusted data; no instruction-like sentence is executed.
Only explicit interviewer questions and explicitly marked answers are used.
Weakness tags are candidate signals, not judgments about a real person.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task05.json"
QUESTION_RE = re.compile(r"^\s*(?:面试官|Q\d*|问题\s*\d*)\s*[：:]\s*(.+\S)\s*$")
ANSWER_RE = re.compile(r"^\s*(?:回答|候选人|A\d*[：:])\s*[：:]\s*(.+)$")
WEAKNESS_RULES = {
    "逻辑漏洞": re.compile(r"逻辑漏洞|因果不清|前后矛盾"),
    "量化不足": re.compile(r"量化不足|缺少数字|没有指标"),
    "STAR缺失": re.compile(r"STAR缺失|缺少情境|没有结果"),
    "业务理解": re.compile(r"业务理解|业务背景不清楚"),
    "表达冗余": re.compile(r"表达冗余|回答过长|不够简洁"),
}
INSTRUCTION_RE = re.compile(r"忽略[^\n]{0,20}(指令|约束|规则)|提交[^\n]{0,20}(申请|投递)|写入[^\n]{0,20}凭据", re.IGNORECASE)


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _project_root() -> Path:
    return _TOOLS_DIR.parent


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _project_root() / path


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_transcript(path: str | Path) -> str:
    text = Path(path).read_text(encoding="utf-8-sig")
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("transcript JSON must be an object")
        return str(payload.get("transcript") or payload.get("text") or "")
    return text


def add_questions(
    questions: list[str],
    bank_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    path = _resolve(bank_path or cfg["question_bank_path"])
    if path.is_file():
        bank = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        bank = {"version": 1, "questions": []}
    if not isinstance(bank, dict) or not isinstance(bank.get("questions"), list):
        raise ValueError("question bank must be an object with a questions array")
    existing = {
        _sha256(str(item.get("question") if isinstance(item, dict) else item))
        for item in bank["questions"]
    }
    added = 0
    for question in questions:
        digest = _sha256(question)
        if digest in existing:
            continue
        existing.add(digest)
        bank["questions"].append(
            {
                "id": digest[:12],
                "question": question,
                "source": "debrief_new_question",
                "section": None,
                "_note": "测试数据/逐字稿抽取；尚未归类，不编造面经",
            }
        )
        added += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(bank, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return {"path": str(path), "added": added, "total": len(bank["questions"])}


def debrief(
    transcript: str,
    interview_id: str = "demo",
    bank_path: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    questions: list[str] = []
    answers: list[str] = []
    anomalies: list[dict[str, str]] = []
    for line in transcript.splitlines():
        if INSTRUCTION_RE.search(line):
            anomalies.append({"quote": line.strip()[:500], "action": "quoted_as_untrusted_data_not_executed"})
            continue
        q = QUESTION_RE.match(line)
        a = ANSWER_RE.match(line)
        if q:
            questions.append(q.group(1).strip())
        elif a:
            answers.append(a.group(1).strip())
    highlights = [answer[:180] for answer in answers if answer.strip()]
    tags = [
        tag for tag, pattern in WEAKNESS_RULES.items()
        if tag in cfg["weakness_tags"] and pattern.search(transcript)
    ]
    new_questions = questions
    bank_result = add_questions(new_questions, bank_path, cfg)
    card: dict[str, Any] = {
        "interview_id": interview_id,
        "created_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "interviewer_questions": questions,
        "answer_highlights": highlights,
        "logic_gaps": [],
        "new_questions": new_questions,
        "weakness_tags": tags,
        "next_actions": [],
        "input_anomalies": anomalies,
        "engine": "offline-deterministic-rules",
        "evidence_note": "空字段表示逐字稿没有显式证据；未对候选人做实质性能力评价。",
    }
    directory = _resolve(cfg["interview_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / f"{interview_id}.md"
    lines = [f"# 复盘卡片：{interview_id}（测试数据）", ""]
    for key in (
        "interviewer_questions", "answer_highlights", "logic_gaps",
        "new_questions", "weakness_tags", "next_actions",
    ):
        lines += [f"## {key}", ""]
        values = card[key]
        lines += [f"- {value}" for value in values] if values else ["（无明确证据，留空）"]
        lines.append("")
    lines += ["## 原始结构化数据", "", "```json", json.dumps(card, ensure_ascii=False, indent=2), "```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    card["out"] = str(out)
    card["question_bank"] = bank_result
    return card


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline transcript debrief card")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--id", default="demo")
    parser.add_argument("--bank", help="optional local question bank path")
    args = parser.parse_args(argv)
    try:
        text = load_transcript(args.transcript)
        result = debrief(text, args.id, args.bank)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
