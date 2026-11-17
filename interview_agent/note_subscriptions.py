"""Durable single-note schedules and a transactional application inbox."""

import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from interview_hub.store import NotFoundError, ConflictError
from .xhs_notes import NoteCollector, NoteFailure, checked_url, parse_note


PERMANENT = {"need_login", "id_mismatch", "invalid_url", "no_post_id", "not_found"}


class NoteSubscriptions:
    def __init__(self, root, owner, *, collector=None, clock=time.time):
        self.path = Path(root) / ("note-subscriptions-" + hashlib.sha256(owner.encode()).hexdigest()[:20] + ".sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.stop = threading.Event()
        self.tick_lock = threading.Lock()
        self.task = None
        self.heartbeat = None
        self.worker_error = None
        self.collector = collector or NoteCollector(self.request_gate)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, url TEXT NOT NULL UNIQUE, config TEXT NOT NULL,
                    enabled INTEGER NOT NULL, next_run REAL NOT NULL,
                    lease_id TEXT, lease_until REAL, failures INTEGER NOT NULL DEFAULT 0,
                    last_reason TEXT, last_checked REAL, last_success REAL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, started REAL NOT NULL,
                    finished REAL, reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, hash TEXT NOT NULL,
                    source_url TEXT NOT NULL, fetched REAL NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(job_id, hash));
                CREATE TABLE IF NOT EXISTS inbox (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, note_id TEXT,
                    created REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    read_at REAL);
                CREATE TABLE IF NOT EXISTS rate_gate (id INTEGER PRIMARY KEY, next_request REAL NOT NULL);
                INSERT OR IGNORE INTO rate_gate VALUES (1, 0);
                CREATE INDEX IF NOT EXISTS jobs_due ON jobs(enabled, next_run);
                CREATE INDEX IF NOT EXISTS runs_job ON runs(job_id, started);
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def request_gate(self):
        if self.stop.is_set():
            raise NoteFailure("stopped")
        # Reserve network slots across workers/processes, including redirects.
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            due = max(self.clock(), db.execute("SELECT next_request FROM rate_gate WHERE id=1").fetchone()[0])
            db.execute("UPDATE rate_gate SET next_request=? WHERE id=1", (due + 4,))
        if self.stop.wait(max(0, due - self.clock())):
            raise NoteFailure("stopped")

    def create(self, url, interval_hours=24, keywords=None):
        checked_url(url)
        if type(interval_hours) is not int or not 1 <= interval_hours <= 168:
            raise ValueError("Interval must be 1..168 hours")
        keywords = [] if keywords is None else keywords
        if (not isinstance(keywords, list) or len(keywords) > 10
                or any(not isinstance(k, str) or not 1 <= len(k.strip()) <= 50 for k in keywords)):
            raise ValueError("Provide at most ten keywords")
        config = {"interval_hours": interval_hours, "keywords": list(dict.fromkeys(k.strip() for k in keywords))}
        key = "sub_" + uuid.uuid4().hex
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE url=?", (url,)).fetchone()
            if existing:
                if json.loads(existing["config"]) != config:
                    if existing["enabled"]:
                        raise ConflictError("Pause the existing subscription before changing its schedule")
                    db.execute("UPDATE jobs SET config=?,enabled=1,next_run=?,failures=0 WHERE id=?",
                               (json.dumps(config, ensure_ascii=False), self.clock(), existing["id"]))
                    return self.job_view(db.execute("SELECT * FROM jobs WHERE id=?", (existing["id"],)).fetchone())
                return self.job_view(existing)
            if db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 100:
                raise ValueError("At most 100 explicit note subscriptions")
            db.execute("INSERT INTO jobs(id,url,config,enabled,next_run) VALUES(?,?,?,1,?)",
                       (key, url, json.dumps(config, ensure_ascii=False), self.clock()))
        return self.get(key)

    @staticmethod
    def job_view(row):
        return {k: row[k] for k in ("id", "url", "enabled", "next_run", "failures", "last_reason", "last_checked", "last_success")} | json.loads(row["config"])

    def get(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
        if row is None:
            raise NotFoundError("Subscription not found")
        return self.job_view(row)

    def listing(self):
        with self.db() as db:
            return [self.job_view(row) for row in db.execute("SELECT * FROM jobs ORDER BY rowid DESC")]

    def enable(self, key, enabled):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE id=?", (key,)).fetchone()
            if row is None:
                raise NotFoundError("Subscription not found")
            if row["lease_id"]:
                db.execute("UPDATE runs SET reason='cancelled',finished=? WHERE id=?", (self.clock(), row["lease_id"]))
            db.execute("UPDATE jobs SET enabled=?,next_run=?,lease_id=NULL,lease_until=NULL,failures=0 WHERE id=?",
                       (int(enabled), self.clock(), key))
        return self.get(key)

    def claim(self):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM jobs WHERE enabled=1 AND next_run<=?
                AND (lease_until IS NULL OR lease_until<=?) ORDER BY next_run,rowid LIMIT 1""", (self.clock(), self.clock())).fetchone()
            if row is None:
                return None
            if row["lease_id"]:
                db.execute("UPDATE runs SET reason='interrupted',finished=? WHERE id=?", (self.clock(), row["lease_id"]))
            lease = "run_" + uuid.uuid4().hex
            db.execute("UPDATE jobs SET lease_id=?,lease_until=? WHERE id=?", (lease, self.clock() + 180, row["id"]))
            db.execute("INSERT INTO runs(id,job_id,started,reason) VALUES(?,?,?,'running')", (lease, row["id"], self.clock()))
            return dict(row) | {"lease_id": lease}

    @staticmethod
    def revision(value):
        return hashlib.sha256(json.dumps({k: value[k] for k in ("title", "author", "content", "images")},
                                         ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def put_note(self, db, job_id, url, value, notify):
        if value.get("ok") is not True or value.get("reason") != "success" or not value.get("content", "").strip():
            raise ValueError("Cannot persist a failed or empty note")
        hashed = self.revision(value)
        key = "note_" + uuid.uuid4().hex
        inserted = db.execute("INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?)",
            (key, job_id, hashed, url, self.clock(), json.dumps(value, ensure_ascii=False))).rowcount
        row = db.execute("SELECT id FROM notes WHERE job_id=? AND hash=?", (job_id, hashed)).fetchone()
        if inserted and notify:
            self.push(db, job_id, row["id"], "note_updated", {"title": value["title"], "source_url": url})
        return row["id"], bool(inserted)

    def push(self, db, job_id, note_id, kind, payload):
        db.execute("INSERT INTO inbox VALUES(?,?,?,?,?,?,NULL)",
            ("msg_" + uuid.uuid4().hex, job_id, note_id, self.clock(), kind, json.dumps(payload, ensure_ascii=False)))

    def complete(self, job, value):
        reason, at = value["reason"], self.clock()
        config = json.loads(job["config"])
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
            if (current["lease_id"] != job["lease_id"] or not current["enabled"]
                    or current["lease_until"] <= at):
                return  # A paused or expired worker cannot commit late results.
            if reason == "stopped":
                db.execute("UPDATE runs SET reason='interrupted',finished=? WHERE id=?", (at, job["lease_id"]))
                db.execute("UPDATE jobs SET lease_id=NULL,lease_until=NULL WHERE id=?", (job["id"],))
                return
            failures = 0 if value["ok"] else current["failures"] + 1
            paused = reason in PERMANENT or failures >= 3 and reason in {"parse_error", "empty_content", "internal_error"}
            if value["ok"]:
                haystack = (value["title"] + "\n" + value["content"]).casefold()
                matched = not config["keywords"] or any(k.casefold() in haystack for k in config["keywords"])
                self.put_note(db, job["id"], job["url"], value, matched)
            elif paused or failures == 1:
                self.push(db, job["id"], None, "subscription_paused" if paused else "collection_failed", {"reason": reason})
            delay = config["interval_hours"] * 3600
            if not value["ok"]:
                delay = max(delay, min(7 * 86400, 3600 * 2 ** min(failures, 8)))
            db.execute("""UPDATE jobs SET enabled=?,next_run=?,lease_id=NULL,lease_until=NULL,failures=?,
                last_reason=?,last_checked=?,last_success=CASE WHEN ? THEN ? ELSE last_success END WHERE id=?""",
                (int(not paused), at + delay, failures, reason, at, int(value["ok"]), at, job["id"]))
            db.execute("UPDATE runs SET reason=?,finished=? WHERE id=?", (reason, at, job["lease_id"]))

    def tick(self):
        if not self.tick_lock.acquire(blocking=False):
            return
        try:
            self.heartbeat = self.clock()
            job = None if self.stop.is_set() else self.claim()
            if job:
                try:
                    value = self.collector.fetch(job["url"])
                except Exception:
                    value = {"ok": False, "reason": "internal_error"}
                self.complete(job, value)
                self.worker_error = None
        except Exception:
            self.worker_error = "scheduler_error"
        finally:
            self.heartbeat = self.clock()
            self.tick_lock.release()

    async def start(self):
        async def loop():
            while not self.stop.is_set():
                await asyncio.to_thread(self.tick)
                await asyncio.to_thread(self.stop.wait, 2)
        self.task = asyncio.create_task(loop())

    async def close(self):
        self.stop.set()
        if self.task:
            await self.task

    def collect(self, url):
        if not self.tick_lock.acquire(blocking=False):
            from .xhs_notes import result
            return result("collector_busy")
        try:
            value = self.collector.fetch(url)
            if not value["ok"]:
                return value
            with self.db() as db:
                db.execute("BEGIN IMMEDIATE")
                note_id, inserted = self.put_note(db, "manual:" + hashlib.sha256(url.encode()).hexdigest(), url, value, True)
            return {**value, "note_id": note_id, "saved": inserted, "source_url": url}
        finally:
            self.tick_lock.release()

    def inbox(self, limit=30, offset=0):
        with self.db() as db:
            rows = db.execute("SELECT * FROM inbox ORDER BY created DESC,rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            unread = db.execute("SELECT count(*) FROM inbox WHERE read_at IS NULL").fetchone()[0]
            total = db.execute("SELECT count(*) FROM inbox").fetchone()[0]
        return {"items": [{k: row[k] for k in ("id", "job_id", "note_id", "created", "kind", "read_at")} | json.loads(row["payload"]) for row in rows],
                "unread": unread, "total": total, "next_offset": offset + len(rows) if offset + len(rows) < total else None}

    def read(self, key):
        with self.db() as db:
            if not db.execute("UPDATE inbox SET read_at=COALESCE(read_at,?) WHERE id=?", (self.clock(), key)).rowcount:
                raise NotFoundError("Message not found")
        return {"ok": True}

    def note(self, key):
        with self.db() as db:
            row = db.execute("SELECT * FROM notes WHERE id=?", (key,)).fetchone()
        if row is None:
            raise NotFoundError("Note not found")
        return {"id": row["id"], "source_url": row["source_url"], "fetched_at": row["fetched"], **json.loads(row["payload"])}

    def runs(self, key, limit=30):
        self.get(key)
        with self.db() as db:
            return {"items": [dict(row) for row in db.execute("SELECT * FROM runs WHERE job_id=? ORDER BY started DESC,rowid DESC LIMIT ?", (key, limit))]}

    def health(self):
        at = self.clock()
        expired = overdue = paused = None
        try:
            with self.db() as db:
                integrity = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
                db.execute("SAVEPOINT health_write")
                db.execute("INSERT OR REPLACE INTO rate_gate VALUES(2,0)")
                db.execute("ROLLBACK TO health_write")
                db.execute("RELEASE health_write")
                expired = db.execute("SELECT count(*) FROM jobs WHERE lease_until<=?", (at,)).fetchone()[0]
                overdue = db.execute("SELECT count(*) FROM jobs WHERE enabled=1 AND next_run<? AND lease_id IS NULL", (at - 300,)).fetchone()[0]
                paused = db.execute("SELECT count(*) FROM jobs WHERE enabled=0").fetchone()[0]
        except sqlite3.Error:
            integrity = False
        alive = bool(self.task and not self.task.done() and self.heartbeat is not None and at - self.heartbeat < 240)
        sample_id = "0" * 24
        sample = {"noteData": {"data": {"noteData": {"noteId": sample_id, "desc": "自检样例 {undefined}", "title": "自检", "user": {}}}}}
        parser_ok = parse_note("window.__INITIAL_STATE__=" + json.dumps(sample), sample_id)["ok"]
        return {"ok": integrity and parser_ok and alive and not self.worker_error and not expired and not overdue,
                "database_ok": integrity, "scheduler_alive": alive, "last_heartbeat": self.heartbeat,
                "parser_fixture_ok": parser_ok,
                "worker_error": self.worker_error, "expired_leases": expired, "overdue_jobs": overdue,
                "paused_jobs": paused, "channel": "application_inbox", "external_site_verified": False}

    async def command(self, text):
        """Explicit commands avoid model-generated URLs and keep xsec tokens local."""
        parts = text.strip().split()
        name = parts[0] if parts else ""
        if name == "/面经收藏" and len(parts) == 2:
            value = await asyncio.to_thread(self.collect, parts[1])
            return "已收藏面经：" + value["title"] + "\n" + value["content"][:4000] if value["ok"] else "采集失败：" + value["reason"]
        if name == "/面经订阅" and 2 <= len(parts) <= 4:
            row = self.create(parts[1], int(parts[2]) if len(parts) >= 3 else 24,
                              parts[3].replace("，", ",").split(",") if len(parts) == 4 else [])
            return f"订阅已保存：{row['id']}；状态：{'启用' if row['enabled'] else '暂停（需显式恢复）'}；每 {row['interval_hours']} 小时检查这一条笔记；通知渠道：应用内消息。"
        if name in {"/面经暂停", "/面经恢复"} and len(parts) == 2:
            row = self.enable(parts[1], name == "/面经恢复")
            return f"{row['id']} 已{'恢复' if row['enabled'] else '暂停'}。"
        if name == "/面经订阅列表" and len(parts) == 1:
            return "\n".join(f"{r['id']}：{'启用' if r['enabled'] else '暂停'}，{r['interval_hours']} 小时，最近结果 {r['last_reason'] or '等待首次检查'}" for r in self.listing()) or "暂无面经订阅。"
        if name == "/面经消息" and len(parts) == 1:
            data = self.inbox()
            return f"未读 {data['unread']} 条。\n" + ("\n".join(f"{r['id']}：{r.get('title') or r.get('reason') or r['kind']}；笔记 {r['note_id'] or '无'}" for r in data["items"]) or "暂无消息。")
        if name == "/面经查看" and len(parts) == 2:
            row = self.note(parts[1])
            return row["title"] + "\n作者：" + row["author"] + "\n" + row["content"][:6000]
        if name == "/面经已读" and len(parts) == 2:
            self.read(parts[1])
            return "该消息已标记为已读。"
        if name == "/面经自检" and len(parts) == 1:
            value = await asyncio.to_thread(self.health)
            return json.dumps(value, ensure_ascii=False)
        return ("用法：/面经收藏 链接；/面经订阅 链接 [周期小时1至168] [关键词逗号分隔]；"
                "/面经订阅列表；/面经暂停 订阅ID；/面经恢复 订阅ID；/面经消息；/面经查看 笔记ID；/面经已读 消息ID；/面经自检。"
                "只处理明确给出的单条链接，不搜索或批量抓取。")
