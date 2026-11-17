"""Owner-scoped career artifacts; published materials and resumes are immutable."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

from .store import ConflictError, NotFoundError


class CareerRecords:
    def __init__(self, path, owner):
        self.path, self.owner = path, owner
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS career_records (
                owner TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(owner,kind,id))""")

    def put(self, kind, key, value, *, replace=False):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM career_records WHERE owner=? AND kind=? AND id=?",
                             (self.owner, kind, key)).fetchone()
            if old and old[0] != encoded and not replace:
                raise ConflictError("Artifact is immutable")
            db.execute("""INSERT INTO career_records VALUES(?,?,?,?,?) ON CONFLICT(owner,kind,id)
                       DO UPDATE SET payload=excluded.payload""", (self.owner, kind, key, encoded, datetime.now(timezone.utc).isoformat()))
        return value

    def get(self, kind, key):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT payload FROM career_records WHERE owner=? AND kind=? AND id=?",
                             (self.owner, kind, key)).fetchone()
        if not row:
            raise NotFoundError("Career artifact not found")
        return json.loads(row[0])

    def list(self, kind, *, limit=100, offset=0):
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid artifact page")
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT payload FROM career_records WHERE owner=? AND kind=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                              (self.owner, kind, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]
