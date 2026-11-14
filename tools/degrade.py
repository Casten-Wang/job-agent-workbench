#!/usr/bin/env python3
"""Structured, append-only degradation warnings for optional local modules."""

from __future__ import annotations

import datetime as dt
import json
import sys
import traceback
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

CONFIG_PATH = _TOOLS_DIR / "config_task06.json"
DEFAULT_LOG = _TOOLS_DIR / "data" / "degrade.log"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _TOOLS_DIR.parent / path


def warn(module: str, error: BaseException, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Append one structured warning and return it; never silently swallow."""
    cfg = config or load_config()
    path = _resolve(cfg["degrade_log"])
    detail = "".join(traceback.format_exception_only(type(error), error)).strip()[:500]
    event = {
        "recorded_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "module": module,
        "status": "module_unavailable",
        "error_type": type(error).__name__,
        "error_detail": detail,
        "action": "degraded; orchestrator continued with other modules",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def load_module_safely(
    module_name: str,
    module_path: str | Path,
    config: dict[str, Any] | None = None,
) -> tuple[Any | None, dict[str, Any] | None]:
    """Import one local module by path; log a warning on any failure."""
    import importlib.util

    try:
        spec = importlib.util.spec_from_file_location(module_name, Path(module_path))
        if spec is None or spec.loader is None:
            raise ImportError("no module spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except Exception as exc:  # degradation is the intended behavior here
        return None, warn(module_name, exc, config)
