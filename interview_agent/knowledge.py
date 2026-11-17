"""Owner-scoped, model-free local project knowledge and immutable citations."""

import asyncio
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from github_source.authorization import GitHubAuthorization
from github_source.github_api import GitHubClient, parse_repository
from github_source.ingest import source_lines
from interview_hub.store import ConflictError, NotFoundError
from .knowledge_source import github_documents, manual_documents

INDEX_VERSION = 3


def identity(prefix, value):
    return prefix + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]


def tokens(text):
    # Windows OCR separates Chinese characters with spaces; normalize only
    # horizontal CJK gaps for search, while preserving the cited original text.
    text = re.sub(r'(?<=[\u3400-\u9fff])[ \t\u3000]+(?=[\u3400-\u9fff])', '', text)
    terms = []
    for word in re.findall(r"[\u3400-\u9fff]+|[A-Za-z0-9_]+", text):
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            terms.extend(word[i:i + 2] for i in range(len(word) - 1))
            if len(word) == 1:
                terms.append(word)
        else:
            terms.append(word.lower())
            terms.extend(part.lower() for part in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+", word))
    return list(dict.fromkeys(terms))


def coverage(entries, inventory_complete):
    rows = [e for e in entries if e.get("type") != "tree"]
    return {"inventory_complete": inventory_complete, "total_files": len(rows),
            "indexed_files": sum(e["status"] == "downloaded" for e in rows),
            "statuses": dict(Counter(e["status"] for e in rows)),
            "exclusion_reasons": dict(Counter(e["reason"] for e in rows if e.get("reason"))),
            "document_files": sum('document_units' in e for e in rows),
            "document_units": sum(e.get('document_units', 0) for e in rows),
            "document_text_units": sum(e.get('text_units', 0) for e in rows),
            "document_ocr_units": sum(e.get('ocr_units', 0) for e in rows),
            "complete": inventory_complete and not any(e["status"] in {"failed", "pending"}
                or e.get("reason") in {"snapshot_budget", "file_size_budget"}
                or str(e.get('reason', '')).startswith('document_') for e in rows)}


class KnowledgeService:
    def __init__(self, business_db, owner, root, *, authorization=None, client_factory=None):
        self.business_db, self.owner, self.root = Path(business_db), owner, Path(root)
        self.directory = self.root / "knowledge" / identity("owner_", owner)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "knowledge.db"
        self.auth = authorization or GitHubAuthorization(root)
        self.owns_auth = authorization is None
        self.client_factory = client_factory or (lambda: GitHubClient(token=self.auth.token()))
        self.tasks = {}
        self.semaphore = asyncio.Semaphore(1)
        self.stopped = threading.Event()
        with self.connection() as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,snapshot TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS chunks_snapshot ON chunks(snapshot);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(terms);
            """)
            for row in db.execute("SELECT id,payload FROM sources").fetchall():
                source = json.loads(row[1])
                if source["status"] in {"queued", "building"}:
                    source.update(status="interrupted", error="build_interrupted")
                    db.execute("UPDATE sources SET payload=? WHERE id=?", (json.dumps(source), row[0]))

    def connection(self):
        return closing(sqlite3.connect(self.path, timeout=10))

    def projects(self):
        if not self.business_db.is_file():
            return []
        with closing(sqlite3.connect(self.business_db)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='career_records'").fetchone():
                return []
            return [json.loads(row[0]) for row in db.execute(
                "SELECT payload FROM career_records WHERE owner=? AND kind='project' ORDER BY id", (self.owner,))]

    def get(self, table, key):
        # table is internal, never a request parameter.
        with self.connection() as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (key,)).fetchone()
        if row is None:
            raise NotFoundError("Knowledge record not found")
        return json.loads(row[0])

    def save_source(self, source):
        with self.connection() as db, db:
            # Preserve project associations that arrived while a worker was building.
            old = db.execute("SELECT payload FROM sources WHERE id=?", (source["source_id"],)).fetchone()
            if old:
                source["project_ids"] = sorted(set(source["project_ids"] + json.loads(old[0])["project_ids"]))
            db.execute("INSERT OR REPLACE INTO sources VALUES(?,?)", (source["source_id"], json.dumps(source, ensure_ascii=False)))

    def all_sources(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT payload FROM sources ORDER BY id")]

    def list_sources(self, limit=20, offset=0):
        if type(limit) is not int or type(offset) is not int or not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Invalid pagination")
        with self.connection() as db:
            total = db.execute("SELECT count(*) FROM sources").fetchone()[0]
            rows = db.execute("SELECT payload FROM sources ORDER BY id LIMIT ? OFFSET ?", (limit, offset))
            return {"items": [json.loads(row[0]) for row in rows], "total": total,
                    "next_offset": offset + limit if offset + limit < total else None}

    def register(self, data):
        if set(data) == {"project_id"}:
            project = next((p for p in self.projects() if p["project_id"] == data["project_id"] and p.get("is_demo") is False), None)
            if project is None:
                raise NotFoundError("Project not found")
            if not project.get("source_commit"):
                return {"status": "waiting_for_source", "project_ids": [project["project_id"]], "snapshot_id": None}
            repository = project["repository"]
            commit = project["source_commit"]
            kind = project.get("source_type", "github")
            project_ids = [project["project_id"]]
        elif set(data) == {"repository"}:
            repository = "/".join(parse_repository(data["repository"]))
            existing = [s for s in self.all_sources() if s["source_type"] == "github"
                        and s["repository"].lower() == repository.lower()]
            if existing:
                self.schedule(existing[0])
                return existing[0]
            commit, kind, project_ids = None, "github", []
        else:
            raise ValueError("Expected repository or project_id")
        if kind == "github":
            repository = "/".join(parse_repository(repository))
        if commit and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise ValueError("Invalid pinned commit")
        # Reuse a source selected before preparation as soon as its version is known.
        existing = next((s for s in self.all_sources() if s["source_type"] == kind
                         and s["repository"].lower() == repository.lower() and s.get("source_commit") == commit), None)
        sid = existing["source_id"] if existing else identity("ksrc_", [kind, repository.lower(), commit])
        source = existing or {"source_id": sid, "repository": repository, "source_commit": commit,
            "source_type": kind, "project_ids": [], "status": "pending", "snapshot_id": None,
            "coverage": None, "index_version": INDEX_VERSION}
        source["project_ids"] = sorted(set(source["project_ids"] + project_ids))
        self.save_source(source)
        self.schedule(source)
        return source

    def schedule(self, source):
        sid = source["source_id"]
        if sid in self.tasks or self.stopped.is_set():
            return
        if source["status"] in {"ready", "partial", "empty"} and source.get("index_version") == INDEX_VERSION:
            report = source.get("coverage") or {}
            incomplete_documents = report.get('document_text_units', 0) < report.get('document_units', 0)
            if not report.get("statuses", {}).get("failed") and not incomplete_documents:
                try:
                    self.get("snapshots", source["snapshot_id"])
                    return
                except NotFoundError:
                    pass
        source.update(status="queued", error=None)
        self.save_source(source)
        task = asyncio.create_task(self.build(source))
        self.tasks[sid] = task
        task.add_done_callback(lambda done: self.tasks.pop(sid, None))

    async def warmup(self):
        for project in self.projects():
            if project.get("is_demo") is False:
                self.register({"project_id": project["project_id"]})
        for source in self.all_sources():
            self.schedule(source)
        return {"queued": len(self.tasks), "source_count": len(self.all_sources())}

    async def close(self):
        self.stopped.set()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        if self.owns_auth:
            self.auth.close()

    async def build(self, source):
        async with self.semaphore:
            if self.stopped.is_set():
                source.update(status="interrupted", error="build_interrupted")
                self.save_source(source)
                return
            try:
                await asyncio.to_thread(self.build_sync, source)
            except Exception:
                # Never include source text, local paths or upstream bodies in errors.
                source.update(status="interrupted" if self.stopped.is_set() else "failed",
                              error="build_interrupted" if self.stopped.is_set() else "source_build_failed")
                self.save_source(source)

    def progress(self, source, entries):
        source.update(status="building", processed_files=len(entries))
        self.save_source(source)

    def build_sync(self, source):
        started = time.perf_counter()
        self.progress(source, [])
        if source["source_type"] == "manual":
            project = next(p for p in self.projects() if p["project_id"] in source["project_ids"])
            documents, entries, inventory, files = manual_documents(project)
        else:
            documents, entries, inventory, files = github_documents(self.root, self.directory / "sources",
                source, self.client_factory, self.stopped, self.progress)
        report = coverage(entries, inventory)
        source["coverage"] = report
        if not documents and not report["complete"]:
            raise ValueError("No available source content")
        snapshot_id = identity("ksnap_", [INDEX_VERSION, source["source_type"], source["repository"].lower(),
            source["source_commit"], files, entries])
        context = {"snapshot_id": snapshot_id, "source_type": source["source_type"],
            "repository": source["repository"], "source_commit": source["source_commit"], "files": files,
            "coverage": report, "file_statuses": entries, "index_version": INDEX_VERSION,
            "limitations": ["关键词检索不等同于语义理解；未执行项目代码。", "仓库内容不证明个人完成或独立掌握。"],
            "source_notice": "用户提供的经历原文，未经独立核验。" if source["source_type"] == "manual" else "固定提交的项目原文。"}
        if report['document_files']:
            context['limitations'].append('文档为文字提取结果，OCR 识别内容需对照原页核对；不代表已核验文档中的成果声明。')
        chunks = []
        for document in documents:
            lines = source_lines(document["text"])
            for offset in range(0, len(lines), 60):
                end = min(offset + 60, len(lines))
                text = "\n".join(lines[offset:end])
                chunk = {k: document[k] for k in ("path", "sha256", "source_kind", "source_url")}
                if document['source_kind'] == 'document_text':
                    chunk.update({k: document[k] for k in ('unit_type', 'unit_number', 'extraction_kind', 'text_sha256', 'needs_review')})
                    chunk.update(line_basis='extracted_text', **{
                        'page_number' if document['unit_type'] == 'page' else 'slide_number': document['unit_number']})
                chunk.update(snapshot_id=snapshot_id, source_commit=source["source_commit"], line_start=offset + 1,
                             line_end=end, text=text, personal_contribution="unconfirmed")
                if source["source_type"] == "github" and document['source_kind'] != 'document_text':
                    chunk["source_url"] += f"#L{offset + 1}-L{end}"
                chunk["evidence_id"] = identity("kev_", [snapshot_id, document["path"],
                    document.get('unit_type'), document.get('unit_number'), offset + 1, end])
                chunks.append((chunk, " ".join(tokens(document["path"] + " " + text))))
        if self.stopped.is_set():
            raise InterruptedError("Build interrupted")
        with self.connection() as db, db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM snapshots WHERE id=?", (snapshot_id,)).fetchone():
                db.execute("INSERT INTO snapshots VALUES(?,?)", (snapshot_id, json.dumps(context, ensure_ascii=False)))
                for chunk, terms in chunks:
                    cursor = db.execute("INSERT INTO chunks(snapshot,payload) VALUES(?,?)", (snapshot_id, json.dumps(chunk, ensure_ascii=False)))
                    db.execute("INSERT INTO search(rowid,terms) VALUES(?,?)", (cursor.lastrowid, terms))
            # Source pointer and its searchable contents become visible together.
            old = json.loads(db.execute("SELECT payload FROM sources WHERE id=?", (source["source_id"],)).fetchone()[0])
            source.update(project_ids=old["project_ids"], snapshot_id=snapshot_id, coverage=report,
                status="empty" if not chunks else "ready" if report["complete"] else "partial",
                error=None, index_version=INDEX_VERSION, build_ms=round((time.perf_counter() - started) * 1000, 2))
            db.execute("UPDATE sources SET payload=? WHERE id=?", (json.dumps(source, ensure_ascii=False), source["source_id"]))

    def context(self, snapshot_id):
        try:
            context = self.get("snapshots", snapshot_id)
        except NotFoundError:
            if any(s["source_id"] == snapshot_id for s in self.all_sources()):
                raise ConflictError("Knowledge is not ready; use an available snapshot_id") from None
            raise
        sources = [s for s in self.all_sources() if s.get("snapshot_id") == snapshot_id]
        project_ids = sorted({pid for s in sources for pid in s["project_ids"]})
        claims = []
        if self.business_db.is_file():
            with closing(sqlite3.connect(self.business_db)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='materials'").fetchone():
                    for row in db.execute("SELECT payload_json FROM materials WHERE owner=?", (self.owner,)):
                        material = json.loads(row[0])
                        if (material.get("is_demo") is False and material.get("source_commit") == context["source_commit"]
                                and material.get("source_repository", "").lower() == context["repository"].lower()):
                            claims.extend(c for c in material["claims"] if c.get("personal_contribution") == "confirmed")
        return {**context, "project_ids": project_ids,
                "confirmed_contributions": list({c["claim_id"]: c for c in claims}.values())}

    def search(self, data):
        if set(data) - {"snapshot_ids", "query", "top_k", "source_kind"}:
            raise ValueError("Unknown search fields")
        ids, query, limit = data.get("snapshot_ids"), data.get("query"), data.get("top_k", 8)
        source_kind = data.get('source_kind')
        if source_kind is not None and (not isinstance(source_kind, str)
                or source_kind not in {'source_text', 'document_text', 'user_supplied'}):
            raise ValueError('Invalid source kind')
        if (not isinstance(ids, list) or not ids or len(ids) > 100 or any(not isinstance(i, str) for i in ids)
                or not isinstance(query, str) or not 1 <= len(query.strip()) <= 1000
                or type(limit) is not int or not 1 <= limit <= 20):
            raise ValueError("Invalid search")
        for key in ids:
            try:
                self.get("snapshots", key)
            except NotFoundError:
                if any(s["source_id"] == key for s in self.all_sources()):
                    raise ConflictError("Source is not ready; use an available snapshot_id") from None
                raise
        terms = tokens(query)[:128]
        if not terms:
            raise ValueError("No searchable terms")
        expression = " OR ".join('"' + t + '"' for t in terms)
        placeholders = ",".join("?" for _ in ids)
        started = time.perf_counter()
        with self.connection() as db:
            rows = db.execute(f"""SELECT chunks.payload,bm25(search) FROM search JOIN chunks ON chunks.id=search.rowid
                WHERE search MATCH ? AND chunks.snapshot IN ({placeholders})
                AND (? IS NULL OR json_extract(chunks.payload,'$.source_kind')=?)
                ORDER BY bm25(search),chunks.id LIMIT ?""", (expression, *ids, source_kind, source_kind, limit)).fetchall()
        return {"items": [{**json.loads(r[0]), "score": -r[1]} for r in rows],
                "snapshot_ids": ids, "search_ms": round((time.perf_counter() - started) * 1000, 2)}
