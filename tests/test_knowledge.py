import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from github_source.ingest import blob_sha, ingest, source_lines
from interview_agent.knowledge import INDEX_VERSION
from interview_agent.knowledge_api import create_knowledge_app
from interview_hub.career_store import CareerRecords
from interview_hub.store import Store
from test_ingest import FakeClient, SHA

TOKEN = "knowledge-synthetic-service-token-only"


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "interview.db"
        Store(self.db)
        self.records = CareerRecords(self.db, "alice")
        self.client_calls = 0
        self.remote = FakeClient()
        self.remote.refs = []
        resolve = self.remote.resolve_repository
        def pinned(repo, ref):
            self.remote.refs.append(ref)
            return resolve(repo, ref)
        self.remote.resolve_repository = pinned
        self.client = None

    def tearDown(self):
        if self.client:
            self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def factory(self):
        self.client_calls += 1
        return self.remote

    def offline(self):
        raise AssertionError("Offline operation must not create a network client")

    def start(self, owner="alice", factory=None):
        self.client = TestClient(create_knowledge_app(self.db, owner, TOKEN, self.root,
                                                     client_factory=factory or self.factory))
        self.client.__enter__()
        return self.client

    def call(self, method, path, data=None, status=200):
        response = self.client.request(method, "/v1/knowledge" + path, json=data,
                                       headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def wait(self):
        async def drain():
            service = self.client.app.state.knowledge
            await asyncio.gather(*list(service.tasks.values()))
        self.client.portal.call(drain)
        rows = self.call("GET", "/sources?limit=100")["items"]
        self.assertTrue(all(s["status"] not in {"queued", "building"} for s in rows))
        return rows

    def project(self, pid="project_one", commit=SHA):
        value = {"project_id": pid, "repository": "example/demo", "source_commit": commit,
                 "project_snapshot_id": f"github:123:{commit}", "is_demo": False,
                 "status": "ready", "claims": [], "contribution": "用户自述职责"}
        self.records.put("project", pid, value)
        return value

    def cached(self, sources=None, max_files=250):
        return ingest(FakeClient(sources), "example/demo", self.root / "sources", max_files=max_files)

    def test_offline_all_file_types_citations_and_warmup_idempotence(self):
        sources = {"src/session.py": "def permission_check():\n    return '项目登录鉴权'\n".encode(),
                   "tests/test_session.py": b"assert permission_check()\n", "README.md": "项目知识库说明".encode(),
                   "config.yaml": b"permission_timeout: 30\n", "node_modules/x.js": b"excluded",
                   ".env": b"CREDENTIAL=excluded", "image.png": b"\0binary"}
        self.cached(sources)
        self.project()
        with patch.dict("os.environ", {}, clear=True):
            self.start(factory=self.offline)
            source = self.wait()[0]
            self.assertEqual(source["status"], "ready")
            snapshot = source["snapshot_id"]
            context = self.call("GET", f"/snapshots/{snapshot}/context")
            self.assertEqual(len(context["files"]), 4)
            self.assertEqual(context["coverage"]["exclusion_reasons"]["sensitive_path"], 1)
            timings = []
            for query in ("登录鉴权", "permission_check", "知识库", "permission_timeout"):
                result = self.call("POST", "/search", {"snapshot_ids": [snapshot], "query": query})
                timings.append(result["search_ms"])
                self.assertTrue(result["items"], query)
                for item in result["items"]:
                    raw = sources[item["path"]]
                    self.assertEqual(item["text"], "\n".join(source_lines(raw.decode())[item["line_start"]-1:item["line_end"]]))
                    self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
                    self.assertIn(SHA, item["source_url"])
            before = deepcopy(source)
            for _ in range(3):
                result = self.call("POST", "/warmup", {}, 202)
                self.assertEqual(result["queued"], 0)
            self.assertEqual(self.wait()[0], before)
            print("knowledge benchmark:", source["build_ms"], "ms build; search ms:", timings)

    def test_more_than_250_files_are_completed_at_the_same_commit(self):
        self.remote.sources = {f"src/f{i:03}.py": f"value_{i} = {i}\n".encode() for i in range(260)}
        self.remote.archive_sources = self.remote.sources
        self.cached(self.remote.sources)
        self.project()
        self.start()
        source = self.wait()[0]
        self.assertEqual(source["coverage"]["indexed_files"], 260)
        self.assertTrue(source["coverage"]["complete"])
        self.assertEqual(self.remote.blob_calls, 10)
        self.assertEqual(self.remote.refs, [])  # Local pinned inventory, never resolve main again.
        result = self.call("POST", "/search", {"snapshot_ids": [source["snapshot_id"]], "query": "value_259"})
        self.assertTrue(any(item["path"] == "src/f259.py" for item in result["items"]))

    def test_selection_registers_without_model_and_retries_do_not_duplicate(self):
        self.start()
        rows = [self.call("POST", "/sources", {"repository": "example/demo"}, 202) for _ in range(3)]
        self.assertEqual(len({s["source_id"] for s in rows}), 1)
        source = self.wait()[0]
        self.assertEqual(source["status"], "ready")
        self.assertEqual(self.remote.refs, [None])
        self.call("POST", "/warmup", {}, 202)
        self.assertEqual(self.client_calls, 1)

    def test_auth_owner_validation_and_not_ready_are_explicit(self):
        self.project()
        self.start(owner="bob")
        self.assertEqual(self.client.get("/v1/knowledge/sources").status_code, 401)
        self.assertEqual(self.call("GET", "/sources")["total"], 0)
        self.call("POST", "/sources", {"project_id": "project_one"}, 404)
        self.call("POST", "/sources", {"repository": "https://example.invalid/repo"}, 400)
        self.call("POST", "/sources", {"repository": "example/demo", "path": "C:/"}, 400)
        self.call("POST", "/warmup", {"owner": "alice"}, 400)
        service = self.client.app.state.knowledge
        service.save_source({"source_id": "ksrc_wait", "project_ids": [], "source_type": "github",
            "repository": "example/demo", "source_commit": SHA, "status": "building", "snapshot_id": None})
        self.call("GET", "/snapshots/ksrc_wait/context", status=409)
        self.call("POST", "/search", {"snapshot_ids": ["ksrc_wait"], "query": "x"}, 409)
        for body in ({"snapshot_ids": [], "query": "x"}, {"snapshot_ids": ["unknown"], "query": "x", "top_k": 21}):
            self.call("POST", "/search", body, 400)

    def test_unavailable_or_tampered_content_is_not_reported_as_empty_ready(self):
        directory, _ = self.cached()
        (directory / "source/src/sign.py").write_text("tampered", encoding="utf-8")
        self.project()
        def unavailable():
            raise OSError("synthetic offline")
        self.start(factory=unavailable)
        source = self.wait()[0]
        self.assertEqual(source["status"], "failed")
        self.assertIsNone(source["snapshot_id"])
        self.assertEqual(source["coverage"]["exclusion_reasons"]["local_content_changed"], 1)

    def test_partial_and_budget_coverage_are_visible(self):
        directory, manifest = self.cached({"a.py": b"present\n", "b.py": b"missing\n"})
        (directory / "source/b.py").unlink()
        manifest["files"].append({"path": "huge.txt", "type": "blob", "size": 600000, "sha": "c"*40})
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.project()
        def unavailable():
            raise OSError("synthetic offline")
        self.start(factory=unavailable)
        source = self.wait()[0]
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["coverage"]["exclusion_reasons"], {"source_unavailable": 1, "file_size_budget": 1})
        context = self.call("GET", f"/snapshots/{source['snapshot_id']}/context")
        self.assertFalse(context["coverage"]["complete"])

    def test_large_attachments_are_declared_exclusions_not_text_coverage_gaps(self):
        large = b"x" * (512 * 1024 + 1)
        self.cached({"src/main.py": b"def complete_source():\n    return True\n",
                     "output/diagram.PNG": large, "output/raw-image.jpg": large,
                     "output/legacy.ppt": large, "output/archive.zip": b"\0binary"})
        self.project()
        self.start(factory=self.offline)
        source = self.wait()[0]
        self.assertEqual(source["status"], "ready")
        self.assertTrue(source["coverage"]["complete"])
        self.assertEqual(source["coverage"]["indexed_files"], 1)
        self.assertEqual(source["coverage"]["exclusion_reasons"], {"non_text_attachment": 4})
        context = self.call("GET", f"/snapshots/{source['snapshot_id']}/context")
        self.assertEqual([f["path"] for f in context["files"]], ["src/main.py"])

    def test_manual_originals_are_indexed_even_when_model_preparation_failed(self):
        value = self.project()
        value.update(source_type="manual", status="failed", repository="真实经历",
                     experience={"context": "客户研究项目", "contribution": "完成用户访谈", "source_text": "访谈纪要\n第二行原文"})
        self.records.put("project", value["project_id"], value, replace=True)
        self.start(factory=self.offline)
        source = self.wait()[0]
        self.assertEqual(source["status"], "ready")
        result = self.call("POST", "/search", {"snapshot_ids": [source["snapshot_id"]], "query": "用户访谈"})
        self.assertEqual(result["items"][0]["source_kind"], "user_supplied")
        self.assertEqual(result["items"][0]["personal_contribution"], "unconfirmed")

    def test_rebuild_failure_preserves_old_snapshot_and_restart_reuses_it(self):
        self.cached()
        self.project()
        self.start(factory=self.offline)
        source = self.wait()[0]
        snapshot = source["snapshot_id"]
        source.update(index_version=INDEX_VERSION-1, status="interrupted")
        self.client.app.state.knowledge.save_source(source)
        with patch("interview_agent.knowledge.github_documents", side_effect=OSError("synthetic failure")):
            self.call("POST", "/warmup", {}, 202)
            failed = self.wait()[0]
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["snapshot_id"], snapshot)
        self.assertTrue(self.call("POST", "/search", {"snapshot_ids": [snapshot], "query": "sign"})["items"])
        self.client.__exit__(None, None, None)
        self.client = None
        self.start(factory=self.offline)
        self.assertEqual(self.wait()[0]["snapshot_id"], snapshot)

    def test_all_project_associations_include_more_than_100_records(self):
        self.cached()
        for i in range(105):
            self.project(pid=f"project_{i}")
        self.start(factory=self.offline)
        source = self.wait()[0]
        self.assertEqual(len(source["project_ids"]), 105)
        self.assertEqual(self.call("GET", "/sources?limit=1")["total"], 1)
        self.call("GET", "/sources?limit=101", status=400)

    def test_empty_repository_and_total_budget_are_honest(self):
        directory, manifest = self.cached({"a.txt": b"12345678", "b.txt": b"87654321"})
        self.project()
        with patch("interview_agent.knowledge_source.MAX_TOTAL_BYTES", 10):
            self.start(factory=self.offline)
            source = self.wait()[0]
        self.assertEqual(source["status"], "partial")
        self.assertEqual(source["coverage"]["exclusion_reasons"]["snapshot_budget"], 1)
        self.client.__exit__(None, None, None)
        self.client = None
        # An actually empty pinned inventory is distinct from unavailable content.
        manifest["files"] = []
        (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.start(factory=self.offline)
        sha2 = "e" * 40
        empty_directory = directory.parent / sha2
        empty_directory.mkdir()
        manifest["commit_sha"] = sha2
        (empty_directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.project("project_empty", sha2)
        self.call("POST", "/warmup", {}, 202)
        empty = next(s for s in self.wait() if s["source_commit"] == sha2)
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["coverage"]["total_files"], 0)
        self.assertEqual(self.call("POST", "/search", {"snapshot_ids": [empty["snapshot_id"]], "query": "anything"})["items"], [])

    def test_new_commits_and_other_owner_cannot_change_old_context(self):
        directory, manifest = self.cached()
        self.project()
        self.start(factory=self.offline)
        original = self.wait()[0]["snapshot_id"]
        before = self.call("GET", f"/snapshots/{original}/context")
        sha2 = "d" * 40
        newer = directory.parent / sha2
        shutil.copytree(directory, newer)
        text = b"def newer_version():\n    return 'different'\n"
        (newer / "source/src/sign.py").write_bytes(text)
        manifest["commit_sha"] = sha2
        entry = manifest["files"][0]
        entry.update(sha=blob_sha(text), sha256=hashlib.sha256(text).hexdigest(), size=len(text))
        (newer / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.project("project_new", sha2)
        demo = self.project("project_demo")
        demo["is_demo"] = True
        self.records.put("project", "project_demo", demo, replace=True)
        self.call("POST", "/warmup", {}, 202)
        sources = self.wait()
        self.assertEqual(len(sources), 2)
        self.assertEqual(self.call("GET", f"/snapshots/{original}/context"), before)
        new_snapshot = next(s["snapshot_id"] for s in sources if s["source_commit"] == sha2)
        self.assertNotEqual(original, new_snapshot)
        self.assertEqual(self.call("POST", "/search", {"snapshot_ids": [original], "query": "newer_version"})["items"], [])
        self.assertTrue(self.call("POST", "/search", {"snapshot_ids": [new_snapshot], "query": "newer_version"})["items"])
        self.client.__exit__(None, None, None)
        self.client = None
        self.start(owner="bob", factory=self.offline)
        self.call("GET", f"/snapshots/{original}/context", status=404)

    def test_interrupted_first_download_resumes_pinned_inventory_and_verified_files(self):
        self.remote.sources = {"a.py": b"first_file\n", "b.py": b"second_file\n"}
        self.start()
        original_get = self.remote.get_json
        def interrupt(path):
            value = original_get(path)
            self.client.app.state.knowledge.stopped.set()
            return value
        with patch.object(self.remote, "get_json", side_effect=interrupt):
            self.call("POST", "/sources", {"repository": "example/demo"}, 202)
            interrupted = self.wait()[0]
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["source_commit"], SHA)
        self.assertEqual(self.remote.blob_calls, 1)
        self.client.__exit__(None, None, None)
        self.client = None
        self.start()
        restored = self.wait()[0]
        self.assertEqual(restored["status"], "ready")
        self.assertEqual(self.remote.blob_calls, 2)
        self.assertEqual(self.remote.refs, [None])


if __name__ == "__main__":
    unittest.main()
