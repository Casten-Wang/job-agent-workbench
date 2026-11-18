"""Opt-in LangSmith tracing with redacted inputs and outputs by default."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def enabled() -> bool:
    return (not _truthy("LANGFUSE_TRACING") and _truthy("LANGSMITH_TRACING")
            and bool(os.getenv("LANGSMITH_API_KEY", "").strip()))


def capture_content() -> bool:
    # Privacy is mandatory, including legacy LangSmith, regardless of environment.
    return False


def status() -> dict[str, Any]:
    return {
        "provider": "langsmith",
        "enabled": enabled(),
        "project": os.getenv("LANGSMITH_PROJECT", "offerpilot-local"),
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "capture_content": capture_content() if enabled() else False,
        "graph_state_capture": False,
        "mode": "manual_redacted_agent_stage_traces",
        "agent_id": os.getenv("LANGSMITH_AGENT_ID", "offerpilot-local-agent"),
        "agent_environment": os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "production"),
        "redaction": "content omitted; lengths and SHA-256 only",
    }


def _digest(value: Any) -> tuple[int, str]:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return len(raw), hashlib.sha256(raw).hexdigest()


def _trace_value(value: Any, label: str) -> dict[str, Any]:
    length, digest = _digest(value)
    if capture_content():
        return {label: value, "chars": length, "sha256": digest}
    return {f"{label}_chars": length, f"{label}_sha256": digest}


def _safe_error(error: BaseException) -> str:
    return "model_execution_failed"


class AgentTrace:
    """Small async wrapper so tracing failures never break model execution."""

    def __init__(self, stage: str, value: Any, generation: dict[str, Any]):
        from .langfuse_monitor import LangfuseTrace
        self.langfuse = LangfuseTrace(stage, value)
        self.run = None
        if not enabled():
            return
        try:
            from .decisions import OUTPUTS
            stage = stage if stage in OUTPUTS else "unknown"
            from langsmith.address import agent_address
            from langsmith.run_trees import RunTree
            agent_id = os.getenv("LANGSMITH_AGENT_ID", "").strip()
            agent_environment = os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "").strip()
            address = agent_address(agent_id, agent_environment) if agent_id and agent_environment else None
            self.run = RunTree(
                name=f"agent.{stage}",
                run_type="chain",
                inputs={"stage": stage, **_trace_value(value, "input")},
                project_name=None if address else os.getenv("LANGSMITH_PROJECT", "offerpilot-local"),
                address=address,
                tags=["offerpilot", "agent", stage],
                extra={"metadata": {"stage": stage, "content_captured": False}},
            )
        except Exception:
            self.run = None

    async def start(self) -> None:
        await asyncio.to_thread(self.langfuse.start)
        if self.run is not None:
            try:
                await asyncio.to_thread(self.run.post)
            except Exception:
                self.run = None

    async def finish(self, output: Any = None, error: BaseException | None = None) -> None:
        await asyncio.to_thread(self.langfuse.finish, output, error)
        if self.run is None:
            return
        try:
            if error is not None:
                self.run.end(error=_safe_error(error))
            else:
                self.run.end(outputs=_trace_value(output, "output"))
            await asyncio.to_thread(self.run.patch)
        except Exception:
            # Observability is best-effort and must never change product behavior.
            return
