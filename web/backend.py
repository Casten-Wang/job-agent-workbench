#!/usr/bin/env python3
"""Backend logic for the OfferPilot (秋招规划师) workbench.

The local workbench owns its JSON workspace. The embedded automation runtime
owns its credentials, SQLite database, browser session, and platform workflow.
The workbench calls it in-process; all external text is data and no instruction
in a JD, email, transcript, or upload is executed.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import re
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
TOOLS_DIR = ROOT / "tools"
DEMO_DIR = ROOT / "demo"
CV_PATH = ROOT / "workspace" / "resume.md"
TESTS_DIR = TOOLS_DIR / "tests"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import offerpilot_adapter  # noqa: E402
import offerpilot_runtime  # noqa: E402
import mail_classifier  # noqa: E402
import analytics  # noqa: E402
import jd_intake  # noqa: E402
import approval_queue  # noqa: E402
import ats_check  # noqa: E402
import calendar_ics  # noqa: E402
import feishu_adapter  # noqa: E402
import filters  # noqa: E402
import greeting  # noqa: E402
import interview_analytics  # noqa: E402
import interview_debrief  # noqa: E402
import mock_interview  # noqa: E402
import precheck  # noqa: E402
import state_machine  # noqa: E402
import variants  # noqa: E402
import degrade  # noqa: E402

MAX_TEXT = 60_000
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
DATE_RE = re.compile(r"(20\d{2})[-/年.]\s*(\d{1,2})[-/月.]\s*(\d{1,2})")
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")
SKILL_TERMS = (
    "需求分析", "用户调研", "产品设计", "产品原型", "Axure", "Visio",
    "Mindmanager", "数据分析", "交互设计", "流程图", "用户体验",
    "PowerPoint", "Excel", "Word", "UI",
)
DOCUMENT_DOWNLOADS = {
    "readme": ROOT / "README.md",
    "final-result": ROOT / "FINAL-RESULT.md",
    "demo-report": ROOT / "demo" / "REPORT.md",
    "web-design": WEB_DIR / "DESIGN.md",
    "pipeline-api": WEB_DIR / "PIPELINE-API.md",
    "profile-api": WEB_DIR / "PROFILE-API.md",
    "task03": ROOT / "prompts" / "TASK-03-验收.md",
    "task04": ROOT / "prompts" / "TASK-04-验收.md",
    "task05": ROOT / "prompts" / "TASK-05-验收.md",
    "task06": ROOT / "prompts" / "TASK-06-验收.md",
    "task07": ROOT / "prompts" / "TASK-07-验收.md",
}
WEAKNESS_TAGS = ("逻辑漏洞", "量化不足", "STAR缺失", "业务理解", "表达冗余")
INTENT_LABELS = {
    "interview_invite": "面试邀请",
    "assessment": "笔试/测评",
    "rejection": "淘汰",
    "offer": "Offer",
    "other": "其他",
}
STATES = state_machine.load_config()["states"]

OFFERPILOT_EMBEDDED_URL = "embedded://offerpilot"
OFFERPILOT_AGENT_API_VERSION = "v1"
OFFERPILOT_TASK_MODES = frozenset({"collect", "monitor", "full"})

# The core application flow is shared with an external agent project. The local
# workbench owns the first four stages; the last two are contract-only until the
# external agent reports back. No stage can submit an application on its own.
PIPELINE_STAGES = (
    {
        "key": "intake",
        "title": "岗位采集",
        "owner": "local",
        "owner_label": "本地工作台",
        "entry": "jobs",
        "actions": ["parse-jd", "import-jobs"],
        "description": "优先读取已运行 岗位自动化的岗位池；不可用时保留手动 JD/JSON 导入。",
    },
    {
        "key": "screening",
        "title": "AI 评分与筛选",
        "owner": "local",
        "owner_label": "本地规则 + 可选评分",
        "entry": "jobs",
        "actions": ["enqueue"],
        "description": "硬性条件过滤、可选 0–5 评分与评分门；结果只进入待确认队列。",
    },
    {
        "key": "approval",
        "title": "人工确认",
        "owner": "human",
        "owner_label": "人工",
        "entry": "queue",
        "actions": ["confirm"],
        "description": "输入完整确认语后才标记 approved；approved 仅表示可人工投递。",
    },
    {
        "key": "greeting",
        "title": "生成招呼语",
        "owner": "local",
        "owner_label": "本地工作台",
        "entry": "jobs",
        "actions": ["prepare"],
        "description": "基于本地简历事实生成招呼语与人工准备清单，不发送。",
    },
    {
        "key": "send",
        "title": "发送",
        "owner": "external",
        "owner_label": "外部 Agent",
        "entry": "queue",
        "actions": [],
        "event_stage": "send",
        "description": "复用岗位自动化既有流程；启动前明确确认，发送前仍保留人工确认和时间窗口。",
    },
    {
        "key": "monitor",
        "title": "监控 HR 回复",
        "owner": "hybrid",
        "owner_label": "外部 Agent / 本地邮件解析",
        "entry": "mail",
        "actions": ["parse-mail", "generate-ics"],
        "event_stage": "monitor",
        "description": "读取岗位自动化监测任务状态；本地仍可粘贴 HR 邮件做离线分类。",
    },
)
PIPELINE_EVENT_STATUSES = ("started", "succeeded", "failed", "skipped")
RESERVED_FEATURES = (
    {"key": "mock_interview", "title": "模拟面试", "panel": "interview", "status": "local_partial"},
    {"key": "push", "title": "信息推送", "panel": "push", "status": "dry_run_only"},
    {"key": "resume", "title": "定制简历", "panel": "resume", "status": "local_partial"},
)
PROFILE_PREREQUISITE = {
    "key": "profile",
    "title": "个人资料",
    "panel": "profile",
    "required": False,
    "status": "local_ready",
    "description": "结构化基本信息、求职偏好、教育/经历/项目与技能。是模拟面试与定制简历的软前置；不完整时工作台仍可运行，但会提示缺失项。",
}
PROFILE_LIMITS = {
    "short": 120,
    "text": 2_000,
    "long": 6_000,
    "items": 20,
    "list": 30,
}
PROFILE_DEGREES = ("大专", "本科", "硕士", "博士", "其他")
PROFILE_JOB_TYPES = ("全职", "实习", "兼职", "合同")
PROFILE_SECTIONS = (
    ("basic", "基本信息", 25, "填写姓名、邮箱与所在城市"),
    ("job_intent", "求职偏好", 15, "填写目标岗位与目标城市"),
    ("education", "教育经历", 10, "至少一段教育经历"),
    ("experiences", "工作经历", 15, "至少一段工作/实习经历"),
    ("projects", "项目经历", 15, "至少一个可核实项目"),
    ("skills", "技能标签", 10, "至少三个技能或工具"),
    ("summary", "个人简介", 5, "用几句话说明你的方向与优势"),
    ("truth_confirmed", "事实确认", 5, "确认资料真实、可用于生成草稿"),
)


class ApiError(Exception):
    """Expected, user-facing API failure."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class Store:
    """Own one clearly marked local dataset: demo or user."""

    VALID_MODES = ("demo", "user")

    def __init__(self, mode: str = "demo"):
        self.mode = mode
        self.root = WEB_DIR / "data" / mode
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = {
            "jobs": self.root / "jobs.json",
            "queue": self.root / "approval-queue.json",
            "mails": self.root / "mails.json",
            "debriefs": self.root / "debriefs.json",
            "events": self.root / "status-log.jsonl",
            "pipeline": self.root / "pipeline-events.jsonl",
            "activity": self.root / "activity.jsonl",
            "variants": self.root / "variants.json",
            "bank": self.root / "question-bank.json",
            "profile": self.root / "profile.json",
            "config": self.root / "config.json",
            "downloads": self.root / "downloads",
        }
        self.files["downloads"].mkdir(parents=True, exist_ok=True)

    def _read_json(self, key: str, default: Any) -> Any:
        path = self.files[key]
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"{path.name} 无法读取：{exc}", 500) from exc

    def _write_json(self, key: str, value: Any) -> None:
        path = self.files[key]
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    def _read_lines(self, key: str) -> list[dict[str, Any]]:
        path = self.files[key]
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
        return rows

    def _append_line(self, key: str, value: dict[str, Any]) -> None:
        path = self.files[key]
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, ensure_ascii=False) + "\n")

    def jobs(self) -> list[dict[str, Any]]:
        value = self._read_json("jobs", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_jobs(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("jobs", rows)

    def queue(self) -> list[dict[str, Any]]:
        value = self._read_json("queue", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_queue(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("queue", rows)

    def mails(self) -> list[dict[str, Any]]:
        value = self._read_json("mails", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_mails(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("mails", rows)

    def debriefs(self) -> list[dict[str, Any]]:
        value = self._read_json("debriefs", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_debriefs(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("debriefs", rows)

    def events(self) -> list[dict[str, Any]]:
        return self._read_lines("events")

    def pipeline_events(self) -> list[dict[str, Any]]:
        return self._read_lines("pipeline")

    def append_pipeline_event(self, value: dict[str, Any]) -> None:
        self._append_line("pipeline", value)

    def variants(self) -> list[dict[str, Any]]:
        value = self._read_json("variants", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_variants(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("variants", rows)

    def question_bank(self) -> dict[str, Any]:
        value = self._read_json("bank", {"version": 1, "questions": []})
        if not isinstance(value, dict) or not isinstance(value.get("questions"), list):
            return {"version": 1, "questions": []}
        return value

    def set_question_bank(self, value: dict[str, Any]) -> None:
        self._write_json("bank", value)

    def profile(self) -> dict[str, Any]:
        value = self._read_json("profile", None)
        return normalize_profile(value) if isinstance(value, dict) else default_profile()

    def set_profile(self, value: dict[str, Any]) -> None:
        self._write_json("profile", value)

    def config(self) -> dict[str, Any]:
        default = {
            "target_cities": filters.load_config()["target_cities"],
            "score": approval_queue.load_config()["score"],
            "boundaries": approval_queue.load_config()["boundaries"],
            "question_bank_path": "tools/data/question-bank.json",
            "interview_dir": "tools/data/interviews",
            "empty_bank_message": "题库为空，需补充题目",
            "sections": mock_interview.load_config()["sections"],
            "weakness_tags": list(WEAKNESS_TAGS),
        }
        current = self._read_json("config", {})
        if isinstance(current, dict):
            default.update(current)
        return default

    def log(self, action: str, detail: str, ok: bool = True) -> None:
        self._append_line("activity", {
            "at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
            "action": action,
            "detail": detail[:260],
            "ok": ok,
        })

    def activity(self, limit: int = 30) -> list[dict[str, Any]]:
        return list(reversed(self._read_lines("activity")))[:limit]

    def write_download(self, name: str, content: str, suffix: str = ".txt") -> Path:
        safe = SAFE_ID_RE.sub("-", name).strip("-")[:64] or "download"
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = self.files["downloads"] / f"{safe}-{stamp}{suffix}"
        path.write_text(content, encoding="utf-8")
        return path

    def list_downloads(self) -> list[dict[str, Any]]:
        rows = []
        for path in sorted(self.files["downloads"].glob("*"), reverse=True):
            if path.is_file() and path.stat().st_size <= MAX_DOWNLOAD_BYTES:
                rows.append({
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "modified": dt.datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                })
        return rows[:30]

    def download_path(self, name: str) -> Path:
        safe = SAFE_FILENAME_RE.sub("_", name)
        path = self.files["downloads"] / safe
        if path.parent != self.files["downloads"] or not path.is_file():
            raise ApiError("下载文件不存在", 404)
        return path


def _bounded_text(value: Any, label: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ApiError(f"{label} 必须是文本")
    if len(value.encode("utf-8")) > limit:
        raise ApiError(f"{label} 超过 {limit // 1024} KB 上限")
    return value


def _bounded_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ApiError(f"{label} 必须是 JSON 对象")
    return value


def _safe_id(value: Any, default: str) -> str:
    text = SAFE_ID_RE.sub("-", str(value or "")).strip("-")[:80]
    return text or default


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


# Structured personal profile
#
# profile.json is the local source of truth for "who the user is". It lives in
# web/data/<mode>/ and is gitignored. Demo mode only ever contains an obviously
# fictional profile. Nothing here sends data anywhere; contact fields are kept
# out of generated greetings, worksheets, and exported documents.


def _clean_text(value: Any, limit: int, multiline: bool = False) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    text = str(value)
    text = "".join(" " if (ord(ch) < 32 and ch not in "\n\t") else ch for ch in text)
    if multiline:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
    else:
        text = re.sub(r"\s+", " ", text)
    return text.strip()[:limit]


def _string_list(value: Any, item_limit: int = PROFILE_LIMITS["short"]) -> list[str]:
    if isinstance(value, str):
        raw = re.split(r"[,，、;；\n]", value)
    elif isinstance(value, list):
        raw = value
    else:
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _clean_text(item, item_limit)
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        rows.append(text)
        if len(rows) >= PROFILE_LIMITS["list"]:
            break
    return rows


def _profile_number(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 1_000_000 else None


def _profile_records(value: Any, fields: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for item in value[: PROFILE_LIMITS["items"]]:
        if not isinstance(item, dict):
            continue
        row = {
            field: _clean_text(item.get(field), PROFILE_LIMITS["text"] if field in ("summary", "highlights") else PROFILE_LIMITS["short"])
            for field in fields
        }
        if any(row.values()):
            rows.append(row)
    return rows


def default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": "",
        "truth_confirmed": False,
        "basic": {"name": "", "phone": "", "email": "", "city": "", "wechat": "", "links": ""},
        "job_intent": {
            "titles": [],
            "cities": [],
            "salary_min": None,
            "salary_max": None,
            "job_type": "全职",
            "availability": "",
        },
        "education": [],
        "experiences": [],
        "projects": [],
        "skills": {"tools": [], "strengths": []},
        "summary": "",
        "excluded_terms": [],
    }


def normalize_profile(value: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded, known-shape profile; unknown keys are discarded."""
    source = value if isinstance(value, dict) else {}
    profile = default_profile()
    basic = source.get("basic") if isinstance(source.get("basic"), dict) else {}
    intent = source.get("job_intent") if isinstance(source.get("job_intent"), dict) else {}
    skills = source.get("skills") if isinstance(source.get("skills"), dict) else {}
    profile["basic"] = {
        "name": _clean_text(basic.get("name"), PROFILE_LIMITS["short"]),
        "phone": _clean_text(basic.get("phone"), 40),
        "email": _clean_text(basic.get("email"), PROFILE_LIMITS["short"]),
        "city": _clean_text(basic.get("city"), PROFILE_LIMITS["short"]),
        "wechat": _clean_text(basic.get("wechat"), 60),
        "links": _clean_text(basic.get("links"), 300),
    }
    job_type = _clean_text(intent.get("job_type"), 20)
    profile["job_intent"] = {
        "titles": _string_list(intent.get("titles")),
        "cities": _string_list(intent.get("cities")),
        "salary_min": _profile_number(intent.get("salary_min")),
        "salary_max": _profile_number(intent.get("salary_max")),
        "job_type": job_type if job_type in PROFILE_JOB_TYPES else "全职",
        "availability": _clean_text(intent.get("availability"), PROFILE_LIMITS["short"]),
    }
    profile["education"] = _profile_records(source.get("education"), ("school", "major", "degree", "start", "end", "summary"))
    for row in profile["education"]:
        if row["degree"] not in PROFILE_DEGREES:
            row["degree"] = ""
    profile["experiences"] = _profile_records(
        source.get("experiences"), ("company", "title", "start", "end", "summary")
    )
    profile["projects"] = _profile_records(
        source.get("projects"), ("name", "role", "start", "end", "summary")
    )
    profile["skills"] = {
        "tools": _string_list(skills.get("tools"), 60),
        "strengths": _string_list(skills.get("strengths"), 60),
    }
    profile["summary"] = _clean_text(source.get("summary"), PROFILE_LIMITS["long"], multiline=True)
    profile["excluded_terms"] = _string_list(source.get("excluded_terms"), 60)
    profile["truth_confirmed"] = source.get("truth_confirmed") is True
    profile["updated_at"] = _clean_text(source.get("updated_at"), 64)
    return profile


def profile_completeness(profile: dict[str, Any]) -> dict[str, Any]:
    basic = profile.get("basic") or {}
    intent = profile.get("job_intent") or {}
    skills = profile.get("skills") or {}
    checks = {
        "basic": bool(basic.get("name") and basic.get("email") and basic.get("city")),
        "job_intent": bool(intent.get("titles") and intent.get("cities")),
        "education": any(row.get("school") for row in profile.get("education") or []),
        "experiences": any(row.get("company") or row.get("title") for row in profile.get("experiences") or []),
        "projects": any(row.get("name") for row in profile.get("projects") or []),
        "skills": len(skills.get("tools") or []) + len(skills.get("strengths") or []) >= 3,
        "summary": len(str(profile.get("summary") or "")) >= 20,
        "truth_confirmed": profile.get("truth_confirmed") is True,
    }
    sections = [
        {"key": key, "label": label, "weight": weight, "done": checks[key], "hint": hint}
        for key, label, weight, hint in PROFILE_SECTIONS
    ]
    percent = sum(section["weight"] for section in sections if section["done"])
    missing = [section["label"] for section in sections if not section["done"]]
    if percent == 0:
        level = "empty"
    elif percent >= 80 and checks["truth_confirmed"]:
        level = "ready"
    else:
        level = "partial"
    return {
        "percent": percent,
        "level": level,
        "ready": level == "ready",
        "sections": sections,
        "missing": missing,
    }


def profile_has_content(profile: dict[str, Any]) -> bool:
    basic = profile.get("basic") or {}
    return bool(
        any(basic.get(key) for key in ("name", "email", "city"))
        or profile.get("education")
        or profile.get("experiences")
        or profile.get("projects")
        or (profile.get("skills") or {}).get("tools")
        or (profile.get("skills") or {}).get("strengths")
        or profile.get("summary")
    )


def profile_context_text(profile: dict[str, Any]) -> str:
    """Professional facts only: no phone, email, WeChat, or links."""
    lines: list[str] = []
    intent = profile.get("job_intent") or {}
    if intent.get("titles"):
        lines.append("目标岗位：" + "、".join(intent["titles"]))
    if profile.get("summary"):
        lines.append("个人简介：" + str(profile["summary"]))
    skills = profile.get("skills") or {}
    if skills.get("tools"):
        lines.append("工具：" + "、".join(skills["tools"]))
    if skills.get("strengths"):
        lines.append("优势：" + "、".join(skills["strengths"]))
    for row in profile.get("experiences") or []:
        head = " · ".join(part for part in (row.get("company"), row.get("title")) if part)
        if head:
            lines.append(f"工作经历：{head}。{row.get('summary') or ''}".strip())
    for row in profile.get("projects") or []:
        head = " · ".join(part for part in (row.get("name"), row.get("role")) if part)
        if head:
            lines.append(f"项目经历：{head}。{row.get('summary') or ''}".strip())
    for row in profile.get("education") or []:
        head = " · ".join(part for part in (row.get("school"), row.get("major"), row.get("degree")) if part)
        if head:
            lines.append("教育经历：" + head)
    return "\n".join(lines)[: MAX_TEXT]


def profile_public(profile: dict[str, Any]) -> dict[str, Any]:
    data = normalize_profile(profile)
    data["completeness"] = profile_completeness(data)
    data["has_content"] = profile_has_content(data)
    return data


def save_profile(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    raw = payload.get("profile")
    if not isinstance(raw, dict):
        raise ApiError("profile 必须是 JSON 对象")
    store = get_store(mode)
    profile = normalize_profile(raw)
    profile["updated_at"] = _now()
    store.set_profile(profile)
    completeness = profile_completeness(profile)
    store.log("保存个人资料", f"完整度 {completeness['percent']}%；truth_confirmed={profile['truth_confirmed']}")
    return {
        "ok": True,
        "profile": profile_public(profile),
        "message": f"个人资料已保存到本机；完整度 {completeness['percent']}%。",
    }


def _extract_profile_from_cv(text: str) -> dict[str, Any]:
    profile = default_profile()
    basic = profile["basic"]
    heading = re.search(r"^\s*#\s+(.+)$", text, re.MULTILINE)
    if heading:
        name = re.sub(r"(的个人)?简历|resume|cv", "", heading.group(1), flags=re.IGNORECASE).strip(" -·|")
        basic["name"] = _clean_text(name, PROFILE_LIMITS["short"])
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
    if email:
        basic["email"] = email.group(0)[: PROFILE_LIMITS["short"]]
    phone = re.search(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", text)
    if phone:
        basic["phone"] = phone.group(0)
    for city in ("北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州", "西安", "长沙", "重庆", "天津", "合肥", "厦门", "青岛", "郑州", "济南", "大连", "宁波"):
        if city in text:
            basic["city"] = city
            break
    profile["skills"]["tools"] = [term for term in SKILL_TERMS if term in text]
    paragraphs = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-", "*", "|", ">"))
    ]
    for paragraph in paragraphs:
        if len(paragraph) >= 20:
            profile["summary"] = paragraph[: PROFILE_LIMITS["long"]]
            break
    return profile


def import_profile_cv(payload: dict[str, Any]) -> dict[str, Any]:
    """Suggest profile fields from the local workspace/resume.md; never auto-save."""
    mode = str(payload.get("mode") or "user")
    if mode != "user":
        raise ApiError("演示模式不读取真实简历；请切换到 user 模式")
    if not CV_PATH.is_file():
        raise ApiError("未找到 workspace/resume.md；可先在「个人资料」中手动填写", 404)
    text = CV_PATH.read_text(encoding="utf-8-sig")
    suggestion = _extract_profile_from_cv(text)
    store = get_store(mode)
    store.log("读取简历建议资料", "workspace/resume.md；未自动保存")
    return {
        "ok": True,
        "profile": suggestion,
        "message": "已从本地简历提取可识别字段；请核对后再保存。",
    }


def _job_id(record: dict[str, Any], index: int) -> str:
    raw = str(record.get("id") or "").strip()
    if raw:
        return _safe_id(raw, f"job-{index}")
    seed = "|".join(str(record.get(key) or "") for key in ("company", "title", "city"))
    return "j-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def _salary_label(record: dict[str, Any]) -> str:
    low, high = record.get("salary_min"), record.get("salary_max")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        return f"{int(low)//1000}–{int(high)//1000}k"
    return str(record.get("salary_text") or record.get("salary") or "未填写")


def _job_date(record: dict[str, Any]) -> str:
    for key in ("posted_at", "created_at", "date", "updated_at"):
        match = DATE_RE.search(str(record.get(key) or ""))
        if match:
            try:
                return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
            except ValueError:
                continue
    return "unknown"


def _score(record: dict[str, Any]) -> float | None:
    raw = record.get("score")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _hard_filter_decision(record: dict[str, Any]) -> str:
    value = record.get("hard_filter")
    if isinstance(value, dict):
        return str(value.get("status") or "unknown")
    return str(value or "unknown")


def _state_for_job(job: dict[str, Any], events: list[dict[str, Any]], queue: list[dict[str, Any]]) -> str:
    explicit = str(job.get("state") or "")
    if explicit in STATES:
        return explicit
    job_id = str(job.get("id") or "")
    current = ""
    for event in events:
        if str(event.get("job_id")) == job_id and str(event.get("to")) in STATES:
            current = str(event["to"])
    if current:
        return current
    if any(str(row.get("id")) == job_id and row.get("status") == "approved" for row in queue):
        return "简历已定制"
    if _hard_filter_decision(job) == "reject":
        return "淘汰"
    return "已采集"


CHANNEL_ALIASES = {
    "手动粘贴": "manual_paste",
    "手动录入": "manual_paste",
    "offerpilot 导出": "offerpilot_manual_export",
    "offerpilot导出": "offerpilot_manual_export",
    "岗位自动化导出": "offerpilot_manual_export",
}


def _normalize_channel(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    return CHANNEL_ALIASES.get(text.casefold(), text)


def _normalize_job(record: dict[str, Any], index: int, source: str) -> dict[str, Any]:
    job = dict(record)
    job["id"] = _job_id(record, index)
    job["company"] = str(record.get("company") or "未填写公司")
    job["title"] = str(record.get("title") or record.get("role") or "未填写岗位")
    job["city"] = str(record.get("city") or "")
    job["salary_min"] = record.get("salary_min")
    job["salary_max"] = record.get("salary_max")
    job["salary_text"] = str(record.get("salary_text") or record.get("salary") or "")
    job["source_channel"] = _normalize_channel(
        record.get("source_channel") or record.get("Source_Channel") or source
    )
    job["posted_at"] = record.get("posted_at")
    job["contact"] = record.get("contact")
    job["raw_text"] = str(record.get("raw_text") or record.get("description") or record.get("jd") or "")
    job["hard_filter"] = record.get("hard_filter") if isinstance(record.get("hard_filter"), dict) else {
        "status": _hard_filter_decision(record), "reasons": [], "warnings": [], "engine": "manual-import"
    }
    job["warnings"] = record.get("warnings") if isinstance(record.get("warnings"), list) else []
    job["fingerprint"] = str(record.get("fingerprint") or "")
    job["analytics"] = record.get("analytics") if isinstance(record.get("analytics"), dict) else {}
    job["created_at"] = record.get("created_at") or _now()
    job["score"] = _score(record)
    job["salary_label"] = _salary_label(job)
    job["date"] = _job_date(job)
    return job


def _job_fingerprint(job: dict[str, Any]) -> str:
    return "|".join(str(job.get(key) or "").strip() for key in ("company", "title", "city", "source_channel"))


def _demo_jobs() -> list[dict[str, Any]]:
    rows = []
    for index, path in enumerate(sorted(DEMO_DIR.glob("demo-job-*.md")), start=1):
        parsed = jd_intake.parse_jd_text(path.read_text(encoding="utf-8-sig"), path.stem)
        job = _normalize_job(parsed, index, "manual_paste")
        job["score"] = _demo_scores().get(str(job["id"]))
        rows.append(job)
    return rows


def _demo_scores() -> dict[str, float]:
    return {"demo-job-001": 4.7, "demo-job-002": 4.2, "demo-job-003": 3.5}


def _demo_queue() -> list[dict[str, Any]]:
    rows = []
    for job in _demo_jobs():
        score = _demo_scores().get(str(job["id"]))
        if score is None or score < 4.0:
            continue
        rows.append({
            "id": job["id"],
            "score": score,
            "company": job["company"],
            "title": job["title"],
            "status": "pending",
            "Source_Channel": job["source_channel"],
            "created_at": "2026-11-14T09:00:00+08:00",
            "high_confidence": score >= 4.5,
        })
    return rows


def _demo_mails() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(DEMO_DIR.glob("mail-*.json")):
        mail = mail_classifier.load_mail(path)
        result = mail_classifier.classify(mail)
        rows.append({"id": str(mail.get("message_id") or path.stem), "source_file": path.name, "mail": mail, "classification": result})
    return rows


def _demo_debriefs() -> list[dict[str, Any]]:
    text = (DEMO_DIR / "transcript-01.md").read_text(encoding="utf-8-sig")
    card = interview_debrief.debrief(text, "demo-transcript", bank_path=WEB_DIR / "data" / "demo" / "question-bank.json", config={
        **interview_debrief.load_config(),
        "question_bank_path": str(WEB_DIR / "data" / "demo" / "question-bank.json"),
        "interview_dir": str(WEB_DIR / "data" / "demo" / "downloads"),
    })
    card["id"] = "demo-debrief"
    card["source"] = "demo/transcript-01.md"
    return [card]


def _demo_events() -> list[dict[str, Any]]:
    return [
        {"job_id": "demo-job-001", "from": "已采集", "to": "已过滤", "note": "测试状态", "recorded_at": "2026-11-10T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "已过滤", "to": "简历已定制", "note": "测试状态", "recorded_at": "2026-11-11T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "简历已定制", "to": "已投递/已沟通", "note": "演示数据：人工投递后记录", "recorded_at": "2026-11-12T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "已投递/已沟通", "to": "一面", "note": "测试状态", "recorded_at": "2026-11-13T09:00:00+08:00"},
        {"job_id": "demo-job-002", "from": "已采集", "to": "已过滤", "note": "测试状态", "recorded_at": "2026-11-11T09:00:00+08:00"},
    ]


def _demo_variants() -> list[dict[str, Any]]:
    return [{
        "id": "demo-variant-001",
        "project": "虚构官网项目",
        "created_at": "2026-11-10T10:00:00+08:00",
        "text": "测试数据：用户手动改写的项目描述原文，未经模型生成或补充数字。",
        "sha256": hashlib.sha256("demo".encode("utf-8")).hexdigest(),
    }]


def _demo_profile() -> dict[str, Any]:
    """Obviously fictional demo profile; never a real person's contact data."""
    return normalize_profile({
        "truth_confirmed": True,
        "basic": {
            "name": "演示用户（虚构演示）",
            "phone": "00000000000",
            "email": "demo@example.invalid",
            "city": "上海",
            "wechat": "demo_only",
            "links": "https://example.invalid/portfolio",
        },
        "job_intent": {
            "titles": ["产品经理", "产品助理"],
            "cities": ["上海", "杭州"],
            "salary_min": 15000,
            "salary_max": 25000,
            "job_type": "全职",
            "availability": "一个月内",
        },
        "education": [{
            "school": "虚构大学",
            "major": "信息管理",
            "degree": "本科",
            "start": "2018-09",
            "end": "2022-06",
            "summary": "演示数据，仅用于验证个人资料模块。",
        }],
        "experiences": [{
            "company": "虚构科技有限公司",
            "title": "产品实习生",
            "start": "2021-07",
            "end": "2022-05",
            "summary": "演示经历：参与需求分析、用户调研与产品原型整理。",
        }],
        "projects": [{
            "name": "虚构官网改版",
            "role": "产品助理",
            "start": "2021-09",
            "end": "2022-03",
            "summary": "演示项目：整理流程图、竞品资料与用户体验反馈。",
        }],
        "skills": {
            "tools": ["Axure", "Visio", "Excel", "PowerPoint"],
            "strengths": ["需求分析", "用户调研", "数据分析"],
        },
        "summary": "虚构演示资料：信息管理背景，关注需求分析与用户体验，正在寻找产品方向的机会。",
        "excluded_terms": ["外包", "驻场"],
    })


def _demo_bank() -> dict[str, Any]:
    return {
        "version": 1,
        "questions": [
            {"id": "q-demo-1", "question": "请解释一次需求分析？", "section": "业务拆解", "source": "user_demo"},
            {"id": "q-demo-2", "question": "如何复盘量化不足与逻辑漏洞？", "section": "项目深挖", "source": "user_demo"},
        ],
    }


def seed_demo(store: Store) -> None:
    """Seed isolated, obviously fictional demo data; never overwrite user data."""
    if store.mode != "demo":
        raise ApiError("只能重置演示数据")
    store.set_jobs(_demo_jobs())
    store.set_queue(_demo_queue())
    store.set_mails(_demo_mails())
    store.set_debriefs(_demo_debriefs())
    store.set_variants(_demo_variants())
    store.set_question_bank(_demo_bank())
    demo_profile = _demo_profile()
    demo_profile["updated_at"] = "2026-11-14T09:00:00+08:00"
    store.set_profile(demo_profile)
    store.files["events"].write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in _demo_events()), encoding="utf-8")
    store.files["pipeline"].write_text("", encoding="utf-8")
    store.files["activity"].write_text("", encoding="utf-8")
    for path in store.files["downloads"].glob("*"):
        if path.is_file():
            path.unlink()
    store.log("载入演示数据", "3 条虚构 JD、2 封虚构邮件、1 份虚构复盘")


def get_store(mode: str, seed_if_empty: bool = True) -> Store:
    if mode not in Store.VALID_MODES:
        raise ApiError("数据模式只能是 demo 或 user")
    store = Store(mode)
    if mode == "demo" and seed_if_empty and not store.jobs():
        seed_demo(store)
    return store


def _activity_title(row: dict[str, Any]) -> str:
    return f"{'完成' if row.get('ok', True) else '拒绝'} · {row.get('action') or '操作'}"


def _filter_payload(jobs: list[dict[str, Any]], mails: list[dict[str, Any]], debriefs: list[dict[str, Any]], events: list[dict[str, Any]], query: dict[str, str]) -> dict[str, Any]:
    period = query.get("period", "all")
    start = None
    today = dt.date.today()
    if period == "7d":
        start = today - dt.timedelta(days=7)
    elif period == "30d":
        start = today - dt.timedelta(days=30)
    elif period == "90d":
        start = today - dt.timedelta(days=90)

    def in_period(value: str) -> bool:
        # No period filter: keep every row, including undated ones. With a
        # period filter, an empty/unknown/invalid date cannot be proven to be
        # inside the window, so exclude it instead of silently including it.
        if not start:
            return True
        text = (value or "").strip()
        if not text or text.casefold() == "unknown":
            return False
        try:
            return dt.date.fromisoformat(text[:10]) >= start
        except ValueError:
            return False

    channel = query.get("channel", "all")
    state = query.get("state", "all")
    filtered_jobs = []
    for job in jobs:
        if channel != "all" and job.get("source_channel") != channel:
            continue
        if not in_period(str(job.get("date") or "")):
            continue
        filtered_jobs.append(job)
    filtered_ids = {str(job.get("id")) for job in filtered_jobs}
    filtered_events = [event for event in events if str(event.get("job_id")) in filtered_ids]
    filtered_mails = [mail for mail in mails if in_period(str(mail.get("mail", {}).get("date") or "")) or not start]
    filtered_debriefs = [card for card in debriefs if in_period(str(card.get("created_at") or "")) or not start]
    if state != "all":
        filtered_ids &= {
            str(job.get("id")) for job in filtered_jobs
            if job.get("state") == state
        }
        filtered_jobs = [job for job in filtered_jobs if str(job.get("id")) in filtered_ids]
        filtered_events = [event for event in filtered_events if str(event.get("job_id")) in filtered_ids]
    return {"jobs": filtered_jobs, "mails": filtered_mails, "debriefs": filtered_debriefs, "events": filtered_events, "start": start.isoformat() if start else None}


def _state_counts(jobs: list[dict[str, Any]], events: list[dict[str, Any]], queue: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for job in jobs:
        counts[_state_for_job(job, events, queue)] += 1
    return {state: counts.get(state, 0) for state in STATES}


def _channel_rows(jobs: list[dict[str, Any]], events: list[dict[str, Any]], debriefs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = analytics.analyze(jobs, events, debriefs)
    return result["channels"]


def _quarter_rows(jobs: list[dict[str, Any]], events: list[dict[str, Any]], debriefs: list[dict[str, Any]]) -> dict[str, Any]:
    return analytics.analyze(jobs, events, debriefs)["quarterly_radar"]


def _weakness_rows(debriefs: list[dict[str, Any]]) -> list[dict[str, str | int]]:
    result = interview_analytics.summarize(debriefs)
    counts = result.get("weakness_tag_counts", {})
    return [{"label": tag, "value": int(counts.get(tag, 0))} for tag in WEAKNESS_TAGS]


def _mail_rows(mails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter(str(row.get("classification", {}).get("intent") or "other") for row in mails)
    return [
        {"key": key, "label": INTENT_LABELS.get(key, key), "value": counts.get(key, 0)}
        for key in INTENT_LABELS
    ]


def _demo_offerpilot_state(store: Store) -> dict[str, Any]:
    profile = store.profile()
    intent = profile.get("job_intent") if isinstance(profile.get("job_intent"), dict) else {}
    skills = profile.get("skills") if isinstance(profile.get("skills"), dict) else {}
    return {
        "ok": True,
        "embedded": True,
        "base_url": "embedded://offerpilot",
        "api_version": OFFERPILOT_AGENT_API_VERSION,
        "preferences": {
            "keywords": list(intent.get("titles") or []),
            "cities": list(intent.get("cities") or []),
            "salary": {"min": intent.get("salary_min", 0), "max": intent.get("salary_max", 0)},
            "deal_breakers": list(profile.get("excluded_terms") or []),
            "jd_deal_breakers": [],
            "blocked_companies": [],
            "education": (profile.get("basic") or {}).get("education", ""),
            "recruitment_type": intent.get("job_type", ""),
            "allow_internship": intent.get("job_type") == "实习",
            "score_threshold": 60,
            "platform_order": ["boss"],
            "max_pages": {"boss": 1},
        },
        "ai": {"configured": False},
        "capabilities": {
            "collect_without_ai": False,
            "evaluate_with_local_agent_without_ai": False,
            "monitor_without_ai": False,
            "start_full_flow": False,
            "human_confirmation_before_delivery": True,
        },
        "task": None,
        "last_task": None,
        "resume": {"available": False, "filename": None, "size_label": None, "uploaded_at": None},
        "mode": "demo",
        "note": "演示模式只展示虚构数据，不启动真实采集。",
    }


def _demo_offerpilot_jobs(store: Store) -> dict[str, Any]:
    allowed = ("id", "title", "company", "salary", "city", "experience", "education", "recruitment_type", "status", "score", "created_at", "updated_at")
    jobs = []
    for row in store.jobs():
        jobs.append({key: row.get(key) for key in allowed if key in row})
    return {"ok": True, "embedded": True, "source": "demo", "read_only": True, "jobs": jobs, "count": len(jobs), "limit": 100}


def get_offerpilot_state(mode: str = "user") -> dict[str, Any]:
    """Return the credential-free state of the in-process OfferPilot backend."""
    if mode == "demo":
        return _demo_offerpilot_state(get_store("demo"))
    state = offerpilot_runtime.get_state()
    if not state.get("ok"):
        state.setdefault("base_url", "embedded://offerpilot")
    return state


def get_offerpilot_jobs(mode: str = "user") -> dict[str, Any]:
    """Read the embedded OfferPilot job pool without an HTTP hop."""
    if mode == "demo":
        return _demo_offerpilot_jobs(get_store("demo"))
    return offerpilot_runtime.get_jobs()


def upload_offerpilot_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Store a resume for the embedded runtime's scoring step (user mode only)."""
    mode = str(payload.get("mode") or payload.get("data_mode") or "user")
    if mode != "user":
        raise ApiError("演示模式不能上传简历；请切换到「我的 user」", 400)
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise ApiError("缺少简历文件名")
    if len(filename) > 240 or any(ord(char) < 32 for char in filename):
        raise ApiError("简历文件名无效")
    encoded = _bounded_text(payload.get("content_base64"), "简历内容", 7 * 1024 * 1024)
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ApiError("简历内容不是有效的 base64") from exc
    try:
        result = offerpilot_runtime.save_resume(filename, raw)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    store = get_store(mode)
    store.log("上传评分简历", f"{result.get('filename')}；仅保存在本机运行时目录")
    return {
        "ok": True,
        "resume": result,
        "message": f"已保存简历「{result.get('filename')}」；本次采集可以自动评分",
    }


OFFERPILOT_OPTION_KEYS = {"platform", "keywords", "cities", "max_pages", "auto_score", "pace"}
OFFERPILOT_PACE_MULTIPLIERS = {"cautious": 3.0, "standard": 1.5, "fast": 1.0}


def _offerpilot_text_list(value: Any, label: str, limit: int) -> list[str]:
    if isinstance(value, str):
        items = value.replace("，", ",").split(",")
    elif isinstance(value, list):
        items = value
    else:
        raise ApiError(f"{label}必须是逗号分隔的文本或字符串数组")
    cleaned: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 80:
            raise ApiError(f"{label}单项不能超过 80 个字符")
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        raise ApiError(f"至少填写一个{label}")
    if len(cleaned) > limit:
        raise ApiError(f"{label}最多 {limit} 个")
    return cleaned


def _offerpilot_options(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the optional search override sent by the collection form."""
    raw = payload.get("options")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiError("采集设置必须是对象")
    unexpected = sorted(set(raw) - OFFERPILOT_OPTION_KEYS)
    if unexpected:
        raise ApiError("采集设置包含不支持的字段：" + "、".join(unexpected))
    platform = str(raw.get("platform") or "boss").strip().lower()
    if platform != "boss":
        raise ApiError("当前采集窗口只开放 BOSS 直聘；其他平台请使用静态 JSON 导入")
    keywords = _offerpilot_text_list(raw.get("keywords"), "搜索关键词", 10)
    cities = _offerpilot_text_list(raw.get("cities"), "城市", 5)
    try:
        max_pages = int(raw.get("max_pages", 1))
    except (TypeError, ValueError) as exc:
        raise ApiError("每个关键词的页数必须是整数") from exc
    if not 1 <= max_pages <= 10:
        raise ApiError("每个关键词的页数必须在 1–10 之间")
    auto_score = raw.get("auto_score", False)
    if not isinstance(auto_score, bool):
        raise ApiError("auto_score 必须是布尔值")
    pace = str(raw.get("pace") or "cautious").strip().lower()
    if pace not in OFFERPILOT_PACE_MULTIPLIERS:
        raise ApiError("采集节奏只能是 cautious、standard 或 fast")
    return {
        "platform_order": [platform],
        "platforms": {
            platform: {
                "keywords": keywords,
                "cities": cities,
                "max_pages": max_pages,
            }
        },
        "auto_score": auto_score,
        "pace": pace,
    }


def start_offerpilot_task(payload: dict[str, Any]) -> dict[str, Any]:
    task_mode = str(payload.get("mode") or "")
    data_mode = str(payload.get("data_mode") or "user")
    if set(payload) - {"mode", "data_mode", "confirm", "risk_acknowledged", "options", "action"}:
        raise ApiError("岗位自动化任务只接受 mode、data_mode、confirm、risk_acknowledged 和 options")
    if payload.get("action") not in (None, "offerpilot-start"):
        raise ApiError("动作与 OfferPilot 启动请求不匹配")
    if data_mode not in Store.VALID_MODES:
        raise ApiError("数据模式只能是 demo 或 user")
    if data_mode == "demo":
        raise ApiError("演示模式不启动真实采集；请切换到用户数据后再启动", 403)
    if task_mode not in OFFERPILOT_TASK_MODES:
        raise ApiError("仅允许 collect、monitor 或 full；发送任务不开放直接调用", 403)
    if payload.get("confirm") is not True:
        raise ApiError("启动 岗位自动化任务前必须明确传 confirm: true", 400)
    if payload.get("risk_acknowledged") is not True:
        raise ApiError("招聘平台自动化存在账号封禁风险；确认风险后传 risk_acknowledged: true", 400)
    options = _offerpilot_options(payload)
    if task_mode == "monitor" and options is not None:
        raise ApiError("监控任务不接受搜索条件；请选择 collect 或 full")
    try:
        response = (
            offerpilot_runtime.start_task(task_mode)
            if options is None
            else offerpilot_runtime.start_task(task_mode, options)
        )
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    except KeyError as exc:
        raise ApiError("岗位自动化任务不存在", 404) from exc
    except Exception as exc:
        raise ApiError(f"岗位自动化 启动失败：{type(exc).__name__}", 500) from exc
    message = "岗位自动化任务已受控提交；发送仍须经过人工确认门和配置时间窗口"
    if task_mode == "collect":
        message = "采集任务已受控提交；完成后会自动导入岗位池，再到「岗位池」挑选并加入审批队列"
    return {"ok": True, "task": response, "message": message}


def start_offerpilot_greet(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate greetings for approved jobs. Never sends anything."""
    data_mode = str(payload.get("mode") or payload.get("data_mode") or "user")
    if data_mode not in Store.VALID_MODES:
        raise ApiError("数据模式只能是 demo 或 user")
    if data_mode == "demo":
        raise ApiError("演示模式不能生成招呼语；请切换到「我的 user」", 403)
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError("请先勾选至少一条已确认岗位")
    if len(ids) > 10:
        raise ApiError("一次最多为 10 条岗位生成招呼语")
    store = get_store(data_mode)
    queue = {str(row.get("id")): row for row in store.queue()}
    jobs = {str(job.get("id")): job for job in store.jobs()}
    vendor_ids: list[str] = []
    invalid: list[str] = []
    for item in ids:
        job_id = str(item or "").strip()
        row = queue.get(job_id)
        if not row or row.get("status") != "approved":
            invalid.append(job_id or "?")
            continue
        vendor_id = str((jobs.get(job_id) or {}).get("offerpilot_id") or "").strip()
        if not vendor_id:
            invalid.append(job_id)
            continue
        if vendor_id not in vendor_ids:
            vendor_ids.append(vendor_id)
    if invalid:
        raise ApiError(
            "只有已确认且来自采集结果的岗位可以生成招呼语；请检查："
            + "、".join(invalid[:5]),
            409,
        )
    try:
        result = offerpilot_runtime.start_greet_task(vendor_ids)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    except KeyError as exc:
        raise ApiError("岗位自动化任务不存在", 404) from exc
    except Exception as exc:
        raise ApiError(f"生成招呼语失败：{type(exc).__name__}", 500) from exc
    store.log("生成招呼语", f"{len(vendor_ids)} 条；只生成，不发送")
    return {
        "ok": True,
        "task": result.get("task"),
        "requested": result.get("requested", len(vendor_ids)),
        "message": f"已开始为 {len(vendor_ids)} 条岗位生成招呼语；只生成，不发送",
    }


def preflight_offerpilot_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Check the same start conditions without launching a task."""
    task_mode = str(payload.get("mode") or "collect")
    data_mode = str(payload.get("data_mode") or "user")
    if set(payload) - {"mode", "data_mode", "options", "action"}:
        raise ApiError("启动前检查只接受 mode、data_mode 和 options")
    if payload.get("action") not in (None, "offerpilot-preflight"):
        raise ApiError("动作与 OfferPilot 启动前检查不匹配")
    if data_mode not in Store.VALID_MODES:
        raise ApiError("数据模式只能是 demo 或 user")
    if data_mode == "demo":
        raise ApiError("演示模式只读；切换到用户数据后再检查真实采集环境", 403)
    if task_mode not in OFFERPILOT_TASK_MODES:
        raise ApiError("仅允许 collect、monitor 或 full；发送任务不开放直接调用", 403)
    options = _offerpilot_options(payload)
    if task_mode == "monitor" and options is not None:
        raise ApiError("监控任务不接受搜索条件；请选择 collect 或 full")
    try:
        result = offerpilot_runtime.preflight(task_mode, options)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    except Exception as exc:
        raise ApiError(f"岗位自动化 启动前检查失败：{type(exc).__name__}", 500) from exc
    return {"ok": bool(result.get("ok")), **result}


OFFERPILOT_APPROVAL_RAW = 71.0


def _offerpilot_score(raw_score: Any) -> float | None:
    """Map OfferPilot's 0–100 score onto the workbench's 0–5 scale.

    Anchor OfferPilot's own approval threshold (71) at the workbench threshold
    (4.0), so a job that OfferPilot considers qualified can enter the approval
    queue after import.  Values above 88.75 are capped at 5.0.
    """
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool) or raw_score <= 0:
        return None
    value = float(raw_score)
    if value <= 5:
        return round(value, 1)
    return min(5.0, round(value * 4.0 / OFFERPILOT_APPROVAL_RAW, 1))


def _rescale_imported_jobs(store: Store) -> int:
    """Re-map previously imported OfferPilot scores to the anchored scale."""
    rows = store.jobs()
    changed = 0
    for row in rows:
        if not row.get("offerpilot_id"):
            continue
        raw = row.get("score_raw")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= 5:
            continue
        score = _offerpilot_score(raw)
        if score is None:
            continue
        if row.get("score") != score or row.get("score_scale") != "0-100→0-5（71→4.0）":
            row["score"] = score
            row["score_scale"] = "0-100→0-5（71→4.0）"
            changed += 1
    if changed:
        store.set_jobs(rows)
    return changed


def _import_offerpilot_records(store: Store, runtime_jobs: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    """Copy selected read-only OfferPilot jobs into the workbench job pool."""
    rows = store.jobs()
    existing = {_job_fingerprint(row) for row in rows}
    by_id = {str(job.get("id")): job for job in runtime_jobs if isinstance(job, dict)}
    added: list[str] = []
    duplicates = 0
    unscored = 0
    for index, job_id in enumerate(ids, start=1):
        source = by_id.get(job_id)
        if source is None:
            continue
        raw_score = source.get("score")
        score = _offerpilot_score(raw_score)
        if score is None:
            unscored += 1
        record = {
            "company": source.get("company"),
            "title": source.get("title"),
            "city": source.get("city"),
            "salary_text": source.get("salary"),
            "posted_at": source.get("created_at"),
            "source_channel": "boss",
            "raw_text": "",
            "score": score,
            "offerpilot_id": job_id,
            "score_raw": raw_score if score is not None else None,
            "score_scale": "0-100→0-5（71→4.0）" if score is not None else None,
        }
        job = _normalize_job(record, index, "boss")
        fingerprint = _job_fingerprint(job)
        if fingerprint in existing:
            duplicates += 1
            continue
        existing.add(fingerprint)
        rows.append(job)
        added.append(str(job["id"]))
    store.set_jobs(rows)
    store.log("导入采集岗位", f"新增 {len(added)} 条，重复 {duplicates} 条，未评分 {unscored} 条")
    message = f"已导入 {len(added)} 条到岗位池"
    if duplicates:
        message += f"，跳过 {duplicates} 条重复记录"
    if unscored:
        message += f"；其中 {unscored} 条没有评分，不会进入审批队列"
    return {"ok": True, "added": added, "duplicates": duplicates, "unscored": unscored, "message": message}


def import_offerpilot_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    data_mode = str(payload.get("data_mode") or payload.get("mode") or "user")
    if data_mode != "user":
        raise ApiError("采集结果只能导入 user 岗位池；demo 数据不会写入真实岗位")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError("请先勾选至少一条采集结果")
    if len(ids) > 100:
        raise ApiError("一次最多导入 100 条")
    safe_ids: list[str] = []
    for item in ids:
        text = str(item or "").strip()
        # IDs come from the local runtime database, not from a URL or path.
        # They may contain platform-specific punctuation, so only reject
        # empty/oversized/control-character values and match them exactly
        # against the runtime's own job list below.
        if not text or len(text) > 200 or any(ord(char) < 32 for char in text):
            raise ApiError("采集结果 id 无效")
        if text not in safe_ids:
            safe_ids.append(text)
    response = offerpilot_runtime.get_jobs(limit=500)
    if not response.get("ok"):
        raise ApiError(str(response.get("error") or "无法读取采集结果"), 503)
    runtime_jobs = response.get("jobs") or []
    available = {str(job.get("id")) for job in runtime_jobs if isinstance(job, dict)}
    selected = [job_id for job_id in safe_ids if job_id in available]
    if not selected:
        raise ApiError("选中的岗位已不在采集结果中，请刷新后重新选择", 409)
    store = get_store("user")
    _rescale_imported_jobs(store)
    result = _import_offerpilot_records(store, runtime_jobs, selected)
    missing = len(safe_ids) - len(selected)
    if missing:
        result["missing"] = missing
        result["message"] += f"；{missing} 条已不在采集结果中"
    return result


def stop_offerpilot_task(task_id: str, data_mode: str = "user") -> dict[str, Any]:
    safe_id = str(task_id or "").strip()
    if data_mode not in Store.VALID_MODES:
        raise ApiError("数据模式只能是 demo 或 user")
    if data_mode == "demo":
        raise ApiError("演示模式没有真实采集任务", 403)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", safe_id):
        raise ApiError("岗位自动化 task_id 无效")
    try:
        result = offerpilot_runtime.stop_task(safe_id)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except KeyError as exc:
        raise ApiError("岗位自动化任务不存在", 404) from exc
    except Exception as exc:
        raise ApiError(f"岗位自动化 停止失败：{type(exc).__name__}", 500) from exc
    return {"ok": True, "task": result}


def pipeline_contract() -> dict[str, Any]:
    """Describe the six-stage flow and the embedded automation runtime."""
    return {
        "version": "1.0",
        "flow": [stage["title"] for stage in PIPELINE_STAGES],
        "stages": [
            {
                "key": stage["key"],
                "title": stage["title"],
                "owner": stage["owner"],
                "owner_label": stage["owner_label"],
                "description": stage["description"],
                "entry_panel": stage["entry"],
                "local_actions": list(stage["actions"]),
                "external_event_stage": stage.get("event_stage"),
            }
            for stage in PIPELINE_STAGES
        ],
        "event_endpoint": "POST /api/pipeline/event",
        "offerpilot": {
            "base_url": "embedded://offerpilot",
            "agent_api_version": OFFERPILOT_AGENT_API_VERSION,
            "loopback_only": True,
            "owns_credentials": True,
            "embedded": True,
            "separate_service_required": False,
            "runtime_dir": "web/data/<mode>/offerpilot",
        },
        "event_schema": {
            "type": "object",
            "required": ["stage", "status"],
            "properties": {
                "mode": {"type": "string", "enum": ["demo", "user"], "default": "user"},
                "stage": {"type": "string", "enum": ["send", "monitor"]},
                "status": {"type": "string", "enum": list(PIPELINE_EVENT_STATUSES)},
                "job_id": {"type": "string", "description": "本地岗位 id（可选）"},
                "message": {"type": "string", "maxLength": 2000},
                "occurred_at": {"type": "string", "format": "date-time", "maxLength": 64},
            },
        },
        "guarantees": {
            "auto_submit": False,
            "auto_send": False,
            "platform_scraping": "岗位自动化 采集器；仅本机、仅人工确认后投递",
            "external_api_calls": "AI 服务与招聘平台页面由岗位自动化 发起；工作台不新增远程服务",
            "loopback_only": True,
            "human_confirmation_before_delivery": True,
            "configured_send_window_required": True,
            "event_is_record_only": True,
            "separate_offerpilot_service": False,
        },
        "reserved_features": [dict(feature) for feature in RESERVED_FEATURES],
        "document": "web/PIPELINE-API.md",
    }


def pipeline_status(
    store: Store,
    jobs: list[dict[str, Any]],
    queue: list[dict[str, Any]],
    mails: list[dict[str, Any]],
    boss_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute display counts for the six-stage workbench panel.

    Counts are global (not affected by the table filters) so the flow panel
    always describes the whole local dataset.
    """
    prepared = sum(1 for path in store.files["downloads"].glob("prepare-*") if path.is_file())
    external = store.pipeline_events()
    boss = boss_state if boss_state is not None else get_offerpilot_state(store.mode)
    boss_connected = bool(boss.get("ok"))
    boss_task = boss.get("task") if isinstance(boss.get("task"), dict) else {}
    send_events = [row for row in external if row.get("stage") == "send"]
    monitor_events = [row for row in external if row.get("stage") == "monitor"]
    approved = sum(1 for row in queue if row.get("status") == "approved")
    evaluated = sum(1 for job in jobs if _score(job) is not None)
    counts = {
        "intake": len(jobs),
        "screening": evaluated,
        "approval": approved,
        "greeting": prepared,
        "send": sum(1 for row in send_events if row.get("status") == "succeeded"),
        "monitor": len(mails),
    }
    units = {
        "intake": "个岗位",
        "screening": "个已评分",
        "approval": "个已确认",
        "greeting": "份准备清单",
        "send": "条成功回报",
        "monitor": "封本地邮件",
    }
    statuses = {
        "intake": "connected" if boss_connected else "ready",
        "screening": "connected" if boss_connected else "ready",
        "approval": "ready",
        "greeting": "connected" if boss_connected else "ready",
        "send": "active" if boss_task.get("mode") in {"full", "deliver"} and boss_task.get("status") in {"running", "stopping"} else "connected" if send_events else "waiting",
        "monitor": "active" if boss_task.get("mode") == "monitor" and boss_task.get("status") in {"running", "stopping"} else "connected" if boss_connected or monitor_events else "local",
    }
    stages = []
    for stage in PIPELINE_STAGES:
        key = stage["key"]
        stages.append({
            "key": key,
            "title": stage["title"],
            "owner": stage["owner"],
            "owner_label": stage["owner_label"],
            "description": stage["description"],
            "entry": stage["entry"],
            "count": counts[key],
            "unit": units[key],
            "status": statuses[key],
            "external": stage["owner"] in ("external", "hybrid"),
        })
    return {
        "version": "1.0",
        "flow": [stage["title"] for stage in PIPELINE_STAGES],
        "stages": stages,
        "external_events": list(reversed(external))[:8],
        "external_connected": bool(external),
        "offerpilot": {
            "connected": boss_connected,
            "base_url": boss.get("base_url") or OFFERPILOT_EMBEDDED_URL,
            "task": boss_task or None,
            "last_task": boss.get("last_task") if boss_connected else None,
            "preferences": boss.get("preferences") if boss_connected else None,
            "ai": boss.get("ai") if boss_connected else None,
            "capabilities": boss.get("capabilities") if boss_connected else None,
            "resume": boss.get("resume") if boss_connected else None,
            "error": boss.get("error") if not boss_connected else None,
        },
        "reserved_features": [dict(feature) for feature in RESERVED_FEATURES],
    }


def ingest_pipeline_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Record an external agent report. This never sends or submits anything."""
    mode = str(payload.get("mode") or "user")
    stage = str(payload.get("stage") or "")
    if stage not in ("send", "monitor"):
        raise ApiError("外部回报只接受 send 或 monitor 阶段")
    status = str(payload.get("status") or "")
    if status not in PIPELINE_EVENT_STATUSES:
        raise ApiError("外部回报状态只能是 started / succeeded / failed / skipped")
    message = _bounded_text(payload.get("message", ""), "回报说明", 2000)
    job_id = _safe_id(payload.get("job_id"), "")
    occurred_at = str(payload.get("occurred_at") or "")[:64]
    store = get_store(mode)
    event = {
        "received_at": _now(),
        "stage": stage,
        "status": status,
        "job_id": job_id,
        "message": message,
        "occurred_at": occurred_at,
        "actor": "external_agent",
        "auto_submit": False,
    }
    store.append_pipeline_event(event)
    store.log("记录外部 Agent 回报", f"{stage}/{status} {job_id}".strip())
    return {
        "ok": True,
        "event": event,
        "message": "已记录外部 Agent 回报；没有触发发送、投递或平台请求",
    }


def snapshot(mode: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    query = query or {}
    store = get_store(mode)
    jobs = store.jobs()
    events = store.events()
    queue = store.queue()
    profile = store.profile()
    profile_skills = list((profile.get("skills") or {}).get("tools") or []) + list((profile.get("skills") or {}).get("strengths") or [])
    cv_text = CV_PATH.read_text(encoding="utf-8-sig") if CV_PATH.is_file() else ""
    skill_terms = [term for term in SKILL_TERMS if any(term in value for value in profile_skills)]
    if not skill_terms:
        skill_terms = [term for term in SKILL_TERMS if term in cv_text]
    profile_intent = profile.get("job_intent") or {}
    target_cities = profile_intent.get("cities") or filters.load_config()["target_cities"]
    excluded_terms = list(dict.fromkeys(list(profile.get("excluded_terms") or []) + list(filters.load_config()["excluded_terms"])))
    for job in jobs:
        job["state"] = _state_for_job(job, events, queue)
        job["approval"] = next((row.get("status") for row in queue if str(row.get("id")) == str(job.get("id"))), None)
    sliced = _filter_payload(jobs, store.mails(), store.debriefs(), events, query)
    boss_state = get_offerpilot_state(mode)
    filtered_jobs = sliced["jobs"]
    state_counts = _state_counts(filtered_jobs, sliced["events"], queue)
    channel_rows = _channel_rows(filtered_jobs, sliced["events"], sliced["debriefs"])
    quarter = _quarter_rows(filtered_jobs, sliced["events"], sliced["debriefs"])
    weakness = _weakness_rows(sliced["debriefs"])
    applied = sum(int(row.get("投递数") or 0) for row in channel_rows)
    interviews = sum(int(row.get("面试数") or 0) for row in channel_rows)
    offers = sum(int(row.get("Offer数") or 0) for row in channel_rows)
    filtered_job_ids = {str(job.get("id")) for job in filtered_jobs}
    pending = sum(
        1
        for row in queue
        if row.get("status") == "pending" and str(row.get("id")) in filtered_job_ids
    )
    channels = sorted({str(job.get("source_channel") or "unknown") for job in jobs})
    warnings = sum(len(job.get("warnings") or []) for job in filtered_jobs)
    queue_view = [dict(row) for row in queue]
    if boss_state.get("ok"):
        job_by_id = {str(job.get("id")): job for job in jobs}
        vendor_by_job: dict[str, str] = {}
        for row in queue_view:
            if row.get("status") != "approved":
                continue
            vendor_id = str((job_by_id.get(str(row.get("id"))) or {}).get("offerpilot_id") or "").strip()
            if vendor_id:
                vendor_by_job[str(row.get("id"))] = vendor_id
        if vendor_by_job:
            try:
                preview = offerpilot_runtime.get_greetings(list(vendor_by_job.values())[:50])
            except Exception:
                preview = {"ok": False, "greetings": []}
            by_vendor = {
                str(item.get("id")): item
                for item in (preview.get("greetings") or [])
                if isinstance(item, dict)
            }
            for row in queue_view:
                vendor_id = vendor_by_job.get(str(row.get("id")))
                item = by_vendor.get(vendor_id) if vendor_id else None
                if item:
                    row["greeting"] = {
                        key: item.get(key)
                        for key in ("status", "greeting", "selection", "style_issues", "reviewed", "ready")
                    }
    return {
        "mode": mode,
        "generated_at": _now(),
        "filter": {"period": query.get("period", "all"), "channel": query.get("channel", "all"), "state": query.get("state", "all")},
        "states": STATES,
        "transitions": state_machine.load_config()["transitions"],
        "scope": {"jobs": len(filtered_jobs), "all_jobs": len(jobs), "mails": len(sliced["mails"]), "debriefs": len(sliced["debriefs"]), "started_at": sliced["start"]},
        "kpis": {"jobs": len(filtered_jobs), "pending": pending, "interviews": interviews, "offers": offers, "applied": applied, "warnings": warnings},
        "state_counts": state_counts,
        "channels": channels,
        "channel_rows": channel_rows,
        "quarterly_radar": quarter,
        "weakness_rows": weakness,
        "mail_rows": _mail_rows(sliced["mails"]),
        "jobs": [{k: job.get(k) for k in (
            "id", "company", "title", "city", "salary_label", "source_channel",
            "posted_at", "hard_filter", "warnings", "score", "state", "approval",
            "fingerprint", "raw_text", "date", "created_at",
        )} for job in filtered_jobs],
        "queue": queue_view,
        "mails": sliced["mails"],
        "debriefs": sliced["debriefs"],
        "events": sorted(
            sliced["events"],
            key=lambda event: str(event.get("recorded_at") or ""),
            reverse=True,
        )[:30],
        "variants": store.variants(),
        "question_bank": store.question_bank(),
        "activity": [{"title": _activity_title(row), **row} for row in store.activity()],
        "downloads": store.list_downloads(),
        "pipeline": pipeline_status(store, jobs, queue, store.mails(), boss_state),
        "profile": profile_public(profile),
        "config": {
            "target_cities": target_cities,
            "excluded_terms": excluded_terms,
            "title_keywords": filters.load_config()["title_keywords"],
            "salary_min_threshold": filters.load_config()["salary"]["min_threshold"],
            "score": approval_queue.load_config()["score"],
            "boundaries": approval_queue.load_config()["boundaries"],
            "weakness_tags": list(WEAKNESS_TAGS),
        },
        "cv_skills": skill_terms,
        "boundaries": {
            "auto_submit": False,
            "platform_scraping": "embedded_offerpilot_only",
            "browser_takeover": "embedded_offerpilot_only",
            "offerpilot_integration": "embedded" if boss_state.get("ok") else "unavailable",
            "wechat_hook": False,
            # OfferPilot calls the user's configured AI service and platform pages;
            # the workbench itself does not add another remote service.
            "external_api": "embedded_offerpilot_only",
            "real_imap": "not_implemented_offline_build",
            "real_feishu_http": "dry_run_only",
            "real_asr": "unavailable",
        },
    }


def parse_jd(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    text = _bounded_text(payload.get("text"), "JD 文本")
    source = str(payload.get("source_channel") or "manual_paste")[:100]
    stable_id = _safe_id(payload.get("id"), "jd-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10])
    parsed = jd_intake.parse_jd_text(text, stable_id)
    parsed["source_channel"] = parsed.get("source_channel") or source
    job = _normalize_job(parsed, 1, source)
    job["score"] = _score(payload)
    store = get_store(mode)
    rows = store.jobs()
    key = _job_fingerprint(job)
    if any(_job_fingerprint(row) == key for row in rows):
        store.log("拒绝重复岗位", job["title"], False)
        return {"ok": False, "duplicate": True, "job": job, "message": "相同公司、岗位、城市、渠道的记录已存在"}
    rows.append(job)
    store.set_jobs(rows)
    store.log("录入 JD", f"{job['company']} · {job['title']}")
    return {"ok": True, "job": job, "message": "岗位已录入本地工作区"}


def import_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    text = _bounded_text(payload.get("text"), "导出 JSON")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(f"JSON 无法解析：{exc.msg}") from exc
    converted = offerpilot_adapter.convert_payload(raw)
    store = get_store(mode)
    rows = store.jobs()
    existing = {_job_fingerprint(row) for row in rows}
    added: list[str] = []
    duplicates = 0
    for index, record in enumerate(converted["jobs"], start=1):
        job = _normalize_job(record, index, converted["source_channel"])
        if _job_fingerprint(job) in existing:
            duplicates += 1
            continue
        existing.add(_job_fingerprint(job))
        rows.append(job)
        added.append(str(job["id"]))
    store.set_jobs(rows)
    store.log("导入静态岗位池", f"新增 {len(added)} 条，重复 {duplicates} 条")
    return {"ok": True, "count": len(converted["jobs"]), "added": added, "duplicates": duplicates, "message": f"已导入 {len(added)} 条，跳过 {duplicates} 条重复记录"}


def _append_manual_queue(store: Store, entries: list[dict[str, Any]]) -> list[str]:
    """Queue explicitly chosen low/unscored jobs without lowering the shared gate."""
    cfg = approval_queue.load_config()
    rows = approval_queue.load_queue(store.files["queue"], cfg)
    existing = {approval_queue._fingerprint(row) for row in rows}
    added: list[str] = []
    stamp = _now()
    for entry in entries:
        row = {
            "id": entry["id"],
            "score": entry.get("score"),
            "company": entry.get("company") or "",
            "title": entry.get("title") or "",
            "status": cfg["approval"]["pending_status"],
            "Source_Channel": entry.get("Source_Channel") or "unknown",
            "created_at": stamp,
            "high_confidence": False,
            "manual_override": True,
        }
        key = approval_queue._fingerprint(row)
        if key in existing:
            continue
        existing.add(key)
        rows.append(row)
        added.append(str(row["id"]))
    if added:
        approval_queue.save_queue(rows, store.files["queue"], cfg)
    return added


def enqueue(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ApiError("ids 必须是字符串数组")
    allow_low = payload.get("allow_low_score") is True
    store = get_store(mode)
    jobs = {str(job.get("id")): job for job in store.jobs()}
    candidates = []
    for job_id in ids:
        job = jobs.get(job_id)
        if not job:
            continue
        score = _score(job)
        if score is None and not allow_low:
            continue
        candidates.append({
            "id": job_id,
            "score": score,
            "company": job.get("company"),
            "title": job.get("title"),
            "Source_Channel": job.get("source_channel"),
            "created_at": _now(),
        })
    result = approval_queue.enqueue(candidates, store.files["queue"])
    manual: list[str] = []
    if allow_low:
        threshold = float(approval_queue.load_config()["score"]["approval_min"])
        low = [item for item in candidates if item["score"] is None or item["score"] < threshold]
        manual = _append_manual_queue(store, low)
        if manual:
            result["manual"] = manual
            # 手动加入的岗位不再算作「未入队」，避免同一条记录被报告两次。
            result["dropped"] = [job_id for job_id in result["dropped"] if job_id not in manual]
            result["count"] = len(approval_queue.load_queue(store.files["queue"]))
    store.log("加入审批队列", f"接受 {len(result['accepted'])} 条，手动 {len(manual)} 条；低分或重复 {len(result['dropped']) + len(result['duplicate'])} 条")
    message = "已进入待确认队列；没有自动投递"
    if manual:
        message += f"；其中 {len(manual)} 条为手动加入（低于评分门或未评分）"
    return {"ok": True, **result, "message": message}


def confirm_queue(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ApiError("ids 必须是字符串数组")
    token = str(payload.get("confirm") or "")
    if token != "确认可人工投递":
        raise ApiError("请在确认框输入「确认可人工投递」")
    store = get_store(mode)
    result = approval_queue.confirm(ids, store.files["queue"])
    store.log("确认可人工投递", f"{len(result['confirmed'])} 条；auto_submit=false")
    return {"ok": True, **result, "message": "已标记为可人工投递；仍需本人到平台提交"}


def prepare(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    job_id = _safe_id(payload.get("id"), "")
    if not job_id:
        raise ApiError("缺少岗位 id")
    store = get_store(mode)
    job = next((row for row in store.jobs() if str(row.get("id")) == job_id), None)
    if not job:
        raise ApiError("找不到该岗位", 404)
    profile = store.profile()
    profile_text = profile_context_text(profile)
    cv_text = profile_text or (CV_PATH.read_text(encoding="utf-8-sig") if CV_PATH.is_file() else "")
    draft = greeting.make_greeting(job, cv_text)
    if profile_text:
        draft["source"] = "个人资料 profile.json + 本地 JD 字段"
    completeness = profile_completeness(profile)
    tracker_path = ROOT / "workspace" / "applications.md"
    tracker = tracker_path.read_text(encoding="utf-8-sig") if tracker_path.is_file() else ""
    dedupe = precheck.evaluate_tracker_text(tracker, str(job.get("company") or ""), str(job.get("title") or ""), str(job.get("city") or ""), dt.date.today())
    report = {
        "job_id": job_id,
        "generated_at": _now(),
        "company": job.get("company"),
        "title": job.get("title"),
        "status": "prepared_for_manual_review_only",
        "greeting": draft,
        "profile": {"percent": completeness["percent"], "ready": completeness["ready"], "missing": completeness["missing"]},
        "pre_apply_dedupe": dedupe,
        "resume_task_checklist": [
            ("从「个人资料」读取事实，不新增数字或经历" if profile_text else "从 workspace/resume.md 读取事实，不新增数字或经历"),
            "依据本地 JD 标记核对关键词，人工复核后生成单栏 ATS PDF",
            "用 tools/ats_check.py 做自动可读性检查；不可解析时人工核查",
        ],
        "form_fields": ["用户手动填写公司官网表单", "用户手动上传 PDF", "用户自行点击提交"],
        "auto_submit": False,
    }
    out = store.write_download(f"prepare-{job_id}", json.dumps(report, ensure_ascii=False, indent=2), ".json")
    store.log("生成投递准备清单", f"{job_id}；仅草稿与去重检查")
    return {"ok": True, "report": report, "download": out.name, "message": "已生成人工准备清单；没有提交申请"}


def transition(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    job_id = _safe_id(payload.get("id"), "")
    to_state = str(payload.get("to") or "")
    if not job_id or to_state not in STATES:
        raise ApiError("岗位 id 或目标状态无效")
    store = get_store(mode)
    events = store.events()
    current = _state_for_job({"id": job_id, "state": payload.get("from")}, events, store.queue())
    result = state_machine.transition(job_id, current, to_state, log_path=store.files["events"], note="网页手动状态更新")
    if not result["ok"]:
        store.log("拒绝状态跃迁", f"{job_id}: {current} → {to_state}", False)
        raise ApiError(f"状态跃迁被拒绝：{result['error']}")
    store.log("更新岗位状态", f"{job_id}: {current} → {to_state}")
    return {"ok": True, **result, "message": f"状态已记录为「{to_state}」"}


def parse_mail(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    subject = _bounded_text(payload.get("subject", ""), "邮件主题", 1000)
    body = _bounded_text(payload.get("body", ""), "邮件正文", 30_000)
    mail = {
        "from": str(payload.get("from") or "")[:300],
        "subject": subject,
        "body": body,
        "date": str(payload.get("date") or dt.date.today().isoformat())[:100],
        "message_id": str(payload.get("message_id") or "")[:300],
    }
    result = mail_classifier.classify(mail)
    store = get_store(mode)
    rows = store.mails()
    mail_id = mail["message_id"] or "mail-" + hashlib.sha256((subject + body).encode("utf-8")).hexdigest()[:12]
    if any(str(row.get("id")) == mail_id for row in rows):
        return {"ok": False, "duplicate": True, "classification": result, "message": "相同 Message-ID 的邮件已存在"}
    rows.append({"id": mail_id, "source_file": "网页输入", "mail": mail, "classification": result})
    store.set_mails(rows)
    store.log("解析邮件", f"{INTENT_LABELS.get(result['intent'], result['intent'])}；离线规则")
    return {"ok": True, "id": mail_id, "classification": result, "message": "邮件已按离线规则分类"}


def generate_ics(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    mail_id = str(payload.get("id") or "")
    store = get_store(mode)
    mail = next((row for row in store.mails() if str(row.get("id")) == mail_id), None)
    if not mail:
        raise ApiError("找不到该邮件", 404)
    classification = dict(mail.get("classification") or {})
    event_time = classification.get("event_time")
    if not event_time:
        raise ApiError("这封邮件没有明确时间；不猜测日期")
    summary = f"{classification.get('company') or '公司'} · {classification.get('title') or classification.get('intent') or '面试'}"
    result = calendar_ics.make_ics(str(event_time), summary, 60, "Asia/Shanghai", (classification.get("meeting_links") or [None])[0])
    if not result["ok"]:
        raise ApiError(f"日历生成失败：{result.get('error')}")
    path = store.write_download("interview", result["ics"], ".ics")
    store.log("生成日历文件", f"{path.name}；UTC Z 时间")
    return {"ok": True, "ics": result["ics"], "download": path.name, "message": "已生成 .ics；请手动导入系统日历"}


def worksheet(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    minutes = payload.get("minutes", 30)
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 180:
        raise ApiError("时长必须是 1–180 分钟")
    store = get_store(mode)
    bank = store.question_bank()
    jd_text = _bounded_text(payload.get("jd", ""), "JD 文本", 20_000)
    profile = store.profile()
    profile_text = profile_context_text(profile)
    cv_text = profile_text or (CV_PATH.read_text(encoding="utf-8-sig") if CV_PATH.is_file() else "")
    selected = mock_interview.select_questions(bank, jd_text, cv_text)
    config = store.config()
    sections = config["sections"]
    scale = minutes / sum(int(section["minutes"]) for section in sections)
    completeness = profile_completeness(profile)
    lines = ["# Mock 题单（本地生成）", "", f"- 生成时间：{_now()}", f"- 计划时长：{minutes} 分钟", "- 题目只来自本地题库；不编造面经或公司业务动态。"]
    if profile_has_content(profile):
        lines.append(f"- 个人资料完整度：{completeness['percent']}%（{'可用于草稿' if completeness['ready'] else '部分缺失：' + '、'.join(completeness['missing'][:4])}）")
        projects = [row.get("name") for row in profile.get("projects") or [] if row.get("name")]
        if projects:
            lines.append("- 资料中的项目：" + "、".join(projects[:5]))
    else:
        lines.append("- 个人资料尚未填写；题单仍可生成，建议先补充项目与经历以便追问。")
    lines.append("")
    total = sum(len(items) for items in selected.values())
    if not total:
        lines += ["> " + config["empty_bank_message"], ""]
    for section in sections:
        name = str(section["name"])
        duration = max(1, round(int(section["minutes"]) * scale))
        lines += [f"## {name}（约 {duration} 分钟）", ""]
        items = selected.get(name, [])
        if not items:
            lines += ["本段暂无题库条目；" + config["empty_bank_message"] + "。", ""]
        for index, item in enumerate(items, start=1):
            lines += [f"### {index}. {item['question']}", "", "回答：", ""]
    lines += ["## 一问一答记录", "", "（由用户手动填写；本工具不生成答案。）", ""]
    text = "\n".join(lines)
    path = store.write_download("worksheet", text, ".md")
    store.log("生成 Mock 题单", f"{total} 题；{minutes} 分钟")
    return {"ok": True, "worksheet": text, "question_count": total, "download": path.name, "message": "题单已生成；空题库不会编造题目"}


def add_bank_question(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    question = _bounded_text(payload.get("question"), "题目", 1000).strip()
    section = str(payload.get("section") or "业务拆解")
    if not question:
        raise ApiError("题目不能为空")
    if section not in ("业务拆解", "项目深挖", "压力测试"):
        raise ApiError("分段无效")
    store = get_store(mode)
    bank = store.question_bank()
    existing_ids = {str(item.get("id")) for item in bank["questions"] if isinstance(item, dict)}
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
    if digest in existing_ids:
        return {"ok": False, "duplicate": True, "message": "相同题目已存在"}
    bank["questions"].append({"id": digest, "question": question, "section": section, "source": "user_manual"})
    store.set_question_bank(bank)
    store.log("补充题库", question[:80])
    return {"ok": True, "id": digest, "message": "题目已加入本地题库"}


def debrief(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    text = _bounded_text(payload.get("transcript"), "逐字稿", 30_000)
    store = get_store(mode)
    card = interview_debrief.debrief(text, "web-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], bank_path=store.files["bank"], config={
        **interview_debrief.load_config(),
        "question_bank_path": str(store.files["bank"]),
        "interview_dir": str(store.files["downloads"]),
    })
    card["id"] = "debrief-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    card["source"] = "网页输入"
    rows = store.debriefs()
    if any(str(row.get("id")) == card["id"] for row in rows):
        return {"ok": False, "duplicate": True, "card": card, "message": "相同逐字稿已复盘过"}
    rows.append(card)
    store.set_debriefs(rows)
    store.log("生成复盘卡片", f"{card['id']}；显式证据字段")
    return {"ok": True, "card": card, "message": "复盘卡片已生成；未做实质性能力评价"}


def add_variant(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    project = _bounded_text(payload.get("project"), "项目名", 300).strip()
    text = _bounded_text(payload.get("text"), "经历原文", 20_000)
    if not project or not text.strip():
        raise ApiError("项目名和经历原文不能为空")
    store = get_store(mode)
    rows = store.variants()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if any(str(row.get("sha256")) == digest for row in rows):
        return {"ok": False, "duplicate": True, "message": "相同经历变体已存在"}
    rows.append({"id": "variant-" + digest[:12], "project": project, "created_at": _now(), "text": text, "sha256": digest})
    store.set_variants(rows)
    store.log("保存经历变体", project[:80])
    return {"ok": True, "message": "经历原文已保存；未修改 Master Resume"}


def check_pdf(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    encoded = _bounded_text(payload.get("content_base64"), "PDF 内容", 7 * 1024 * 1024)
    keywords = _bounded_text(payload.get("keywords", ""), "关键词", 2000)
    try:
        import base64
        import binascii
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ApiError("PDF 不是有效的 Base64 数据") from exc
    if not raw:
        raise ApiError("PDF 内容为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError("PDF 超过 5 MB 上限")
    if not raw.startswith(b"%PDF-"):
        raise ApiError("文件头不是 PDF；已拒绝，不写入磁盘")
    store = get_store(mode)
    path = store.files["downloads"] / ("ats-check-" + hashlib.sha256(raw).hexdigest()[:12] + ".pdf")
    if not path.is_file():
        path.write_bytes(raw)
    result = ats_check.check_pdf(path, keywords)
    result["uploaded_filename"] = str(payload.get("filename") or "upload.pdf")[:160]
    store.log("ATS 静态检查", str(result.get("verdict") or "unknown"))
    return {"ok": True, "result": result, "message": "检查完成；无法解析的文字层仍需人工核查"}


def dry_run(payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "job_id": str(payload.get("job_id") or "web-demo")[:100],
        "company": str(payload.get("company") or "虚构公司")[:160],
        "title": str(payload.get("title") or "岗位")[:160],
        "status": str(payload.get("status") or "已采集")[:80],
        "score": 0,
        "source_channel": str(payload.get("source_channel") or "manual_paste")[:100],
        "updated_at": dt.date.today().isoformat(),
    }
    return {"ok": True, "result": feishu_adapter.sync_job(row), "message": "只显示 dry-run payload；没有发出 HTTP 请求"}


def run_tests() -> dict[str, Any]:
    sys.dont_write_bytecode = True
    suite = unittest.TestSuite()
    discovered = unittest.defaultTestLoader.discover(str(TESTS_DIR), pattern="test*.py", top_level_dir=str(TESTS_DIR))
    suite.addTests(discovered)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    output = stream.getvalue()
    return {
        "ok": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "output": output[-8000:],
        "summary": f"Ran {result.testsRun} tests · {'OK' if result.wasSuccessful() else 'FAILED'}",
    }


def web_report(mode: str) -> dict[str, Any]:
    store = get_store(mode)
    snap = snapshot(mode)
    result = run_tests()
    lines = [
        "# 离线网页工作台验收报告",
        "",
        f"- 生成时间：{_now()}",
        f"- 数据模式：{mode}（{'明显虚构的演示数据' if mode == 'demo' else '用户本地数据'}）",
        "- 运行边界：127.0.0.1、无外部 API、无真实邮箱/飞书、无自动投递。",
        "",
        "## 自动检查",
        "",
        f"- 全量测试：{result['summary']}；failures={result['failures']}，errors={result['errors']}。",
        f"- 当前数据：岗位 {snap['scope']['all_jobs']} 条、待确认 {snap['kpis']['pending']} 条、邮件 {len(store.mails())} 封、复盘 {len(store.debriefs())} 份。",
        f"- 状态机：{', '.join(STATES)}。",
        "- 网页功能：JD 录入、静态 JSON 导入、审批队列、显式确认、30 天去重、话术草稿、状态跃迁、邮件解析、ICS、Mock、复盘、变体、ATS 静态检查、飞书 dry-run、测试、报告与导出。",
        "- 人工确认门：所有 >=4.0 的岗位默认 pending；显式输入确认语才标记 approved；approved 只表示可人工投递。",
        "",
        "## 需人工验证",
        "",
        "- 真实 JD 评分、定制简历、ATS PDF 渲染、中文字体与事实数字溯源。",
        "- 真实邮箱/飞书/日历 5 分钟端到端时延、真实录音转写、真实平台投递。",
        "- `[[ILLEGIBLE]]` 与联系方式占位符补全后重新核查 CV。",
        "",
        "## 未实现",
        "",
        "- 平台抓取、反爬/检测绕过、微信 Hook/MITM、浏览器 CDP 接管。",
        "- 无人确认的自动投递、自动发送招呼语、自动提交表单。",
        "- 真实 IMAP 连接、真实飞书 HTTP、真实系统日历写入、真实 ASR 运行、外部 LLM。",
        "",
        "## 快照摘要",
        "",
        "```json",
        json.dumps({
            "filter": snap["filter"],
            "kpis": snap["kpis"],
            "state_counts": snap["state_counts"],
            "channels": snap["channel_rows"],
            "quarterly_radar": snap["quarterly_radar"],
            "weakness_rows": snap["weakness_rows"],
            "boundaries": snap["boundaries"],
        }, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    text = "\n".join(lines)
    path = store.write_download("web-acceptance-report", text, ".md")
    store.log("生成网页验收报告", f"{path.name}；tests={result['tests_run']}")
    return {"ok": result["ok"], "download": path.name, "report": text, "tests": result, "message": "网页验收报告已生成；测试结果为 " + result["summary"]}


def export_data(mode: str) -> dict[str, Any]:
    store = get_store(mode)
    payload = {
        "_note": "本地离线工作台数据导出；不含凭据。导入前请自行审查第三方个人信息。",
        "exported_at": _now(),
        "mode": mode,
        "jobs": store.jobs(),
        "queue": store.queue(),
        "mails": store.mails(),
        "debriefs": store.debriefs(),
        "events": store.events(),
        "pipeline_events": store.pipeline_events(),
        "variants": store.variants(),
        "question_bank": store.question_bank(),
        "profile": store.profile(),
        "activity": store.activity(200),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path = store.write_download(f"workspace-{mode}-export", text, ".json")
    store.log("导出本地数据", path.name)
    return {"ok": True, "download": path.name, "bytes": len(text.encode("utf-8")), "message": "本地数据已导出"}


def reset_demo() -> dict[str, Any]:
    store = Store("demo")
    seed_demo(store)
    offerpilot_runtime.reset_runtime("demo")
    return {"ok": True, "message": "演示数据已恢复；用户数据未改变"}


ACTIONS = {
    "parse-jd": parse_jd,
    "import-jobs": import_jobs,
    "enqueue": enqueue,
    "confirm": confirm_queue,
    "prepare": prepare,
    "transition": transition,
    "parse-mail": parse_mail,
    "generate-ics": generate_ics,
    "worksheet": worksheet,
    "add-question": add_bank_question,
    "debrief": debrief,
    "add-variant": add_variant,
    "check-pdf": check_pdf,
    "dry-run": dry_run,
    "pipeline-event": ingest_pipeline_event,
    "save-profile": save_profile,
    "import-profile-cv": import_profile_cv,
    "offerpilot-start": start_offerpilot_task,
    "offerpilot-greet": start_offerpilot_greet,
    "offerpilot-import": import_offerpilot_jobs,
    "offerpilot-resume": upload_offerpilot_resume,
    "offerpilot-stop": lambda payload: stop_offerpilot_task(
        str(payload.get("task_id") or ""),
        str(payload.get("data_mode") or payload.get("mode") or "user"),
    ),
}
