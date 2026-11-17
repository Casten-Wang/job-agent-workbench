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

import json
import shutil
import sys
import threading
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


def save_reviewed_greeting(job_id: str, text: str) -> dict[str, Any]:
    server = load_backend()
    if not text.strip() or len(text) > 300:
        raise ValueError("招呼语需要为 1 至 300 字，请先修改草稿")
    with server.job_mutation_lock, server.greeting_activity.claim(job_id, "editing") as acquired:
        if not acquired:
            raise ValueError("岗位正在处理，请稍后再同步")
        db = server.get_db(server.DATA_DIR / "offerpilot.db")
        try:
            from offerpilot.db import select_job_greeting, update_job_status
            row = db.execute("SELECT status FROM jobs WHERE id=? AND deleted_at IS NULL", (job_id,)).fetchone()
            if row and row["status"] in {"pending", "scored", "new", "filtered"}:
                update_job_status(db, job_id, "ready")
            select_job_greeting(db, job_id, "edited", edited_greeting=text, confirmed=True)
        finally:
            db.close()
    return {"ok": True, "message": "已同步你核对的招呼语，尚未发送。"}


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
        })
    return {"ok": True, "embedded": True, "read_only": True, "greetings": greetings}


def start_greet_task(ids: Any) -> dict[str, Any]:
    """Start a greet-only runtime task. It generates text and never sends."""
    safe_ids = _clean_job_ids(ids, 10)
    server = load_backend()
    from offerpilot.ai.greeter import greeting_config_error  # type: ignore
    from offerpilot.db import add_history, query_jobs, update_job_status  # type: ignore
    from offerpilot.web.tasks import TaskAlreadyRunningError  # type: ignore

    config = effective_ai_config(server.load_config(server.CONFIG_PATH))
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
        config = effective_ai_config(server.load_config(server.CONFIG_PATH))
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
        "recruitment_type", "status", "score", "created_at", "updated_at",
    )
    jobs = []
    for row in rows:
        record = serialize_job(dict(row))
        jobs.append({
            key: (record[key][:500] if isinstance(record[key], str) else record[key])
            for key in allowed
            if key in record and (record[key] is None or isinstance(record[key], (str, int, float, bool)))
        })
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

    config = effective_ai_config(load_config(server.CONFIG_PATH))
    try:
        options = _task_options(mode, config, raw_options)
    except ValueError as exc:
        return {
            "ok": False,
            "checks": [],
            "messages": [str(exc)],
            "summary": _options_summary(mode, None),
        }
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

    config = effective_ai_config(load_config(server.CONFIG_PATH))
    resume_blocker = _resume_blocker(server, mode, config)
    if resume_blocker:
        raise ValueError(resume_blocker)
    options = _task_options(mode, config, raw_options)
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
    with server.job_mutation_lock:
        task = server.task_runner.start(mode, {**config, **extra, "_agent_workflow": True})
    return {
        "task": _safe_task(task),
        "checks": checks,
        "summary": _options_summary(mode, options),
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
