"""Manual, metadata-only Langfuse observations; no automatic instrumentation."""

import atexit
import os
import threading
from urllib.parse import urlsplit

_client = None
_lock = threading.Lock()


def endpoint():
    return os.getenv("LANGFUSE_BASE_URL", "").rstrip("/")


def configured():
    try:
        url = urlsplit(endpoint())
    except ValueError:
        return False
    return bool(url.hostname and not (url.username or url.password or url.query or url.fragment)
                and (url.scheme == "https" or url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1"})
                and os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def status():
    return {"provider": "Langfuse", "enabled": os.getenv("LANGFUSE_TRACING", "").lower() == "true" and configured(),
            "configured": configured(), "content_capture": False, "graph_state_capture": False,
            "mode": "manual_metadata_only", "evaluation": "local_rules_v1",
            "semantic_judge": False}


def client():
    global _client
    if not status()["enabled"]:
        return None
    with _lock:
        if _client is None:
            from langfuse import Langfuse
            from opentelemetry.sdk.trace import TracerProvider
            _client = Langfuse(public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
                               secret_key=os.environ["LANGFUSE_SECRET_KEY"], base_url=endpoint(),
                               tracer_provider=TracerProvider(), timeout=3,
                               environment="production")
            atexit.register(_client.shutdown)
    return _client


class LangfuseTrace:
    def __init__(self, stage, value):
        self.stage, self.value = stage, value
        self.span = None
        self.client = None

    def start(self):
        from .decisions import OUTPUTS
        from .observability import _digest
        try:
            self.client = client()
            if self.client is not None:
                # Arbitrary stage names, generation metadata and error strings can contain private text.
                name = self.stage if self.stage in OUTPUTS else "unknown"
                self.span = self.client.start_observation(name="agent." + name,
                    as_type="span", input={"input_bytes": _digest(self.value)[0]},
                    metadata={"content_capture": False, "evaluation_version": 1})
        except Exception:
            self.span = None

    def finish(self, output=None, error=None):
        if self.span is None:
            return
        from .evaluation import evaluate
        from .observability import _digest
        try:
            self.span.update(output={"output_bytes": _digest(output)[0], "success": error is None},
                             level="ERROR" if error is not None else "DEFAULT")
            self.span.score(name="execution_success", value=float(error is None))
            if error is None:
                try:
                    scores = evaluate(self.stage, self.value, output)
                except Exception:
                    self.span.score(name="evaluation_completed", value=0.0)
                else:
                    self.span.score(name="evaluation_completed", value=1.0)
                    for name, score in scores.items():
                        self.span.score(name=name, value=score)
        except Exception:
            pass  # Telemetry must never change a successful business result.
        finally:
            try:
                self.span.end()
            except Exception:
                pass
            self.value = None
