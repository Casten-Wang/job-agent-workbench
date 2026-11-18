#!/usr/bin/env python3
"""Local-only HTTP server for the OfferPilot (秋招规划师) workbench.

The server binds to loopback and serves same-origin static files plus a small
JSON API. The embedded automation runtime runs in the same process; the server
has no credential store, no browser automation of its own, and no submission
path.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEB_DIR = Path(__file__).resolve().parent
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))
sys.dont_write_bytecode = True

import backend  # noqa: E402  (known local module in WEB_DIR)
import deploy_mode  # noqa: E402
import agent_capabilities  # noqa: E402
import career_agent_runtime  # noqa: E402
import career_user_runtime  # noqa: E402
import workbench_agent_runtime  # noqa: E402
import workbench_runtime  # noqa: E402

STATIC_DIR = WEB_DIR / "static"
MAX_BODY_BYTES = 8 * 1024 * 1024
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/offer-theme.css": ("offer-theme.css", "text/css; charset=utf-8"),
    "/ui-signals.css": ("ui-signals.css", "text/css; charset=utf-8"),
    "/ui-signals.js": ("ui-signals.js", "text/javascript; charset=utf-8"),
    "/workbench-agent.css": ("workbench-agent.css", "text/css; charset=utf-8"),
    "/career-resume.css": ("career-resume.css", "text/css; charset=utf-8"),
    "/sg-base.css": ("sg-base.css", "text/css; charset=utf-8"),
    "/sg-pipeline.css": ("sg-pipeline.css", "text/css; charset=utf-8"),
    "/sg-tools.css": ("sg-tools.css", "text/css; charset=utf-8"),
    "/mj-base.css": ("mj-base.css", "text/css; charset=utf-8"),
    "/mj-pages.css": ("mj-pages.css", "text/css; charset=utf-8"),
    "/workbench-agent.js": ("workbench-agent.js", "text/javascript; charset=utf-8"),
    "/career-user.js": ("career-user.js", "text/javascript; charset=utf-8"),
}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'; worker-src 'none'; manifest-src 'none'"
)


class JobAgentHandler(BaseHTTPRequestHandler):
    server_version = "JobAgentLocal/1.0"
    sys_version = ""

    def version_string(self) -> str:
        return self.server_version

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep local request logging concise; never log request bodies.
        if self.path.startswith("/api/"):
            sys.stderr.write("local-api %s - %s\n" % (self.address_string(), fmt % args))

    def _security_headers(self) -> None:
        if deploy_mode.enabled():
            # 展示部署：只放行魔搭域名嵌入，其余来源仍禁止（见 deploy_mode.frame_ancestors）。
            self.send_header("Content-Security-Policy", CSP.replace("frame-ancestors 'none'", deploy_mode.frame_ancestors()))
        else:
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")

    def _host_is_allowed(self) -> bool:
        raw_host = self.headers.get("Host", "").strip()
        if not raw_host:
            return False
        if deploy_mode.enabled():
            return deploy_mode.same_origin(raw_host, self.headers.get("Origin"), self.headers.get("X-Forwarded-Host"))
        if raw_host.startswith("["):
            # Bracketed IPv6, optionally followed by :port.
            end = raw_host.find("]")
            if end < 0:
                return False
            host = raw_host[1:end]
        elif raw_host.count(":") == 1:
            host = raw_host.rsplit(":", 1)[0]
        else:
            # Bare IPv6 (or malformed host); only ::1 is accepted.
            host = raw_host
        if host not in LOOPBACK_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlsplit(origin)
            if parsed.scheme not in ("http", "https") or parsed.hostname not in LOOPBACK_HOSTS:
                return False
        return True

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        disposition: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self._security_headers()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _stream_workbench_agent(self, path: str, query: dict[str, str]) -> None:
        """Relay the workbench agent SSE stream frame by frame.

        The generator validates mode and tokens on first iteration, so the first frame is
        read before headers are written. A validation failure becomes a plain JSON error.
        """
        last_event_id = self.headers.get("Last-Event-ID")
        events = workbench_agent_runtime.stream_events(path, query, last_event_id)
        try:
            first = next(events)
        except StopIteration:
            return
        except backend.ApiError as exc:
            self._error(str(exc), exc.status)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"retry: 1500\n\n")
            self.wfile.write(first)
            self.wfile.flush()
            for line in events:
                self.wfile.write(line)
                self.wfile.flush()

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise backend.ApiError("Content-Length 无效") from exc
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise backend.ApiError("请求体超过 8 MB 上限", 413)
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise backend.ApiError("请求体不是有效 JSON") from exc
        if not isinstance(value, dict):
            raise backend.ApiError("请求体必须是 JSON 对象")
        return value

    def _attachment_disposition(self, filename: str, inline: bool = False) -> str:
        safe = filename.replace('"', "")
        quoted = urllib.parse.quote(filename, safe="")
        kind = "inline" if inline else "attachment"
        return f"{kind}; filename=\"{safe}\"; filename*=UTF-8''{quoted}"

    def do_HEAD(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if not self._host_is_allowed():
            self._error("只允许 loopback 来源", 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
        try:
            if path.startswith(("/api/resume-agent/", "/api/interview-agent/")):
                result, status = career_agent_runtime.dispatch("GET", path, query)
                self._json(result, status)
                return
            if path.startswith("/api/workbench-agent/") and path.endswith("/stream"):
                self._stream_workbench_agent(path, query)
                return
            if path.startswith("/api/workbench-agent/"):
                result, status = workbench_agent_runtime.dispatch("GET", path, query)
                self._json(result, status)
                return
            if path.startswith("/api/career-user/") and path.endswith("/pdf"):
                content = career_user_runtime.pdf_document(path, query)
                filename = path.split("/")[-2] + ("_" + query["template"] if "template" in query else "") + ".pdf"
                self._send_bytes(200, content, "application/pdf", self._attachment_disposition(filename))
                return
            if path.startswith("/api/career-user/") and path.endswith("/print"):
                html = career_user_runtime.print_document(path, query)
                self._send_bytes(200, html.encode("utf-8") if isinstance(html, str) else html, "text/html; charset=utf-8")
                return
            if path.startswith("/api/career-user/"):
                result, status = career_user_runtime.dispatch("GET", path, query)
                self._json(result, status)
                return
            if path.startswith("/api/workbench/"):
                result, status = workbench_runtime.dispatch("GET", path, query)
                self._json(result, status)
                return
            if path == "/api/agent/capabilities":
                self._json(agent_capabilities.snapshot())
                return
            if path == "/api/health":
                offerpilot = backend.get_offerpilot_state(query.get("mode", "user"))
                self._json({
                    "ok": True,
                    "service": "offerpilot",
                    "host": "127.0.0.1",
                    "offline": not offerpilot.get("ok"),
                    "auto_submit": False,
                    "external_api": "embedded_offerpilot_only",
                    "offerpilot": offerpilot,
                    "python": sys.version.split()[0],
                })
                return
            if path == "/api/offerpilot/state":
                mode = query.get("mode", "user")
                self._json({"ok": True, "state": backend.get_offerpilot_state(mode)})
                return
            if path == "/api/offerpilot/jobs":
                mode = query.get("mode", "user")
                self._json(backend.get_offerpilot_jobs(mode))
                return
            if path == "/api/offerpilot/conversations":
                mode = query.get("mode", "user")
                self._json(backend.get_offerpilot_conversations(mode, query.get("platform", "boss")))
                return
            if path == "/api/offerpilot/conversations/summary":
                mode = query.get("mode", "user")
                self._json(backend.get_offerpilot_conversations_summary(mode))
                return
            if path == "/api/offerpilot/conversation":
                mode = query.get("mode", "user")
                extra = {"force": True} if query.get("force") == "1" else {}
                self._json(backend.get_offerpilot_conversation(
                    mode, query.get("id", ""), query.get("platform", "boss"), **extra
                ))
                return
            if path == "/api/pipeline":
                mode = query.get("mode", "user")
                store = backend.get_store(mode)
                self._json({
                    "ok": True,
                    "mode": store.mode,
                    "contract": backend.pipeline_contract(),
                    "status": backend.pipeline_status(store, store.jobs(), store.queue(), store.mails()),
                })
                return
            if path == "/api/profile":
                mode = query.get("mode", "user")
                store = backend.get_store(mode)
                self._json({
                    "ok": True,
                    "mode": store.mode,
                    "profile": backend.profile_for_api(mode, store),
                    "guarantees": {
                        "local_only": True,
                        "contact_fields_in_drafts": False,
                        "auto_submit": False,
                    },
                })
                return
            if path == "/api/state":
                mode = query.get("mode", "user")
                result = backend.snapshot(mode, {
                    "period": query.get("period", "all"),
                    "channel": query.get("channel", "all"),
                    "state": query.get("state", "all"),
                })
                self._json(result)
                return
            if path.startswith("/api/download/"):
                parts = path.split("/")
                if len(parts) != 5:
                    self._error("下载路径格式应为 /api/download/<mode>/<filename>", 404)
                    return
                mode, filename = urllib.parse.unquote(parts[3]), urllib.parse.unquote(parts[4])
                store = backend.get_store(mode, seed_if_empty=False)
                target = store.download_path(filename)
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if target.suffix in (".md", ".txt", ".json", ".ics", ".csv"):
                    content_type += "; charset=utf-8"
                self._send_bytes(
                    200,
                    target.read_bytes(),
                    content_type,
                    self._attachment_disposition(target.name),
                )
                return
            if path.startswith("/api/doc/"):
                key = urllib.parse.unquote(path.split("/")[-1])
                target = backend.DOCUMENT_DOWNLOADS.get(key)
                if target is None or not target.is_file():
                    self._error("文档不存在", 404)
                    return
                self._send_bytes(
                    200,
                    target.read_bytes(),
                    "text/markdown; charset=utf-8",
                    self._attachment_disposition(target.name, inline=True),
                )
                return
            if path == "/favicon.ico":
                self._send_bytes(204, b"", "image/x-icon")
                return
            static = STATIC_FILES.get(path)
            if static:
                filename, content_type = static
                target = STATIC_DIR / filename
                if not target.is_file():
                    self._send_bytes(
                        503,
                        b"<!doctype html><meta charset='utf-8'><p>Web frontend is still being prepared; API is available at /api/health.</p>",
                        "text/html; charset=utf-8",
                    )
                    return
                self._send_bytes(200, target.read_bytes(), content_type)
                return
            self._error("未找到该路径", 404)
        except backend.ApiError as exc:
            self._error(exc.message, exc.status)
        except Exception as exc:  # structured degrade warning; no stack trace to browser
            backend.degrade.warn("web_get", exc)
            self._error("本地请求处理失败；降级日志已记录", 500)

    def do_POST(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        if not self._host_is_allowed():
            self._error("只允许 loopback 来源", 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            payload = self._read_json_body()
            if deploy_mode.enabled():
                reason = deploy_mode.blocked_reason(path, payload)
                if reason:
                    self._error(reason, 403)
                    return
                if deploy_mode.uses_model(path, payload) and not deploy_mode.limiter.allow(
                        deploy_mode.client_id(self.headers, self.client_address[0])):
                    self._error("访问太频繁，请几分钟后再试", 429)
                    return
            if path.startswith(("/api/resume-agent/", "/api/interview-agent/")):
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
                result, status = career_agent_runtime.dispatch("POST", path, query, payload)
                self._json(result, status)
                return
            if path == "/api/workbench/internal/business":
                self._json(workbench_runtime.internal(self.headers, payload))
                return
            if path == "/api/workbench-agent/internal/profile":
                self._json(workbench_agent_runtime.commit_profile(self.headers, payload))
                return
            if path.startswith("/api/workbench-agent/"):
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
                result, status = workbench_agent_runtime.dispatch("POST", path, query, payload)
                self._json(result, status)
                return
            if path.startswith("/api/career-user/"):
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
                result, status = career_user_runtime.dispatch("POST", path, query, payload)
                self._json(result, status)
                return
            if path.startswith("/api/workbench/"):
                query = {key: values[0] for key, values in urllib.parse.parse_qs(parsed.query, keep_blank_values=True).items()}
                result, status = workbench_runtime.dispatch("POST", path, query, payload)
                self._json(result, status)
                return
            if path == "/api/interview/stream":
                events = backend.interview_stream_events(payload)
                first = next(events)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self._security_headers()
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(backend.interview_chat.encode_sse(first[0], first[1]))
                    self.wfile.flush()
                    for event, data in events:
                        self.wfile.write(backend.interview_chat.encode_sse(event, data))
                        self.wfile.flush()
                return
            if path == "/api/action":
                action = str(payload.get("action") or "")
                handler = backend.ACTIONS.get(action)
                if handler is None:
                    self._error(f"未知操作：{action}", 404)
                    return
                self._json(handler(payload))
                return
            if path == "/api/interview/stream":
                events = backend.interview_stream_events(payload)
                first = next(events)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-store, max-age=0")
                self.send_header("Connection", "close")
                self.send_header("X-Accel-Buffering", "no")
                self._security_headers()
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(backend.interview_chat.encode_sse(first[0], first[1]))
                    self.wfile.flush()
                    for event, data in events:
                        self.wfile.write(backend.interview_chat.encode_sse(event, data))
                        self.wfile.flush()
                return
            if path == "/api/offerpilot/preflight":
                self._json(backend.preflight_offerpilot_task(payload))
                return
            if path == "/api/offerpilot/tasks":
                self._json(backend.start_offerpilot_task(payload), 202)
                return
            if path == "/api/offerpilot/conversations/sync":
                self._json(backend.start_offerpilot_conversations_sync(payload), 202)
                return
            if path.startswith("/api/offerpilot/tasks/") and path.endswith("/stop"):
                task_id = urllib.parse.unquote(path[len("/api/offerpilot/tasks/"):-len("/stop")].rstrip("/"))
                self._json(backend.stop_offerpilot_task(task_id, str(payload.get("data_mode") or "user")))
                return
            if path == "/api/pipeline/event":
                self._json(backend.ingest_pipeline_event(payload))
                return
            if path == "/api/run-tests":
                self._json(backend.run_tests())
                return
            if path == "/api/web-report":
                self._json(backend.web_report(str(payload.get("mode") or "user")))
                return
            if path == "/api/export":
                self._json(backend.export_data(str(payload.get("mode") or "user")))
                return
            self._error("未找到该操作", 404)
        except backend.ApiError as exc:
            self._error(exc.message, exc.status)
        except Exception as exc:
            backend.degrade.warn("web_post", exc)
            self._error("本地操作处理失败；降级日志已记录", 500)


class LocalHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_server(host: str = "127.0.0.1", port: int = 8766) -> LocalHTTPServer:
    # 只有显式的展示部署模式（OFFERPILOT_DEPLOY=1）才允许非 loopback 监听。
    if host not in LOOPBACK_HOSTS and not deploy_mode.enabled():
        raise ValueError("server must bind to loopback only")
    return LocalHTTPServer((host, port), JobAgentHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only Job Agent web workbench")
    parser.add_argument("--host", default="127.0.0.1", choices=sorted(LOOPBACK_HOSTS | ({"0.0.0.0"} if deploy_mode.enabled() else set())))
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args(argv)
    server = make_server(args.host, args.port)
    actual_host, actual_port = server.server_address[:2]
    print(f"Job Agent web workbench ready at http://{actual_host}:{actual_port} (local only, no auto-submit)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
