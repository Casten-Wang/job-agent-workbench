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
import functools
import hashlib
import io
import json
import re
import sys
import threading
import unittest
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent
ROOT = WEB_DIR.parent
TOOLS_DIR = ROOT / "tools"
CV_PATH = ROOT / "workspace" / "resume.md"
TESTS_DIR = TOOLS_DIR / "tests"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import offerpilot_adapter  # noqa: E402
import offerpilot_runtime  # noqa: E402
import profile_import  # noqa: E402
import mail_classifier  # noqa: E402
import analytics  # noqa: E402
import jd_intake  # noqa: E402
import approval_queue  # noqa: E402
import ats_check  # noqa: E402
import calendar_ics  # noqa: E402
import feishu_adapter  # noqa: E402
import filters  # noqa: E402
import resume_quality  # noqa: E402
import evidence_checker  # noqa: E402
import greeting  # noqa: E402
import job_dossier  # noqa: E402
import job_match  # noqa: E402
import job_risk  # noqa: E402
import job_standardize  # noqa: E402
import quota_planner  # noqa: E402
import interview_analytics  # noqa: E402
import interview_debrief  # noqa: E402
import interview_chat  # noqa: E402
import mock_interview  # noqa: E402
import interview_chat  # noqa: E402
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
        "description": "点击「通过所选」或评分达标自动通过后标记 approved；approved 仅表示可人工投递，不代表已发送。",
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
        "description": "由内嵌岗位自动化执行；工作台要求逐批确认语与风险确认，发送仍受日限、间隔与平台风控锁约束（全天可发送），结果按岗位回报。",
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

# 影响后续流程（采集搜索条件、评分、生成招呼语）的字段：缺任意一项都会让采集/生成失去依据，
# 因此单独标记为「必填」，与 PROFILE_SECTIONS 的完整度打分分开判断。
# - basic_name / basic_city：写入招呼语与简历草稿的身份事实。
# - job_intent：采集的搜索关键词（目标岗位）与城市过滤（目标城市）直接读取这两个字段。
# - education：教育经历是可核实事实里最基础的一项，招呼语生成会用到。
# - experience_or_project：评分与招呼语需要至少一段工作/实习或项目经历作为事实来源；
#   两者满足其一即可，不要求同时填写。
# - skills：匹配打分读取技能/工具列表。
# - summary：个人简介被拼进生成招呼语的事实文本。
# - truth_confirmed：用户对真实性的确认，是生成任何草稿前的前提。
PROFILE_REQUIRED_RULES = (
    ("basic_name", "姓名", lambda p: bool((p.get("basic") or {}).get("name"))),
    ("basic_city", "所在城市", lambda p: bool((p.get("basic") or {}).get("city"))),
    ("job_intent_titles", "目标岗位", lambda p: bool((p.get("job_intent") or {}).get("titles"))),
    ("job_intent_cities", "目标城市", lambda p: bool((p.get("job_intent") or {}).get("cities"))),
    ("education", "教育经历", lambda p: any(row.get("school") for row in p.get("education") or [])),
    (
        "experience_or_project",
        "工作/实习经历或项目经历（至少一项）",
        lambda p: any(row.get("company") or row.get("title") for row in p.get("experiences") or [])
        or any(row.get("name") for row in p.get("projects") or []),
    ),
    (
        "skills",
        "技能标签（至少三个）",
        lambda p: len((p.get("skills") or {}).get("tools") or []) + len((p.get("skills") or {}).get("strengths") or []) >= 3,
    ),
    ("summary", "个人简介（至少 20 字）", lambda p: len(str(p.get("summary") or "")) >= 20),
    ("truth_confirmed", "真实性确认", lambda p: p.get("truth_confirmed") is True),
)


class ApiError(Exception):
    """Expected, user-facing API failure."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# 审批队列、岗位池、投递记录都是「整读 → 改内存 → 整写」的 JSON 文件，而服务器每个请求一个线程。
# 对这些写入口串行化（可重入，因为 run_offerpilot_pipeline 会调用 enqueue），避免并发请求互相覆盖。
_STORE_WRITE_LOCK = threading.RLock()


def _serialized_store_write(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _STORE_WRITE_LOCK:
            return func(*args, **kwargs)
    return wrapper


class Store:
    """Own the single local dataset at ``web/data/user``.

    ``mode`` is kept only as a compatibility field: the product has one mode,
    so every value maps to the same local dataset.
    """

    MODE = "user"
    VALID_MODES = (MODE,)

    def __init__(self, mode: str = MODE):
        self.mode = self.MODE
        self.root = WEB_DIR / "data" / self.MODE
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
            "deliveries": self.root / "deliveries.json",
            "interview_session": self.root / "interview-session.json",
            "interview_materials": self.root / "interview-materials.json",
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

    def all_jobs(self) -> list[dict[str, Any]]:
        """Every job record on disk, including soft-deleted ones (``deleted_at``).

        Writers that rewrite jobs.json and fingerprint de-duplication must use
        this, otherwise a soft-deleted record would be dropped from the file or
        re-imported as new.
        """
        value = self._read_json("jobs", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def jobs(self) -> list[dict[str, Any]]:
        """The visible job pool: soft-deleted jobs are excluded."""
        return [row for row in self.all_jobs() if not row.get("deleted_at")]

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

    def interview_session(self) -> dict[str, Any] | None:
        value = self._read_json("interview_session", None)
        return value if isinstance(value, dict) and value else None

    def set_interview_session(self, value: dict[str, Any]) -> None:
        self._write_json("interview_session", value)

    def clear_interview_session(self) -> None:
        path = self.files["interview_session"]
        if path.is_file():
            path.unlink()

    def interview_materials(self) -> list[dict[str, Any]]:
        value = self._read_json("interview_materials", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_interview_materials(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("interview_materials", rows)

    def profile(self) -> dict[str, Any]:
        value = self._read_json("profile", None)
        return normalize_profile(value) if isinstance(value, dict) else default_profile()

    def set_profile(self, value: dict[str, Any]) -> None:
        self._write_json("profile", value)

    def deliveries(self) -> list[dict[str, Any]]:
        value = self._read_json("deliveries", [])
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def set_deliveries(self, rows: list[dict[str, Any]]) -> None:
        self._write_json("deliveries", rows)

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
# web/data/user/ and is gitignored. Nothing here sends data anywhere; contact
# fields are kept out of generated greetings, worksheets, and exported documents.


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
    required = [{"key": key, "label": label, "done": bool(rule(profile))} for key, label, rule in PROFILE_REQUIRED_RULES]
    required_missing = [item["label"] for item in required if not item["done"]]
    return {
        "percent": percent,
        "level": level,
        "ready": level == "ready",
        "sections": sections,
        "missing": missing,
        # 新增键：必填项清单与未满足项。采集与招呼语生成必须等这里为空才能继续。
        "required": required,
        "required_missing": required_missing,
        "required_ok": not required_missing,
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


CV_SECTION_HEADINGS = (
    # Order matters: "Project Experience" must resolve to projects, not experiences.
    ("projects", ("project", "项目")),
    ("experiences", ("experience", "工作经历", "实习经历", "工作经验")),
    ("education", ("education", "教育")),
    ("summary", ("summary", "个人简介", "个人概述", "自我评价")),
    ("skills", ("skill", "技能")),
)
CV_CITIES = (
    "北京", "上海", "深圳", "广州", "杭州", "成都", "武汉", "南京", "苏州", "西安",
    "长沙", "重庆", "天津", "合肥", "厦门", "青岛", "郑州", "济南", "大连", "宁波",
)
# One date such as 2019, 2019.03, 2019-03 or 2019年3月.
CV_DATE_PART = r"\d{4}(?:\s*[./年-]\s*\d{1,2}月?)?"
# A date range such as "2019年10月 - 至今", "2018.03-2018.06", "2019-03 ~ 2019-06", "2025.09–2026.03".
CV_DATE_RANGE_RE = re.compile(
    rf"({CV_DATE_PART})\s*(?:[-~～–—－]+|到|至(?!今)|(?=至今|现在))\s*(至今|现在|Present|present|Now|now|{CV_DATE_PART})"
)
CV_ILLEGIBLE_RE = re.compile(r"\[\[ILLEGIBLE\]\]")
CV_BULLET_RE = re.compile(r"^\s*(?:[-•]\s*|\*\s+)")
CV_HEADING_SEP_RE = re.compile(r"\s*(?:—|–|｜|\||·)\s*|\s+-\s+")
CV_EDU_SEP_RE = re.compile(r"\s*(?:—|–|｜|\||·|，|,|、|\u3000)\s*|\s+-\s+|\s{2,}")
CV_EDU_DEGREES = ("大专", "本科", "硕士", "博士")
CV_CITY_TAIL_RE = re.compile(r"（\s*(?:" + "|".join(CV_CITIES) + r")\s*）\s*$")
CV_SKILL_LABEL_RE = re.compile(r"^(?:技能|工具|专业技能|技术栈|tools?|skills?)\s*[:：]\s*(.+)$", re.IGNORECASE)


def _is_cv_bullet(line: str) -> bool:
    return bool(CV_BULLET_RE.match(line))


def _cv_bullet_text(line: str) -> str:
    return CV_BULLET_RE.sub("", line, count=1).strip()


def _clean_cv_text(text: str) -> str:
    """Drop ``[[ILLEGIBLE]]`` markers and keep the readable part.

    Returns "" when too little readable text is left (a bullet that was only
    the marker, or a stub such as "与"), so the caller skips it rather than
    inventing wording around the gap.
    """
    cleaned = CV_ILLEGIBLE_RE.sub("", text)
    cleaned = re.sub(r"\s+([，,。；;、：:])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,、；;：:")
    if len(re.sub(r"[\W_]+", "", cleaned)) < 4:
        return ""
    return cleaned


def _cv_bullet_texts(lines: list[str]) -> list[str]:
    rows: list[str] = []
    for line in lines:
        if _is_cv_bullet(line):
            text = _clean_cv_text(_cv_bullet_text(line))
            if text:
                rows.append(text)
    return rows


def _cv_join_bullets(texts: list[str]) -> str:
    parts = [text.rstrip("。.；;") for text in texts if text.rstrip("。.；;")]
    return ("；".join(parts) + "。") if parts else ""


def _normalize_cv_date(value: str) -> str:
    text = value.strip()
    if text in ("至今", "现在", "Present", "present", "Now", "now"):
        return "至今"
    match = re.match(r"(\d{4})(?:\s*[./年-]\s*(\d{1,2}))?", text)
    if not match:
        return _clean_text(text, 20)
    if match.group(2):
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return match.group(1)


def _split_cv_date_range(text: str) -> tuple[str, str]:
    match = CV_DATE_RANGE_RE.search(text)
    if not match:
        return "", ""
    return _normalize_cv_date(match.group(1)), _normalize_cv_date(match.group(2))


def _cv_heading_text(line: str) -> str:
    return re.sub(r"^\s*###\s*", "", line).strip()


def _cv_head(text: str) -> str:
    """A heading or lead line without its date range and without empty brackets."""
    text = text.replace("(", "（").replace(")", "）")
    text = CV_DATE_RANGE_RE.sub("", text)
    text = re.sub(r"（[\s，,、;；|｜]*）", "", text)
    text = re.sub(r"（[\s，,、;；]+", "（", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip(" ，,、;；|｜—–-·\u3000")


def _cv_heading_parts(text: str) -> list[str]:
    return [part.strip() for part in CV_HEADING_SEP_RE.split(text) if part.strip()]


def _cv_block_prose(body: list[str]) -> list[str]:
    """Plain description lines in a block: skips bullets, bold titles and date lines."""
    rows: list[str] = []
    for line in body:
        text = line.strip()
        if not text or _is_cv_bullet(line) or re.fullmatch(r"\*\*.+?\*\*", text) or _split_cv_date_range(text) != ("", ""):
            continue
        cleaned = _clean_cv_text(text)
        if cleaned:
            rows.append(cleaned.rstrip("。.；;") + "。")
    return rows


def _cv_block_summary(body: list[str]) -> str:
    """Prose first, then bullet points, joined into one single-line record summary."""
    return _cv_join_bullets(_cv_block_prose(body) + _cv_bullet_texts(body))


def _cv_body_dates(body: list[str]) -> tuple[str, str]:
    """The first date range written on a plain (non-bullet) line of a block."""
    for line in body:
        text = line.strip()
        if text and not _is_cv_bullet(line):
            start, end = _split_cv_date_range(text)
            if start or end:
                return start, end
    return "", ""


def _cv_section_key(label: str) -> str | None:
    folded = label.casefold()
    for key, names in CV_SECTION_HEADINGS:
        if any(name in folded for name in names):
            return key
    return None


def _cv_sections(text: str) -> dict[str, list[str]]:
    """Group lines under recognized ``##`` headings; unknown headings are skipped."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"^\s*##\s+(.+?)\s*$", line)
        if heading:
            current = _cv_section_key(heading.group(1))
            if current:
                sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)
    return sections


def _cv_subsection_blocks(lines: list[str]) -> list[list[str]]:
    """Split a section into blocks that start at each ``###`` heading."""
    blocks: list[list[str]] = []
    for line in lines:
        if re.match(r"^\s*###\s+", line):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)
    return blocks


def _extract_cv_experiences(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for block in _cv_subsection_blocks(lines):
        heading = _cv_heading_text(block[0])
        start, end = _split_cv_date_range(heading)
        parts = _cv_heading_parts(_cv_head(heading))
        company = parts[0] if parts else ""
        body = block[1:]
        bold_title = next(
            (match.group(1).strip() for match in (re.fullmatch(r"\*\*(.+?)\*\*", line.strip()) for line in body) if match),
            "",
        )
        # "### 公司 — 城市" plus a bold "**职位**" line is the common layout: the bold line is the title.
        # A heading part is used as the title only when no bold line exists, and never when it is a city.
        heading_title = next((part for part in parts[1:] if part not in CV_CITIES), "")
        title = bold_title or heading_title
        if not start and not end:
            start, end = _cv_body_dates(body)
        summary = _cv_block_summary(body)
        if company or title or summary:
            rows.append({"company": company, "title": title, "start": start, "end": end, "summary": summary})
    return rows


def _extract_cv_projects(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for block in _cv_subsection_blocks(lines):
        heading = _cv_heading_text(block[0])
        start, end = _split_cv_date_range(heading)
        if not start and not end:
            # "项目名｜角色｜2025.09" style: a single date is the project's start date.
            single = re.search(r"(\d{4}(?:\s*[./年-]\s*\d{1,2}月?)?)\s*$", heading)
            if single:
                start = _normalize_cv_date(single.group(1))
                heading = heading[: single.start()]
        parts = _cv_heading_parts(_cv_head(heading))
        name = parts[0] if parts else ""
        role = parts[1] if len(parts) > 1 else ""
        body = block[1:]
        if not start and not end:
            start, end = _cv_body_dates(body)
        summary = _cv_block_summary(body)
        if name or role or summary:
            rows.append({"name": name, "role": role, "start": start, "end": end, "summary": summary})
    return rows


def _parse_cv_education_line(line: str) -> dict[str, str]:
    start, end = _split_cv_date_range(line)
    # Parenthesized text in an education line is a city, a date, or a note: never a school or major.
    head = re.sub(r"（[^）]*）", "", _cv_head(line))
    head = CV_CITY_TAIL_RE.sub("", head)
    tokens = [token.strip() for token in CV_EDU_SEP_RE.split(head) if token.strip()]
    # A trailing degree word ("…信息系统 本科") is split off the last token when no separator precedes it.
    degree = ""
    if tokens:
        for item in CV_EDU_DEGREES:
            if tokens[-1].endswith(item) and tokens[-1] != item:
                tokens[-1] = tokens[-1][: -len(item)].strip()
                degree = item
                break
            if tokens[-1] == item:
                tokens.pop()
                degree = item
                break
    school = tokens[0] if tokens else ""
    major = tokens[1] if len(tokens) > 1 else ""
    if len(tokens) > 2:
        major = " ".join(tokens[1:])
    return {"school": school, "major": major, "degree": degree, "start": start, "end": end, "summary": ""}


def _extract_cv_education(lines: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    blocks = _cv_subsection_blocks(lines)
    if blocks:
        for block in blocks:
            row = _parse_cv_education_line(_cv_heading_text(block[0]))
            if not row["start"] and not row["end"]:
                row["start"], row["end"] = _cv_body_dates(block[1:])
            row["summary"] = _cv_block_summary(block[1:])
            rows.append(row)
    else:
        for line in lines:
            if _is_cv_bullet(line) and CV_DATE_RANGE_RE.search(line):
                rows.append(_parse_cv_education_line(_cv_bullet_text(line)))
    return [row for row in rows if row["school"]]


def _extract_cv_skills(lines: list[str]) -> list[str]:
    tools: list[str] = []
    for line in lines:
        text = _cv_bullet_text(line) if _is_cv_bullet(line) else line.strip()
        match = CV_SKILL_LABEL_RE.match(text)
        if match:
            tools.extend(item for item in _string_list(match.group(1)) if len(item) <= 30)
    return tools


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
    for city in CV_CITIES:
        if city in text:
            basic["city"] = city
            break

    sections = _cv_sections(text)
    tools = _extract_cv_skills(sections.get("skills", []))
    tools += [term for term in SKILL_TERMS if term in text]
    profile["skills"]["tools"] = list(dict.fromkeys(tools))[: PROFILE_LIMITS["list"]]
    profile["experiences"] = _extract_cv_experiences(sections.get("experiences", []))
    profile["projects"] = _extract_cv_projects(sections.get("projects", []))
    profile["education"] = _extract_cv_education(sections.get("education", []))

    if "summary" in sections:
        lines = sections["summary"]
        bullets = _cv_bullet_texts(lines)
        if bullets:
            profile["summary"] = "\n".join(item.rstrip("。.；;") + "。" for item in bullets)
        else:
            paragraphs = [_clean_cv_text(line.strip()) for line in lines if line.strip() and not line.lstrip().startswith("#")]
            profile["summary"] = "\n".join(item for item in paragraphs if item)
    elif not sections:
        # Unstructured resume with no recognized headings: keep the first substantial line.
        for raw_line in text.splitlines():
            cleaned = re.sub(r"\s+", " ", raw_line).strip()
            if cleaned and not raw_line.lstrip().startswith(("#", "-", "*", "|", ">")) and len(cleaned) >= 20:
                profile["summary"] = cleaned
                break
    profile["summary"] = profile["summary"][: PROFILE_LIMITS["long"]]
    return profile


def _runtime_resume_files() -> list[Path]:
    """Files in the embedded runtime's uploaded-resume directory, listed read-only."""
    directory = offerpilot_runtime.runtime_dir("user") / "data" / "resumes"
    try:
        if not directory.is_dir():
            return []
        return [path for path in directory.iterdir() if path.is_file() and not path.name.startswith(".")]
    except OSError:
        return []


def _profile_cv_source() -> tuple[Path, str] | None:
    """The resume to read: the newer of the uploaded Markdown resume and workspace/resume.md.

    A resume uploaded on the collect page must win over a stale
    ``workspace/resume.md`` (that was the bug: the file existed, so a new upload
    was ignored).  The uploaded ``.md`` is used only when it is strictly newer
    than ``workspace/resume.md``; otherwise the workspace file stays the source.
    """
    markdown = [path for path in _runtime_resume_files() if path.suffix.lower() == ".md"]
    uploaded: Path | None = None
    if markdown:
        preferred = [path for path in markdown if path.name == "resume.md"]
        uploaded = preferred[0] if preferred else max(markdown, key=lambda path: path.stat().st_mtime)
    uploaded_at = _mtime(uploaded)
    workspace_at = _mtime(CV_PATH if CV_PATH.is_file() else None)
    if uploaded is not None and (workspace_at is None or (uploaded_at is not None and uploaded_at > workspace_at)):
        return uploaded, "采集页已上传的 Markdown 简历"
    if CV_PATH.is_file():
        return CV_PATH, "workspace/resume.md"
    return None


def _mtime(path: Path | None) -> float | None:
    """Modification time, or ``None`` when the file is missing or unreadable."""
    if path is None:
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def profile_for_api(mode: str, store: Store) -> dict[str, Any]:
    """Profile payload for the API and snapshot: public fields plus two read-only flags.

    ``saved``: the local dataset has a profile.json written by save-profile.
    ``cv_available``: a Markdown resume can be read for import.
    """
    return {
        **profile_public(store.profile()),
        "saved": store.files["profile"].is_file(),
        "cv_available": _profile_cv_source() is not None,
    }


def import_profile_cv(payload: dict[str, Any]) -> dict[str, Any]:
    """Suggest profile fields from a local resume; never auto-save."""
    if "filename" in payload or "content_base64" in payload:
        return _import_profile_upload(payload)
    source = _profile_cv_source()
    if source is None:
        if any(path.suffix.lower() != ".md" for path in _runtime_resume_files()):
            raise ApiError("采集页上传的简历不是 Markdown（.md）格式，暂无法自动提取；请在「个人资料」中手动填写，或上传 .md 简历", 400)
        raise ApiError("未找到 workspace/resume.md；可先在「个人资料」中手动填写", 404)
    path, label = source
    if path.stat().st_size > offerpilot_runtime.MAX_RESUME_BYTES:
        raise ApiError("简历文件超过 5 MB 上限", 400)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ApiError(f"{label} 无法按 UTF-8 文本读取：{exc.__class__.__name__}", 400) from exc
    suggestion = normalize_profile(_extract_profile_from_cv(text))
    store = get_store("user")
    store.log("读取简历建议资料", f"{label}；未自动保存")
    return {
        "ok": True,
        "profile": suggestion,
        "source": label,
        "filename": path.name,
        "message": "已从本地简历提取可识别字段；请核对后再保存。",
    }


def _import_profile_upload(payload: dict[str, Any]) -> dict[str, Any]:
    """Uploaded PDF/DOCX/MD/TXT: parse text locally, let the resume Agent suggest fields.

    Never saves and never falls back to partial local parsing when the Agent fails.
    """
    if str(payload.get("mode") or "user") != "user":
        raise ApiError("仅支持 user 模式导入简历")
    filename = _bounded_text(payload.get("filename"), "文件名", 255)
    encoded = _bounded_text(payload.get("content_base64"), "文件内容", 7 * 1024 * 1024)
    if not filename or not encoded:
        raise ApiError("请选择完整的本地简历文件")
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        content = base64.b64decode(encoded, validate=True)
        text = profile_import.extract_resume_text(filename, content)
    except ValueError as exc:
        raise ApiError(str(exc) if str(exc) else "简历文件传输失败，请重新选择文件") from exc
    from career_user_runtime import upstream
    try:
        extraction = upstream("POST", "/v1/career/profile-import", {"text": text})
    except ApiError as exc:
        raise ApiError("简历 Agent 解析未完成，当前资料未修改；请检查模型服务后重试。", exc.status) from None
    if not isinstance(extraction.get("profile"), dict):
        raise ApiError("简历 Agent 返回格式异常，当前资料未修改，请重试。", 502)
    suggestion = normalize_profile(extraction["profile"])
    suggestion["truth_confirmed"] = False
    get_store("user").log("读取简历建议资料", "本地文件；未自动保存")
    return {
        "ok": True,
        "profile": suggestion,
        "source": filename,
        "source_text": text,
        "filename": filename,
        "warnings": extraction.get("warnings", []),
        "generation": extraction.get("generation", {}),
        "message": "Agent 已解析整份简历并填入资料及经历；请核对各项内容，确认真实性后保存。",
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


def _job_risk_map(jobs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Read-only risk screen for every job; never edits the job rows."""
    counts = Counter(
        (str(job.get("company") or "").strip().lower(), str(job.get("title") or "").strip().lower())
        for job in jobs
    )
    result: dict[str, dict[str, Any]] = {}
    for job in jobs:
        key = (str(job.get("company") or "").strip().lower(), str(job.get("title") or "").strip().lower())
        result[str(job.get("id"))] = job_risk.assess_job_risk(job, duplicate_count=max(counts[key] - 1, 0))
    return result


def _contact_plan(
    queue_view: list[dict[str, Any]],
    jobs: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    risk_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Read-only ranking of today's approved, unsent rows within the daily quota."""
    job_by_id = {str(job.get("id")): job for job in jobs}
    history: list[dict[str, Any]] = []
    sent_ids: set[str] = set()
    for batch in deliveries:
        for item in batch.get("items") or []:
            if not isinstance(item, dict) or item.get("status") != "sent":
                continue
            job_id = str(item.get("job_id") or "")
            job = job_by_id.get(job_id) or {}
            sent_ids.add(job_id)
            history.append({
                "company": job.get("company"),
                "title": job.get("title"),
                "contacted_at": item.get("finished_at"),
            })
    candidates = []
    for row in queue_view:
        row_id = str(row.get("id"))
        if row.get("status") != "approved" or row_id in sent_ids:
            continue
        job = job_by_id.get(row_id) or {}
        candidates.append({
            "id": row_id,
            "company": row.get("company") or job.get("company"),
            "title": row.get("title") or job.get("title"),
            "score": row.get("score"),
            "risk_level": (risk_map.get(row_id) or {}).get("level"),
            "posted_at": job_standardize.source_updated_at(job),
        })
    plan = quota_planner.plan_contact_queue(
        candidates,
        daily_quota=DEFAULT_DAILY_CONTACT_QUOTA,
        history=history,
        today=dt.date.today(),
    )
    plan["daily_quota"] = DEFAULT_DAILY_CONTACT_QUOTA
    return plan


def _job_fingerprint(job: dict[str, Any]) -> str:
    """Pool-level identity key: normalized company/title/city plus the source channel.

    Company, title and city use the same normalization as ``_dedup_fingerprint``
    (tools/precheck.py), so two records that differ only by punctuation,
    spacing, width or a legal company suffix are the same job. The channel stays
    part of the key: the same opening collected from two platforms may be
    handled separately. A blank or placeholder company/title falls back to
    content identity — the JD text hash, a source URL or a platform job id — so
    two different JDs are never treated as duplicates.
    """
    company = str(job.get("company") or "").strip()
    title = str(job.get("title") or "").strip()
    channel = str(job.get("source_channel") or "").strip()
    if company and company != PLACEHOLDER_COMPANY and title and title != PLACEHOLDER_TITLE:
        return "job:" + precheck.compute_fingerprint(company, title, job.get("city")) + "|" + channel
    identity = ""
    raw_text = str(job.get("raw_text") or "").strip()
    if raw_text:
        identity = "jd:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    if not identity:
        for field in ("source_url", "url"):
            value = str(job.get(field) or "").strip()
            if value:
                identity = f"url:{value}"
                break
    if not identity:
        platform = str(job.get("source_platform") or job.get("platform") or "").strip()
        platform_job_id = str(job.get("platform_job_id") or "").strip()
        if platform and platform_job_id:
            identity = f"platform:{platform}|{platform_job_id}"
    if not identity:
        offerpilot_id = str(job.get("offerpilot_id") or "").strip()
        if offerpilot_id:
            identity = f"offerpilot:{offerpilot_id}"
    if not identity:
        own_id = str(job.get("id") or "").strip()
        identity = f"row:{own_id}" if own_id else ""
    return f"{identity}|{channel}" if identity else ""


def _pool_duplicate_index(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group pool rows by identity key; rows without any usable identity are skipped."""
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = _job_fingerprint(row)
        if key:
            index.setdefault(key, []).append(row)
    return index


def _resolve_pool_duplicate(
    index: dict[str, list[dict[str, Any]]], fingerprint: str
) -> tuple[dict[str, Any] | None, bool]:
    """Find the pool row with this identity; revive it when it was soft-deleted.

    A soft-deleted record is still the same job: adding it again restores it
    (``deleted_at`` cleared) instead of creating a second copy or reporting an
    unrelated duplicate. Returns ``(row, restored)``; ``(None, False)`` means
    the key is new.
    """
    if not fingerprint:
        return None, False
    for row in index.get(fingerprint) or []:
        if row.get("deleted_at"):
            row.pop("deleted_at", None)
            return row, True
        return row, False
    return None, False


def _hard_filter_view(value: Any) -> dict[str, Any] | None:
    """JSON-safe hard-filter view for the snapshot: ``{status, reasons:[可读字符串]}``."""
    if isinstance(value, str):
        return {"status": value, "reasons": []}
    if not isinstance(value, dict):
        return None
    raw_reasons = value.get("reasons")
    reasons: list[str] = []
    for item in raw_reasons if isinstance(raw_reasons, list) else []:
        if isinstance(item, dict):
            text = str(item.get("message") or item.get("code") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            reasons.append(text)
    status = str(value.get("status") or ("reject" if reasons else "unknown"))
    return {"status": status, "reasons": reasons}


def _score_scale_of(job: dict[str, Any]) -> str | None:
    """Which scale the numeric score is on: ``100`` for document scores, ``5`` for legacy manual ones."""
    if _score(job) is None:
        return None
    if job.get("score_scale") == MATCH_SCORE_SCALE_LABEL:
        return "100"
    return "5"


def get_store(mode: str = "user", seed_if_empty: bool = True) -> Store:
    """Return the single local dataset.

    ``mode`` and ``seed_if_empty`` stay in the signature so existing callers
    keep working; both are ignored. There is no second dataset to choose.
    """
    return Store()


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


def get_offerpilot_state(mode: str = "user") -> dict[str, Any]:
    """Return the credential-free state of the in-process OfferPilot backend."""
    state = offerpilot_runtime.get_state()
    if not state.get("ok"):
        state.setdefault("base_url", "embedded://offerpilot")
        state["pipeline"] = _pipeline_state(mode)
        return state
    # The OfferPilot config's target_cities can lag the workbench profile. The
    # collect form prefills from these preferences, so use the workbench's
    # job_intent.cities as the single source for the prefill.
    intent = get_store(mode).profile().get("job_intent")
    intent_cities = intent.get("cities") if isinstance(intent, dict) else None
    if isinstance(intent_cities, list):
        preferences = state.get("preferences")
        if isinstance(preferences, dict):
            preferences["cities"] = [str(city).strip() for city in intent_cities if str(city).strip()]
    state["pipeline"] = _pipeline_state(mode)
    return state


def get_offerpilot_jobs(mode: str = "user") -> dict[str, Any]:
    """Read the embedded OfferPilot job pool without an HTTP hop."""
    return offerpilot_runtime.get_jobs()


CONVERSATION_ID_RE = re.compile(r"[0-9a-f]{32}")
OFFERPILOT_COLLECT_PLATFORMS = ("boss", "zhilian", "51job", "liepin")


def _offerpilot_platform(value: Any, *, allow_all: bool = False) -> str:
    platform = str(value or "boss").strip().lower()
    allowed = OFFERPILOT_COLLECT_PLATFORMS + (("all",) if allow_all else ())
    if platform not in allowed:
        if allow_all:
            raise ApiError("平台只能是 boss、zhilian、51job、liepin 或 all")
        raise ApiError("平台只能是 boss、zhilian、51job 或 liepin")
    return platform


def get_offerpilot_conversations(mode: str = "user", platform: Any = "boss") -> dict[str, Any]:
    """Return the conversations already stored on this machine.

    The page renders immediately from disk; a platform read only happens when
    the caller starts a background sync.  ``platform="all"`` returns every
    stored platform; the default stays ``boss`` so existing callers keep their
    contract.  ``syncing`` and ``last_synced_at`` tell the UI whether a refresh
    is in flight and how old the stored copy is.
    """
    platform = _offerpilot_platform(platform, allow_all=True)
    try:
        return offerpilot_runtime.cached_conversations(platform)
    except ValueError as exc:
        raise ApiError(str(exc), 409) from exc


def get_offerpilot_conversations_summary(mode: str = "user") -> dict[str, Any]:
    """Counts and freshness per platform, read from local storage only."""
    return offerpilot_runtime.conversations_summary()


def start_offerpilot_conversations_sync(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Start one background incremental sync; never blocks the request."""
    body = payload if isinstance(payload, dict) else {}
    platform = _offerpilot_platform(body.get("platform", "all"), allow_all=True)
    try:
        return offerpilot_runtime.start_conversations_sync(platform)
    except ValueError as exc:
        raise ApiError(str(exc), 409) from exc


def get_offerpilot_conversation(
    mode: str, conversation_id: str, platform: Any = "boss", force: bool = False,
) -> dict[str, Any]:
    """Read one conversation's messages; the thread stays in memory.

    With ``platform="all"`` the runtime resolves the platform from the cached
    aggregated list, so the hashed conversation id is enough.
    """
    platform = _offerpilot_platform(platform, allow_all=True)
    text = str(conversation_id or "").strip()
    if not CONVERSATION_ID_RE.fullmatch(text):
        raise ApiError("会话 id 无效")
    try:
        if force:
            return offerpilot_runtime.get_thread(text, platform, force=True)
        return offerpilot_runtime.get_thread(text, platform)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 409) from exc


def send_offerpilot_reply(payload: dict[str, Any]) -> dict[str, Any]:
    """Send one confirmed HR reply; the message body is never logged."""
    text = payload.get("text")
    if not isinstance(text, str):
        raise ApiError("回复内容必须是文本")
    conversation_id = str(payload.get("id") or payload.get("conversation_id") or "").strip()
    if not CONVERSATION_ID_RE.fullmatch(conversation_id):
        raise ApiError("会话 id 无效")
    try:
        result = offerpilot_runtime.send_reply(
            conversation_id,
            text,
            confirm=payload.get("confirm"),
            risk_acknowledged=payload.get("risk_acknowledged") is True,
        )
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        status = 409 if "会话不在最近" in str(exc) else 400
        raise ApiError(str(exc), status) from exc
    except Exception as exc:
        # 平台出现验证码/风控页：立即停手，不重试，等用户到平台人工处理。
        if type(exc).__name__ == "MonitorRiskDetected":
            raise ApiError(
                "平台出现验证码或风控页，已停止发送，请到平台人工处理后再试", 409
            ) from exc
        raise
    store = get_store("user")
    # Log the action and company only: never the reply body or HR name.
    store.log("发送 HR 回复", str(result.get("company") or "未知公司"))
    return {
        "ok": True,
        "conversation_id": result.get("conversation_id"),
        "company": result.get("company"),
        "message": "已发送 1 条 HR 回复；不回写岗位或投递记录",
    }


def upload_offerpilot_resume(payload: dict[str, Any]) -> dict[str, Any]:
    """Store a resume for the embedded runtime's scoring step."""
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
    store = get_store("user")
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
    platform = _offerpilot_platform(raw.get("platform") or "boss")
    keywords = _offerpilot_text_list(raw.get("keywords"), "搜索关键词", 10)
    cities = _offerpilot_text_list(raw.get("cities"), "城市", 5)
    for item in keywords + cities:
        if any(ord(char) < 32 or ord(char) == 127 for char in item):
            raise ApiError("关键词和城市不能包含控制字符", 400)
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
    if task_mode not in OFFERPILOT_TASK_MODES:
        raise ApiError("仅允许 collect、monitor 或 full；发送任务不开放直接调用", 403)
    if payload.get("confirm") is not True:
        raise ApiError("启动 岗位自动化任务前必须明确传 confirm: true", 400)
    if payload.get("risk_acknowledged") is not True:
        raise ApiError("招聘平台自动化存在账号封禁风险；确认风险后传 risk_acknowledged: true", 400)
    options = _offerpilot_options(payload)
    if task_mode == "monitor" and options is not None:
        raise ApiError("监控任务不接受搜索条件；请选择 collect 或 full")
    profile_blocker = _profile_required_blocker(data_mode, task_mode)
    if profile_blocker:
        raise ApiError(profile_blocker, 400)
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
        # 运行时的互斥异常按类名识别，不 import vendor 内部模块。
        if type(exc).__name__ == "TaskAlreadyRunningError":
            raise ApiError("已有后台任务正在运行，请等它结束或先停止", 409) from exc
        raise ApiError(f"岗位自动化 启动失败：{type(exc).__name__}", 500) from exc
    message = "岗位自动化任务已受控提交；发送仍须经过人工确认门、每日上限与平台风控锁"
    if task_mode == "collect":
        message = "采集任务已受控提交；完成后会自动导入岗位池，再到「岗位池」挑选并加入审批队列"
    elif task_mode == "full":
        message = "完整流程已受控提交；采集、评分、入队与招呼语会自动完成，最后停在发送确认门"
    return {"ok": True, "task": response, "message": message}


def start_offerpilot_greet(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate greetings for approved jobs. Never sends anything."""
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError("请先勾选至少一条已确认岗位")
    if len(ids) > 10:
        raise ApiError("一次最多为 10 条岗位生成招呼语")
    store = get_store("user")
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


DELIVERY_CONFIRM_TEMPLATE = "确认发送本批 {count} 条"
# 与内嵌发送器的 throttle.daily_limit 默认值一致；仅用于排序提示，实际上限仍由发送器强制。
DEFAULT_DAILY_CONTACT_QUOTA = 30

DELIVERY_BLOCKED_REASONS = frozenset(
    {
        "captcha",
        "rate_limit",
        "blocked",
        "consecutive_errors",
        "persistent_risk_lock",
        "daily_platform_page_limit",
    }
)
# 读不到平台发送状态时最多再试 4 次；第 5 次仍读不到才按 unknown 定稿。
DELIVERY_SYNC_MAX_ATTEMPTS = 5


def _delivery_item(job: dict[str, Any], job_id: str) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "offerpilot_id": str(job.get("offerpilot_id") or ""),
        "company": str(job.get("company") or ""),
        "title": str(job.get("title") or ""),
        "status": "starting",
        "error_code": None,
        "started_at": _now(),
        "finished_at": None,
    }


@_serialized_store_write
def start_offerpilot_deliver(payload: dict[str, Any]) -> dict[str, Any]:
    """Send reviewed greetings for approved jobs through the runtime guards."""
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ApiError("请先勾选至少一条已确认岗位")
    if len(ids) > 10:
        raise ApiError("一次最多发送 10 条")
    job_ids: list[str] = []
    for item in ids:
        job_id = str(item or "").strip()
        if job_id and job_id not in job_ids:
            job_ids.append(job_id)
    expected = DELIVERY_CONFIRM_TEMPLATE.format(count=len(job_ids))
    if str(payload.get("confirm") or "") != expected:
        raise ApiError(f"请输入确认语「{expected}」")
    if payload.get("risk_acknowledged") is not True:
        raise ApiError("发送前必须确认平台自动化风险")

    store = get_store("user")
    queue = {str(row.get("id")): row for row in store.queue()}
    jobs = {str(job.get("id")): job for job in store.jobs()}
    vendor_ids: list[str] = []
    invalid: list[str] = []
    for job_id in job_ids:
        row = queue.get(job_id)
        if not row or row.get("status") != "approved":
            invalid.append(job_id)
            continue
        vendor_id = str((jobs.get(job_id) or {}).get("offerpilot_id") or "").strip()
        if not vendor_id:
            invalid.append(job_id)
            continue
        vendor_ids.append(vendor_id)
    if invalid:
        raise ApiError(
            "只有已确认且来自采集结果的岗位可以发送；请检查：" + "、".join(invalid[:5]),
            409,
        )
    send_blocked = {"zhilian": "智联招聘", "51job": "前程无忧", "liepin": "猎聘"}
    unsupported = [
        job_id for job_id in job_ids
        if str((jobs.get(job_id) or {}).get("source_channel") or "") in send_blocked
    ]
    if unsupported:
        names = "、".join(sorted({
            send_blocked[str((jobs.get(job_id) or {}).get("source_channel"))] for job_id in unsupported
        }))
        raise ApiError(
            f"{names} 暂不支持在工作台发送；请取消勾选这些岗位，把招呼语复制到平台里自己发送",
            409,
        )

    # 建批次前先看运行时是否已有任务：采集/监控/评分运行中时启动发送必然被拒，
    # 先拒绝可以避免留下一个永远起不来的批次。
    runtime_state = offerpilot_runtime.get_state()
    active_task = runtime_state.get("task") if isinstance(runtime_state.get("task"), dict) else {}
    if str(active_task.get("status") or "") in {"running", "stopping"}:
        raise ApiError("后台任务运行中，结束后再发送", 409)

    batch_id = "dlv-" + dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    batch = {
        "batch_id": batch_id,
        "task_id": None,
        "created_at": _now(),
        "finished_at": None,
        "status": "starting",
        "requested": len(job_ids),
        "sent": 0,
        "failed": 0,
        "deferred": 0,
        "blocked": 0,
        "stop_reason": None,
        "items": [_delivery_item(jobs[job_id], job_id) for job_id in job_ids],
    }
    deliveries = store.deliveries()
    deliveries.append(batch)
    store.set_deliveries(deliveries)

    busy = False
    try:
        result = offerpilot_runtime.start_deliver_task(vendor_ids)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        error = ApiError(str(exc), 503)
    except ValueError as exc:
        error = ApiError(str(exc), 400)
    except KeyError as exc:
        error = ApiError("岗位自动化任务不存在", 404)
    except Exception as exc:
        if type(exc).__name__ == "TaskAlreadyRunningError":
            busy = True
            error = ApiError("后台任务运行中，结束后再发送", 409)
        else:
            error = ApiError(f"发送任务启动失败：{type(exc).__name__}", 500)
    else:
        error = None
    if error is not None:
        if busy:
            # 互斥任务抢在预检之后启动：没有任何一条发送过，删掉刚建的批次，
            # 不要把它标成 failed，否则会留下错误的失败记录。
            store.set_deliveries([
                row for row in deliveries
                if str(row.get("batch_id") or "") != batch_id
            ])
            store.log("发送未启动", f"批次 {batch_id}；后台任务运行中", False)
            raise error
        batch["status"] = "failed"
        batch["stop_reason"] = "start_failed"
        batch["finished_at"] = _now()
        for item in batch["items"]:
            item["status"] = "failed"
            item["error_code"] = "start_failed"
            item["finished_at"] = batch["finished_at"]
        store.set_deliveries(deliveries)
        store.log("发送未启动", f"批次 {batch_id}；{error.message}", False)
        raise error

    task = result.get("task") or {}
    batch["task_id"] = task.get("id")
    batch["status"] = "sending"
    for item in batch["items"]:
        item["status"] = "sending"
    store.set_deliveries(deliveries)
    store.log("确认发送", f"批次 {batch_id}；{len(vendor_ids)} 条；受日限与间隔约束")
    return {
        "ok": True,
        "batch": batch,
        "task": task,
        "message": f"已提交本批 {len(vendor_ids)} 条发送；受每日上限与随机间隔约束",
    }


@_serialized_store_write
def _sync_deliveries(store: Store, boss_state: dict[str, Any]) -> list[dict[str, Any]]:
    """Finalize finished batches and record one pipeline event per job."""
    deliveries = store.deliveries()
    active = boss_state.get("task") if isinstance(boss_state.get("task"), dict) else {}
    active_id = str(active.get("id") or "")
    active_status = str(active.get("status") or "")
    last = boss_state.get("last_task") if isinstance(boss_state.get("last_task"), dict) else {}
    # 本批任务自己的状态：active 只指向当前占用运行时的任务，排队中的批次
    # 可能不是 active，不能据此提前定稿。
    task_statuses: dict[str, str] | None = None

    def task_status_of(task_id: str) -> str:
        nonlocal task_statuses
        if not task_id:
            return ""
        if task_statuses is None:
            task_statuses = {}
            try:
                status = offerpilot_runtime.load_backend().task_runner.status() or {}
            except Exception:
                status = {}
            for task in status.get("tasks") or []:
                if isinstance(task, dict):
                    task_statuses[str(task.get("id") or "")] = str(task.get("status") or "")
        return task_statuses.get(task_id, "")

    unfinished_statuses = {"running", "stopping", "queued", "pending"}
    changed = False
    for batch in deliveries:
        if batch.get("status") not in {"starting", "sending"}:
            continue
        task_id = str(batch.get("task_id") or "")
        if active_id and task_id and active_id == task_id and active_status in unfinished_statuses:
            continue
        if task_id:
            own_status = task_status_of(task_id)
            if own_status in unfinished_statuses:
                continue
            if not own_status and active_id:
                # 查不到本批任务，但运行时仍有别的任务在跑：无法确认本批已结束，等下次同步。
                continue
        items = [item for item in batch.get("items") or [] if isinstance(item, dict)]
        vendor_ids = [str(item.get("offerpilot_id") or "") for item in items if item.get("offerpilot_id")]
        preview_ok = True
        sync_error = ""
        preview: dict[str, Any] = {}
        if vendor_ids:
            try:
                preview = offerpilot_runtime.get_greetings(vendor_ids)
            except Exception as exc:
                preview = {}
                preview_ok = False
                sync_error = f"读取发送状态失败：{type(exc).__name__}"
            else:
                if not isinstance(preview, dict):
                    preview = {}
                    preview_ok = False
                    sync_error = "读取发送状态失败：返回格式不可用"
                elif preview.get("ok") is not True:
                    preview_ok = False
                    sync_error = str(preview.get("error") or "读取发送状态失败")
        if not preview_ok:
            # 读不到平台状态时不能猜 sent/failed：批次保持 starting/sending，
            # 记下错误并累计次数；达到上限后才按 unknown 定稿，交用户人工核实。
            attempts = int(batch.get("sync_attempts") or 0) + 1
            batch["sync_attempts"] = attempts
            batch["sync_error"] = sync_error
            changed = True
            if attempts < DELIVERY_SYNC_MAX_ATTEMPTS:
                continue
            finished_at = _now()
            for item in items:
                item["status"] = "unknown"
                item["error_code"] = "status_unreadable"
                item["finished_at"] = finished_at
                label = f"{item.get('company') or ''}｜{item.get('title') or ''}".strip("｜")
                store.append_pipeline_event({
                    "received_at": _now(),
                    "stage": "send",
                    "status": "skipped",
                    "job_id": str(item.get("job_id") or ""),
                    "message": f"{label} unknown".strip(),
                    "occurred_at": "",
                    "actor": "embedded_runtime",
                    "auto_submit": False,
                })
            batch.update({
                "status": "unknown",
                "sent": 0,
                "failed": 0,
                "deferred": 0,
                "blocked": 0,
                "unknown": len(items),
                "stop_reason": "status_unreadable",
                "finished_at": finished_at,
            })
            continue
        if batch.pop("sync_error", None) is not None:
            changed = True
        by_vendor = {
            str(item.get("id")): item
            for item in preview.get("greetings") or []
            if isinstance(item, dict)
        }
        stop_reason = ""
        if task_id and str(last.get("id") or "") == task_id:
            stop_reason = str(last.get("stop_reason") or "")
        elif task_id:
            # last_task 只是「最近启动的任务」；本批任务之后又启动了别的任务时，按任务 id 回查。
            try:
                stop_reason = offerpilot_runtime.task_stop_reason(task_id)
            except Exception:
                stop_reason = ""
        if not task_id:
            stop_reason = stop_reason or "task_not_started"
        counts = {"sent": 0, "failed": 0, "deferred": 0, "blocked": 0, "unknown": 0}
        for item in items:
            greeting = by_vendor.get(str(item.get("offerpilot_id") or ""))
            vendor_status = str((greeting or {}).get("status") or "")
            if vendor_status in offerpilot_runtime.DELIVERY_SENT_STATUSES:
                item["status"] = "sent"
                item["error_code"] = None
            elif vendor_status == "error":
                item["status"] = "failed"
                item["error_code"] = "send_error"
            elif stop_reason in DELIVERY_BLOCKED_REASONS:
                item["status"] = "blocked"
                item["error_code"] = stop_reason
            else:
                item["status"] = "deferred"
                item["error_code"] = stop_reason or "not_sent"
            item["finished_at"] = _now()
            counts[item["status"]] += 1
            event_status = (
                "succeeded"
                if item["status"] == "sent"
                else "failed"
                if item["status"] in {"failed", "blocked"}
                else "skipped"
            )
            label = f"{item.get('company') or ''}｜{item.get('title') or ''}".strip("｜")
            store.append_pipeline_event({
                "received_at": _now(),
                "stage": "send",
                "status": event_status,
                "job_id": str(item.get("job_id") or ""),
                "message": f"{label} {item['status']}".strip(),
                "occurred_at": "",
                "actor": "embedded_runtime",
                "auto_submit": False,
            })
        batch.update({
            "sent": counts["sent"],
            "failed": counts["failed"],
            "deferred": counts["deferred"],
            "blocked": counts["blocked"],
            "unknown": counts["unknown"],
            "stop_reason": stop_reason or None,
            "finished_at": _now(),
        })
        if counts["failed"] == 0 and counts["blocked"] == 0 and counts["deferred"] == 0:
            batch["status"] = "completed"
        elif counts["sent"] == 0:
            batch["status"] = "failed"
        else:
            batch["status"] = "partial"
        changed = True
    if changed:
        store.set_deliveries(deliveries)
    return deliveries


def _delivery_summary(deliveries: list[dict[str, Any]]) -> dict[str, Any]:
    latest = deliveries[-1] if deliveries else None
    return {
        "latest_batch": latest,
        "active": bool(latest and latest.get("status") in {"starting", "sending"}),
        "batches": deliveries[-5:],
    }


def _profile_required_blocker(mode: str, task_mode: str) -> str | None:
    """Collect/full tasks need the profile fields that feed search, scoring and
    greeting drafts (see PROFILE_REQUIRED_RULES). Monitor does not depend on
    profile content, so it is never blocked here."""
    if task_mode not in {"collect", "full"}:
        return None
    completeness = profile_completeness(get_store(mode).profile())
    missing = completeness.get("required_missing") or []
    if not missing:
        return None
    return "个人资料缺少必填项：" + "、".join(missing) + "；请先在「个人资料」页补全并保存。"


def preflight_offerpilot_task(payload: dict[str, Any]) -> dict[str, Any]:
    """Check the same start conditions without launching a task."""
    task_mode = str(payload.get("mode") or "collect")
    data_mode = str(payload.get("data_mode") or "user")
    if set(payload) - {"mode", "data_mode", "options", "action"}:
        raise ApiError("启动前检查只接受 mode、data_mode 和 options")
    if payload.get("action") not in (None, "offerpilot-preflight"):
        raise ApiError("动作与 OfferPilot 启动前检查不匹配")
    if task_mode not in OFFERPILOT_TASK_MODES:
        raise ApiError("仅允许 collect、monitor 或 full；发送任务不开放直接调用", 403)
    options = _offerpilot_options(payload)
    if task_mode == "monitor" and options is not None:
        raise ApiError("监控任务不接受搜索条件；请选择 collect 或 full")
    profile_blocker = _profile_required_blocker(data_mode, task_mode)
    if profile_blocker:
        return {
            "ok": False,
            "checks": [{
                "id": "profile_required",
                "title": "个人资料",
                "status": "error",
                "message": profile_blocker,
                "detail": "在「个人资料」页补全必填项并保存后，再检查环境。",
                "action": "profile",
            }],
            "messages": [profile_blocker],
            "summary": {},
        }
    try:
        result = offerpilot_runtime.preflight(task_mode, options)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    except Exception as exc:
        raise ApiError(f"岗位自动化 启动前检查失败：{type(exc).__name__}", 500) from exc
    return {"ok": bool(result.get("ok")), **result}


MATCH_SCORE_MODEL = "match-coefficients-v3"
MATCH_SCORE_SCALE_LABEL = "0-100（文档匹配分）"


def _offerpilot_score(raw_score: Any, coverage: Any = None) -> int | None:
    """Return the document's 0–100 integer score, or ``None`` when unscored.

    No threshold is applied.  A runtime score of 0 is treated as "not scored"
    unless the new scoring also stored a positive information coverage (a
    genuine all-zero result still has known dimensions).
    """
    if not isinstance(raw_score, (int, float)) or isinstance(raw_score, bool):
        return None
    value = float(raw_score)
    if not 0 <= value <= 100:
        return None
    has_coverage = (
        isinstance(coverage, (int, float))
        and not isinstance(coverage, bool)
        and 0 <= float(coverage) <= 1
    )
    if value <= 0 and not (has_coverage and float(coverage) > 0):
        return None
    return int(round(value))


def _rescale_imported_jobs(store: Store) -> int:
    """Move previously imported scores onto the document's 0–100 scale."""
    rows = store.all_jobs()  # rewrites jobs.json: must keep soft-deleted records
    changed = 0
    for row in rows:
        if not row.get("offerpilot_id"):
            continue
        raw = row.get("score_raw")
        coverage = row.get("score_coverage")
        # Old imported rows stored the 0–5 mapped score plus the raw score.
        # Restore the raw integer; rows without score_raw are left untouched.
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        score = _offerpilot_score(raw, coverage)
        if score is None:
            continue
        if row.get("score") != score or row.get("score_scale") != MATCH_SCORE_SCALE_LABEL:
            row["score"] = score
            row["score_scale"] = MATCH_SCORE_SCALE_LABEL
            changed += 1
    if changed:
        store.set_jobs(rows)
    return changed


def _import_offerpilot_records(store: Store, runtime_jobs: list[dict[str, Any]], ids: list[str]) -> dict[str, Any]:
    """Copy selected read-only OfferPilot jobs into the workbench job pool."""
    # all_jobs(): soft-deleted rows are part of the index; a match revives them.
    rows = store.all_jobs()
    index = _pool_duplicate_index(rows)
    used_ids = {str(row.get("id") or ""): row for row in rows}
    hard_cfg = _hard_filter_config(_profile_target_cities(store.profile()))
    by_id = {str(job.get("id")): job for job in runtime_jobs if isinstance(job, dict)}
    added: list[str] = []
    restored: list[str] = []
    hard_rejected = 0
    duplicates = 0
    unscored = 0
    backfilled = 0
    for position, job_id in enumerate(ids, start=1):
        source = by_id.get(job_id)
        if source is None:
            continue
        raw_score = source.get("score")
        coverage = source.get("score_coverage")
        score = _offerpilot_score(raw_score, coverage)
        if score is None:
            unscored += 1
        platform = str(source.get("source_platform") or "boss").strip().lower()
        if platform not in OFFERPILOT_COLLECT_PLATFORMS:
            platform = "boss"
        record = {
            "company": source.get("company"),
            "title": source.get("title"),
            "city": source.get("city"),
            "salary_text": source.get("salary"),
            # 运行时岗位只带本地库的 created_at/updated_at，没有平台发布时间；
            # 不把入库时间冒充 posted_at，否则超期判断和「来源更新时间」都会失真。
            "posted_at": None,
            "source_channel": platform,
            "source_platform": platform,
            "raw_text": "",
            "score": score,
            "offerpilot_id": job_id,
            "score_raw": raw_score if score is not None else None,
            "score_scale": MATCH_SCORE_SCALE_LABEL if score is not None else None,
            "scoring_model": MATCH_SCORE_MODEL if coverage is not None else None,
            "score_coverage": coverage,
            "mandatory_status": source.get("mandatory_status") or "unknown",
            "hiring_status": source.get("hiring_status") or "unknown",
            "mandatory_conditions": source.get("mandatory_conditions") or [],
        }
        # 采集导入同样要过共享硬性筛选（城市/排除词/薪资下限），结果随记录持久化；
        # 命中 reject 的记录仍然入库，但 enqueue 会按同一规则复查并拦下。
        hard = filters.apply_hard_filters(_hard_filter_fields(record), hard_cfg)
        record["hard_filter"] = hard["hard_filter"]
        if hard["hard_filter"]["status"] == "reject":
            hard_rejected += 1
        job = _normalize_job(record, position, platform)
        # 同公司/岗位/城市来自不同渠道时 _job_id 的种子相同：把渠道并入哈希重新生成，
        # 让两条记录各有独立 id，不在 jobs.json 里出现重复 id。
        holder = used_ids.get(str(job.get("id") or ""))
        if holder is not None and str(holder.get("source_channel") or "") != str(job.get("source_channel") or ""):
            seed = "|".join(str(job.get(key) or "") for key in ("company", "title", "city"))
            candidate = "j-" + hashlib.sha256(f"{seed}|{platform}".encode("utf-8")).hexdigest()[:12]
            salt = 0
            while candidate in used_ids:
                salt += 1
                candidate = "j-" + hashlib.sha256(
                    f"{seed}|{platform}|{salt}".encode("utf-8")
                ).hexdigest()[:12]
            job["id"] = candidate
        fingerprint = _job_fingerprint(job)
        match, revived = _resolve_pool_duplicate(index, fingerprint)
        if match is not None:
            if revived:
                restored.append(str(match.get("id") or ""))
                # Re-apply the current profile's hard filter to the revived row.
                match["hard_filter"] = record["hard_filter"]
            else:
                duplicates += 1
            # Backfill an unscored row; a row already carrying a document score
            # is refreshed because re-scoring is the same rule, not a user edit.
            if score is not None:
                if match.get("score") is None or record["scoring_model"] == MATCH_SCORE_MODEL:
                    match["score"] = score
                    match["score_raw"] = raw_score
                    match["score_scale"] = record["score_scale"]
                    match["scoring_model"] = record["scoring_model"]
                    match["score_coverage"] = coverage
                    match["mandatory_status"] = record["mandatory_status"]
                    match["hiring_status"] = record["hiring_status"]
                    match["mandatory_conditions"] = record["mandatory_conditions"]
                    backfilled += 1
            continue
        rows.append(job)
        used_ids[str(job["id"])] = job
        if fingerprint:
            index.setdefault(fingerprint, []).append(job)
        added.append(str(job["id"]))
    store.set_jobs(rows)
    log_detail = (
        f"新增 {len(added)} 条，重复 {duplicates} 条，恢复 {len(restored)} 条，"
        f"硬性筛选拦截 {hard_rejected} 条，未评分 {unscored} 条，回填评分 {backfilled} 条"
    )
    store.log("导入采集岗位", log_detail)
    message = f"已导入 {len(added)} 条到岗位池"
    if duplicates:
        message += f"，跳过 {duplicates} 条重复记录"
    if restored:
        message += f"，恢复 {len(restored)} 条此前删除的记录"
    if hard_rejected:
        message += f"；其中 {hard_rejected} 条命中城市/排除词/薪资硬性筛选，入队时会被拦下"
    if backfilled:
        message += f"；{backfilled} 条已有记录补上了评分"
    if unscored:
        message += f"；其中 {unscored} 条没有评分，不会进入审批队列"
    return {
        "ok": True,
        "added": added,
        "duplicates": duplicates,
        "restored": restored,
        "hard_filter_blocked": hard_rejected,
        "unscored": unscored,
        "backfilled": backfilled,
        "message": message,
    }



@_serialized_store_write
def import_offerpilot_jobs(payload: dict[str, Any]) -> dict[str, Any]:
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


PIPELINE_GREET_BATCH = 10
_last_pipeline: dict[str, Any] | None = None


def _pipeline_state(mode: str) -> dict[str, Any]:
    """Live pipeline status for the collect/queue views (read-only)."""
    store = get_store(mode)
    approved = [row for row in store.queue() if str(row.get("status") or "") == "approved"]
    snapshot = dict(_last_pipeline) if _last_pipeline else {}
    snapshot["approved_count"] = len(approved)
    snapshot["awaiting_confirmation"] = bool(approved)
    snapshot.setdefault("auto_submit", False)
    return snapshot


@_serialized_store_write
def run_offerpilot_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    """Automate import → enqueue → greeting, then stop at the send gate.

    Everything before the final confirmation runs here, reusing the existing
    gates: import dedupe, 30-day duplicate hold, risk block, city gate,
    missing education/experience warning and the approval score threshold.
    Nothing is sent; sending still needs the review popup and its confirm.
    """
    task_id = str(payload.get("task_id") or "").strip()
    if task_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        raise ApiError("任务 id 无效")
    min_score = _clean_min_score(payload.get("min_score"))
    raw_ids = payload.get("ids")
    if raw_ids is not None:
        if not isinstance(raw_ids, list) or not all(isinstance(item, str) for item in raw_ids):
            raise ApiError("ids 必须是字符串数组")
        if len(raw_ids) > 100:
            raise ApiError("一次最多处理 100 条")

    response = offerpilot_runtime.get_jobs(limit=500)
    if not response.get("ok"):
        raise ApiError(str(response.get("error") or "无法读取采集结果"), 503)
    runtime_jobs = [job for job in response.get("jobs") or [] if isinstance(job, dict)]
    available = {str(job.get("id")): job for job in runtime_jobs}
    if raw_ids is None:
        selected = list(available)
    else:
        cleaned: list[str] = []
        for item in raw_ids:
            text = str(item or "").strip()
            # Same rule as import: ids are local runtime ids, not paths or URLs.
            if not text or len(text) > 200 or any(ord(char) < 32 for char in text):
                raise ApiError("采集结果 id 无效")
            if text not in cleaned:
                cleaned.append(text)
        selected = [job_id for job_id in cleaned if job_id in available]
    if not selected:
        raise ApiError("没有可处理的采集结果", 409)

    store = get_store("user")
    _rescale_imported_jobs(store)
    imported = _import_offerpilot_records(store, runtime_jobs, selected)

    selected_set = set(selected)
    queued_ids = {str(row.get("id")) for row in store.queue()}
    candidates = [
        str(job.get("id"))
        for job in store.jobs()
        if str(job.get("offerpilot_id") or "") in selected_set
        and str(job.get("id")) not in queued_ids
    ]
    queued: dict[str, Any] = {
        "approved": [], "dropped": [], "duplicate": [], "risk_blocked": [],
        "city_blocked": [], "mandatory_blocked": [], "closed_blocked": [],
        "incomplete": [], "unscored": [], "recent_duplicates": [], "below_min_score": [],
        "message": "没有需要入队的岗位",
    }
    if candidates:
        queued = enqueue({"mode": "user", "ids": candidates, "min_score": min_score})

    greeting: dict[str, Any] = {
        "requested": 0, "task": None, "already_ready": 0, "deferred": 0, "error": None,
    }
    jobs_by_id = {str(job.get("id")): job for job in store.jobs()}
    approved_vendor: list[str] = []
    for row in store.queue():
        if str(row.get("status") or "") != "approved":
            continue
        vendor_id = str((jobs_by_id.get(str(row.get("id"))) or {}).get("offerpilot_id") or "").strip()
        if vendor_id and vendor_id not in approved_vendor:
            approved_vendor.append(vendor_id)
    if approved_vendor:
        try:
            preview = offerpilot_runtime.get_greetings(approved_vendor)
            ready = {
                str(item.get("id"))
                for item in preview.get("greetings") or []
                if isinstance(item, dict) and item.get("ready")
            }
        except Exception:
            ready = set()
        pending = [vendor_id for vendor_id in approved_vendor if vendor_id not in ready]
        greeting["already_ready"] = len(approved_vendor) - len(pending)
        if len(pending) > PIPELINE_GREET_BATCH:
            greeting["deferred"] = len(pending) - PIPELINE_GREET_BATCH
            pending = pending[:PIPELINE_GREET_BATCH]
        if pending:
            try:
                started = offerpilot_runtime.start_greet_task(pending)
            except offerpilot_runtime.OfferPilotUnavailable as exc:
                greeting["error"] = str(exc)
            except ValueError as exc:
                greeting["error"] = str(exc)
            except Exception as exc:
                greeting["error"] = f"生成招呼语失败：{type(exc).__name__}"
            else:
                greeting["requested"] = int(started.get("requested") or len(pending))
                greeting["task"] = started.get("task")
                # One activity row per batch, same shape as the manual greeting
                # action; the automated path starts the task directly, so it
                # must write its own summary instead of one row per job.
                store.log("生成招呼语", f"{greeting['requested']} 条；只生成，不发送")

    approved_count = len(queued.get("approved") or [])
    message = (
        f"自动流程已停在最终确认门：导入 {len(imported['added'])} 条，"
        f"入队 {approved_count} 条，生成招呼语 {greeting['requested']} 条；尚未发送任何消息"
    )
    below_count = len(queued.get("below_min_score") or [])
    if below_count and min_score is not None:
        message += f"；{below_count} 条低于合格线 {min_score:g} 分，未自动入队"
    if greeting["error"]:
        message += f"；招呼语暂未生成：{greeting['error']}"
    if greeting["deferred"]:
        message += f"；另有 {greeting['deferred']} 条待下一轮生成"
    result = {
        "ok": True,
        "task_id": task_id or None,
        "imported": {
            "added": len(imported["added"]),
            "duplicates": imported["duplicates"],
            "unscored": imported["unscored"],
            "backfilled": imported["backfilled"],
        },
        "queued": queued,
        "greeting": greeting,
        "awaiting_confirmation": True,
        "auto_submit": False,
        "message": message,
    }
    global _last_pipeline
    _last_pipeline = {**result, "updated_at": _now()}
    store.log("自动流程", message)
    return result


def stop_offerpilot_task(task_id: str, data_mode: str = "user") -> dict[str, Any]:
    safe_id = str(task_id or "").strip()
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
            "runtime_dir": "web/data/user/offerpilot",
        },
        "event_schema": {
            "type": "object",
            "required": ["stage", "status"],
            "properties": {
                "mode": {"type": "string", "enum": ["user"], "default": "user"},
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
            "configured_send_window_required": False,
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
    risk_map = _job_risk_map(jobs)
    # 详情/核对面板读 standard、match、dossier、traceability；这四个键只读派生，
    # 只用本机已有数据，缺失字段保持 None，不会触发任何外部请求。
    analysis_cv_text = profile_context_text(profile) or cv_text
    analysis_variants = store.variants()
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
    deliveries = _sync_deliveries(store, boss_state)
    latest_by_job: dict[str, dict[str, Any]] = {}
    for batch in deliveries:
        for item in batch.get("items") or []:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("job_id") or "")
            if job_id:
                latest_by_job[job_id] = {
                    "batch_id": batch.get("batch_id"),
                    "status": item.get("status"),
                    "error_code": item.get("error_code"),
                    "finished_at": item.get("finished_at"),
                }
    queue_view = [dict(row) for row in queue]
    # 判断置信度是独立结果（必备条件证据的充分度，缺失时取资料覆盖率），
    # 与队列里的 high_confidence 阈值标记不是一回事；这里只给队列行追加字段。
    all_jobs_by_id = {str(job.get("id")): job for job in jobs}
    for row in queue_view:
        source_job = all_jobs_by_id.get(str(row.get("id")))
        row["fit_confidence"] = job_match.fit_confidence(source_job) if source_job else None
    materials_by_vendor: dict[str, Any] = {}
    if boss_state.get("ok"):
        job_by_id = {str(job.get("id")): job for job in jobs}
        vendor_by_job: dict[str, str] = {}
        for row in queue_view:
            if row.get("status") != "approved":
                continue
            vendor_id = str((job_by_id.get(str(row.get("id"))) or {}).get("offerpilot_id") or "").strip()
            if vendor_id:
                vendor_by_job[str(row.get("id"))] = vendor_id
        # jobs[] also carries materials, so preview every collected job once.
        vendor_ids = list(dict.fromkeys(
            [
                str(job.get("offerpilot_id") or "").strip()
                for job in filtered_jobs
                if str(job.get("offerpilot_id") or "").strip()
            ]
            + list(vendor_by_job.values())
        ))
        by_vendor: dict[str, dict[str, Any]] = {}
        for start in range(0, len(vendor_ids), 50):
            try:
                preview = offerpilot_runtime.get_greetings(vendor_ids[start:start + 50])
            except Exception:
                continue
            for item in preview.get("greetings") or []:
                if isinstance(item, dict):
                    by_vendor[str(item.get("id"))] = item
        materials_by_vendor = {
            vendor_id: item.get("materials")
            for vendor_id, item in by_vendor.items()
            if isinstance(item.get("materials"), dict)
        }
        for row in queue_view:
            vendor_id = vendor_by_job.get(str(row.get("id")))
            item = by_vendor.get(vendor_id) if vendor_id else None
            if item:
                row["greeting"] = {
                    key: item.get(key)
                    for key in (
                        "status", "greeting", "selection", "style_issues",
                        "reviewed", "ready", "materials",
                    )
                }
                greeting_text = str(row["greeting"].get("greeting") or "")
                if greeting_text:
                    # Read-only: flags numbers with no match in the user's own facts.
                    row["greeting"]["evidence_check"] = evidence_checker.check_text_against_facts(
                        greeting_text, profile_context_text(profile) + "\n" + cv_text
                    )
    for row in queue_view:
        delivery = latest_by_job.get(str(row.get("id")))
        if delivery:
            row["delivery"] = delivery
    contact_plan = _contact_plan(queue_view, jobs, deliveries, risk_map)
    ranked_by_id = {item["id"]: item for item in contact_plan["ranked"]}
    deferred_by_id = {item["id"]: item for item in contact_plan["deferred"]}
    for row in queue_view:
        row_id = str(row.get("id"))
        if row_id in ranked_by_id:
            row["plan"] = {"today": True, "rank": ranked_by_id[row_id]["rank"], "reason": ranked_by_id[row_id]["reason"]}
        elif row_id in deferred_by_id:
            row["plan"] = {"today": False, "rank": None, "reason": deferred_by_id[row_id]["reason"]}
    pipeline_payload = pipeline_status(store, jobs, queue, store.mails(), boss_state)
    pipeline_payload["delivery"] = _delivery_summary(deliveries)
    pipeline_payload["delivery"]["quota"] = {
        "daily": contact_plan["daily_quota"],
        "remaining": contact_plan["remaining_quota"],
        "planned_today": len(contact_plan["ranked"]),
    }
    return {
        "mode": store.mode,
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
            "posted_at", "warnings", "score", "state", "approval",
            "fingerprint", "raw_text", "date", "created_at",
            "mandatory_status", "hiring_status", "score_coverage", "offerpilot_id",
        )} | {
            # 硬筛原因在快照里只给可读字符串，原始 reason 字典不直接进界面。
            "hard_filter": _hard_filter_view(job.get("hard_filter")),
            "score_scale": _score_scale_of(job),
            "risk": risk_map.get(str(job.get("id"))),
            "materials": materials_by_vendor.get(str(job.get("offerpilot_id") or "")),
        } | decorate_job_analysis(
            job, profile=profile, cv_text=analysis_cv_text, variants=analysis_variants
        ) for job in filtered_jobs],
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
        "pipeline": pipeline_payload,
        "profile": profile_for_api(mode, store),
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


def decorate_job_analysis(
    job: dict[str, Any],
    profile: dict[str, Any] | None = None,
    cv_text: str = "",
    variants: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the additive, read-only analysis view for one job row.

    Keys: ``standard`` (what the posting says), ``match`` (fit score,
    confidence and risk kept separate), ``dossier`` (application package) and
    ``traceability`` (requirement → verbatim profile evidence). Every value
    comes from local data already on the row or in the profile; missing data
    stays ``None`` and nothing is sent.
    """
    return {
        "standard": job_standardize.standardize_job(job),
        "match": job_match.match_job(job),
        "dossier": job_dossier.build_dossier(
            job, profile=profile, variants=variants, cv_text=cv_text
        ),
        "traceability": job_dossier.build_traceability(job, profile=profile),
    }


@_serialized_store_write
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
    profile = store.profile()
    cv_text = profile_context_text(profile) or (
        CV_PATH.read_text(encoding="utf-8-sig") if CV_PATH.is_file() else ""
    )
    job_view = dict(job)
    job_view.update(
        decorate_job_analysis(job, profile=profile, cv_text=cv_text, variants=store.variants())
    )
    rows = store.all_jobs()  # keeps soft-deleted records in jobs.json
    index = _pool_duplicate_index(rows)
    match, restored = _resolve_pool_duplicate(index, _job_fingerprint(job))
    if match is not None:
        if restored:
            # The job was deleted by the user before; adding it again revives
            # the original record instead of creating a second copy.
            store.set_jobs(rows)
            store.log("恢复已删除岗位", f"{match.get('company')} · {match.get('title')}")
            restored_view = dict(match)
            restored_view.update(
                decorate_job_analysis(match, profile=profile, cv_text=cv_text, variants=store.variants())
            )
            return {
                "ok": True,
                "restored": [str(match.get("id") or "")],
                "job": restored_view,
                "message": "该岗位此前已删除，已恢复",
            }
        store.log("拒绝重复岗位", job["title"], False)
        return {"ok": False, "duplicate": True, "job": job_view, "message": "相同公司、岗位、城市、渠道的记录已存在"}
    rows.append(job)
    store.set_jobs(rows)
    store.log("录入 JD", f"{job['company']} · {job['title']}")
    return {"ok": True, "job": job_view, "message": "岗位已录入本地工作区"}


@_serialized_store_write
def import_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    text = _bounded_text(payload.get("text"), "导出 JSON")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiError(f"JSON 无法解析：{exc.msg}") from exc
    converted = offerpilot_adapter.convert_payload(raw)
    store = get_store(mode)
    rows = store.all_jobs()  # keeps soft-deleted records; they count as duplicates
    index = _pool_duplicate_index(rows)
    added: list[str] = []
    restored: list[str] = []
    duplicates = 0
    for position, record in enumerate(converted["jobs"], start=1):
        job = _normalize_job(record, position, converted["source_channel"])
        key = _job_fingerprint(job)
        match, revived = _resolve_pool_duplicate(index, key)
        if match is not None:
            if revived:
                restored.append(str(match.get("id") or ""))
            else:
                duplicates += 1
            continue
        rows.append(job)
        if key:
            index.setdefault(key, []).append(job)
        added.append(str(job["id"]))
    store.set_jobs(rows)
    log_detail = f"新增 {len(added)} 条，重复 {duplicates} 条"
    message = f"已导入 {len(added)} 条，跳过 {duplicates} 条重复记录"
    if restored:
        log_detail += f"，恢复 {len(restored)} 条此前删除的记录"
        message += f"，恢复 {len(restored)} 条此前删除的记录"
    store.log("导入静态岗位池", log_detail)
    return {
        "ok": True,
        "count": len(converted["jobs"]),
        "added": added,
        "duplicates": duplicates,
        "restored": restored,
        "message": message,
    }


# 30 天内同一岗位（公司、岗位名、城市指纹相同）不重复入队或发送，窗口规则与 tools/precheck.py 一致。
RECENT_DUPLICATE_DAYS = 30
PLACEHOLDER_COMPANY = "未填写公司"
PLACEHOLDER_TITLE = "未填写岗位"
# 手动加入低分/未评分岗位时的原因只能从这三项中选（前端下拉框，用户不打字）。
MANUAL_OVERRIDE_REASONS = (
    "值得沟通，人工判断",
    "有内推或熟人渠道",
    "公司或岗位我已了解",
)


def _clean_override_reason(value: Any) -> str:
    """Manual adds of low or unscored jobs must carry one of the dropdown reasons."""
    text = str(value or "").strip()
    if text not in MANUAL_OVERRIDE_REASONS:
        raise ApiError("手动加入低分或未评分岗位时，请从下拉框选择原因", 400)
    return text


def _parse_day(value: Any) -> dt.date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text).date()
    except ValueError:
        pass
    match = DATE_RE.search(text)
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _dedup_fingerprint(
    company: Any,
    title: Any,
    city: Any,
    job: dict[str, Any] | None = None,
    job_id: str = "",
) -> str:
    """Same fingerprint rule as tools/precheck.py. Placeholder names never match each other.

    A job without a usable company/title pair is not automatically "unique": it
    falls back to its own stable identifier so the same job cannot be queued or
    sent twice within the window. Keys are prefixed with ``id:`` so they can
    never collide with a company/title fingerprint, and two blank-name jobs with
    different identifiers stay unrelated. Without any identifier the job cannot
    be matched and keeps the old empty-key behavior.
    """
    company_text = str(company or "").strip()
    title_text = str(title or "").strip()
    if (
        company_text
        and company_text != PLACEHOLDER_COMPANY
        and title_text
        and title_text != PLACEHOLDER_TITLE
    ):
        return precheck.compute_fingerprint(company_text, title_text, city)

    record = job if isinstance(job, dict) else {}
    for field in ("source_url", "url"):
        value = str(record.get(field) or "").strip()
        if value:
            return f"id:{field}:{value}"
    offerpilot_id = str(record.get("offerpilot_id") or "").strip()
    if offerpilot_id:
        return f"id:offerpilot:{offerpilot_id}"
    platform = str(record.get("source_platform") or record.get("platform") or "").strip()
    platform_job_id = str(record.get("platform_job_id") or "").strip()
    if platform and platform_job_id:
        return f"id:platform:{platform}|{platform_job_id}"
    fallback = str(record.get("id") or job_id or "").strip()
    return f"id:job:{fallback}" if fallback else ""


def _recent_duplicate_index(
    store: Store,
    jobs_by_id: dict[str, dict[str, Any]],
    today: dt.date,
    include_queue: bool = True,
) -> dict[str, dict[str, Any]]:
    """Fingerprints already queued or delivered within the last 30 days.

    Queue rows and delivery items carry only job ids, so company, title and city
    are read from the job record. Terminal statuses (discarded, closed, etc.) are
    skipped with the same list precheck uses. ``include_queue=False`` looks only
    at sent deliveries, which is what confirm needs: a pending row is itself in
    the queue and would otherwise match its own fingerprint.
    """
    window_start = today - dt.timedelta(days=RECENT_DUPLICATE_DAYS)
    index: dict[str, dict[str, Any]] = {}

    def remember(job_id: str, day: dt.date | None, source: str, status: str) -> None:
        if day is None or not (window_start <= day <= today):
            return
        if precheck.normalize_status(status) in precheck.EXCLUDED_STATUSES:
            return
        job = jobs_by_id.get(job_id) or {}
        key = _dedup_fingerprint(job.get("company"), job.get("title"), job.get("city"), job, job_id)
        if not key or key in index:
            return
        index[key] = {"job_id": job_id, "date": day.isoformat(), "source": source, "status": status}

    if include_queue:
        for row in store.queue():
            job_id = str(row.get("id") or "")
            day = _parse_day(row.get("approved_at") or row.get("created_at"))
            remember(job_id, day, "queue", str(row.get("status") or ""))
    for batch in store.deliveries():
        for item in batch.get("items") or []:
            if not isinstance(item, dict) or item.get("status") != "sent":
                continue
            job_id = str(item.get("job_id") or "")
            day = _parse_day(item.get("finished_at") or item.get("started_at") or batch.get("created_at"))
            remember(job_id, day, "delivery", "sent")
    return index


def _split_recent_duplicates(
    store: Store,
    jobs_by_id: dict[str, dict[str, Any]],
    job_ids: list[str],
    include_queue: bool = True,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Return (ids that may proceed, duplicates with the reason they were held)."""
    today = dt.datetime.now(dt.timezone.utc).astimezone().date()
    index = _recent_duplicate_index(store, jobs_by_id, today, include_queue)
    kept: list[str] = []
    held: list[dict[str, Any]] = []
    for job_id in job_ids:
        job = jobs_by_id.get(job_id) or {}
        key = _dedup_fingerprint(job.get("company"), job.get("title"), job.get("city"), job, job_id)
        hit = index.get(key) if key else None
        if hit is None:
            kept.append(job_id)
            continue
        where = "已在审批队列" if hit["source"] == "queue" else "已发送过"
        held.append({
            "id": job_id,
            "company": job.get("company") or "",
            "title": job.get("title") or "",
            "reason": f"{RECENT_DUPLICATE_DAYS} 天内{where}（{hit['date']}）",
        })
    return kept, held


def _missing_intake_fields(job: dict[str, Any]) -> list[str]:
    """Education / experience not recorded on the job: pass with a warning, never block.

    The user chose 放行并提示 for these fields. The shared filter has no rule for them,
    so the check lives here and only reports; it never guesses a value.
    """
    missing = []
    if not str(job.get("education") or "").strip():
        missing.append("学历")
    if not str(job.get("experience") or "").strip():
        missing.append("经验")
    return missing


CITY_SUFFIXES = ("新区", "市", "区", "县", "省")
# 城市由 _job_city_reject 单独复查（需要双向包含匹配），这里只拦排除词与薪资下限。
HARD_FILTER_BLOCK_FIELDS = ("jd_text", "salary_min")


def _profile_target_cities(profile: dict[str, Any]) -> list[str]:
    """Target cities from profile.json (job_intent.cities); empty when unset."""
    intent = profile.get("job_intent") if isinstance(profile.get("job_intent"), dict) else {}
    cities = intent.get("cities") if isinstance(intent.get("cities"), list) else []
    return [str(city).strip() for city in cities if str(city).strip()]


def _hard_filter_config(profile_cities: list[str]) -> dict[str, Any]:
    """Shared filter config with the profile's target cities taking precedence.

    tools/filters.py stays the rule owner and is only read here; the profile's
    city list replaces the config default only when the profile has one.
    """
    cfg = dict(filters.load_config())
    if profile_cities:
        cfg["target_cities"] = list(profile_cities)
    return cfg


def _hard_filter_fields(job: dict[str, Any]) -> dict[str, str]:
    """Fields the shared hard filter reads. JD text stays data, never instructions."""
    return {
        "company": str(job.get("company") or ""),
        "title": str(job.get("title") or ""),
        "city": str(job.get("city") or ""),
        "salary_text": str(job.get("salary_text") or job.get("salary_label") or ""),
        "source_channel": str(job.get("source_channel") or ""),
        "contact": str(job.get("contact") or ""),
        "raw_text": str(job.get("raw_text") or ""),
    }


def _hard_filter_block_reason(job: dict[str, Any], cfg: dict[str, Any]) -> str:
    """Re-check excluded terms and the salary floor; return a readable reason or "".

    City is checked by ``_job_city_reject`` with its own matching rule, so city
    reasons from the shared filter are ignored here to avoid rejecting a job the
    city gate already passed (e.g. 上海市 vs 上海·浦东).
    """
    result = filters.apply_hard_filters(_hard_filter_fields(job), cfg)
    messages = [
        str(item.get("message") or "").strip()
        for item in result["hard_filter"]["reasons"]
        if isinstance(item, dict) and item.get("field") in HARD_FILTER_BLOCK_FIELDS
    ]
    return "；".join(text for text in messages if text)


def _city_core(value: Any) -> str:
    """主城市名：去掉「·」「-」后面的区域，再去掉 市/区/县/省 后缀。"""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.split(r"[·・\-–—]", text, maxsplit=1)[0].strip()
    # 「上海市浦东新区」没有分隔符时，主城市名到第一个「市」为止。
    marker = text.find("市")
    if 0 < marker < len(text) - 1:
        text = text[: marker + 1]
    for suffix in CITY_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)].strip()
            break
    return text.casefold()


def _city_matches(job_city: Any, target: Any) -> bool:
    """双向包含：上海市 ≈ 上海·浦东 ≈ 上海。"""
    job_core = _city_core(job_city)
    target_core = _city_core(target)
    if not job_core or not target_core:
        return False
    return job_core in target_core or target_core in job_core


def _job_city_reject(job: dict[str, Any], profile_cities: list[str]) -> str:
    """Return a reject reason when the job's city is outside the profile's target cities, else "".

    Target cities come from profile.json (job_intent.cities), falling back to
    tools/config.json only when the profile has none. Both sides are reduced to
    their main city name (region after ``·``/``-`` dropped, 市/区/县/省 suffix
    removed) and compared by two-way containment, so 「上海市」matches
    「上海·浦东」. A missing job city passes with a warning, never a guess.
    """
    city = str(job.get("city") or "").strip()
    if not city:
        return ""
    targets = profile_cities or [
        str(item) for item in filters.load_config().get("target_cities") or []
    ]
    targets = [str(item).strip() for item in targets if str(item).strip()]
    if not targets:
        return ""
    if any(_city_matches(city, target) for target in targets):
        return ""
    return f"城市不在目标城市列表：{city}"


def _append_manual_queue(store: Store, entries: list[dict[str, Any]], reason: str = "") -> list[str]:
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
            # The user's explicit click on a low-score job is the approval.
            "status": cfg["approval"]["approved_status"],
            "Source_Channel": entry.get("Source_Channel") or "unknown",
            "created_at": stamp,
            "approved_at": stamp,
            "high_confidence": False,
            "manual_override": True,
            "override_reason": reason,
            "override_at": stamp,
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


@_serialized_store_write
def _clean_min_score(value: Any) -> float | None:
    """合格线：0–100 的数字；缺省表示不设合格线（沿用文档规则）。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ApiError("合格线必须是 0–100 的数字")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError("合格线必须是 0–100 的数字") from None
    if not (0 <= number <= 100):
        raise ApiError("合格线必须是 0–100 的数字")
    return number


def enqueue(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
        raise ApiError("ids 必须是字符串数组")
    allow_low = payload.get("allow_low_score") is True
    min_score = _clean_min_score(payload.get("min_score"))
    # 手动加入低分/未评分岗位必须带原因；校验放在读写队列之前，失败时不改动任何数据。
    override_reason = _clean_override_reason(payload.get("override_reason")) if allow_low else ""
    store = get_store(mode)
    jobs = {str(job.get("id")): job for job in store.jobs()}
    ids, recent_duplicates = _split_recent_duplicates(store, jobs, ids)
    profile_cities = _profile_target_cities(store.profile())
    hard_cfg = _hard_filter_config(profile_cities)
    doc_candidates: list[dict[str, Any]] = []
    manual_only: set[str] = set()
    dropped_ids: list[str] = []
    risk_blocked: list[str] = []
    city_blocked: list[dict[str, Any]] = []
    hard_filter_blocked: list[dict[str, Any]] = []
    mandatory_blocked: list[dict[str, Any]] = []
    closed_blocked: list[dict[str, Any]] = []
    zero_score_held: list[dict[str, Any]] = []
    below_min_score: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    unscored: list[str] = []
    risk_map = _job_risk_map(list(jobs.values()))
    for job_id in ids:
        job = jobs.get(job_id)
        if not job:
            continue
        # 高风险岗位（收费/培训贷/保就业承诺等）不进入队列，手动加入也不例外。
        if (risk_map.get(job_id) or {}).get("blocks_queue"):
            risk_blocked.append(job_id)
            continue
        # 城市不在 profile.json 的目标城市内：硬性拒绝，手动加入也不放行。
        city_reason = _job_city_reject(job, profile_cities)
        if city_reason:
            city_blocked.append({"id": job_id, "reason": city_reason})
            continue
        # 采集导入会持久化 hard_filter，但这里按当前 profile 复查一遍：
        # 排除词与薪资下限为硬性拒绝，手动加入也不放行。
        hard_reason = _hard_filter_block_reason(job, hard_cfg)
        if hard_reason:
            hard_filter_blocked.append({"id": job_id, "reason": hard_reason})
            continue
        missing = _missing_intake_fields(job)
        if missing:
            incomplete.append({"id": job_id, "missing": missing})
        # 评分规则里的“明确不满足”和“已关闭或确认失效”都移出默认推荐；
        # 与低分岗位一样，只有用户手动加入并填写原因才进入队列。
        not_recommended = ""
        conditions = job.get("mandatory_conditions") if isinstance(job.get("mandatory_conditions"), list) else []
        if job.get("mandatory_status") == "unsatisfied":
            names = [
                str(item.get("condition") or "").strip()
                for item in conditions
                if isinstance(item, dict) and item.get("status") == "明确不满足"
            ]
            not_recommended = "；".join(name for name in names if name)[:120] or "必备条件明确不满足"
            mandatory_blocked.append({"id": job_id, "reason": not_recommended})
        if job.get("hiring_status") == "closed":
            closed_blocked.append({"id": job_id, "reason": "岗位已关闭或确认失效"})
            not_recommended = not_recommended or "岗位已关闭或确认失效"
        score = _score(job)
        coverage = job.get("score_coverage")
        doc_scored = (
            job.get("scoring_model") == MATCH_SCORE_MODEL
            or (job.get("offerpilot_id") and isinstance(coverage, (int, float)) and not isinstance(coverage, bool))
        )
        has_doc_score = doc_scored and score is not None and float(coverage or 0) > 0
        # 入队只认文档评分：没有按文档评分的岗位（含旧六维度本地岗位）不自动入队。
        if not has_doc_score:
            if allow_low:
                manual_only.add(job_id)
            elif score is None or doc_scored:
                # 未评分，或全部维度未知（覆盖率 0）的待确认岗位：
                # 需要用户明确手动加入，这里记下来避免被静默丢弃。
                unscored.append(job_id)
            else:
                # 旧评分（非文档模型）不再自动入队，也不冒充文档评分。
                dropped_ids.append(job_id)
            continue
        if not_recommended and not allow_low:
            continue
        # 文档评分为 0：每个已知维度都不匹配。不自动通过，和必备条件不满足一样只能手动加入。
        if not not_recommended and score is not None and float(score) <= 0:
            not_recommended = "文档评分为 0，各项都不匹配"
            zero_score_held.append({"id": job_id, "reason": not_recommended})
            if not allow_low:
                continue
        # 合格线（可选）：低于线的岗位不自动通过，和零分一样只能手动加入。
        if not not_recommended and min_score is not None and score is not None and float(score) < min_score:
            not_recommended = f"评分 {float(score):g} 分，低于合格线 {min_score:g} 分"
            below_min_score.append({"id": job_id, "score": float(score), "reason": not_recommended})
            if not allow_low:
                continue
        if not_recommended:
            manual_only.add(job_id)
            continue
        candidate = {
            "id": job_id,
            "score": score,
            "company": job.get("company"),
            "title": job.get("title"),
            "Source_Channel": job.get("source_channel"),
            "created_at": _now(),
        }
        doc_candidates.append(candidate)

    # 文档规则岗位：不再与任何数字阈值比较，只要已按文档评分（覆盖率 > 0）、
    # 没有明确不满足的必备条件且岗位未关闭，就进入审批队列。
    # 这里只给 approval_queue.enqueue 传内存中的 config 覆盖，不改 tools 配置文件。
    doc_auto = doc_candidates
    result: dict[str, Any] = {"accepted": [], "dropped": [], "duplicate": [], "count": 0}
    if doc_auto:
        doc_cfg = approval_queue.load_config()
        doc_cfg = {
            **doc_cfg,
            "score": {
                **doc_cfg.get("score", {}),
                # 文档评分不与数字阈值比较，只需把入队线降到 0。
                # high_threshold 保留工具里的真实配置：high_confidence 只是标记，
                # 不参与入队、确认或投递判定，也不再在界面显示。
                "approval_min": 0,
            },
        }
        doc_result = approval_queue.enqueue(doc_auto, store.files["queue"], config=doc_cfg)
        for key in ("accepted", "dropped", "duplicate"):
            result[key].extend(doc_result[key])
    result["dropped"].extend(dropped_ids)
    result["count"] = len(approval_queue.load_queue(store.files["queue"]))
    # 符合筛选规则的岗位直接标记为 approved；人工确认只保留在最终发送前。
    approved: list[str] = []
    if result["accepted"]:
        confirmed = approval_queue.confirm(result["accepted"], store.files["queue"])
        approved = confirmed.get("confirmed") or []
    manual: list[str] = []
    if allow_low:
        low = [
            {
                "id": job_id,
                "score": _score(jobs[job_id]) if jobs.get(job_id) else None,
                "company": (jobs.get(job_id) or {}).get("company"),
                "title": (jobs.get(job_id) or {}).get("title"),
                "Source_Channel": (jobs.get(job_id) or {}).get("source_channel"),
                "created_at": _now(),
            }
            for job_id in ids
            if job_id in manual_only and job_id in jobs
        ]
        manual = _append_manual_queue(store, low, override_reason)
        if manual:
            result["manual"] = manual
            # 手动加入的岗位不再算作「未入队」，避免同一条记录被报告两次。
            result["dropped"] = [job_id for job_id in result["dropped"] if job_id not in manual]
            result["count"] = len(approval_queue.load_queue(store.files["queue"]))
    result["approved"] = approved
    result["risk_blocked"] = risk_blocked
    result["city_blocked"] = city_blocked
    result["hard_filter_blocked"] = hard_filter_blocked
    result["mandatory_blocked"] = mandatory_blocked
    result["closed_blocked"] = closed_blocked
    result["zero_score_held"] = zero_score_held
    result["below_min_score"] = below_min_score
    result["min_score"] = min_score
    result["incomplete"] = incomplete
    result["unscored"] = unscored
    result["recent_duplicates"] = recent_duplicates
    store.log(
        "加入审批队列",
        f"按规则自动通过 {len(approved)} 条，手动加入 {len(manual)} 条（原因：{override_reason or '无'}）；"
        f"未入队 {len(result['dropped']) + len(result['duplicate'])} 条；"
        f"城市拦截 {len(city_blocked)} 条，硬性筛选拦截 {len(hard_filter_blocked)} 条；"
        f"必备条件不满足 {len(mandatory_blocked)} 条，已关闭 {len(closed_blocked)} 条；"
        f"{RECENT_DUPLICATE_DAYS} 天内重复拦截 {len(recent_duplicates)} 条",
    )
    message = "已进入审批队列" if (result["accepted"] or result["duplicate"]) else "没有岗位入队"
    if approved:
        message = f"{len(approved)} 条已按文档规则评分并通过筛选，已自动通过"
    if manual:
        message += f"；{len(manual)} 条未自动通过，已按你的选择手动加入（标记为已通过）"
    if below_min_score:
        message += f"；{len(below_min_score)} 条评分低于合格线 {min_score:g} 分，未自动通过（可在「筛选」里手动加入）"
    if risk_blocked:
        message += f"；{len(risk_blocked)} 条疑似高风险岗位（收费/承诺类），已拦截不入队"
    if city_blocked:
        message += f"；{len(city_blocked)} 条城市不在目标城市内，已拦截不入队"
    if hard_filter_blocked:
        message += f"；{len(hard_filter_blocked)} 条命中硬性排除词或薪资下限，已拦截不入队"
    if mandatory_blocked:
        message += (
            f"；{len(mandatory_blocked)} 条必备条件明确不满足，已移出默认推荐"
            + ("并按你的选择手动加入" if allow_low else "，需要时请点「手动加入」并填写原因")
        )
    if closed_blocked:
        message += (
            f"；{len(closed_blocked)} 条岗位已关闭或确认失效"
            + ("并按你的选择手动加入" if allow_low else "，未自动入队")
        )
    if incomplete:
        message += f"；{len(incomplete)} 条缺少学历或经验字段，已放行并提示，请人工核对"
    if zero_score_held and not allow_low:
        message += f"；{len(zero_score_held)} 条文档评分为 0，未自动通过，需要时请点「手动加入」"
    if unscored:
        message += f"；{len(unscored)} 条未评分岗位未入队，需要你点「手动加入」"
    if recent_duplicates:
        message += f"；{len(recent_duplicates)} 条与 {RECENT_DUPLICATE_DAYS} 天内的记录重复，已跳过"
    return {"ok": True, **result, "message": message}


@_serialized_store_write
def confirm_queue(payload: dict[str, Any]) -> dict[str, Any]:
    """Mark pending rows approved after one explicit click.

    No typed phrase: the button itself is the human decision. Sending still
    goes through the separate delivery review panel. A row whose job was already
    sent within the last 30 days is held back and reported instead of approved.
    """
    mode = str(payload.get("mode") or "user")
    ids = payload.get("ids")
    if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids) or not ids:
        raise ApiError("请先勾选至少一条待确认岗位")
    store = get_store(mode)
    jobs = {str(job.get("id")): job for job in store.jobs()}
    pending_status = approval_queue.load_config()["approval"]["pending_status"]
    pending_ids = {str(row.get("id")) for row in store.queue() if row.get("status") == pending_status}
    not_pending = [item for item in ids if item not in pending_ids]
    ids = [item for item in ids if item in pending_ids]
    ids, held = _split_recent_duplicates(store, jobs, ids, include_queue=False)
    result = approval_queue.confirm(ids, store.files["queue"]) if ids else {
        "confirmed": [], "not_found": [], "status": "ready_for_manual_submission_only", "auto_submit": False,
    }
    result["recent_duplicates"] = held
    result["not_pending"] = not_pending
    store.log(
        "人工通过待确认岗位",
        f"非待确认跳过 {len(not_pending)} 条；通过 {len(result['confirmed'])} 条；"
        f"30 天内重复拦截 {len(held)} 条；auto_submit=false",
    )
    message = "已通过；发送前还会再让你复核一次"
    if held:
        message += f"；{len(held)} 条 {RECENT_DUPLICATE_DAYS} 天内已发送过，未通过"
    return {"ok": True, **result, "message": message}


def _delivered_job_ids(store: Store) -> set[str]:
    """Job ids that appear anywhere in deliveries.json (any item, any status)."""
    sent: set[str] = set()
    for batch in store.deliveries():
        for item in batch.get("items") or []:
            if isinstance(item, dict):
                job_id = str(item.get("job_id") or "").strip()
                if job_id:
                    sent.add(job_id)
    return sent


@_serialized_store_write
def delete_jobs(payload: dict[str, Any]) -> dict[str, Any]:
    """Soft-delete jobs from the pool: mark ``deleted_at`` instead of removing.

    Jobs are kept in jobs.json (deduplication by fingerprint on re-import
    depends on the record still existing) and are simply hidden from every
    reader via ``Store.jobs()``. A job that is already approved in the queue
    or has ever appeared in a delivery batch is protected and skipped; a
    pending queue row for a deleted job is removed along with it.
    """
    ids = payload.get("ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(item, str) and item.strip() for item in ids):
        raise ApiError("ids 必须是非空字符串列表")
    if len(ids) > 100:
        raise ApiError("一次最多删除 100 条")
    safe_ids: list[str] = []
    for item in ids:
        text = item.strip()
        if text not in safe_ids:
            safe_ids.append(text)

    store = get_store("user")
    rows = store.all_jobs()
    by_id = {str(row.get("id")): row for row in rows}
    queue = store.queue()
    queue_status = {str(row.get("id")): str(row.get("status") or "") for row in queue}
    delivered_ids = _delivered_job_ids(store)

    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    now = _now()
    for job_id in safe_ids:
        row = by_id.get(job_id)
        if row is None or row.get("deleted_at"):
            skipped.append({"id": job_id, "reason": "not_found"})
            continue
        if queue_status.get(job_id) == "approved":
            skipped.append({"id": job_id, "reason": "approved"})
            continue
        if job_id in delivered_ids:
            skipped.append({"id": job_id, "reason": "delivered"})
            continue
        row["deleted_at"] = now
        deleted.append(job_id)

    if deleted:
        store.set_jobs(rows)
        deleted_set = set(deleted)
        remaining_queue = [row for row in queue if str(row.get("id")) not in deleted_set]
        if len(remaining_queue) != len(queue):
            store.set_queue(remaining_queue)

    protected = sum(1 for item in skipped if item["reason"] in ("approved", "delivered"))
    missing = len(skipped) - protected
    message = f"已删除 {len(deleted)} 条；{protected} 条因已通过或已发送未删除"
    if missing:
        message += f"；{missing} 条已不在岗位池中"
    store.log("删除岗位", f"删除 {len(deleted)} 条，受保护跳过 {protected} 条，不存在 {missing} 条")
    return {"ok": True, "deleted": len(deleted), "skipped": skipped, "message": message}


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


def interview_ai_configured(mode: str) -> bool:
    """True only when the embedded OfferPilot config actually has an AI key."""
    try:
        state = get_offerpilot_state(mode)
    except Exception:
        return False
    return bool((state.get("ai") or {}).get("configured"))


def _complete_interview_plan(system_prompt: str, user_text: str, timeout: float = interview_chat.PLAN_TIMEOUT_SECONDS) -> str:
    """Call the configured external AI. Tests patch this; it never invents questions."""
    try:
        server = offerpilot_runtime.load_backend()
        config = offerpilot_runtime.effective_ai_config(server.load_config(server.CONFIG_PATH))
        from offerpilot.ai.credentials import AIRequestError, call_anthropic_text, get_ai_api_key
    except Exception as exc:
        raise interview_chat.PlanGenerationError("unavailable") from exc
    if not get_ai_api_key(config):
        raise interview_chat.PlanGenerationError("unavailable")
    prompt = f"{system_prompt.strip()}\n\n{user_text}"
    try:
        text = call_anthropic_text(
            prompt,
            config,
            max_tokens=4096,
            timeout=timeout,
            purpose="interview_plan",
        )
    except AIRequestError as exc:
        kind = "timeout" if "timeout" in str(getattr(exc, "kind", "") or "").lower() else "unavailable"
        raise interview_chat.PlanGenerationError(kind) from exc
    except TimeoutError as exc:
        raise interview_chat.PlanGenerationError("timeout") from exc
    except Exception as exc:
        kind = "timeout" if "timeout" in type(exc).__name__.lower() else "unavailable"
        raise interview_chat.PlanGenerationError(kind) from exc
    if not text or not str(text).strip():
        raise interview_chat.PlanGenerationError("unavailable")
    return str(text)


def _complete_interview_json(
    system_prompt: str,
    user_text: str,
    timeout: float,
    purpose: str,
    error_cls: type,
) -> str:
    """Non-streaming model call for debrief/drill. Tests patch the wrappers, not this."""
    try:
        runtime = offerpilot_runtime.load_backend()
        config = offerpilot_runtime.effective_ai_config(runtime.load_config(runtime.CONFIG_PATH))
        from offerpilot.ai.credentials import AIRequestError, call_anthropic_text, get_ai_api_key
    except Exception as exc:
        raise error_cls("unavailable") from exc
    if not get_ai_api_key(config):
        raise error_cls("unavailable")
    prompt = f"{system_prompt.strip()}\n\n{user_text}"
    try:
        text = call_anthropic_text(
            prompt,
            config,
            max_tokens=4096,
            timeout=timeout,
            purpose=purpose,
        )
    except AIRequestError as exc:
        kind = "timeout" if "timeout" in str(getattr(exc, "kind", "") or "").lower() else "unavailable"
        raise error_cls(kind) from exc
    except TimeoutError as exc:
        raise error_cls("timeout") from exc
    except Exception as exc:
        kind = "timeout" if "timeout" in type(exc).__name__.lower() else "unavailable"
        raise error_cls(kind) from exc
    if not text or not str(text).strip():
        raise error_cls("unavailable")
    return str(text)


def _complete_interview_debrief(
    system_prompt: str,
    user_text: str,
    timeout: float = interview_chat.DEBRIEF_TIMEOUT_SECONDS,
) -> str:
    return _complete_interview_json(
        system_prompt,
        user_text,
        timeout,
        "interview_debrief",
        interview_chat.DebriefGenerationError,
    )


def _complete_interview_drill(
    system_prompt: str,
    user_text: str,
    timeout: float = interview_chat.DRILL_TIMEOUT_SECONDS,
) -> str:
    return _complete_interview_json(
        system_prompt,
        user_text,
        timeout,
        "interview_drill",
        interview_chat.DrillGenerationError,
    )


def _public_material(row: dict[str, Any]) -> dict[str, Any]:
    kind = str(row.get("kind") or "")
    item = {
        "id": row.get("id"),
        "kind": kind,
        "title": row.get("title") or "",
        "created_at": row.get("created_at") or "",
    }
    if kind == "jingyan":
        item["jingyan_is_not_official"] = True
    return item


def interview_material_upload(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    kind = str(payload.get("kind") or "").strip()
    body = str(payload.get("body") or payload.get("text") or "").strip()
    if not body:
        raise ApiError(interview_chat.MSG_MATERIAL_EMPTY)
    if kind not in interview_chat.MATERIAL_KINDS:
        raise ApiError(interview_chat.MSG_MATERIAL_EMPTY)
    store = get_store(mode)
    digest = hashlib.sha256(f"{kind}\n{body}".encode("utf-8")).hexdigest()[:12]
    material_id = "mat-" + digest
    rows = store.interview_materials()
    existing = next((row for row in rows if str(row.get("id")) == material_id), None)
    if existing:
        return {
            "ok": True,
            "id": material_id,
            "kind": kind,
            "jingyan_is_not_official": kind == "jingyan",
            "materials": [_public_material(row) for row in rows],
            "message": "该材料已在本机列表中",
        }
    title = _clean_text(payload.get("title"), PROFILE_LIMITS["short"]) or body[:40]
    row = {
        "id": material_id,
        "kind": kind,
        "title": title,
        "body": body[:MAX_TEXT],
        "created_at": _now(),
        "jingyan_is_not_official": kind == "jingyan",
    }
    rows.append(row)
    store.set_interview_materials(rows)
    store.log("保存面试材料", f"{kind} {material_id}")
    return {
        "ok": True,
        "id": material_id,
        "kind": kind,
        "jingyan_is_not_official": kind == "jingyan",
        "materials": [_public_material(item) for item in rows],
        "message": "已保存到本机，下一场面试可勾选。",
    }


def _selected_interview_materials(store: Store, material_ids: Any) -> list[dict[str, Any]]:
    if not isinstance(material_ids, list):
        return []
    wanted = [str(item) for item in material_ids if str(item).strip()]
    if not wanted:
        return []
    by_id = {str(row.get("id")): row for row in store.interview_materials()}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ident in wanted:
        row = by_id.get(ident)
        if row and ident not in seen:
            selected.append(row)
            seen.add(ident)
    return selected


def _interview_job_display(store: Store, job_id: str) -> tuple[dict[str, str], str]:
    if not job_id:
        return {}, ""
    job = next((row for row in store.jobs() if str(row.get("id")) == job_id), None)
    if not job:
        return {}, ""
    display = {
        "company": str(job.get("company") or ""),
        "title": str(job.get("title") or ""),
    }
    jd_text = str(job.get("raw_text") or job.get("jd") or "")
    return display, jd_text


def _in_progress_interview(session: dict[str, Any] | None) -> bool:
    if not session:
        return False
    return str(session.get("user_status") or "") in {"preparing", "in_progress", "ready_to_end", "drilling"}


def interview_start(payload: dict[str, Any]) -> dict[str, Any]:
    mode = str(payload.get("mode") or "user")
    try:
        round_key = interview_chat.parse_round(payload.get("round"))
        duration_minutes = interview_chat.parse_duration(payload.get("duration_minutes"))
    except ValueError as exc:
        raise ApiError(str(exc)) from exc
    store = get_store(mode)
    profile = store.profile()
    if not interview_chat.profile_has_internship_or_project(profile):
        raise ApiError(interview_chat.MSG_NO_RESUME)
    if not interview_ai_configured(mode):
        raise ApiError(interview_chat.MSG_AI_MISSING)
    jd_text = str(payload.get("jd") or "").strip()
    job_id = str(payload.get("job_id") or "").strip()
    display, job_jd = _interview_job_display(store, job_id)
    if not jd_text:
        jd_text = job_jd
    materials = _selected_interview_materials(store, payload.get("material_ids"))
    generic_role = (not str(payload.get("jd") or "").strip()) and (not job_id or not display)
    resume_text = interview_chat.resume_evidence_text(profile)
    try:
        blueprint = interview_chat.plan_interview(
            round_key=round_key,
            duration_minutes=duration_minutes,
            resume_text=resume_text,
            jd_text=jd_text,
            materials=materials,
            complete=_complete_interview_plan,
        )
    except interview_chat.PlanGenerationError as exc:
        status = 503 if exc.kind in {"timeout", "unavailable"} else 400
        raise ApiError(interview_chat.MSG_PLAN_FAILED, status) from exc
    previous = store.interview_session()
    discarded = _in_progress_interview(previous)
    session_id = "iv-" + uuid.uuid4().hex[:12]
    has_jingyan = any(str(row.get("kind")) == "jingyan" for row in materials)
    session = {
        "id": session_id,
        "round": round_key,
        "duration_minutes": duration_minutes,
        "rules_text": interview_chat.build_rules_text(round_key, duration_minutes, generic_role),
        "generic_role": generic_role,
        "display": display,
        "user_status": "preparing",
        "remaining_seconds": duration_minutes * 60,
        "end_available": False,
        "time_up": False,
        "current_question": None,
        "turns": [],
        "blueprint": blueprint,
        "interview_started_at": None,
        "current_main_id": None,
        "followup_count": 0,
        "jingyan_is_not_official": True if has_jingyan else False,
        "material_ids": [str(row.get("id")) for row in materials],
        "job_id": job_id,
        "jd": jd_text[: interview_chat.MATERIAL_MODEL_LIMIT],
    }
    store.set_interview_session(session)
    store.log("开始文字面试规划", f"{round_key} {duration_minutes}分钟")
    public = interview_chat.public_session(session)
    public["ok"] = True
    public["discarded_in_progress"] = discarded
    if has_jingyan:
        public["jingyan_is_not_official"] = True
    public["message"] = "规则已准备，正在根据简历准备问题"
    return public


def _stream_interview_question(
    system_prompt: str,
    user_text: str,
    timeout: float = interview_chat.CHAT_TIMEOUT_SECONDS,
) -> Any:
    """Stream one interviewer question from the configured external AI.

    Tests patch this. It never invents a canned stem when the model fails.
    """
    try:
        runtime = offerpilot_runtime.load_backend()
        config = offerpilot_runtime.effective_ai_config(runtime.load_config(runtime.CONFIG_PATH))
        from offerpilot.ai.credentials import (
            AIRequestError,
            build_anthropic_client_kwargs,
            get_ai_api_key,
        )
    except Exception as exc:
        raise interview_chat.StreamGenerationError("unavailable") from exc
    if not get_ai_api_key(config):
        raise interview_chat.StreamGenerationError("unavailable")
    prompt = f"{system_prompt.strip()}\n\n{user_text}"
    ai_cfg = config.get("ai", {}) if isinstance(config, dict) else {}
    try:
        if ai_cfg.get("provider") == "openai_compatible":
            yield from _stream_openai_compatible_question(prompt, config, timeout)
            return
        import anthropic

        client = anthropic.Anthropic(**build_anthropic_client_kwargs(config))
        model = str(ai_cfg.get("model") or "claude-sonnet-4-6")
        with client.messages.stream(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        ) as stream:
            for text in stream.text_stream:
                if text:
                    yield str(text)
    except interview_chat.StreamGenerationError:
        raise
    except AIRequestError as exc:
        kind = "timeout" if "timeout" in str(getattr(exc, "kind", "") or "").lower() else "unavailable"
        raise interview_chat.StreamGenerationError(kind) from exc
    except TimeoutError as exc:
        raise interview_chat.StreamGenerationError("timeout") from exc
    except Exception as exc:
        kind = "timeout" if "timeout" in type(exc).__name__.lower() else "unavailable"
        raise interview_chat.StreamGenerationError(kind) from exc


def _stream_openai_compatible_question(prompt: str, config: dict[str, Any], timeout: float) -> Any:
    from offerpilot.ai.credentials import get_ai_api_key, get_ai_base_url, get_openai_compatible_model
    import httpx

    api_key = get_ai_api_key(config)
    base_url = get_ai_base_url(config)
    model = get_openai_compatible_model(config)
    if not api_key or not base_url:
        raise interview_chat.StreamGenerationError("unavailable")
    yielded = False
    try:
        with httpx.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.2,
                "stream": True,
            },
            timeout=timeout,
            trust_env=False,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                text = line.decode("utf-8") if isinstance(line, bytes) else str(line)
                if not text.startswith("data:"):
                    continue
                payload = text[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    body = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                choices = body.get("choices") if isinstance(body, dict) else None
                if not choices:
                    continue
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
                chunk = ""
                if isinstance(delta, dict):
                    chunk = str(delta.get("content") or "")
                if chunk:
                    yielded = True
                    yield chunk
    except TimeoutError as exc:
        raise interview_chat.StreamGenerationError("timeout") from exc
    except Exception as exc:
        kind = "timeout" if "timeout" in type(exc).__name__.lower() else "unavailable"
        raise interview_chat.StreamGenerationError(kind) from exc
    if not yielded:
        raise interview_chat.StreamGenerationError("empty")


def _load_interview_session(payload: dict[str, Any]) -> tuple[Store, dict[str, Any]]:
    mode = str(payload.get("mode") or "user")
    store = get_store(mode)
    session = store.interview_session()
    if not session:
        raise ApiError(interview_chat.MSG_NO_SESSION)
    wanted = str(payload.get("session_id") or payload.get("id") or "").strip()
    if wanted and wanted != str(session.get("id") or ""):
        raise ApiError(interview_chat.MSG_NO_SESSION)
    return store, session


def _session_materials(store: Store, session: dict[str, Any]) -> list[dict[str, Any]]:
    return _selected_interview_materials(store, session.get("material_ids") or [])


def _public_reply(session: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    interview_chat.apply_timing(session)
    public = interview_chat.public_session(session)
    public["ok"] = True
    if extra:
        public.update(extra)
    return public


def interview_reply(payload: dict[str, Any]) -> dict[str, Any]:
    store, session = _load_interview_session(payload)
    answer = str(payload.get("answer") or payload.get("text") or "").strip()
    if not answer:
        raise ApiError(interview_chat.MSG_EMPTY_ANSWER)
    if not interview_chat.awaiting_answer(session):
        raise ApiError(interview_chat.MSG_QUESTION_INCOMPLETE, 409)
    status = str(session.get("user_status") or "")
    if status not in {"in_progress", "preparing"}:
        raise ApiError(interview_chat.MSG_QUESTION_INCOMPLETE, 409)
    turns = list(session.get("turns") or [])
    turns.append({"role": "candidate", "text": answer})
    session["turns"] = turns
    session["last_answer"] = answer
    session["question_complete"] = False
    now = interview_chat._now()
    interview_chat.apply_timing(session, now)
    remaining = int(session.get("remaining_seconds") or 0)
    if remaining <= 0:
        session["time_up"] = True
        session["end_available"] = True
        session["need_next"] = False
        session["user_status"] = "ready_to_end"
        session["remaining_seconds"] = 0
    elif interview_chat.should_end_after_answer(session, answer):
        session["time_up"] = False
        session["end_available"] = True
        session["need_next"] = False
        session["user_status"] = "ready_to_end"
    else:
        session["time_up"] = False
        session["end_available"] = False
        session["need_next"] = True
        session["user_status"] = "in_progress"
    store.set_interview_session(session)
    store.log("提交面试回答", f"{len(answer)}字")
    public = _public_reply(session)
    public["need_next"] = bool(session.get("need_next"))
    public["end_available"] = bool(session.get("end_available"))
    public["time_up"] = bool(session.get("time_up"))
    public["remaining_seconds"] = int(session.get("remaining_seconds") or 0)
    public["message"] = "回答已记下" if public["need_next"] else "可以结束面试"
    return public


def interview_end(payload: dict[str, Any]) -> dict[str, Any]:
    store, session = _load_interview_session(payload)
    interview_chat.apply_timing(session)
    if str(session.get("user_status") or "") != "ready_to_end":
        raise ApiError(interview_chat.MSG_END_LOCKED, 409)
    try:
        card = interview_chat.generate_debrief(session, _complete_interview_debrief)
    except interview_chat.DebriefGenerationError as exc:
        raise ApiError(interview_chat.MSG_DEBRIEF_UNAVAILABLE, 503) from exc
    card_id = "ivdebrief-" + str(session.get("id") or uuid.uuid4().hex[:12])
    stored = {
        **card,
        "id": card_id,
        "session_id": session.get("id"),
        "created_at": _now(),
        "source": "interview-end",
    }
    rows = store.debriefs()
    rows.append(stored)
    store.set_debriefs(rows)
    session["user_status"] = "debriefed"
    session["end_available"] = False
    session["need_next"] = False
    session["debrief_id"] = card_id
    session["debrief_card"] = card
    store.set_interview_session(session)
    store.log("生成模拟面试复盘", card_id)
    public = interview_chat.public_session(session)
    public["ok"] = True
    public["card"] = {**card, "id": card_id, "session_id": session.get("id")}
    public["message"] = "复盘已生成；未写入定制简历"
    return public


def interview_drill(payload: dict[str, Any]) -> dict[str, Any]:
    store, session = _load_interview_session(payload)
    status = str(session.get("user_status") or "")
    if status not in interview_chat.DRILL_STATUSES:
        raise ApiError(interview_chat.MSG_DRILL_LOCKED, 409)
    item = interview_chat.find_drill_item(session, str(payload.get("item_id") or ""))
    if not item:
        raise ApiError(interview_chat.MSG_DRILL_ITEM)
    answer = str(payload.get("answer") or payload.get("text") or "")
    try:
        result = interview_chat.generate_drill(session, item, answer, _complete_interview_drill)
    except interview_chat.DrillGenerationError as exc:
        raise ApiError(interview_chat.MSG_DRILL_UNAVAILABLE, 503) from exc
    store.set_interview_session(session)
    store.log("模拟面试重练", f"{item['id']} attempt={result.get('attempt')}")
    public = interview_chat.public_session(session)
    public["ok"] = True
    public.update(result)
    public["user_status"] = session.get("user_status")
    return public


def _stream_decision(session: dict[str, Any], intent: str) -> dict[str, Any]:
    if intent == "retry":
        decision = interview_chat.pending_decision(session)
        if decision:
            return decision
        if str(session.get("user_status") or "") == "preparing":
            return interview_chat.first_question_decision(session)
        last = interview_chat.last_candidate_answer(session)
        decision = interview_chat.decide_next_move(session, last)
        if not decision:
            raise ApiError(interview_chat.MSG_PLAN_DONE, 409)
        return decision
    if intent == "first":
        return interview_chat.first_question_decision(session)
    last = interview_chat.last_candidate_answer(session)
    decision = interview_chat.decide_next_move(session, last)
    if not decision:
        raise ApiError(interview_chat.MSG_PLAN_DONE, 409)
    return decision


def interview_stream_events(payload: dict[str, Any]) -> Any:
    intent = str(payload.get("intent") or "").strip()
    if intent not in interview_chat.STREAM_INTENTS:
        raise ApiError(interview_chat.MSG_INTENT)
    store, session = _load_interview_session(payload)
    interview_chat.apply_timing(session)
    incomplete = bool((session.get("pending") or {}).get("incomplete")) if isinstance(session.get("pending"), dict) else False
    if not incomplete:
        turns = session.get("turns") or []
        last = turns[-1] if turns else None
        incomplete = isinstance(last, dict) and last.get("role") == "interviewer" and bool(last.get("incomplete"))
    remaining = int(session.get("remaining_seconds") or 0)
    if intent == "first" and str(session.get("user_status") or "") not in {"preparing", "in_progress"}:
        raise ApiError(interview_chat.MSG_NO_SESSION)
    if intent == "next":
        if remaining <= 0 and not incomplete:
            raise ApiError(interview_chat.MSG_TIME_UP, 409)
        if session.get("end_available") and not incomplete:
            if session.get("time_up") or remaining <= 0:
                raise ApiError(interview_chat.MSG_TIME_UP, 409)
            raise ApiError(interview_chat.MSG_PLAN_DONE, 409)
        if str(session.get("user_status") or "") not in {"in_progress"}:
            raise ApiError(interview_chat.MSG_NO_SESSION)
    if intent == "retry" and not incomplete and not interview_chat.pending_decision(session):
        if str(session.get("user_status") or "") == "preparing":
            intent = "first"
        else:
            raise ApiError(interview_chat.MSG_QUESTION_INCOMPLETE, 409)
    decision = _stream_decision(session, intent)
    session["pending"] = {
        "intent": intent,
        "move": decision.get("move"),
        "kind": decision.get("kind"),
        "main_id": decision.get("main_id"),
        "stem_intent": decision.get("stem_intent"),
        "gap_labels": decision.get("gap_labels") or [],
        "text": "",
        "incomplete": False,
    }
    store.set_interview_session(session)
    meta = {"session_id": session.get("id"), "move": decision.get("move")}
    yield ("meta", meta)
    resume_text = interview_chat.resume_evidence_text(store.profile())
    materials = _session_materials(store, session)
    system_prompt = interview_chat.load_chat_system_prompt()
    user_text = interview_chat.chat_user_payload(session, decision, resume_text, materials)
    collected = ""
    try:
        for piece in interview_chat.iter_question_tokens(
            system_prompt,
            user_text,
            _stream_interview_question,
            interview_chat.CHAT_TIMEOUT_SECONDS,
        ):
            collected += piece
            yield ("token", {"text": piece})
        if not collected.strip():
            raise interview_chat.StreamGenerationError("empty")
        interview_chat.commit_stream_done(session, decision, collected.strip())
        store.set_interview_session(session)
        yield ("done", {"text": collected.strip(), "session_id": session.get("id")})
    except interview_chat.StreamGenerationError:
        interview_chat.save_incomplete_question(session, decision, collected, intent)
        store.set_interview_session(session)
        yield (
            "error",
            {"message": interview_chat.stream_error_message(intent, str(session.get("user_status") or "preparing"))},
        )


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
    """Append one experience variant to the store shared with tools/variants.py.

    ``Store.variants()`` is ``web/data/user/variants.json``, the same JSON array
    the CLI writes, so a variant added from either side is visible to both.
    Existing response keys keep their meaning; ``variant_id``, ``created_at``
    and ``job_id`` are additive.
    """

    mode = str(payload.get("mode") or "user")
    project = _bounded_text(payload.get("project"), "项目名", 300).strip()
    text = _bounded_text(payload.get("text"), "经历原文", 20_000)
    if not project or not text.strip():
        raise ApiError("项目名和经历原文不能为空")
    job_id = variants.normalize_job_id(payload.get("job_id"))
    store = get_store(mode)
    store_path = store.files["variants"]
    rows = store.variants()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    quality = resume_quality.check_experience_text(text)
    for row in rows:
        if (
            variants.project_slug(row.get("project")) == variants.project_slug(project)
            and str(row.get("sha256") or "") == digest
            and variants.normalize_job_id(row.get("job_id")) == job_id
        ):
            return {
                "ok": False,
                "duplicate": True,
                "message": "相同经历变体已存在",
                "quality": quality,
                "variant_id": row.get("id"),
                "job_id": job_id,
            }
    record: dict[str, Any] = {
        "id": variants.record_id(project, text, job_id),
        "project": project,
        "created_at": _now(),
        "text": text,
        "sha256": digest,
    }
    if job_id:
        record["job_id"] = job_id
    rows.append(record)
    store.set_variants(rows)
    store.log("保存经历变体", project[:80])
    return {
        "ok": True,
        "message": "经历原文已保存；未修改 Master Resume",
        "quality": quality,
        "variant_id": record["id"],
        "created_at": record["created_at"],
        "job_id": job_id,
        "store": str(store_path),
    }


COMPARE_VARIANT_MASTER_LIMIT = 200_000


def _compare_master_text(payload: dict[str, Any]) -> tuple[str, str]:
    """The master wording to compare against: explicit text, else the resume.

    Read-only: the resume file is never written, and only its text is returned.
    """

    provided = payload.get("master_text")
    if provided is not None:
        return _bounded_text(provided, "母版原文", COMPARE_VARIANT_MASTER_LIMIT), "请求提供"
    source = _profile_cv_source()
    if source is None:
        raise ApiError(
            "未找到可对比的母版简历：workspace/resume.md 不存在，也没有已上传的 Markdown 简历",
            404,
        )
    path, label = source
    try:
        return path.read_text(encoding="utf-8-sig"), label
    except (OSError, UnicodeError) as exc:
        raise ApiError(f"{label} 无法按 UTF-8 文本读取：{exc.__class__.__name__}", 400) from exc


def compare_variant(payload: dict[str, Any]) -> dict[str, Any]:
    """Compare one stored variant's wording against the master resume, read-only.

    Accepts ``variant_id``, or ``project``/``text`` to pick the record, plus an
    optional ``master_text``.  Returns the paragraph differences verbatim; it
    never rewrites, generates or stores anything.
    """

    mode = str(payload.get("mode") or "user")
    store = get_store(mode)
    rows = store.variants()
    variant_id = _bounded_text(payload.get("variant_id") or "", "经历变体 id", 200).strip()
    project = _bounded_text(payload.get("project") or "", "项目名", 300).strip()
    job_id = variants.normalize_job_id(payload.get("job_id"))
    given_text = payload.get("text")
    inline_text = _bounded_text(given_text, "经历原文", 20_000) if given_text is not None else ""
    target: dict[str, Any] | None = None
    if variant_id:
        target = next((row for row in rows if str(row.get("id") or "") == variant_id), None)
    elif job_id:
        matches = [
            row for row in rows if variants.normalize_job_id(row.get("job_id")) == job_id
        ]
        matches.sort(key=lambda row: str(row.get("created_at") or ""))
        target = matches[-1] if matches else None
    elif project:
        matches = [
            row
            for row in rows
            if variants.project_slug(row.get("project")) == variants.project_slug(project)
        ]
        matches.sort(key=lambda row: str(row.get("created_at") or ""))
        target = matches[-1] if matches else None
    if target is None and not inline_text:
        raise ApiError(
            "未找到可对比的经历变体：请提供 variant_id、job_id，或 project 与 text", 404
        )
    variant_text = inline_text or str(target.get("text") or "")
    master_text, master_source = _compare_master_text(payload)
    result = variants.compare_variant(variant_text, master_text)
    return {
        "ok": True,
        "variant_id": (target or {}).get("id"),
        "project": (target or {}).get("project") or project or None,
        "job_id": variants.normalize_job_id((target or {}).get("job_id")),
        "master_source": master_source,
        **result,
    }


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
        "job_id": str(payload.get("job_id") or "web-dry-run")[:100],
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
        f"- 数据模式：{store.mode}（本机用户数据；产品只有这一个模式）",
        "- 运行边界：只监听 127.0.0.1；外部 AI、邮箱、飞书与平台会话由用户在本机配置并授权；投递只在人工确认并复核后小批量发送招呼语，不自动提交申请表单。",
        "",
        "## 自动检查",
        "",
        f"- 全量测试：{result['summary']}；failures={result['failures']}，errors={result['errors']}。",
        f"- 当前数据：岗位 {snap['scope']['all_jobs']} 条、待确认 {snap['kpis']['pending']} 条、邮件 {len(store.mails())} 封、复盘 {len(store.debriefs())} 份。",
        f"- 状态机：{', '.join(STATES)}。",
        "- 网页功能：JD 录入、静态 JSON 导入、审批队列、显式确认、30 天去重、话术草稿、状态跃迁、邮件解析、ICS、Mock、复盘、变体、ATS 静态检查、飞书 dry-run、测试、报告与导出。",
        "- 人工确认门：已按文档评分且没有明确不满足必备条件的岗位进入待确认；显式确认后才标记 approved；approved 只表示可人工投递。",
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
        "mode": store.mode,
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
    path = store.write_download(f"workspace-{store.mode}-export", text, ".json")
    store.log("导出本地数据", path.name)
    return {"ok": True, "download": path.name, "bytes": len(text.encode("utf-8")), "message": "本地数据已导出"}


# Local greeting drafts for ready jobs
#
# This is text generation only: it reuses tools/greeting.py, reads facts from
# profile.json (or workspace/resume.md) plus structured JD fields, and writes
# nothing except the ``greeting`` key of each matched job. It never calls a
# model or HTTP API, never opens a browser, and never sends anything.

GREETING_LINK_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _greeting_has_contact(text: str) -> bool:
    """True when a draft carries a phone, email, WeChat id, or a link."""
    if GREETING_LINK_RE.search(text):
        return True
    return any(pattern.search(text) for pattern in offerpilot_runtime.CONTACT_PATTERNS)


def generate_job_greetings(payload: dict[str, Any]) -> dict[str, Any]:
    """Draft a greeting for every ready job that has none yet.

    Only ``status == "ready"`` jobs with an empty ``greeting`` are considered
    (optionally narrowed by ``ids``). Facts come from the local profile/resume
    and structured JD fields; contacts and links are rejected rather than
    written. ``approval-queue.json`` and every other job field stay untouched.
    """
    raw_ids = payload.get("ids")
    wanted: set[str] | None = None
    if raw_ids is not None:
        if not isinstance(raw_ids, list) or not raw_ids:
            raise ApiError("ids 必须是非空岗位 id 数组")
        wanted = {_safe_id(item, "") for item in raw_ids}
        wanted.discard("")
        if not wanted:
            raise ApiError("ids 里没有有效的岗位 id")
    store = get_store("user")
    profile_text = profile_context_text(store.profile())
    cv_text = profile_text or (CV_PATH.read_text(encoding="utf-8-sig") if CV_PATH.is_file() else "")
    if not cv_text.strip():
        raise ApiError("个人资料与本地简历都为空，无法生成只含专业事实的招呼语", 409)
    jobs = store.jobs()
    generated = 0
    skipped: list[dict[str, str]] = []
    for job in jobs:
        job_id = str(job.get("id") or "")
        if str(job.get("status") or "") != "ready":
            continue
        if wanted is not None and job_id not in wanted:
            continue
        if str(job.get("greeting") or "").strip():
            continue
        draft = greeting.make_greeting(job, cv_text)
        text = str(draft.get("greeting") or "").strip()
        if not text:
            skipped.append({"id": job_id, "reason": "岗位与资料中没有可用的专业事实"})
            continue
        if _greeting_has_contact(text):
            skipped.append({"id": job_id, "reason": "草稿包含联系方式或链接，未写入"})
            continue
        job["greeting"] = text
        generated += 1
    if generated:
        store.set_jobs(jobs)
        store.log("生成岗位招呼语", f"{generated} 条；只生成，不发送")
    message = f"已为 {generated} 条岗位写入招呼语草稿；只生成，不发送"
    if skipped:
        message += f"；{len(skipped)} 条跳过"
    return {"ok": True, "generated": generated, "skipped": skipped, "message": message}


def get_ai_settings_api(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return AI settings for 08 设置. Never includes the API key."""
    try:
        return {"ok": True, **offerpilot_runtime.get_ai_settings()}
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc


def test_ai_connection_api(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Test the saved AI settings once. A failed test is a normal result, not an HTTP error."""
    try:
        return offerpilot_runtime.test_ai_connection(payload)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc


def save_ai_settings_api(payload: dict[str, Any]) -> dict[str, Any]:
    """Save AI settings from 08 设置. Validation errors become 400s."""
    try:
        settings = offerpilot_runtime.save_ai_settings(payload)
    except offerpilot_runtime.OfferPilotUnavailable as exc:
        raise ApiError(str(exc), 503) from exc
    except ValueError as exc:
        raise ApiError(str(exc), 400) from exc
    store = get_store("user")
    store.log("保存 AI 接口设置", f"服务 {settings['service']}；密钥{'已更新' if payload.get('api_key') else '未改动'}")
    return {"ok": True, "settings": settings, "message": "AI 接口设置已保存"}


ACTIONS = {
    "parse-jd": parse_jd,
    "import-jobs": import_jobs,
    "enqueue": enqueue,
    "confirm": confirm_queue,
    "delete-jobs": delete_jobs,
    "generate-job-greetings": generate_job_greetings,
    "prepare": prepare,
    "transition": transition,
    "parse-mail": parse_mail,
    "generate-ics": generate_ics,
    "worksheet": worksheet,
    "add-question": add_bank_question,
    "interview-start": interview_start,
    "interview-material-upload": interview_material_upload,
    "interview-reply": interview_reply,
    "interview-end": interview_end,
    "interview-drill": interview_drill,
    "debrief": debrief,
    "add-variant": add_variant,
    "compare-variant": compare_variant,
    "check-pdf": check_pdf,
    "dry-run": dry_run,
    "pipeline-event": ingest_pipeline_event,
    "save-profile": save_profile,
    "import-profile-cv": import_profile_cv,
    "offerpilot-start": start_offerpilot_task,
    "offerpilot-greet": start_offerpilot_greet,
    "offerpilot-deliver": start_offerpilot_deliver,
    "get-ai-settings": get_ai_settings_api,
    "test-ai-connection": test_ai_connection_api,
    "save-ai-settings": save_ai_settings_api,
    "offerpilot-import": import_offerpilot_jobs,
    "offerpilot-automate": run_offerpilot_pipeline,
    "offerpilot-reply": send_offerpilot_reply,
    "offerpilot-resume": upload_offerpilot_resume,
    "offerpilot-stop": lambda payload: stop_offerpilot_task(
        str(payload.get("task_id") or ""),
        str(payload.get("data_mode") or payload.get("mode") or "user"),
    ),
}
