"""Authenticated loopback API for local module integration, not public hosting."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import re
from urllib.parse import parse_qs, urlsplit
import uuid

from .store import ConflictError, NotFoundError
from .recap import build_recap, validate_result
from .plans import apply_plan, freeze_plan


IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,100}\Z")
MAX_BODY = 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Invalid identifier")
    return value


def public_material(record):
    material = record["payload"]
    return {"material_id": record["material_id"], "created_at": record["created_at"],
            "source_repository": material.get("source_repository"), "source_commit": material["source_commit"],
            "project_snapshot_id": material["project_snapshot_id"], "resume_version_id": material["resume_version_id"],
            "claims": material["claims"], "question_count": len(material["questions"]),
            "is_demo": material["is_demo"], "warnings": material.get("warnings", [])}


def make_server(store, owner, token, port=18746):
    if not owner or not isinstance(token, str) or len(token) < 20:
        raise ValueError("A local owner and a service token of at least 20 characters are required")

    def previous_sessions(material, current_id):
        rows = {}
        for claim in material["claims"]:
            for row in store.history(owner, claim["claim_id"], limit=20):
                session = row["session"]
                if session["session_id"] == current_id or row["recap"] is None:
                    continue
                rows[session["session_id"]] = {"session_id": session["session_id"],
                    "source_commit": session["payload"]["source_commit"],
                    "resume_version_id": session["payload"]["resume_version_id"],
                    "target": session["payload"]["target"], "created_at": session["created_at"],
                    "review_status": row["recap"]["payload"]["review_status"],
                    "recap_path": f"/v1/sessions/{session['session_id']}/recap"}
        return sorted(rows.values(), key=lambda row: row["created_at"], reverse=True)[:20]

    class Handler(BaseHTTPRequestHandler):
        server_version = "InterviewHubLocal/0.1"

        def log_message(self, *args):
            pass  # Never put answers, credentials or source snippets in request logs.

        def send_json(self, status, value):
            data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            length = self.headers.get("Content-Length", "")
            if self.headers.get("Transfer-Encoding") or not length.isdigit() or not 0 < int(length) <= MAX_BODY:
                raise ValueError("Expected a JSON body of at most 1 MiB with Content-Length")
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                raise ValueError("Content-Type must be application/json")
            def reject_constant(value):
                raise ValueError("Non-finite JSON numbers are not supported")
            data = json.loads(self.rfile.read(int(length)), parse_constant=reject_constant)
            if not isinstance(data, dict) or "owner_id" in data or "owner" in data:
                raise ValueError("Expected an object without client-provided owner identity")
            return data

        def dispatch(self, method):
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
                return self.send_json(401, {"error": "unauthorized"})
            parsed = urlsplit(self.path)
            parts = parsed.path.strip("/").split("/")
            query = parse_qs(parsed.query)
            try:
                if method == "GET" and parsed.path == "/health":
                    return self.send_json(200, {"status": "ok", "scope": "local_single_owner_prototype"})
                if parts[:1] != ["v1"]:
                    raise NotFoundError("Route not found")
                if method == "GET" and parts in (["v1", "materials"], ["v1", "history"]):
                    limit, offset = int(query.get("limit", [20])[0]), int(query.get("offset", [0])[0])
                    if not 1 <= limit <= 100 or offset < 0:
                        raise ValueError("Invalid pagination")
                    if parts[1] == "materials":
                        items = [public_material(row) for row in store.list_materials(owner, limit, offset)]
                    else:
                        claim_id = query.get("claim_id", [None])[0]
                        if claim_id is not None:
                            identifier(claim_id)
                        items = store.history(owner, claim_id, limit, offset)
                    return self.send_json(200, {"items": items, "limit": limit, "offset": offset})
                if method == "GET" and len(parts) == 3 and parts[:2] == ["v1", "materials"]:
                    return self.send_json(200, public_material(store.get_material(owner, identifier(parts[2]))))
                if method == "POST" and parts == ["v1", "sessions"]:
                    data = self.body()
                    material_id = identifier(data.get("material_id"))
                    material = store.get_material(owner, material_id)["payload"]
                    mode = data.get("mode", "resume_readiness")
                    if mode not in {"resume_readiness", "mock_interview"}:
                        raise ValueError("Invalid interview mode")
                    if mode == "mock_interview" and not material.get("resume_version_id"):
                        raise ValueError("Mock interview requires a saved resume version; this demo uses resume_readiness")
                    target = data.get("target", {})
                    if not isinstance(target, dict) or any(k not in {"company", "role", "round"} or not isinstance(v, str) or len(v) > 200 for k, v in target.items()):
                        raise ValueError("Target fields must be company, role or round strings of at most 200 characters")
                    session_id = identifier(data.get("session_id", "session_" + uuid.uuid4().hex))
                    payload = {"mode": mode, "target": target, "resume_version_id": material["resume_version_id"],
                               "project_snapshot_id": material["project_snapshot_id"], "source_commit": material["source_commit"]}
                    try:
                        existing = store.get_session(owner, session_id)
                    except NotFoundError:
                        existing = None
                    if existing:
                        if existing["material_id"] != material_id or any(existing["payload"].get(k) != v for k, v in payload.items()):
                            raise ConflictError("Session context is immutable")
                        return self.send_json(201, existing)
                    payload["related_history"] = previous_sessions(material, session_id)
                    return self.send_json(201, store.create_session(owner, session_id, material_id, payload))
                if len(parts) >= 3 and parts[:2] == ["v1", "sessions"]:
                    session_id = identifier(parts[2])
                    record = store.get_session(owner, session_id)
                    session = {**record["payload"], "session_id": session_id, "material_id": record["material_id"]}
                    material = store.get_material(owner, record["material_id"])["payload"]
                    if len(parts) == 4 and parts[3] == "question-plan":
                        if method == "GET":
                            return self.send_json(200, store.get_plan(owner, session_id))
                        if method == "POST":
                            plan = freeze_plan(material, self.body())
                            return self.send_json(201, store.save_plan(owner, session_id, plan))
                    try:
                        plan = store.get_plan(owner, session_id)["payload"]
                    except NotFoundError:
                        plan = None
                    material = apply_plan(material, plan)
                    if method == "GET" and len(parts) == 3:
                        return self.send_json(200, record)
                    if method == "GET" and len(parts) == 4 and parts[3] in {"context", "evaluation-context"}:
                        if parts[3] == "evaluation-context":
                            context = material
                        else:
                            context = {k: v for k, v in material.items() if k != "questions"}
                            context["questions"] = [{k: q[k] for k in ("question_id", "claim_id", "text", "evidence_ids", "intent", "reason") if k in q} for q in material["questions"]]
                        return self.send_json(200, {"audience": "trusted_interview_backend", "session": record,
                            "material": context, "related_history": record["payload"].get("related_history", []),
                            "history_scope": "Up to 20 same-claim recaps frozen at session creation, with original versions and confirmation state"})
                    if method == "POST" and len(parts) == 4 and parts[3] == "results":
                        result = self.body()
                        if (result.get("material_id") != record["material_id"]
                                or result.get("source_commit") != material["source_commit"]
                                or result.get("resume_version_id") != material["resume_version_id"]
                                or "session_id" in result and result["session_id"] != session_id
                                or "project_snapshot_id" in result and result["project_snapshot_id"] != material["project_snapshot_id"]):
                            raise ValueError("Result must refer to this session's immutable material and resume")
                        if result.get("question_plan_id") != material.get("question_plan_id"):
                            raise ValueError("Result must identify this session's frozen question plan")
                        result.update(session_id=session_id, project_snapshot_id=material["project_snapshot_id"],
                                      resume_version_id=material["resume_version_id"])
                        validate_result(material, result)
                        return self.send_json(201, store.save_result(owner, session_id, result))
                    if len(parts) == 4 and parts[3] == "recap":
                        if method == "GET":
                            return self.send_json(200, store.get_recap(owner, session_id))
                        if method == "POST":
                            data = self.body()
                            if data:
                                raise ValueError("Recap uses stored results; send an empty object")
                            try:
                                cached = store.get_recap(owner, session_id)
                            except NotFoundError:
                                cached = None
                            if cached:
                                return self.send_json(200, cached)
                            result = store.get_result(owner, session_id)["payload"]
                            recap = build_recap(material, session, result, history=record["payload"].get("related_history", []))
                            return self.send_json(201, store.save_recap(owner, session_id, recap))
                    if method == "GET" and len(parts) == 4 and parts[3] == "results":
                        return self.send_json(200, store.get_result(owner, session_id))
                raise NotFoundError("Route not found")
            except NotFoundError:
                self.send_json(404, {"error": "not_found"})
            except ConflictError:
                self.send_json(409, {"error": "immutable_record_conflict"})
            except (ValueError, KeyError, TypeError, UnicodeError):
                self.send_json(400, {"error": "invalid_request", "message": "Check identifiers, versions, question references and result fields"})
            except Exception:
                self.send_json(500, {"error": "internal_error"})

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
