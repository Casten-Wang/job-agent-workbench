#!/usr/bin/env python3
"""Draft a <=150-character greeting using only explicit local CV/JD facts.

No quantified claim is generated from dynamic data. Job title and company are
copied from structured JD fields as data; skill words are copied only when
they appear verbatim in the local CV. This module does not send or submit.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task06.json"
NUMBER_RE = re.compile(r"\d")
UNSAFE_JD_CHARS_RE = re.compile(r"\d|[一二三四五六七八九十百千万亿]")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _TOOLS_DIR.parent / path


def _safe_text(value: Any, limit: int = 300) -> str:
    text = "".join(" " if ord(ch) < 32 else ch for ch in str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _cv_skill_terms(cv_text: str) -> list[str]:
    candidates = (
        "需求分析", "用户调研", "产品设计", "产品原型", "Axure", "Visio",
        "Mindmanager", "数据分析", "交互设计", "流程图", "用户体验",
        "PowerPoint", "Excel", "Word", "UI",
    )
    return [term for term in candidates if term in cv_text]


def make_greeting(
    job: dict[str, Any],
    cv_text: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    limit = int(cfg["greeting"]["max_chars"])
    company = _safe_text(job.get("company"))
    title = _safe_text(job.get("title"))
    warnings: list[str] = []
    if UNSAFE_JD_CHARS_RE.search(company) or UNSAFE_JD_CHARS_RE.search(title):
        warnings.append("jd-title-or-company-contains-numeric-characters-not-included")
        company = ""
        title = ""
    skills = [term for term in _cv_skill_terms(cv_text) if not NUMBER_RE.search(term)]
    facts = []
    if company:
        facts.append(company)
    if title:
        facts.append(title)
    parts = []
    if company and title:
        parts.append(f"您好，我想了解{company}的{title}岗位。")
    elif title:
        parts.append(f"您好，我想了解{title}岗位。")
    else:
        parts.append("您好，我想了解这个岗位。")
    if skills:
        parts.append("我的简历中有" + "、".join(skills[:3]) + "相关经验。")
    parts.append("方便进一步沟通吗？")
    draft = "".join(parts)
    if len(draft) > limit:
        draft = draft[:limit].rstrip()
        warnings.append("greeting-truncated-to-150-chars")
    if not company or not title:
        warnings.append("company-or-title-missing-not-invented")
    if not skills:
        warnings.append("no-cv-skill-term-found-not-invented")
    # Defensive: no digits or Chinese numerals can enter a user-facing claim.
    if NUMBER_RE.search(draft):
        return {
            "greeting": "",
            "length": 0,
            "max_chars": limit,
            "warnings": warnings + ["numeric-character-in-static-template-blocked"],
            "facts_used": [],
            "source": "none: draft blocked by numeric-character invariant",
            "send_status": "draft_only_not_sent",
        }
    return {
        "greeting": draft,
        "length": len(draft),
        "max_chars": limit,
        "warnings": warnings,
        "facts_used": facts + skills[:3],
        "source": "workspace/resume.md + structured local JD fields",
        "send_status": "draft_only_not_sent",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline greeting draft from local facts")
    parser.add_argument("--job", required=True, help="local structured JD JSON")
    parser.add_argument("--cv", required=True, help="local CV markdown")
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8-sig"))
    result = make_greeting(job, Path(args.cv).read_text(encoding="utf-8-sig"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
