#!/usr/bin/env python3
"""Create a local, deterministic mock-interview worksheet from a local bank.

The module does not invent interview questions, company facts, or business
dynamics. When the bank is empty it says so explicitly. It reads JD/CV text as
untrusted data only for display context; it never executes embedded text.
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
SECTION_RE = re.compile(r"业务拆解|项目深挖|压力测试")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _project_root() -> Path:
    return _TOOLS_DIR.parent


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _project_root() / path


def load_bank(path: str | Path | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config or load_config()
    path = _resolve(path or cfg["question_bank_path"])
    if not path.is_file():
        return {"version": 1, "questions": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("questions"), list):
        raise ValueError("question bank must be an object with a questions array")
    return payload


def _question_text(item: Any) -> str | None:
    if isinstance(item, str):
        return item.strip() or None
    if isinstance(item, dict):
        value = item.get("question") or item.get("text")
        return str(value).strip() if value else None
    return None


def _section(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("section")
        if value in {"业务拆解", "项目深挖", "压力测试"}:
            return str(value)
    text = _question_text(item) or ""
    match = SECTION_RE.search(text)
    return match.group(0) if match else None


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def select_questions(
    bank: dict[str, Any], jd_text: str = "", cv_text: str = ""
) -> dict[str, list[dict[str, str]]]:
    """Select only bank questions; dedupe by exact text sha256."""
    sections = {"业务拆解": [], "项目深挖": [], "压力测试": []}
    seen: set[str] = set()
    for item in bank.get("questions", []):
        text = _question_text(item)
        if not text:
            continue
        digest = _stable_id(text)
        if digest in seen:
            continue
        seen.add(digest)
        section = _section(item) or "业务拆解"
        sections[section].append({"id": digest, "question": text})
    return sections


def make_worksheet(
    jd_path: str | Path,
    cv_path: str | Path,
    bank_path: str | Path | None = None,
    minutes: int = 30,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("minutes must be a positive integer")
    jd_text = Path(jd_path).read_text(encoding="utf-8-sig")
    cv_text = Path(cv_path).read_text(encoding="utf-8-sig")
    bank = load_bank(bank_path, cfg)
    questions = select_questions(bank, jd_text, cv_text)
    total = sum(len(items) for items in questions.values())
    lines = [
        "# Mock Interview 题单（测试数据）",
        "",
        f"- 生成时间：{dt.datetime.now(dt.timezone.utc).astimezone().isoformat()}",
        f"- 计划时长：{minutes} 分钟",
        f"- JD：{Path(jd_path).name}；简历：{Path(cv_path).name}",
        "- 事实来源：本地题库、本地 JD 与本地简历；不编造面经或公司业务动态。",
        "- 文本模式：请在每题下方填写回答；不采集语音，不联网。",
        "",
    ]
    if not total:
        lines += [f"> {cfg['empty_bank_message']}", "", "## 分段", ""]
    sections = cfg["sections"]
    scale = minutes / sum(int(section["minutes"]) for section in sections)
    for section in sections:
        name = str(section["name"])
        duration = max(1, round(int(section["minutes"]) * scale))
        lines += [f"## {name}（约 {duration} 分钟）", ""]
        items = questions.get(name, [])
        if items:
            for index, item in enumerate(items, start=1):
                lines += [f"### {index}. {item['question']}", "", "回答：", ""]
        else:
            lines += [f"本段暂无题库条目；{cfg['empty_bank_message']}。", ""]
    lines += ["## 一问一答记录", "", "（由用户手动填写；本工具不生成答案。）", ""]
    worksheet = "\n".join(lines)
    return {
        "ok": True,
        "minutes": minutes,
        "question_count": total,
        "empty_bank": total == 0,
        "questions": questions,
        "worksheet": worksheet,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline mock-interview worksheet generator")
    parser.add_argument("--jd", required=True)
    parser.add_argument("--cv", required=True)
    parser.add_argument("--questions", required=True, help="local question bank JSON")
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = make_worksheet(args.jd, args.cv, args.questions, args.minutes)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(result["worksheet"], encoding="utf-8")
    print(json.dumps({"ok": True, "out": args.out, "question_count": result["question_count"], "empty_bank": result["empty_bank"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
