"""In-process adapter for the embedded OfferPilot automation runtime.

This module imports the vendored OfferPilot package, points it at the
workbench's gitignored runtime directory, and exposes only the narrow
state/jobs/task operations the UI needs.

Imports are deliberately lazy: the rest of the workbench (and its test suite)
must keep working on a plain Python install without OfferPilot's optional
dependencies.  When the dependencies are missing, the automation panel reports
a clear, local error instead of taking the whole server down.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import inspect
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = Path(__file__).resolve().parent
VENDOR_SRC = ROOT / "vendor" / "offerpilot" / "src"
RUNTIME_MODES = ("demo", "user")
TASK_MODES = ("collect", "monitor", "full")
PACE_MULTIPLIERS = {"cautious": 3.0, "standard": 1.5, "fast": 1.0}
PACE_LABELS = {"cautious": "稳健", "standard": "标准", "fast": "快速"}
MAX_RESUME_BYTES = 5 * 1024 * 1024

_lock = threading.RLock()
_backend: Any | None = None
_backend_error: str | None = None
_backend_base_dir: Path | None = None
# Test seam: the HR conversation store's mode root (``web/data/<mode>``).
# Production leaves it None; tests point it at a temporary directory so no
# test ever reads or writes the real ``web/data/user/hr/conversations.json``.
_hr_store_root: Path | None = None
# Test seam: an in-memory model configuration shared by the workbench's agent
# features. Production leaves it None so config.yaml stays the only source.
workbench_model = None


def effective_ai_config(config: dict[str, Any]) -> dict[str, Any]:
    """Share the configured model in memory; never put its key in config.yaml."""
    if workbench_model is None:
        return config
    from offerpilot.ai.credentials import get_ai_api_key
    if get_ai_api_key(config):
        return config
    ai = workbench_model()
    return {**config, "ai": {**config.get("ai", {}), **ai}} if ai else config


class OfferPilotUnavailable(RuntimeError):
    """The vendored backend cannot be imported or initialized."""


def runtime_dir(mode: str) -> Path:
    if mode not in RUNTIME_MODES:
        raise ValueError("数据模式只能是 demo 或 user")
    return WEB_DIR / "data" / mode / "offerpilot"


def _ensure_user_runtime() -> Path:
    target = runtime_dir("user")
    target.mkdir(parents=True, exist_ok=True)
    (target / "data").mkdir(parents=True, exist_ok=True)
    (target / "data" / "resumes").mkdir(parents=True, exist_ok=True)
    if not (target / "config.yaml").is_file() and (VENDOR_SRC.parent / "config.example.yaml").is_file():
        shutil.copy2(VENDOR_SRC.parent / "config.example.yaml", target / "config.yaml")
    return target


def load_backend() -> Any:
    """Import the vendored package and point it at ``web/data/user/offerpilot``."""
    global _backend, _backend_error, _backend_base_dir
    with _lock:
        if _backend is not None:
            return _backend
        if _backend_error:
            raise OfferPilotUnavailable(_backend_error)
        vendor = str(VENDOR_SRC)
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        try:
            from offerpilot.web import server  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on local install
            _backend_error = (
                "岗位自动化 依赖未安装；请运行 "
                "`.venv/bin/python -m pip install -r requirements-offerpilot.txt` "
                f"（{type(exc).__name__}）"
            )
            raise OfferPilotUnavailable(_backend_error) from exc
        base_dir = _ensure_user_runtime()
        try:
            server.set_base_dir(base_dir)
            # set_base_dir only rebinds the server's own paths. Many vendored modules
            # call get_db() with no argument, which falls back to db.DB_PATH (a
            # cwd-relative ./data/offerpilot.db). Pin it to the runtime database so
            # scoring and collection read and write the same file.
            from offerpilot import db as offerpilot_db  # type: ignore
            offerpilot_db.DB_PATH = base_dir / "data" / "offerpilot.db"
        except Exception as exc:  # pragma: no cover - depends on local data
            _backend_error = f"岗位自动化 初始化失败：{type(exc).__name__}"
            raise OfferPilotUnavailable(_backend_error) from exc
        _backend = server
        _backend_base_dir = base_dir
        return server


def backend_available() -> tuple[bool, str | None]:
    try:
        load_backend()
        return True, None
    except OfferPilotUnavailable as exc:
        return False, str(exc)


def _safe_task(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = (
        "id", "mode", "label", "status", "created_at", "updated_at",
        "deadline_at", "stop_requested", "stop_reason", "error",
    )
    task = {key: value[key] for key in allowed if key in value}
    metrics = value.get("metrics")
    if isinstance(metrics, dict):
        task["metrics"] = {
            key: int(item)
            for key, item in metrics.items()
            if isinstance(key, str) and isinstance(item, (int, float)) and not isinstance(item, bool)
        }
    progress = value.get("progress")
    if isinstance(progress, dict):
        task["progress"] = progress
    return task


def _safe_preferences(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    fields = (
        "keywords", "cities", "salary", "deal_breakers", "jd_deal_breakers",
        "blocked_companies", "education", "recruitment_type", "allow_internship",
        "score_threshold", "platform_order", "max_pages",
    )
    return {key: value[key] for key in fields if key in value}


def _clean_job_ids(ids: Any, limit: int) -> list[str]:
    """Validate workbench-supplied runtime job ids without touching any path."""
    if not isinstance(ids, list) or not ids:
        raise ValueError("请先选择至少一条岗位")
    cleaned: list[str] = []
    for item in ids:
        text = str(item or "").strip()
        if not text or len(text) > 200 or any(ord(char) < 32 for char in text):
            raise ValueError("岗位 id 无效")
        if text not in cleaned:
            cleaned.append(text)
    if len(cleaned) > limit:
        raise ValueError(f"一次最多处理 {limit} 条岗位")
    return cleaned


def _style_issues(raw: Any) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item)[:120] for item in parsed[:5] if str(item).strip()]


def _safe_materials(raw: Any) -> dict[str, Any] | None:
    """Return a stored materials package, or ``None`` when absent or unreadable."""
    if isinstance(raw, dict):
        return raw or None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) and parsed else None


def get_greetings(ids: Any) -> dict[str, Any]:
    """Read greeting previews for runtime jobs (read-only, whitelisted fields)."""
    safe_ids = _clean_job_ids(ids, 50)
    try:
        server = load_backend()
        from offerpilot.db import query_jobs  # type: ignore

        db = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            rows, _total = query_jobs(db, deleted="active", job_ids=safe_ids)
        finally:
            db.close()
    except OfferPilotUnavailable as exc:
        return {"ok": False, "embedded": True, "error": str(exc), "greetings": []}
    except Exception as exc:
        return {"ok": False, "embedded": True, "error": f"招呼语读取失败：{type(exc).__name__}", "greetings": []}
    by_id = {str(row.get("id")): row for row in rows}
    greetings = []
    for job_id in safe_ids:
        row = by_id.get(job_id)
        if row is None:
            continue
        greeting = str(row.get("greeting") or "")[:600]
        selection = str(row.get("greeting_selection") or "")
        greetings.append({
            "id": job_id,
            "company": str(row.get("company") or "")[:200],
            "title": str(row.get("title") or "")[:200],
            "status": str(row.get("status") or "")[:40],
            "greeting": greeting,
            "selection": selection[:40],
            "style_issues": _style_issues(row.get("greeting_style_issues")),
            "reviewed": bool(row.get("greeting_reviewed_at")),
            "ready": bool(greeting.strip()) and selection != "pending",
            "materials": _safe_materials(row.get("materials")),
        })
    return {"ok": True, "embedded": True, "read_only": True, "greetings": greetings}


def start_greet_task(ids: Any) -> dict[str, Any]:
    """Start a greet-only runtime task. It generates text and never sends."""
    safe_ids = _clean_job_ids(ids, 10)
    server = load_backend()
    from offerpilot.ai.greeter import greeting_config_error  # type: ignore
    from offerpilot.db import add_history, query_jobs, update_job_status  # type: ignore
    from offerpilot.web.tasks import TaskAlreadyRunningError  # type: ignore

    config = server.load_config(server.CONFIG_PATH)
    error = greeting_config_error(config)
    if error:
        raise ValueError(error)
    profile = config.get("profile") or {}
    if profile.get("ai_greeting_enabled", True) is not False:
        if not server.get_ai_api_key(config):
            raise ValueError("请先在配置页填写 AI 服务密钥，再生成招呼语")
        if not _resume_info(server, config).get("available"):
            raise ValueError("请先在采集页上传评分简历，再生成招呼语")

    db = server.get_db(server.DATA_DIR / "offerpilot.db")
    try:
        rows, _total = query_jobs(db, deleted="active", job_ids=safe_ids)
    finally:
        db.close()
    found = {str(row.get("id")): str(row.get("status") or "") for row in rows}
    missing = [job_id for job_id in safe_ids if job_id not in found]
    if missing:
        raise ValueError("部分岗位不在本机采集结果中：" + "、".join(missing[:3]))
    terminal = {"sent", "replied", "resume_sent", "needs_resume", "follow_up_sent"}
    finished = [job_id for job_id in safe_ids if found[job_id] in terminal]
    if finished:
        raise ValueError("部分岗位已投递，不能重新生成招呼语：" + "、".join(finished[:3]))
    promotable = {"pending", "scored", "new", "filtered", "ready", "approved", "error"}
    blocked = [job_id for job_id in safe_ids if found[job_id] not in promotable]
    if blocked:
        raise ValueError("部分岗位当前状态不支持生成招呼语：" + "、".join(blocked[:3]))

    def _mark_ready() -> None:
        conn = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            for job_id in safe_ids:
                update_job_status(conn, job_id, "ready")
                add_history(conn, job_id, "workbench_greet", "工作台请求生成招呼语")
        finally:
            conn.close()

    with server.job_mutation_lock:
        try:
            task = server.task_runner.start(
                "greet",
                {**config, "_workbench_job_ids": safe_ids, "_agent_workflow": True},
                before_start=_mark_ready,
            )
        except TaskAlreadyRunningError as exc:
            raise ValueError(str(exc)) from exc
    return {"task": _safe_task(task), "requested": len(safe_ids)}


DELIVERY_SENT_STATUSES = frozenset(
    {"sent", "replied", "resume_sent", "needs_resume", "follow_up_sent"}
)


def start_deliver_task(ids: Any) -> dict[str, Any]:
    """Send reviewed greetings for the selected jobs.

    The runtime keeps its own send window, daily quota, random interval,
    backoff and risk lock; this wrapper only adds the workbench's approval
    gate and never forces any of those guards.
    """
    safe_ids = _clean_job_ids(ids, 10)
    server = load_backend()
    from offerpilot.db import (  # type: ignore
        add_history,
        get_active_platform_safety_lock,
        query_jobs,
        update_job_status,
    )
    from offerpilot.throttle import SendWindowChecker  # type: ignore
    from offerpilot.web.tasks import TaskAlreadyRunningError  # type: ignore

    config = server.load_config(server.CONFIG_PATH)
    throttle = config.get("throttle") or {}
    window = SendWindowChecker(throttle.get("send_windows", ["09:00-16:00"]))
    if not window.is_active():
        raise ValueError("当前不在发送时间窗口内；" + window.next_window_info())

    db = server.get_db(server.DATA_DIR / "offerpilot.db")
    try:
        rows, _total = query_jobs(db, deleted="active", job_ids=safe_ids)
        lock = get_active_platform_safety_lock(db)
    finally:
        db.close()
    if lock:
        raise ValueError("平台风险冷却尚未结束，暂不能发送")
    by_id = {str(row.get("id")): row for row in rows}
    missing = [job_id for job_id in safe_ids if job_id not in by_id]
    if missing:
        raise ValueError("部分岗位不在本机采集结果中：" + "、".join(missing[:3]))
    finished = [
        job_id
        for job_id in safe_ids
        if str(by_id[job_id].get("status") or "") in DELIVERY_SENT_STATUSES
    ]
    if finished:
        raise ValueError("部分岗位已经投递，不能重复发送：" + "、".join(finished[:3]))
    not_ready = [
        job_id
        for job_id in safe_ids
        if str(by_id[job_id].get("status") or "") not in {"ready", "approved"}
    ]
    if not_ready:
        raise ValueError("部分岗位尚未准备好发送：" + "、".join(not_ready[:3]))
    no_greeting = [
        job_id for job_id in safe_ids if not str(by_id[job_id].get("greeting") or "").strip()
    ]
    if no_greeting:
        raise ValueError("部分岗位还没有招呼语：" + "、".join(no_greeting[:3]))
    pending_review = [
        job_id
        for job_id in safe_ids
        if str(by_id[job_id].get("greeting_selection") or "") == "pending"
    ]
    if pending_review:
        raise ValueError("部分岗位的招呼语仍在复核中：" + "、".join(pending_review[:3]))

    def _mark_approved() -> None:
        conn = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            for job_id in safe_ids:
                update_job_status(conn, job_id, "approved")
                add_history(conn, job_id, "workbench_deliver", "工作台确认发送")
        finally:
            conn.close()

    with server.job_mutation_lock:
        try:
            task = server.task_runner.start(
                "deliver",
                {
                    **config,
                    "_workbench_job_ids": safe_ids,
                    "_workbench_skip_greeting": True,
                    "_agent_workflow": True,
                },
                before_start=_mark_approved,
            )
        except TaskAlreadyRunningError as exc:
            raise ValueError(str(exc)) from exc
    return {"task": _safe_task(task), "requested": len(safe_ids)}


def _resume_info(server: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Return the active resume metadata without exposing its text."""
    from offerpilot.web.resume_info import (  # type: ignore
        is_default_resume_placeholder,
        load_resume_info,
        resolve_resume_filesystem_path,
    )

    raw = (config.get("profile") or {}).get("resume_path")
    if is_default_resume_placeholder(raw):
        return {"available": False, "filename": None, "size_label": None, "uploaded_at": None}
    path = resolve_resume_filesystem_path(str(raw), server.BASE_DIR)
    info = load_resume_info(path) if path.is_file() else None
    if not info:
        return {"available": False, "filename": None, "size_label": None, "uploaded_at": None}
    return {
        "available": True,
        "filename": info.get("filename"),
        "size_label": info.get("size_label"),
        "uploaded_at": info.get("uploaded_at"),
        "has_original_pdf": bool(info.get("has_original_pdf")),
    }


def save_resume(filename: str, content: bytes) -> dict[str, Any]:
    """Store an uploaded resume and point the embedded runtime at it.

    Accepts Markdown, DOCX and text-layer PDF; DOCX/PDF are converted to the
    Markdown file the scoring agent reads.  The upload never leaves this
    machine and is written under ``web/data/user/offerpilot/data/resumes``.
    """
    if not filename or not str(filename).strip():
        raise ValueError("缺少简历文件名")
    if not content:
        raise ValueError("简历文件为空")
    if len(content) > MAX_RESUME_BYTES:
        raise ValueError("简历文件超过 5 MB 上限")
    server = load_backend()
    from offerpilot.config import load_config, save_config  # type: ignore
    from offerpilot.web.resume_names import (  # type: ignore
        resolve_active_resume_path,
        select_resume_markdown_filename,
    )
    from offerpilot.web.resume_original import (  # type: ignore
        upload_keeps_original_pdf,
        write_resume_artifacts,
    )
    from offerpilot.web.resume_upload import prepare_resume_content  # type: ignore

    safe_name, stored = prepare_resume_content(str(filename), content)
    server.RESUME_DIR.mkdir(parents=True, exist_ok=True)
    config = load_config(server.CONFIG_PATH)
    active_path = resolve_active_resume_path(
        (config.get("profile") or {}).get("resume_path") or None,
        server.BASE_DIR,
    )
    final_name = select_resume_markdown_filename(server.RESUME_DIR, safe_name, stored, active_path)
    destination = server.RESUME_DIR / final_name
    original_pdf = content if upload_keeps_original_pdf(str(filename)) else None
    write_resume_artifacts(destination, stored, original_pdf_bytes=original_pdf)
    config.setdefault("profile", {})["resume_path"] = str(destination.resolve())
    save_config(config, server.CONFIG_PATH)
    return {"filename": final_name, **_resume_info(server, config)}


def get_state() -> dict[str, Any]:
    """Return the same credential-free shape the old HTTP bridge returned."""
    try:
        server = load_backend()
        config = server.load_config(server.CONFIG_PATH)
        status = server.task_runner.status()
        capabilities = {
            "collect_without_ai": True,
            "evaluate_with_local_agent_without_ai": True,
            "monitor_without_ai": True,
            "start_full_flow": True,
            "human_confirmation_before_delivery": True,
        }
        payload = {
            "api_version": server.AGENT_API_VERSION,
            "preferences": server.agent_preferences(config),
            "ai": {"configured": bool(server.get_ai_api_key(config))},
            "capabilities": capabilities,
            "task": status.get("active"),
            "last_task": status.get("last_task"),
            "resume": _resume_info(server, config),
        }
    except OfferPilotUnavailable as exc:
        return {"ok": False, "embedded": True, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "embedded": True, "error": f"岗位自动化 状态读取失败：{type(exc).__name__}"}
    return {
        "ok": True,
        "embedded": True,
        "api_version": payload.get("api_version"),
        "base_url": "embedded://offerpilot",
        "preferences": _safe_preferences(payload.get("preferences")),
        "ai": {"configured": bool((payload.get("ai") or {}).get("configured"))},
        "capabilities": capabilities,
        "task": _safe_task(payload.get("task")),
        "last_task": _safe_task(payload.get("last_task")),
        "resume": payload.get("resume") if isinstance(payload.get("resume"), dict) else {"available": False},
    }


def get_jobs(limit: int = 100) -> dict[str, Any]:
    """Read the vendored SQLite job pool without an HTTP hop."""
    try:
        server = load_backend()
    except OfferPilotUnavailable as exc:
        return {"ok": False, "embedded": True, "error": str(exc), "jobs": [], "count": 0, "limit": limit}
    try:
        from offerpilot.db import query_jobs, serialize_job  # type: ignore

        db = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            rows, _total = query_jobs(db, deleted="active", limit=min(max(int(limit), 1), 500), offset=0)
        finally:
            db.close()
    except Exception as exc:
        return {"ok": False, "embedded": True, "error": f"岗位自动化 岗位读取失败：{type(exc).__name__}", "jobs": [], "count": 0, "limit": limit}
    allowed = (
        "id", "title", "company", "salary", "city", "experience", "education",
        "recruitment_type", "status", "score", "score_coverage",
        "mandatory_status", "hiring_status", "source_platform",
        "created_at", "updated_at",
    )
    jobs = []
    for row in rows:
        record = serialize_job(dict(row))
        job = {
            key: (record[key][:500] if isinstance(record[key], str) else record[key])
            for key in allowed
            if key in record and (record[key] is None or isinstance(record[key], (str, int, float, bool)))
        }
        try:
            conditions = json.loads(record.get("mandatory_conditions") or "[]")
        except (TypeError, ValueError):
            conditions = []
        job["mandatory_conditions"] = conditions if isinstance(conditions, list) else []
        jobs.append(job)
    return {"ok": True, "embedded": True, "source": "offerpilot", "read_only": True, "jobs": jobs, "count": len(jobs), "limit": limit}


def _task_options(mode: str, config: dict[str, Any], raw_options: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build the collection request without mutating the saved config.

    ``raw_options`` comes from the workbench form and is already shape-checked
    by ``web/backend.py``.  Keeping it as an in-memory override means the UI
    can offer a real search form without writing config.yaml behind the user's
    back.
    """
    if mode not in {"collect", "full"}:
        return None
    from offerpilot.collection.capabilities import platform_supports  # type: ignore
    from offerpilot.collection.orchestrator import normalize_collection_options  # type: ignore

    options = normalize_collection_options(config, raw_options)
    pace = str((raw_options or {}).get("pace") or "cautious").strip().lower()
    options["pace"] = pace if pace in PACE_MULTIPLIERS else "cautious"
    # Resume is a hard prerequisite for collect/full, so scoring is always on.
    options["auto_score"] = True
    if mode == "full":
        collection_only = [
            platform for platform in options["platform_order"]
            if not platform_supports(platform, "deliver")
        ]
        if collection_only:
            raise ValueError("智联、前程无忧和猎聘只能单独采集，不能进入投递全流程")
        options["auto_score"] = True
    return options


def _options_summary(mode: str, options: dict[str, Any] | None) -> dict[str, Any]:
    if not options:
        return {
            "mode": mode,
            "platform_order": [],
            "keywords": [],
            "cities": [],
            "max_pages": {},
            "auto_score": False,
            "pace": None,
            "pace_label": None,
            "delay_seconds": None,
        }
    platforms = options.get("platforms") if isinstance(options.get("platforms"), dict) else {}
    keywords: list[str] = []
    cities: list[str] = []
    max_pages: dict[str, int] = {}
    for platform in options.get("platform_order", []):
        value = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        keywords.extend(str(item) for item in value.get("keywords", []) if str(item).strip())
        cities.extend(str(item) for item in value.get("cities", []) if str(item).strip())
        try:
            max_pages[platform] = int(value.get("max_pages", 1))
        except (TypeError, ValueError):
            max_pages[platform] = 1
    pace = str(options.get("pace") or "cautious")
    multiplier = PACE_MULTIPLIERS.get(pace, PACE_MULTIPLIERS["cautious"])
    return {
        "mode": mode,
        "platform_order": list(options.get("platform_order", [])),
        "keywords": list(dict.fromkeys(keywords)),
        "cities": list(dict.fromkeys(cities)),
        "max_pages": max_pages,
        "auto_score": bool(options.get("auto_score")),
        "pace": pace,
        "pace_label": PACE_LABELS.get(pace, PACE_LABELS["cautious"]),
        "delay_seconds": [round(2.0 * multiplier, 1), round(5.0 * multiplier, 1)],
    }


def _option_cities(options: dict[str, Any] | None) -> list[str]:
    """Collect this run's search cities across the selected platforms."""
    if not isinstance(options, dict):
        return []
    platforms = options.get("platforms") if isinstance(options.get("platforms"), dict) else {}
    cities: list[str] = []
    for platform in options.get("platform_order", []):
        value = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        for item in value.get("cities", []) or []:
            text = str(item or "").strip()
            if text and text not in cities:
                cities.append(text)
    return cities


def _with_collection_cities(config: dict[str, Any], options: dict[str, Any] | None) -> dict[str, Any]:
    """Point the in-memory profile at this run's search cities.

    The quick-score city gate reads ``profile.target_cities``; the search form
    reads the per-platform cities.  They must agree, so a task started with an
    explicit city list also overrides the profile for that run only.  The saved
    ``config.yaml`` is never written and the workbench profile is not read.
    """
    cities = _option_cities(options)
    if not cities:
        return config
    profile = config.get("profile") if isinstance(config.get("profile"), dict) else {}
    return {**config, "profile": {**profile, "target_cities": cities}}


RESUME_REQUIRED_MESSAGE = "请先上传评分简历（.md / .docx / .pdf）；没有简历无法评分，也无法生成招呼语"


def _resume_blocker(server: Any, mode: str, config: dict[str, Any]) -> str | None:
    """Collect/full tasks need an uploaded resume; monitor does not."""
    if mode not in {"collect", "full"}:
        return None
    return None if _resume_info(server, config).get("available") else RESUME_REQUIRED_MESSAGE


def preflight(mode: str, raw_options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the same pre-start checks as ``start_task`` without starting anything."""
    if mode not in TASK_MODES:
        raise ValueError("仅允许 collect、monitor 或 full；发送任务不开放直接调用")
    server = load_backend()
    from offerpilot.config import load_config  # type: ignore
    from offerpilot.web.preflight import collect_preflight_checks, error_messages  # type: ignore

    config = load_config(server.CONFIG_PATH)
    try:
        options = _task_options(mode, config, raw_options)
    except ValueError as exc:
        return {
            "ok": False,
            "checks": [],
            "messages": [str(exc)],
            "summary": _options_summary(mode, None),
        }
    config = _with_collection_cities(config, options)
    summary = _options_summary(mode, options)
    resume_blocker = _resume_blocker(server, mode, config)
    if resume_blocker:
        return {
            "ok": False,
            "checks": [{
                "id": "resume_required",
                "title": "评分简历",
                "status": "error",
                "message": resume_blocker,
                "detail": "在上方「评分简历」处上传后，再检查环境。",
                "action": "resume",
            }],
            "messages": [resume_blocker],
            "summary": summary,
        }
    # A running task owns the browser lock.  The upstream check reports that as
    # a generic "browser connection failed", so answer with the real reason
    # before running any browser diagnostics.
    active = _active_task(server)
    if active:
        return _busy_preflight(summary, active)
    checks = collect_preflight_checks(mode, config, options)
    messages = [*server._preflight_messages(mode, config, options), *error_messages(checks)]
    return {
        "ok": not messages,
        "checks": checks,
        "messages": messages,
        "summary": summary,
    }


def _active_task(server: Any) -> dict[str, Any] | None:
    try:
        status = server.task_runner.status() or {}
    except Exception:
        return None
    active = status.get("active")
    return active if isinstance(active, dict) else None


def _busy_preflight(summary: dict[str, Any], active: dict[str, Any]) -> dict[str, Any]:
    label = str(active.get("label") or active.get("mode") or "当前任务")
    message = f"任务「{label}」正在使用浏览器"
    detail = "请等待它结束，或先在下方停止任务，再重新检查环境。"
    return {
        "ok": False,
        "checks": [{
            "id": "browser_busy",
            "title": "浏览器占用",
            "status": "error",
            "message": message,
            "detail": detail,
            "action": "browser",
        }],
        "messages": [f"{message}；{detail}"],
        "summary": summary,
    }


def start_task(mode: str, raw_options: dict[str, Any] | None = None) -> dict[str, Any]:
    if mode not in TASK_MODES:
        raise ValueError("仅允许 collect、monitor 或 full；发送任务不开放直接调用")
    server = load_backend()
    from offerpilot.config import load_config  # type: ignore
    from offerpilot.web.preflight import collect_preflight_checks, error_messages  # type: ignore

    config = load_config(server.CONFIG_PATH)
    resume_blocker = _resume_blocker(server, mode, config)
    if resume_blocker:
        raise ValueError(resume_blocker)
    options = _task_options(mode, config, raw_options)
    config = _with_collection_cities(config, options)
    checks = collect_preflight_checks(mode, config, options)
    messages = [*server._preflight_messages(mode, config, options), *error_messages(checks)]
    if messages:
        raise ValueError("请先处理启动前检查：" + "；".join(messages[:5]))
    extra: dict[str, Any] = {}
    if options is not None:
        pace = str(options.get("pace") or "cautious")
        collection = dict(config.get("collection") or {})
        collection["collection_delay_multiplier"] = PACE_MULTIPLIERS.get(pace, PACE_MULTIPLIERS["cautious"])
        extra = {"_collection_options": options, "collection": collection}
    if mode == "full":
        # The workbench confirmation gate lives in the approval queue and its
        # delivery popup, so the runtime full flow stops right after scoring
        # instead of waiting on the embedded dashboard's own confirmation.
        extra["_workbench_auto_pipeline"] = True
    with server.job_mutation_lock:
        task = server.task_runner.start(mode, {**config, **extra, "_agent_workflow": True})
    return {
        "task": _safe_task(task),
        "checks": checks,
        "summary": _options_summary(mode, options),
        "auto_pipeline": mode == "full",
        "policy": {
            "auto_score": bool(options.get("auto_score")) if options is not None else None,
            "delivery": "full 工作流会在发送前暂停，必须经现有人工确认流程继续",
        },
    }


def stop_task(task_id: str) -> dict[str, Any]:
    server = load_backend()
    return _safe_task(server.task_runner.stop(task_id)) or {}


def reset_runtime(mode: str = "demo") -> None:
    """Remove a demo runtime so reset-demo cannot keep stale jobs."""
    if mode != "demo":
        raise ValueError("只能重置演示运行时")
    target = runtime_dir(mode)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


# --- HR conversations: read-only list/thread plus one confirmed reply ---------
#
# Conversation text stays in this process only.  No message ever reaches
# jobs.json, deliveries.json, approval-queue.json or any other file; the cache
# below is the only place a thread is held, and it expires after ten minutes.

CONVERSATIONS_TTL_SECONDS = 600
MAX_REPLY_CHARS = 1000
REPLY_CONFIRM_PHRASE = "确认发送这条回复"
DEFAULT_SEND_WINDOW = "09:00-16:00"

# Per-platform read budgets.  Reads stay serial (one platform at a time); the
# budget is checked before and after each CDP call and passed down as that
# call's timeout, so a slow platform can never pin the browser gate and hide
# the next one.
CHAT_LIST_TIMEOUT_SECONDS = 60.0
CHAT_THREAD_TIMEOUT_SECONDS = 30.0
CHAT_CALL_TIMEOUT_SECONDS = 20.0
CHAT_READ_TIMEOUT_ERROR = "读取超时"


class ChatReadTimeout(RuntimeError):
    """One platform's chat read used up its budget."""


class _ChatReadDeadline:
    """A wall-clock budget for one platform read.

    The reader runs in the caller's thread and never abandons a worker: every
    browser call gets ``min(remaining, CHAT_CALL_TIMEOUT_SECONDS)`` as its own
    timeout, so a timeout returns at the CDP layer and the browser gate is free
    again before the next platform starts.
    """

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + max(0.0, float(seconds))

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def check(self) -> None:
        if self.expired():
            raise ChatReadTimeout(CHAT_READ_TIMEOUT_ERROR)

    def call_timeout(self) -> float:
        self.check()
        return max(0.1, min(self.remaining(), CHAT_CALL_TIMEOUT_SECONDS))


def _accepts_timeout(callable_obj: Any) -> bool:
    try:
        parameters = inspect.signature(callable_obj).parameters
    except (TypeError, ValueError):
        return False
    return "timeout" in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _chat_evaluate(monitor: Any, target_id: str, script: str, deadline: "_ChatReadDeadline") -> Any:
    """Evaluate one script within the read's budget.

    The budget is re-checked after every call: an answer that only arrives once
    the budget is gone was too late for this read and is reported as
    ``读取超时``, never as a success.  A ``None`` result with the budget still
    running is left to the caller's normal unreadable-page error.
    """
    timeout = deadline.call_timeout()
    if _accepts_timeout(monitor.evaluate):
        result = monitor.evaluate(target_id, script, timeout=timeout)
    else:  # older browser doubles without the timeout keyword
        result = monitor.evaluate(target_id, script)
    deadline.check()
    return result


def _chat_timeout_result(platform: str) -> dict[str, Any]:
    return {
        "ok": False,
        "available": False,
        "platform": platform,
        "conversations": [],
        "count": 0,
        "error": CHAT_READ_TIMEOUT_ERROR,
    }

_conversation_salt = os.urandom(16)
_conversation_cache: dict[str, dict[str, Any]] = {}
# Last successful listing time per platform.  A single-platform read refreshes
# only its own platform, so another platform's entries keep their own expiry.
_conversation_listed_at_by_platform: dict[str, float] = {}
# Most recent listing time overall, kept for the expiry test and older callers.
_conversation_listed_at: float | None = None
_conversation_cache_lock = threading.RLock()

# Read-only HR chat entry points. BOSS keeps using the monitor's own chat_url;
# the other three are fixed public web entry points, never edited per user.
CHAT_PLATFORMS = ("boss", "zhilian", "51job", "liepin")
PLATFORM_CHAT_LABELS = {
    "boss": "BOSS 直聘",
    "zhilian": "智联招聘",
    "51job": "前程无忧",
    "liepin": "猎聘",
}
PLATFORM_CHAT_URLS = {
    "zhilian": "https://i.zhaopin.com/im?refcode=4017",
    "51job": "https://chat.51job.com/",
    # The "我的沟通" drawer sits on the right of the www search page, and the
    # message list loads once it is logged in.  No query string: the entry is
    # fixed, and nothing is read from or written to the URL.
    "liepin": "https://www.liepin.com/zhaopin/",
}

JS_ZHILIAN_CHAT_LIST = r"""
(() => {
    const pick = (el, sel) => {
        const node = el.querySelector(sel);
        return node ? (node.innerText || '').trim() : '';
    };
    const rows = Array.from(document.querySelectorAll('.im-session-item')).map((el) => {
        const lines = (el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean);
        let company = pick(el, '.im-session-item__company-name');
        let hr_name = pick(el, '.im-session-item__name');
        if (!hr_name) hr_name = lines[0] || '';
        if (!company) {
            const box = el.querySelector('.im-session-item__company');
            company = box ? (box.innerText || '').split('\n')[0].trim() : '';
        }
        if (company === hr_name) company = '';
        return {
            company: company,
            hr_name: hr_name,
            hr_title: pick(el, '.im-session-item__job'),
            last_message: pick(el, '.im-session-item__preview-text'),
            last_message_at: pick(el, '.im-session-item__time'),
            has_unread: !!el.querySelector('.im-session-item__badge'),
            has_reply: !!el.querySelector('.im-session-item__preview-text'),
        };
    });
    return {available: true, rows: rows};
})()
"""

JS_ZHILIAN_OPEN_THREAD = r"""
(() => {
    const hr = __HR_NAME__;
    const company = __COMPANY__;
    const items = Array.from(document.querySelectorAll('.im-session-item'));
    const text = (el) => (el.innerText || '');
    let target = items.find((el) => text(el).includes(hr) && (!company || text(el).includes(company)));
    if (!target) target = items.find((el) => hr && text(el).includes(hr));
    if (!target) return {available: false, reason: '未找到该会话'};
    target.click();
    return {available: true};
})()
"""

JS_ZHILIAN_THREAD = r"""
(() => {
    const rows = Array.from(document.querySelectorAll('.im-message')).map((el) => {
        const tip = el.classList.contains('im-message--tip');
        const me = !!el.querySelector('.im-message__bubble--me');
        const body = el.querySelector('.im-message__bubble-inner');
        const text = ((body ? body.innerText : el.innerText) || '').trim();
        return {sender: tip ? 'system' : (me ? 'me' : 'hr'), text: text};
    }).filter((row) => row.text);
    return {available: true, rows: rows};
})()
"""

JS_LIEPIN_ENSURE_DRAWER = r"""
(() => {
    if (document.querySelector('#im-basic-contact')) return {available: true};
    const entry = document.querySelector('.im-ui-basic-entry');
    if (!entry) return {available: false, reason: '未找到猎聘消息入口'};
    entry.click();
    return {available: true, opened: true};
})()
"""

# The search page (https://www.liepin.com/zhaopin/) shows the "我的沟通" drawer
# on the right once logged in.  The drawer may already be expanded by default:
# if its root (#im-basic-contact) is present, return at once and never click
# again, because a second click could collapse the drawer.  Otherwise prefer the
# known entry class, then a visible short 我的沟通/我的消息 text; never click an
# unrelated "消息" navigation item.
JS_LIEPIN_ENSURE_DRAWER_WWW = r"""
(() => {
    if (document.querySelector('#im-basic-contact')) return {available: true, opened: false, branch: 'expanded'};
    const known = document.querySelector('.im-ui-basic-entry');
    if (known) { known.click(); return {available: true, opened: true, branch: 'clicked_entry'}; }
    const markers = ['我的沟通', '我的消息'];
    const nodes = Array.from(document.querySelectorAll('a, button, div[role="button"], span, li'));
    const hit = nodes.find((el) => {
        const text = (el.innerText || el.textContent || '').replace(/\s+/g, '');
        if (!text || text.length > 12) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        const visible = rect.width > 0 && rect.height > 0
            && style.display !== 'none' && style.visibility !== 'hidden';
        return visible && markers.some((m) => text.includes(m));
    });
    if (!hit) return {available: false, reason: '未找到猎聘「我的沟通」入口'};
    hit.click();
    return {available: true, opened: true, branch: 'clicked_text_entry'};
})()
"""

JS_LIEPIN_CHAT_LIST = r"""
(() => {
    const drawer = document.querySelector('#im-basic-contact');
    if (!drawer) return {available: false, reason: '未找到猎聘聊天抽屉'};
    const root = drawer.querySelector('.im-ui-contacts-wrap') || drawer;
    const items = Array.from(root.querySelectorAll('.im-ui-contact-list-item'));
    // matched: how many row nodes the selector found, so an empty list can be told
    // apart from a selector that matched nothing on this page.
    const matched = items.length;
    const lines = (el) => (el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean);
    const pick = (el, selectors) => {
        for (const sel of selectors) {
            const node = el.querySelector(sel);
            if (node && (node.innerText || '').trim()) return node.innerText.trim();
        }
        return '';
    };
    const rows = items.map((el) => {
        const parts = lines(el);
        // Rows read "招聘方·公司名"; keep only the company part for matching.
        const company = pick(el, ['.im-ui-company-info', '[class*=company]'])
            .replace(/^招聘方[·・]\s*/, '');
        const hr_name = pick(el, ['.im-ui-title', '[class*=name]']) || parts[0] || '';
        const last = pick(el, [
            '.im-ui-last-message-super', '.im-ui-last-message-special',
            '.im-ui-content', '[class*=last-message]',
        ]);
        return {
            company: company,
            hr_name: hr_name,
            hr_title: '',
            last_message: last || (parts.length > 2 ? parts[parts.length - 2] : ''),
            last_message_at: pick(el, ['[class*=time]']) || (parts.length ? parts[parts.length - 1] : ''),
            has_unread: !!el.querySelector('.im-ui-unread-count-badge, [class*=unread]'),
            has_reply: !!last,
        };
    });
    return {available: true, rows: rows, matched: matched};
})()
"""

JS_LIEPIN_OPEN_THREAD = r"""
(() => {
    const hr = __HR_NAME__;
    const company = __COMPANY__;
    const items = Array.from(document.querySelectorAll('.im-ui-contact-list-item'));
    const text = (el) => (el.innerText || '');
    let target = items.find((el) => text(el).includes(hr) && (!company || text(el).includes(company)));
    if (!target) target = items.find((el) => hr && text(el).includes(hr));
    if (!target) return {available: false, reason: '未找到该联系人'};
    target.click();
    return {available: true};
})()
"""

JS_LIEPIN_THREAD = r"""
(() => {
    const root = document.querySelector('.im-ui-chat-content')
        || document.querySelector('#im-basic-contact') || document.body;
    const rows = Array.from(root.querySelectorAll('.im-ui-message-wrapper')).map((el) => {
        const body = el.querySelector('.im-ui-message-body') || el.querySelector('.im-ui-txt-content');
        const node = body || el;
        const text = (node.innerText || el.innerText || '').trim();
        const cls = String(el.className || '') + ' ' + String(node.className || '');
        let sender = /(^|[^a-z])(self|mine|is-me|message-me|right)([^a-z]|$)/i.test(cls) ? 'me' : 'hr';
        if (/tip|notice|system/i.test(cls)) sender = 'system';
        if (!/self|mine|is-me|message-me|right/i.test(cls)) {
            const wrap = el.getBoundingClientRect();
            const rect = node.getBoundingClientRect();
            if (rect.width && wrap.width && rect.left > wrap.left + wrap.width / 2) sender = 'me';
        }
        return {sender: sender, text: text};
    }).filter((row) => row.text);
    return {available: true, rows: rows};
})()
"""


def _monitor() -> Any:
    """Import the vendored monitor module lazily (tests replace this seam)."""
    from offerpilot.executor import monitor  # type: ignore

    return monitor


def _runtime_config(server: Any) -> dict[str, Any]:
    from offerpilot.config import load_config  # type: ignore

    return load_config(server.CONFIG_PATH)


def _store_jobs() -> list[dict[str, Any]]:
    """Read the workbench job pool for conversation → job matching (never writes)."""
    try:
        import backend as workbench_backend  # local module

        return [job for job in workbench_backend.get_store("user").jobs() if isinstance(job, dict)]
    except Exception:
        return []


def _match_text(value: Any) -> str:
    return str(value or "").strip().casefold()


def _match_conversation_job(conversation: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Match by company + HR name; company-only only when it is unambiguous."""
    company = _match_text(conversation.get("company"))
    hr_name = _match_text(conversation.get("hr_name"))
    if not company:
        return None
    company_matches = [
        job for job in jobs
        if company in _match_text(job.get("company")) or _match_text(job.get("company")) in company
    ]
    if not company_matches:
        return None
    if hr_name:
        for job in company_matches:
            if _match_text(job.get("hr_name")) == hr_name:
                return job
    return company_matches[0] if len(company_matches) == 1 else None


CONTACT_PATTERNS = (
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)"),
    re.compile(r"(?:微信|wechat|weixin|vx|v信|威信)\s*[:：]?\s*[A-Za-z][-_A-Za-z0-9]{5,19}", re.IGNORECASE),
)


def _redact_contacts(value: Any) -> str:
    """Keep phone/email/WeChat out of API responses and logs."""
    text = str(value or "")
    for pattern in CONTACT_PATTERNS:
        text = pattern.sub("[联系方式已隐藏]", text)
    return text


def _conversation_id(company: Any, hr_name: Any, hr_title: Any, platform: str = "boss") -> str:
    """Return an opaque id; the raw HR/company text is never part of it."""
    payload = "\x1f".join(
        [_match_text(platform)] + [_match_text(value) for value in (company, hr_name, hr_title)]
    ).encode("utf-8")
    return hashlib.sha256(_conversation_salt + payload).hexdigest()[:32]


def _send_windows(config: dict[str, Any]) -> list[str]:
    """Always enforce the 09:00–16:00 window, even if config lists none."""
    throttle = config.get("throttle") if isinstance(config.get("throttle"), dict) else {}
    return list(throttle.get("send_windows") or [DEFAULT_SEND_WINDOW])


def _with_send_window(config: dict[str, Any]) -> dict[str, Any]:
    throttle = config.get("throttle") if isinstance(config.get("throttle"), dict) else {}
    return {**config, "throttle": {**throttle, "send_windows": _send_windows(config)}}


def _send_window_open(config: dict[str, Any]) -> bool:
    from offerpilot.throttle import SendWindowChecker  # type: ignore

    return SendWindowChecker(_send_windows(config)).is_active()


def _stop_requested(server: Any, config: dict[str, Any]) -> bool:
    monitor = _monitor()
    if monitor.stop_requested(config):
        return True
    active = _active_task(server)
    return bool(active and active.get("stop_requested"))


def _risk_lock_reason(server: Any, config: dict[str, Any]) -> str | None:
    monitor = _monitor()
    guard = config.get("_monitor_safety_guard")
    guard_type = getattr(monitor, "MonitorSafetyGuard", None)
    if guard_type is not None and isinstance(guard, guard_type):
        if guard.consecutive_page_failures >= guard.limit:
            return "监测连续页面失败，风险锁未解除"
    lock = None
    try:
        from offerpilot.db import get_active_platform_safety_lock  # type: ignore

        db = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            lock = get_active_platform_safety_lock(db)
        finally:
            db.close()
    except Exception:
        lock = None
    if lock:
        return "平台风险锁未解除，请稍后再试"
    return None


def _reply_gate(server: Any, config: dict[str, Any]) -> tuple[bool, str | None]:
    if not _send_window_open(config):
        return False, "不在发送窗口（09:00–16:00）"
    if _stop_requested(server, config):
        return False, "当前任务已请求停止"
    lock_reason = _risk_lock_reason(server, config)
    if lock_reason:
        return False, lock_reason
    return True, None


# --- HR conversation store: redacted snapshots on this machine ----------------
#
# Bodies live in ``web/data/<mode>/hr/conversations.json`` (gitignored).  The
# listing refresh is the only place that opens a conversation page, and only
# for conversations whose list signature changed (or that have no body yet).
# Everything written to disk is redacted first: phone, email and WeChat never
# reach the file.  The store never feeds the send gate: ``send_reply`` still
# only accepts ids in the in-memory 10-minute listing.

HR_STORE_RELATIVE = Path("hr") / "conversations.json"
HR_STORE_SCHEMA = 1
HR_SIGNATURE_TEXT_CHARS = 80
HR_MESSAGE_MAX_CHARS = 500
HR_STORED_MESSAGES_MAX = 200
HR_THREAD_OPENS_PER_REFRESH = 5

_hr_store_lock = threading.RLock()


def _hr_store_modes(mode: Any = "user") -> str:
    value = str(mode or "user").strip().lower()
    return value if value in RUNTIME_MODES else "user"


def _hr_store_path(mode: Any = "user") -> Path:
    resolved = _hr_store_modes(mode)
    root = _hr_store_root if _hr_store_root is not None else WEB_DIR / "data" / resolved
    return Path(root) / HR_STORE_RELATIVE


def _hr_store_key(row: dict[str, Any]) -> str:
    return f"{row.get('platform') or 'boss'}:{row.get('id') or ''}"


def _hr_signature(row: dict[str, Any]) -> str:
    """Hash of the list fields that tell a new incoming message from an old one."""
    text = _redact_contacts(row.get("last_message"))[:HR_SIGNATURE_TEXT_CHARS]
    payload = f"{row.get('last_message_at') or ''}\x1f{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _hr_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _load_hr_store(mode: Any = "user") -> dict[str, dict[str, Any]]:
    path = _hr_store_path(mode)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # A damaged cache is not worth crashing over; the next refresh rebuilds it.
        return {}
    rows = payload.get("conversations") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        return {}
    return {
        str(key): dict(value)
        for key, value in rows.items()
        if isinstance(value, dict)
    }


def _save_hr_store(conversations: dict[str, dict[str, Any]], mode: Any = "user") -> None:
    """Write atomically: temp file in the same directory, then ``os.replace``."""
    path = _hr_store_path(mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": HR_STORE_SCHEMA, "conversations": conversations}
    handle, temp_name = tempfile.mkstemp(prefix=".conversations-", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _hr_stored_message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender": row.get("sender") if row.get("sender") in {"hr", "me"} else "system",
        "text": _redact_contacts(row.get("text"))[:HR_MESSAGE_MAX_CHARS],
        "time": str(row.get("time") or "")[:40],
    }


def _hr_merge_messages(
    previous: list[Any], fresh: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append new messages to the stored ones, dropping repeats.

    Counts occurrences rather than a plain set: an identical sentence sent twice
    is kept twice, while re-reading the same page adds nothing.  ``time`` is
    part of the key, and is empty when the page does not expose it.
    """
    merged: list[dict[str, Any]] = []
    for row in previous:
        if not isinstance(row, dict):
            continue
        message = _hr_stored_message(row)
        if message["text"]:
            merged.append(message)
    prior = Counter((m["sender"], m["text"], m["time"]) for m in merged)
    seen: Counter = Counter()
    for row in fresh:
        if not isinstance(row, dict):
            continue
        message = _hr_stored_message(row)
        if not message["text"]:
            continue
        key = (message["sender"], message["text"], message["time"])
        seen[key] += 1
        if seen[key] <= prior[key]:
            continue
        merged.append(message)
    return merged[-HR_STORED_MESSAGES_MAX:]


def _hr_store_record(
    row: dict[str, Any],
    *,
    messages: list[Any],
    signature: str,
    fetched_at: str | None,
    stale: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "platform": str(row.get("platform") or "boss"),
        "id": str(row.get("id") or ""),
        "company": _redact_contacts(row.get("company"))[:200],
        "title": _redact_contacts(row.get("title"))[:200],
        "hr_name": _redact_contacts(row.get("hr_name"))[:100],
        "hr_title": _redact_contacts(row.get("hr_title"))[:100],
        "job_id": row.get("job_id"),
        "last_message_at": str(row.get("last_message_at") or "")[:40],
        "last_message": _redact_contacts(row.get("last_message"))[:200],
        "unread": bool(row.get("unread")),
        "messages": messages,
        "signature": signature,
        "fetched_at": fetched_at,
        "stale": bool(stale),
        "error": _redact_contacts(error)[:300] if error else None,
    }


def _remember_conversations(
    items: list[dict[str, Any]],
    platform: str | None = None,
) -> None:
    """Store a listing in the cache.

    ``platform`` set: a single-platform read.  Only that platform's entries are
    replaced and only its listing time is refreshed; every other platform keeps
    its entries and expiry.  ``platform`` unset: the aggregate path, which
    replaces the whole cache with the union it just read (unchanged behavior).
    """
    global _conversation_listed_at
    now = time.monotonic()
    with _conversation_cache_lock:
        if platform is None:
            _conversation_cache.clear()
            _conversation_listed_at_by_platform.clear()
            for item in items:
                _conversation_cache[item["id"]] = dict(item)
            _conversation_listed_at = now
            for name in {str(item.get("platform") or "") for item in items} - {""}:
                _conversation_listed_at_by_platform[name] = now
            return
        for stale_id in [key for key, value in _conversation_cache.items()
                         if value.get("platform") == platform]:
            del _conversation_cache[stale_id]
        for item in items:
            _conversation_cache[item["id"]] = dict(item)
        _conversation_listed_at_by_platform[platform] = now
        _conversation_listed_at = now


def _cached_conversation(conversation_id: Any) -> dict[str, Any]:
    text = str(conversation_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", text):
        raise ValueError("会话 id 无效")
    now = time.monotonic()
    with _conversation_cache_lock:
        entry = _conversation_cache.get(text)
        if entry is not None:
            listed_at = _conversation_listed_at_by_platform.get(str(entry.get("platform") or ""))
            if listed_at is None or now - listed_at > CONVERSATIONS_TTL_SECONDS:
                entry = None
    if entry is None:
        raise ValueError("会话不在最近 10 分钟的会话列表中，请重新读取会话列表")
    return entry


def _reset_conversation_cache() -> None:
    """Clear the in-memory conversation cache (tests and runtime reset only)."""
    global _conversation_listed_at
    with _conversation_cache_lock:
        _conversation_cache.clear()
        _conversation_listed_at_by_platform.clear()
        _conversation_listed_at = None


def _stored_entry(conversation_id: Any) -> dict[str, Any] | None:
    """Return the stored record for a hashed id, if any (read-only fallback)."""
    text = str(conversation_id or "").strip()
    if not re.fullmatch(r"[0-9a-f]{32}", text):
        return None
    with _hr_store_lock:
        for value in _load_hr_store().values():
            if str(value.get("id") or "") == text:
                return value
    return None


def _mark_platform_stale(platform: str, reason: Any) -> None:
    """A failed platform read keeps its stored conversations, flagged stale."""
    with _hr_store_lock:
        store = _load_hr_store()
        changed = False
        for key, record in store.items():
            if str(record.get("platform") or "") != platform:
                continue
            record["stale"] = True
            record["error"] = _redact_contacts(reason)[:300]
            changed = True
        if not changed:
            return
        try:
            _save_hr_store(store)
        except OSError:
            pass


def _fetch_thread_body(row: dict[str, Any], platform: str) -> dict[str, Any]:
    """Open one conversation once and return its thread result (redacted later)."""
    entry = {
        "id": row.get("id"),
        "platform": platform,
        "company": row.get("company") or "",
        "title": row.get("title") or "",
        "hr_name": row.get("hr_name") or "",
        "hr_title": row.get("hr_title") or "",
    }
    return _read_thread_messages(entry, platform)


def _refresh_platform_store(items: list[dict[str, Any]], platform: str) -> None:
    """Refresh one platform's stored conversations after a list read.

    The listing already happened.  A conversation whose signature is unchanged
    and that already has a stored body is not opened again; a changed (or
    never-read) conversation is opened at most once, and its messages are
    merged into the stored ones.  A failed read keeps the old messages and
    flags the record stale.  A successful listing replaces only this
    platform's records; other platforms' records stay.
    """
    with _hr_store_lock:
        store = _load_hr_store()
    signature_by_key = {_hr_store_key(row): _hr_signature(row) for row in items}
    candidates = [
        row for row in items
        if not (
            (store.get(_hr_store_key(row)) or {}).get("signature") == signature_by_key[_hr_store_key(row)]
            and (store.get(_hr_store_key(row)) or {}).get("messages")
        )
    ]
    # Unread first; the sort is stable, so the platform's own list order holds otherwise.
    candidates.sort(key=lambda row: 0 if row.get("unread") else 1)
    fresh_by_key: dict[str, list[dict[str, Any]]] = {}
    errors_by_key: dict[str, str] = {}
    for row in candidates[:HR_THREAD_OPENS_PER_REFRESH]:
        key = _hr_store_key(row)
        try:
            read = _fetch_thread_body(row, platform)
        except Exception as exc:
            if str(exc) == "当前任务已请求停止，不能读取会话":
                break
            errors_by_key[key] = _redact_contacts(f"{type(exc).__name__}: {exc}")[:300]
            continue
        if read.get("ok") is False or read.get("available") is False:
            errors_by_key[key] = _redact_contacts(read.get("error") or read.get("reply_block_reason") or "会话读取失败")[:300]
            continue
        fresh_by_key[key] = [
            row_value for row_value in (read.get("messages") or [])
            if isinstance(row_value, dict)
        ]

    with _hr_store_lock:
        store = _load_hr_store()  # re-read: another platform may have written while we read
        previous_platform = {
            key: record for key, record in store.items()
            if str(record.get("platform") or "") == platform
        }
        for key in previous_platform:
            # A successful listing replaces this platform's records entirely.
            store.pop(key, None)
        for row in items:
            key = _hr_store_key(row)
            previous = previous_platform.get(key) or {}
            signature = signature_by_key[key]
            fresh = fresh_by_key.get(key)
            same_signature = previous.get("signature") == signature
            if fresh is not None:
                store[key] = _hr_store_record(
                    row,
                    messages=_hr_merge_messages(previous.get("messages") or [], fresh),
                    signature=signature,
                    fetched_at=_hr_now(),
                )
            elif same_signature and previous.get("messages"):
                # Unchanged and already has a body: nothing to open, nothing to change.
                store[key] = _hr_store_record(
                    row,
                    messages=previous.get("messages") or [],
                    signature=signature,
                    fetched_at=previous.get("fetched_at"),
                )
            else:
                # Failed read, or skipped by the refresh cap.  Keep the old signature so
                # the next refresh treats this conversation as changed and tries again.
                failed = key in errors_by_key
                store[key] = _hr_store_record(
                    row,
                    messages=previous.get("messages") or [],
                    signature=previous.get("signature"),
                    fetched_at=previous.get("fetched_at"),
                    stale=failed or (bool(previous.get("messages")) and not same_signature),
                    error=errors_by_key.get(key),
                )
        try:
            _save_hr_store(store)
        except OSError:
            pass


def _read_thread_messages(entry: dict[str, Any], platform: str) -> dict[str, Any]:
    """Read one conversation live (the single page-open path for a body)."""
    if platform == "boss":
        return _get_boss_thread(entry)
    return _get_platform_thread(entry, platform)


def _thread_response(
    entry: dict[str, Any],
    platform: str,
    messages: list[dict[str, Any]],
    *,
    stale: bool,
    error: str | None,
) -> dict[str, Any]:
    """Assemble a thread response; reply permission is never granted from disk."""
    if platform == "boss":
        try:
            server = load_backend()
            config = _with_send_window(_runtime_config(server))
            allowed, reason = _reply_gate(server, config)
        except Exception:
            allowed, reason = False, "回复前检查失败，请稍后重试"
    else:
        allowed, reason = False, "只读模式：当前平台不发送回复"
    response: dict[str, Any] = {
        "ok": not stale,
        "available": True,
        "platform": platform,
        "conversation_id": entry["id"],
        "company": entry.get("company") or "",
        "title": entry.get("title") or "",
        "messages": messages,
        "stale": bool(stale),
        "reply_allowed": allowed,
        "reply_block_reason": None if allowed else reason,
    }
    if error:
        response["error"] = _redact_contacts(error)[:300]
    return response


def _store_response(row: dict[str, Any], platform: str, *, stale: bool, error: str | None) -> dict[str, Any]:
    return _thread_response(
        row,
        platform,
        _stored_thread_messages(row, platform),
        stale=stale,
        error=error,
    )


def _stored_thread_messages(row: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    return [
        {
            "sender": message.get("sender") if message.get("sender") in {"hr", "me"} else "system",
            "text": _redact_contacts(message.get("text"))[:HR_MESSAGE_MAX_CHARS],
            "time": str(message.get("time") or "")[:40],
            "platform": platform,
        }
        for message in (row.get("messages") or [])
        if isinstance(message, dict)
    ]


def _live_thread_messages(thread: dict[str, Any], platform: str) -> list[dict[str, Any]]:
    return [
        {
            "sender": row.get("sender") if row.get("sender") in {"hr", "me"} else "system",
            "text": _redact_contacts(row.get("text"))[:HR_MESSAGE_MAX_CHARS],
            "time": str(row.get("time") or "")[:40],
            "platform": platform,
        }
        for row in (thread.get("messages") or [])
        if isinstance(row, dict)
    ]


def _stored_body_for(entry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    """The stored body when it is current enough to serve without opening.

    A body is only written by a successful read, and every listing refresh
    that sees a changed signature updates it or flags it stale.  A record left
    stale by a failed read is never served here, so the next open retries the
    platform.
    """
    key = _hr_store_key({**entry, "platform": platform})
    with _hr_store_lock:
        record = _load_hr_store().get(key) or {}
    if not record or record.get("stale") or not record.get("messages"):
        return None
    return record


def _merge_live_thread(
    entry: dict[str, Any],
    platform: str,
    messages: list[dict[str, Any]],
    signature: str | None = None,
) -> list[dict[str, Any]]:
    """Merge a live read into the stored body and persist it (best effort).

    Old messages are kept; the live read only adds ones not already stored.
    """
    row = {**entry, "platform": platform}
    key = _hr_store_key(row)
    with _hr_store_lock:
        store = _load_hr_store()
        record = store.get(key) or {}
        merged = _hr_merge_messages(record.get("messages") or [], messages)
        store[key] = _hr_store_record(
            row,
            messages=merged,
            signature=signature or str(record.get("signature") or ""),
            fetched_at=_hr_now(),
        )
        try:
            _save_hr_store(store)
        except OSError:
            pass
    return _stored_thread_messages(store[key], platform)


def _live_thread_for_store(
    thread: dict[str, Any], entry: dict[str, Any], platform: str,
) -> list[dict[str, Any]]:
    signature = _hr_signature({**entry, "platform": platform})
    return _merge_live_thread(entry, platform, _live_thread_messages(thread, platform), signature)


def _chat_platform(value: Any) -> str:
    platform = str(value or "boss").strip().lower()
    if platform not in CHAT_PLATFORMS:
        raise ValueError("会话平台只能是 boss、zhilian、51job 或 liepin")
    return platform


def _json_object(raw: Any) -> dict[str, Any] | None:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _conversation_items(platform: str, rows: list[Any]) -> list[dict[str, Any]]:
    """Map platform rows into the same read-only shape BOSS already returns."""
    jobs = _store_jobs()
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        company = str(row.get("company") or "").strip()
        hr_name = str(row.get("hr_name") or "").strip()
        hr_title = str(row.get("hr_title") or "").strip()
        job = _match_conversation_job(row, jobs)
        items.append({
            "id": _conversation_id(company, hr_name, hr_title, platform),
            "platform": platform,
            "company": company,
            "title": str((job or {}).get("title") or ""),
            "hr_name": hr_name,
            "hr_title": hr_title,
            "last_message": _redact_contacts(row.get("last_message"))[:200],
            "last_message_at": str(row.get("last_message_at") or "")[:40],
            "unread": bool(row.get("has_unread")),
            "job_id": str((job or {}).get("id") or "") or None,
        })
    return items


def _wait_for_chat_page(
    monitor: Any,
    target_id: str,
    config: dict[str, Any],
    deadline: "_ChatReadDeadline",
    timeout: float = 12.0,
) -> bool:
    """Wait for the chat page without abandoning a background worker.

    ``monitor._wait_for_page_or_stop`` runs ``wait_for_load`` through
    ``run_cancellable``, which leaves a daemon thread polling the tab when the
    stop event fires.  Chat reads poll in the caller's thread instead, so a
    timed-out read never keeps a worker talking to the browser afterwards.
    """
    info_fn = getattr(monitor, "get_page_info", None)
    if not callable(info_fn):
        return monitor._wait_for_page_or_stop(target_id, config, timeout=timeout)
    stop_fn = getattr(monitor, "stop_requested", None)
    end = time.monotonic() + max(0.0, min(timeout, deadline.remaining()))
    while True:
        if callable(stop_fn) and stop_fn(config):
            return False
        try:
            info = info_fn(target_id)
        except Exception:
            info = None
        if isinstance(info, dict) and info.get("ready") == "complete":
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.5)


def _open_platform_tab(
    url: str,
    config: dict[str, Any],
    deadline: "_ChatReadDeadline | None" = None,
) -> str | None:
    """Open one chat tab with the monitor's throttle/risk guards (read-only)."""
    monitor = _monitor()
    deadline = deadline or _ChatReadDeadline(CHAT_LIST_TIMEOUT_SECONDS)
    deadline.check()
    target_id = monitor._open_monitor_tab(url, config, background=True)
    if not target_id:
        return None
    try:
        deadline.check()
        if monitor._wait_or_stop(config, 3):
            monitor.close_tab(target_id)
            return None
        if not _wait_for_chat_page(monitor, target_id, config, deadline, timeout=12):
            monitor.close_tab(target_id)
            return None
        deadline.check()
        try:
            monitor._inspect_monitor_page(target_id, config)
        except Exception:
            monitor.close_tab(target_id)
            raise
        deadline.check()
    except ChatReadTimeout:
        monitor.close_tab(target_id)
        raise
    return target_id


def _list_platform_conversations(platform: str) -> dict[str, Any]:
    """Read one non-BOSS platform's list within ``CHAT_LIST_TIMEOUT_SECONDS``.

    Reads stay serial: on timeout this platform reports ``读取超时`` and the
    caller moves on to the next one; nothing keeps running in the background.
    """
    try:
        return _list_platform_conversations_within(platform, _ChatReadDeadline(CHAT_LIST_TIMEOUT_SECONDS))
    except ChatReadTimeout:
        _mark_platform_stale(platform, CHAT_READ_TIMEOUT_ERROR)
        return _chat_timeout_result(platform)


def _list_platform_conversations_within(
    platform: str, deadline: "_ChatReadDeadline",
) -> dict[str, Any]:
    server = load_backend()
    monitor = _monitor()
    config = _runtime_config(server)
    label = PLATFORM_CHAT_LABELS.get(platform, platform)
    if _stop_requested(server, config):
        raise ValueError("当前任务已请求停止，不能读取会话")
    if platform == "51job":
        _mark_platform_stale(platform, "前程无忧没有站内聊天，HR 沟通通过微信扫码完成")
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversations": [],
            "count": 0,
            "error": "前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息",
        }
    target_id = _open_platform_tab(PLATFORM_CHAT_URLS[platform], config, deadline)
    if not target_id:
        raise OfferPilotUnavailable(f"无法打开{label}聊天页面，请检查登录状态")
    drawer_branch: str | None = None
    try:
        if platform == "liepin":
            opened = _json_object(
                _chat_evaluate(monitor, target_id, JS_LIEPIN_ENSURE_DRAWER_WWW, deadline)
            )
            drawer_branch = str((opened or {}).get("branch") or "") or None
            if not opened or not opened.get("available"):
                error_text = str((opened or {}).get("reason") or f"无法打开{label}聊天面板")
                _mark_platform_stale(platform, error_text)
                return {
                    "ok": False,
                    "available": False,
                    "platform": platform,
                    "conversations": [],
                    "count": 0,
                    "error": error_text,
                }
            deadline.check()
            if monitor._wait_or_stop(config, 3):
                raise ValueError("当前任务已请求停止，不能读取会话")
        else:
            deadline.check()
            if monitor._wait_or_stop(config, 2):
                raise ValueError("当前任务已请求停止，不能读取会话")
        script = JS_ZHILIAN_CHAT_LIST if platform == "zhilian" else JS_LIEPIN_CHAT_LIST
        payload = _json_object(_chat_evaluate(monitor, target_id, script, deadline))
    finally:
        monitor.close_tab(target_id)
    if payload is None:
        raise OfferPilotUnavailable(f"{label}聊天列表解析失败，请稍后重试")
    if payload.get("available") is False:
        error_text = str(payload.get("reason") or f"{label}聊天列表不可读")
        _mark_platform_stale(platform, error_text)
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversations": [],
            "count": 0,
            "error": error_text,
        }
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    items = _conversation_items(platform, rows)
    _remember_conversations(items, platform)
    _refresh_platform_store(items, platform)
    result: dict[str, Any] = {
        "ok": True,
        "available": True,
        "platform": platform,
        "conversations": items,
        "count": len(items),
    }
    if platform == "liepin":
        # Diagnostics only: which drawer branch ran, and how many row nodes the
        # selector matched.  count=0 with matched=0 means the page showed no rows
        # to the selector; count=0 with matched>0 would mean rows failed to parse.
        result["drawer_branch"] = drawer_branch
        matched = payload.get("matched")
        result["matched"] = int(matched) if isinstance(matched, int) else None
    return result


def list_conversations(platform: Any = "boss") -> dict[str, Any]:
    """Open a platform chat list read-only and return one row per conversation.

    BOSS reuses the monitor's page opening, risk inspection and chat-list
    parser.  Zhilian and Liepin read their public web chat DOM; 51job has no
    in-site chat (HR talks through WeChat QR scan), so it reports that and
    never opens a page.
    ``platform="all"`` reads every platform in turn and keeps the successful
    ones even when another platform fails.  No function here opens a
    conversation for writing or sends a message.
    """
    requested = str(platform or "all").strip().lower()
    if requested == "all":
        return list_all_conversations()
    platform = _chat_platform(requested)
    if platform == "boss":
        try:
            result = _list_boss_conversations()
        except Exception as exc:
            _mark_platform_stale(platform, f"{type(exc).__name__}: {exc}")
            raise
    else:
        try:
            result = _list_platform_conversations(platform)
        except Exception as exc:
            if exc.__class__.__name__ != "MonitorRiskDetected":
                _mark_platform_stale(platform, f"{type(exc).__name__}: {exc}")
                raise
            _mark_platform_stale(platform, "平台出现验证码或风控拦截")
            return {
                "ok": False,
                "available": False,
                "platform": platform,
                "conversations": [],
                "count": 0,
                "error": "平台出现验证码或风控拦截，已停止读取；请人工处理后重试。未发送任何消息。",
            }
    result["platform"] = platform
    for item in result.get("conversations") or []:
        item["platform"] = platform
    if not (bool(result.get("ok")) and bool(result.get("available"))):
        _mark_platform_stale(
            platform,
            result.get("error") or result.get("reason") or "无法读取该平台会话",
        )
    return result


def list_liepin_conversations() -> dict[str, Any]:
    """Read Liepin's 「我的沟通」 drawer from the www job page (read-only).

    The old ``c.liepin.com/`` entry only showed the home page; the drawer now
    opens from ``https://www.liepin.com/zhaopin/`` and the shared reader parses
    ``#im-basic-contact``.  Kept as a named entry so callers and tests
    can target the www path without knowing the internal dispatch.  The old
    generic ``_list_platform_conversations`` is preserved unchanged for the
    other platforms.
    """
    return _list_platform_conversations("liepin")


def list_all_conversations() -> dict[str, Any]:
    """Read the four platforms' chat lists read-only and merge them.

    Returns the same shape as :func:`list_conversations` for a single platform
    plus ``platforms`` (one status entry per platform) and, when at least one
    platform is readable, ``errors`` for the ones that failed.  Never opens a
    conversation, never types, never sends.
    """
    return _list_all_conversations()


def _list_all_conversations() -> dict[str, Any]:
    """Read every supported platform; one failure never hides the others."""
    items: list[dict[str, Any]] = []
    platforms: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    any_available = False
    for platform in CHAT_PLATFORMS:
        label = PLATFORM_CHAT_LABELS.get(platform, platform)
        try:
            result = list_conversations(platform)
        except (OfferPilotUnavailable, ValueError) as exc:
            reason = _redact_contacts(exc)[:300]
            errors[platform] = reason
            platforms.append({
                "platform": platform,
                "label": label,
                "ok": False,
                "available": False,
                "count": 0,
                "error": reason,
            })
            continue
        except Exception as exc:  # a reader bug must not abort the other platforms
            reason = _redact_contacts(f"{type(exc).__name__}: {exc}")[:300]
            errors[platform] = reason
            platforms.append({
                "platform": platform,
                "label": label,
                "ok": False,
                "available": False,
                "count": 0,
                "error": reason,
            })
            continue
        available = bool(result.get("ok")) and bool(result.get("available"))
        error_text = ""
        if available:
            any_available = True
            items.extend(result.get("conversations") or [])
        else:
            error_text = _redact_contacts(
                result.get("error") or result.get("reason") or "无法读取该平台会话"
            )[:300]
            errors[platform] = error_text
        entry: dict[str, Any] = {
            "platform": platform,
            "label": label,
            "ok": bool(result.get("ok")) and available,
            "available": available,
            "count": int(result.get("count") or 0) if available else 0,
        }
        if error_text:
            entry["error"] = error_text
        platforms.append(entry)
    if items:
        # Every platform read replaced the cache in turn; remember the union so
        # a thread from any platform can still be opened afterwards.
        _remember_conversations(items)
    response: dict[str, Any] = {
        "ok": any_available,
        "available": any_available,
        "platform": "all",
        "conversations": items,
        "count": len(items),
        "platforms": platforms,
    }
    if errors:
        response["errors"] = errors
    if not any_available:
        response["error"] = "所有平台都未能读取会话：" + "；".join(
            f"{PLATFORM_CHAT_LABELS.get(key, key)}：{reason}"
            for key, reason in errors.items()
        )
    return response


def _list_boss_conversations() -> dict[str, Any]:
    """Read the BOSS chat list within ``CHAT_LIST_TIMEOUT_SECONDS``."""
    try:
        return _list_boss_conversations_within(_ChatReadDeadline(CHAT_LIST_TIMEOUT_SECONDS))
    except ChatReadTimeout:
        _mark_platform_stale("boss", CHAT_READ_TIMEOUT_ERROR)
        return _chat_timeout_result("boss")


def _list_boss_conversations_within(deadline: "_ChatReadDeadline") -> dict[str, Any]:
    try:
        server = load_backend()
    except OfferPilotUnavailable as exc:
        return {"ok": False, "available": False, "error": str(exc), "conversations": [], "count": 0}
    monitor = _monitor()
    config = _runtime_config(server)
    if _stop_requested(server, config):
        raise ValueError("当前任务已请求停止，不能读取会话")
    chat_url = str((config.get("monitor") or {}).get("chat_url") or "https://www.zhipin.com/web/geek/chat")
    target_id, _reused = monitor._get_monitor_chat_target(chat_url, config)
    if not target_id:
        raise OfferPilotUnavailable("无法打开聊天列表页，请检查浏览器与 BOSS 登录状态")
    raw = None
    try:
        deadline.check()
        if monitor._wait_or_stop(config, 3) or not _wait_for_chat_page(
            monitor, target_id, config, deadline, timeout=10,
        ):
            raise OfferPilotUnavailable("聊天列表页未加载完成")
        deadline.check()
        monitor._inspect_monitor_page(target_id, config)
        raw = _chat_evaluate(monitor, target_id, monitor.JS_EXTRACT_CHAT_LIST, deadline)
    finally:
        monitor.close_tab(target_id)

    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        rows = None
    if not isinstance(rows, list):
        # Chat reads never feed the shared monitor failure counter: one
        # platform's unreadable list must not move another platform's (or the
        # next collection run's) consecutive-failure count toward a risk lock.
        raise OfferPilotUnavailable("聊天列表解析失败，请稍后重试")

    jobs = _store_jobs()
    items: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        company = str(row.get("company") or "").strip()
        hr_name = str(row.get("hr_name") or "").strip()
        hr_title = str(row.get("hr_title") or "").strip()
        job = _match_conversation_job(row, jobs)
        items.append({
            "id": _conversation_id(company, hr_name, hr_title),
            "platform": "boss",
            "company": company,
            "title": str((job or {}).get("title") or ""),
            "hr_name": hr_name,
            "hr_title": hr_title,
            "last_message": _redact_contacts(row.get("last_message"))[:200],
            "last_message_at": str(row.get("last_message_at") or "")[:40],
            "unread": bool(row.get("has_unread")),
            "job_id": str((job or {}).get("id") or "") or None,
        })
    _remember_conversations(items, "boss")
    _refresh_platform_store(items, "boss")
    return {"ok": True, "available": True, "conversations": items, "count": len(items)}


def get_thread(conversation_id: Any, platform: Any = "boss") -> dict[str, Any]:
    """Return one conversation's messages, read-only.

    A body already stored for the same listing signature is served without
    opening the conversation again.  Otherwise the conversation is opened once
    and the read is merged into the stored body.  If the live read fails, the
    stored messages are returned with ``stale: true`` instead of being lost.
    ``send_reply`` does not use this path: it still requires the id to be in
    the in-memory 10-minute listing, so a stored body never becomes sendable.
    """
    requested = str(platform or "all").strip().lower()
    try:
        entry = _cached_conversation(conversation_id)
    except ValueError:
        entry = _stored_entry(conversation_id)
        if entry is None or (requested != "all" and str(entry.get("platform") or "boss") != _chat_platform(requested)):
            raise
    if requested == "all":
        platform = _chat_platform(str(entry.get("platform") or "boss"))
    else:
        platform = _chat_platform(requested)
        if str(entry.get("platform") or "boss") != platform:
            raise ValueError("会话不属于所选平台，请重新读取该平台的会话列表")
    stored = _stored_body_for(entry, platform)
    if stored is not None:
        return _store_response(stored, platform, stale=False, error=None)
    return _open_and_store_thread(entry, platform)


def _open_and_store_thread(entry: dict[str, Any], platform: str) -> dict[str, Any]:
    """Open the conversation once, merge the read into the store, and respond."""
    if platform == "51job":
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversation_id": entry["id"],
            "company": entry.get("company") or "",
            "title": entry.get("title") or "",
            "messages": [],
            "reply_allowed": False,
            "reply_block_reason": "前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息；当前平台不发送回复。",
        }
    try:
        thread = _read_thread_messages(entry, platform)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        if exc.__class__.__name__ == "MonitorRiskDetected":
            return _stale_or_error(
                entry, platform,
                "平台出现验证码或风控拦截，已停止读取；请人工处理后重试",
                risk_block=True,
            )
        return _stale_or_error(entry, platform, reason)
    failed = thread.get("ok") is False or thread.get("available") is False
    if failed:
        return _stale_or_error(
            entry, platform,
            str(thread.get("error") or thread.get("reply_block_reason") or "会话读取失败"),
        )
    messages = _merge_live_thread(
        entry,
        platform,
        _live_thread_messages(thread, platform),
        _hr_signature({**entry, "platform": platform}),
    )
    response = dict(thread)
    response["messages"] = messages
    response["stale"] = False
    return response


def _stale_or_error(
    entry: dict[str, Any], platform: str, reason: Any, *, risk_block: bool = False,
) -> dict[str, Any]:
    """On a failed live read keep the stored messages, flagged stale."""
    key = _hr_store_key({**entry, "platform": platform})
    with _hr_store_lock:
        store = _load_hr_store()
        record = store.get(key) or {}
        if record.get("messages"):
            store[key] = _hr_store_record(
                {**entry, "platform": platform},
                messages=record.get("messages") or [],
                signature=record.get("signature"),
                fetched_at=record.get("fetched_at"),
                stale=True,
                error=str(reason),
            )
            try:
                _save_hr_store(store)
            except OSError:
                pass
            return _store_response(store[key], platform, stale=True, error=str(reason))
    if risk_block:
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversation_id": entry["id"],
            "company": entry.get("company") or "",
            "title": entry.get("title") or "",
            "messages": [],
            "reply_allowed": False,
            "reply_block_reason": "平台出现验证码或风控拦截，已停止读取；请人工处理后重试",
        }
    raise OfferPilotUnavailable(_redact_contacts(reason)[:300])


def _get_platform_thread(entry: dict[str, Any], platform: str) -> dict[str, Any]:
    """Open one non-BOSS conversation within ``CHAT_THREAD_TIMEOUT_SECONDS``.

    A timed-out read returns a structured, still read-only result; it never
    keeps a worker or a browser tab alive after the budget is gone.
    """
    try:
        return _get_platform_thread_within(entry, platform, _ChatReadDeadline(CHAT_THREAD_TIMEOUT_SECONDS))
    except ChatReadTimeout:
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversation_id": entry.get("id"),
            "company": entry.get("company") or "",
            "title": entry.get("title") or "",
            "messages": [],
            "reply_allowed": False,
            "reply_block_reason": CHAT_READ_TIMEOUT_ERROR,
            "error": CHAT_READ_TIMEOUT_ERROR,
        }


def _get_platform_thread_within(
    entry: dict[str, Any], platform: str, deadline: "_ChatReadDeadline",
) -> dict[str, Any]:
    server = load_backend()
    monitor = _monitor()
    config = _runtime_config(server)
    label = PLATFORM_CHAT_LABELS.get(platform, platform)
    if _stop_requested(server, config):
        raise ValueError("当前任务已请求停止，不能读取会话")
    if platform == "51job":
        return {
            "ok": False,
            "available": False,
            "platform": platform,
            "conversation_id": entry["id"],
            "company": entry.get("company") or "",
            "title": entry.get("title") or "",
            "messages": [],
            "reply_allowed": False,
            "reply_block_reason": "前程无忧没有站内聊天，HR 沟通通过微信扫码完成，工作台不读取其消息；当前平台不发送回复。",
        }
    target_id = _open_platform_tab(PLATFORM_CHAT_URLS[platform], config, deadline)
    if not target_id:
        raise OfferPilotUnavailable(f"无法打开{label}聊天页面，请重新读取会话列表")
    try:
        if platform == "liepin":
            opened = _json_object(
                _chat_evaluate(monitor, target_id, JS_LIEPIN_ENSURE_DRAWER_WWW, deadline)
            )
            if not opened or not opened.get("available"):
                raise OfferPilotUnavailable(str((opened or {}).get("reason") or f"无法打开{label}聊天面板"))
            deadline.check()
            if monitor._wait_or_stop(config, 3):
                raise ValueError("当前任务已请求停止，不能读取会话")
        else:
            deadline.check()
            if monitor._wait_or_stop(config, 2):
                raise ValueError("当前任务已请求停止，不能读取会话")
        script = (JS_ZHILIAN_OPEN_THREAD if platform == "zhilian" else JS_LIEPIN_OPEN_THREAD)
        script = script.replace("__HR_NAME__", json.dumps(entry.get("hr_name") or "", ensure_ascii=False))
        script = script.replace("__COMPANY__", json.dumps(entry.get("company") or "", ensure_ascii=False))
        opened = _json_object(_chat_evaluate(monitor, target_id, script, deadline))
        if not opened or not opened.get("available"):
            raise OfferPilotUnavailable(str((opened or {}).get("reason") or "无法打开该会话"))
        deadline.check()
        if monitor._wait_or_stop(config, 2):
            raise ValueError("当前任务已请求停止，不能读取会话")
        thread_script = JS_ZHILIAN_THREAD if platform == "zhilian" else JS_LIEPIN_THREAD
        payload = _json_object(_chat_evaluate(monitor, target_id, thread_script, deadline))
    finally:
        monitor.close_tab(target_id)
    rows = payload.get("rows") if isinstance(payload, dict) and isinstance(payload.get("rows"), list) else []
    messages = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sender = row.get("sender") if row.get("sender") in {"hr", "me"} else "system"
        messages.append({
            "sender": sender,
            "text": _redact_contacts(row.get("text"))[:500],
            "platform": platform,
        })
    return {
        "ok": True,
        "available": True,
        "platform": platform,
        "conversation_id": entry["id"],
        "company": entry.get("company") or "",
        "title": entry.get("title") or "",
        "messages": messages,
        "reply_allowed": False,
        "reply_block_reason": "只读模式：当前平台不发送回复",
    }


def _get_boss_thread(entry: dict[str, Any]) -> dict[str, Any]:
    server = load_backend()
    monitor = _monitor()
    config = _with_send_window(_runtime_config(server))
    target_id = monitor._open_conversation_from_chat_list(
        {"hr_name": entry.get("hr_name") or "", "company": entry.get("company") or ""},
        config,
        background=False,
    )
    if not target_id:
        raise OfferPilotUnavailable("无法打开该会话，请重新读取会话列表")
    raw = None
    try:
        monitor._inspect_monitor_page(target_id, config)
        raw = monitor.evaluate(target_id, monitor.JS_EXTRACT_CONVERSATION)
    finally:
        monitor.close_tab(target_id)
    try:
        rows = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        rows = []
    if not isinstance(rows, list):
        rows = []
    messages = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sender = row.get("sender") if row.get("sender") in {"hr", "me"} else "system"
        messages.append({
            "sender": sender,
            "text": _redact_contacts(row.get("text"))[:500],
            "platform": "boss",
        })
    allowed, reason = _reply_gate(server, config)
    return {
        "ok": True,
        "available": True,
        "platform": "boss",
        "conversation_id": entry["id"],
        "company": entry.get("company") or "",
        "title": entry.get("title") or "",
        "messages": messages,
        "reply_allowed": allowed,
        "reply_block_reason": None if allowed else reason,
    }


def send_reply(
    conversation_id: Any,
    text: Any,
    *,
    confirm: Any = None,
    risk_acknowledged: Any = False,
) -> dict[str, Any]:
    """Send exactly one HR reply after every guard passes.

    Guards run in a fixed order: text, confirmation phrase, risk
    acknowledgement, send window, stop request, risk locks, and finally the
    conversation must come from the most recent list (10 minutes).  No other
    function in this module or in the workbench calls ``_send_message_in_chat``.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("回复内容不能为空")
    if len(cleaned) > MAX_REPLY_CHARS:
        raise ValueError(f"回复内容不能超过 {MAX_REPLY_CHARS} 字")
    if confirm != REPLY_CONFIRM_PHRASE:
        raise ValueError(f"请先输入确认短语：{REPLY_CONFIRM_PHRASE}")
    if risk_acknowledged is not True:
        raise ValueError("发送前必须确认风险提示")

    server = load_backend()
    config = _with_send_window(_runtime_config(server))
    if not _send_window_open(config):
        raise ValueError("不在发送窗口（09:00–16:00）")
    if _stop_requested(server, config):
        raise ValueError("当前任务已请求停止")
    lock_reason = _risk_lock_reason(server, config)
    if lock_reason:
        raise ValueError(lock_reason)
    entry = _cached_conversation(conversation_id)
    if str(entry.get("platform") or "boss") != "boss":
        raise ValueError("当前只支持在 BOSS 直聘发送回复；其他平台为只读")

    monitor = _monitor()
    target_id = monitor._open_conversation_from_chat_list(
        {"hr_name": entry.get("hr_name") or "", "company": entry.get("company") or ""},
        config,
        background=False,
    )
    if not target_id:
        raise OfferPilotUnavailable("无法打开该会话，请重新读取会话列表")
    try:
        sent = monitor._send_message_in_chat(target_id, cleaned, config)
    finally:
        monitor.close_tab(target_id)
    if not sent:
        raise ValueError("发送未被平台确认，请到 BOSS 页面核实后再试")
    return {
        "ok": True,
        "conversation_id": entry["id"],
        "company": entry.get("company") or "",
        "chars": len(cleaned),
    }
