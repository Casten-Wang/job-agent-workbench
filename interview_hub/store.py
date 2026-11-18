"""File-backed, owner-scoped storage for immutable interview materials and records."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class NotFoundError(LookupError):
    pass


class ConflictError(ValueError):
    pass


def _payload_json(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Owner and record identifiers must be nonempty strings")
    return value


def _pagination(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Limit must be 1-100 and offset must be a nonnegative integer")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _material(row):
    return {"material_id": row["material_id"], "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"]}


def _session(row):
    return {"session_id": row["session_id"], "material_id": row["material_id"],
            "payload": json.loads(row["payload_json"]), "state": row["state"],
            "created_at": row["created_at"]}


def _session_record(row):
    return {"session_id": row["session_id"], "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"]}


class Store:
    """Short SQLite transactions; callers provide the authenticated owner.

    There is no user-authentication mechanism here. The HTTP service must derive
    owner from its own trusted context, rather than a request-body owner field.
    """

    def __init__(self, db_path):
        if str(db_path) == ":memory:":
            raise ValueError("Use a file-backed database for short-lived connections")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS materials (
                    owner TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, material_id)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    material_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('in_progress', 'completed')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, session_id),
                    FOREIGN KEY (owner, material_id) REFERENCES materials (owner, material_id)
                );
                CREATE TABLE IF NOT EXISTS results (
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, session_id),
                    FOREIGN KEY (owner, session_id) REFERENCES sessions (owner, session_id)
                );
                CREATE TABLE IF NOT EXISTS question_plans (
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, session_id),
                    FOREIGN KEY (owner, session_id) REFERENCES sessions (owner, session_id)
                );
                CREATE TABLE IF NOT EXISTS recaps (
                    owner TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (owner, session_id),
                    FOREIGN KEY (owner, session_id) REFERENCES results (owner, session_id)
                );
            """)

    @contextmanager
    def _connection(self, write=False):
        db = sqlite3.connect(self.db_path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def put_material(self, owner, material_id, payload):
        owner, material_id = _identifier(owner), _identifier(material_id)
        encoded = _payload_json(payload)
        with self._connection(write=True) as db:
            row = db.execute("SELECT * FROM materials WHERE owner = ? AND material_id = ?",
                             (owner, material_id)).fetchone()
            if row:
                if row["payload_json"] != encoded:
                    raise ConflictError("Material is immutable; create a new material version")
                return _material(row)
            db.execute("INSERT INTO materials VALUES (?, ?, ?, ?)",
                       (owner, material_id, encoded, _now()))
            row = db.execute("SELECT * FROM materials WHERE owner = ? AND material_id = ?",
                             (owner, material_id)).fetchone()
            return _material(row)

    def get_material(self, owner, material_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM materials WHERE owner = ? AND material_id = ?",
                             (_identifier(owner), _identifier(material_id))).fetchone()
            if row is None:
                raise NotFoundError("Material not found")
            return _material(row)

    def list_materials(self, owner, limit=20, offset=0):
        _pagination(limit, offset)
        with self._connection() as db:
            rows = db.execute("""SELECT * FROM materials WHERE owner = ?
                                 ORDER BY created_at DESC, material_id ASC LIMIT ? OFFSET ?""",
                              (_identifier(owner), limit, offset))
            return [_material(row) for row in rows]

    def list_sessions(self, owner, *, state, limit=100, offset=0):
        _pagination(limit, offset)
        if state not in {"in_progress", "completed"}:
            raise ValueError("Invalid session state")
        with self._connection() as db:
            rows = db.execute("SELECT * FROM sessions WHERE owner=? AND state=? ORDER BY created_at DESC, session_id ASC LIMIT ? OFFSET ?",
                              (_identifier(owner), state, limit, offset))
            return [_session(row) for row in rows]

    def create_session(self, owner, session_id, material_id, payload):
        owner, session_id, material_id = map(_identifier, (owner, session_id, material_id))
        encoded = _payload_json(payload)
        with self._connection(write=True) as db:
            material = db.execute("SELECT 1 FROM materials WHERE owner = ? AND material_id = ?",
                                  (owner, material_id)).fetchone()
            if material is None:
                raise NotFoundError("Material not found")
            row = db.execute("SELECT * FROM sessions WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            if row:
                if row["material_id"] != material_id or row["payload_json"] != encoded:
                    raise ConflictError("Session is immutable; create a new session")
                return _session(row)
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, 'in_progress', ?)",
                       (owner, session_id, material_id, encoded, _now()))
            row = db.execute("SELECT * FROM sessions WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            return _session(row)

    def get_session(self, owner, session_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM sessions WHERE owner = ? AND session_id = ?",
                             (_identifier(owner), _identifier(session_id))).fetchone()
            if row is None:
                raise NotFoundError("Session not found")
            return _session(row)

    def save_plan(self, owner, session_id, payload):
        owner, session_id = _identifier(owner), _identifier(session_id)
        encoded = _payload_json(payload)
        with self._connection(write=True) as db:
            session = db.execute("SELECT state FROM sessions WHERE owner = ? AND session_id = ?",
                                 (owner, session_id)).fetchone()
            if session is None:
                raise NotFoundError("Session not found")
            row = db.execute("SELECT * FROM question_plans WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            if row:
                if row["payload_json"] != encoded:
                    raise ConflictError("Question plan is immutable; start a new session")
                return _session_record(row)
            if session["state"] != "in_progress":
                raise ConflictError("Cannot add questions after finalization")
            db.execute("INSERT INTO question_plans VALUES (?, ?, ?, ?)", (owner, session_id, encoded, _now()))
            return _session_record(db.execute("SELECT * FROM question_plans WHERE owner = ? AND session_id = ?",
                                             (owner, session_id)).fetchone())

    def get_plan(self, owner, session_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM question_plans WHERE owner = ? AND session_id = ?",
                             (_identifier(owner), _identifier(session_id))).fetchone()
            if row is None:
                raise NotFoundError("Question plan not found")
            return _session_record(row)

    def save_result(self, owner, session_id, payload):
        owner, session_id = _identifier(owner), _identifier(session_id)
        encoded = _payload_json(payload)
        with self._connection(write=True) as db:
            session = db.execute("SELECT 1 FROM sessions WHERE owner = ? AND session_id = ?",
                                 (owner, session_id)).fetchone()
            if session is None:
                raise NotFoundError("Session not found")
            plan = db.execute("SELECT payload_json FROM question_plans WHERE owner = ? AND session_id = ?",
                              (owner, session_id)).fetchone()
            plan_id = json.loads(plan["payload_json"])["question_plan_id"] if plan else None
            if payload.get("question_plan_id") != plan_id:
                raise ConflictError("Result must use the frozen question plan")
            row = db.execute("SELECT * FROM results WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            if row:
                if row["payload_json"] != encoded:
                    raise ConflictError("Final result is immutable")
                return _session_record(row)
            db.execute("INSERT INTO results VALUES (?, ?, ?, ?)",
                       (owner, session_id, encoded, _now()))
            db.execute("UPDATE sessions SET state = 'completed' WHERE owner = ? AND session_id = ?",
                       (owner, session_id))
            row = db.execute("SELECT * FROM results WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            return _session_record(row)

    def get_result(self, owner, session_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM results WHERE owner = ? AND session_id = ?",
                             (_identifier(owner), _identifier(session_id))).fetchone()
            if row is None:
                raise NotFoundError("Result not found")
            return _session_record(row)

    def save_recap(self, owner, session_id, payload):
        owner, session_id = _identifier(owner), _identifier(session_id)
        encoded = _payload_json(payload)
        with self._connection(write=True) as db:
            session = db.execute("SELECT 1 FROM sessions WHERE owner = ? AND session_id = ?",
                                 (owner, session_id)).fetchone()
            if session is None:
                raise NotFoundError("Session not found")
            result = db.execute("SELECT 1 FROM results WHERE owner = ? AND session_id = ?",
                                (owner, session_id)).fetchone()
            if result is None:
                raise ConflictError("A final result is required before a recap")
            row = db.execute("SELECT * FROM recaps WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            if row:
                if row["payload_json"] != encoded:
                    raise ConflictError("Saved recap is immutable")
                return _session_record(row)
            db.execute("INSERT INTO recaps VALUES (?, ?, ?, ?)",
                       (owner, session_id, encoded, _now()))
            row = db.execute("SELECT * FROM recaps WHERE owner = ? AND session_id = ?",
                             (owner, session_id)).fetchone()
            return _session_record(row)

    def get_recap(self, owner, session_id):
        with self._connection() as db:
            row = db.execute("SELECT * FROM recaps WHERE owner = ? AND session_id = ?",
                             (_identifier(owner), _identifier(session_id))).fetchone()
            if row is None:
                raise NotFoundError("Recap not found")
            return _session_record(row)

    def history(self, owner, claim_id=None, limit=20, offset=0):
        owner = _identifier(owner)
        if claim_id is not None:
            claim_id = _identifier(claim_id)
        _pagination(limit, offset)
        with self._connection() as db:
            rows = db.execute("""
                SELECT s.session_id, s.material_id, s.payload_json AS session_payload,
                       s.state, s.created_at AS session_created,
                       m.payload_json AS material_payload, m.created_at AS material_created,
                       r.payload_json AS result_payload, r.created_at AS result_created,
                       c.payload_json AS recap_payload, c.created_at AS recap_created,
                       p.payload_json AS plan_payload, p.created_at AS plan_created
                FROM sessions s
                JOIN materials m ON m.owner = s.owner AND m.material_id = s.material_id
                LEFT JOIN results r ON r.owner = s.owner AND r.session_id = s.session_id
                LEFT JOIN recaps c ON c.owner = s.owner AND c.session_id = s.session_id
                LEFT JOIN question_plans p ON p.owner = s.owner AND p.session_id = s.session_id
                WHERE s.owner = ? ORDER BY s.created_at DESC, s.session_id ASC
            """, (owner,))
            history, skipped = [], 0
            for row in rows:
                material_payload = json.loads(row["material_payload"])
                if claim_id is not None and not any(
                        isinstance(claim, dict) and claim.get("claim_id") == claim_id
                        for claim in material_payload.get("claims", [])):
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                session_id = row["session_id"]
                record = {
                    "session": {"session_id": session_id, "material_id": row["material_id"],
                                "payload": json.loads(row["session_payload"]), "state": row["state"],
                                "created_at": row["session_created"]},
                    "material": {"material_id": row["material_id"], "payload": material_payload,
                                 "created_at": row["material_created"]},
                    "result": None,
                    "recap": None,
                    "question_plan": None,
                }
                for kind in ("result", "recap", "plan"):
                    if row[f"{kind}_payload"] is not None:
                        record["question_plan" if kind == "plan" else kind] = {"session_id": session_id,
                                        "payload": json.loads(row[f"{kind}_payload"]),
                                        "created_at": row[f"{kind}_created"]}
                history.append(record)
                if len(history) == limit:
                    break
            return history
