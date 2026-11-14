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

_lock = threading.RLock()
_backend: Any | None = None
_backend_error: str | None = None
_backend_base_dir: Path | None = None


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


def start_task(mode: str) -> dict[str, Any]:
    if mode not in TASK_MODES:
        raise ValueError("仅允许 collect、monitor 或 full；发送任务不开放直接调用")
    server = load_backend()
    from offerpilot.collection.capabilities import platform_supports  # type: ignore
    from offerpilot.collection.orchestrator import normalize_collection_options  # type: ignore
    from offerpilot.config import load_config  # type: ignore
    from offerpilot.web.preflight import collect_preflight_checks, error_messages  # type: ignore

    config = load_config(server.CONFIG_PATH)
    options = None
    if mode in {"collect", "full"}:
        options = normalize_collection_options(config, None)
        if mode == "collect":
            options["auto_score"] = False
        else:
            collection_only = [
                platform for platform in options["platform_order"]
                if not platform_supports(platform, "deliver")
            ]
            if collection_only:
                raise ValueError("智联、前程无忧和猎聘只能单独采集，不能进入投递全流程")
            options["auto_score"] = True
    checks = collect_preflight_checks(mode, config, options)
    messages = [*server._preflight_messages(mode, config, options), *error_messages(checks)]
    if messages:
        raise ValueError("请先处理启动前检查：" + "；".join(messages[:5]))
    extra = {"_collection_options": options} if options is not None else {}
    with server.job_mutation_lock:
        task = server.task_runner.start(mode, {**config, **extra, "_agent_workflow": True})
    return {
        "task": _safe_task(task),
        "checks": checks,
        "policy": {
            "auto_score": False if mode == "collect" else True if mode == "full" else None,
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
