import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from github_source.ingest import blob_sha, cite, ingest, safe_path


SHA = "a" * 40


class FakeClient:
    def __init__(self, sources=None, archive_sources=None):
        self.sources = sources or {"src/sign.py": b"def sign(value):\n    return value + '.signed'\n"}
        self.archive_sources = self.sources if archive_sources is None else archive_sources
        self.request_count = 0
        self.archive_calls = 0
        self.blob_calls = 0
        self.contribution_calls = 0

    def resolve_repository(self, repo, ref):
        self.request_count += 2
        return {"repository": {"id": 123, "full_name": "example/demo", "html_url": "https://github.com/example/demo"},
                "requested_ref": ref or "main", "commit_sha": SHA, "tree_sha": "b" * 40}

    def get_tree(self, *args):
        return [{"path": p, "type": "blob", "mode": "100644", "sha": blob_sha(data), "size": len(data)}
                for p, data in self.sources.items()]

    def download_archive(self, owner, repo, commit):
        assert commit == SHA
        self.archive_calls += 1
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path, data in self.archive_sources.items():
                archive.writestr("repo-root/" + path, data)
        return buffer.getvalue()

    def get_json(self, path):
        self.blob_calls += 1
        sha = path.rsplit("/", 1)[1]
        data = next(data for data in self.sources.values() if blob_sha(data) == sha)
        return {"encoding": "base64", "content": base64.b64encode(data).decode()}

    def get_contributions(self, *args, **kwargs):
        self.contribution_calls += 1
        return {"status": "skipped_no_author", "skipped": True, "commits": [], "pull_requests": []}


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_citation_is_fixed_and_preserves_original_lines(self):
        directory, manifest = ingest(FakeClient(), "example/demo", self.output)
        evidence = cite(directory, "src/sign.py", 1, 2)
        self.assertIn(SHA, evidence["source_url"])
        self.assertEqual(evidence["text"], "def sign(value):\n    return value + '.signed'")
        self.assertEqual(evidence["personal_contribution"], "unconfirmed")
        self.assertEqual(manifest["coverage"]["semantic_read_files"], 0)
        self.assertEqual(manifest["coverage"]["structure_indexed_files"], 0)

    def test_filters_and_coverage_are_explicit(self):
        sources = {".env": b"SECRET=private", "node_modules/x.js": b"skip", "src/main.py": b"print('ok')\n",
                   "asset.png": b"binary\0data", "lfs.txt": b"version https://git-lfs.github.com/spec/v1\noid sha256:x\n"}
        directory, manifest = ingest(FakeClient(sources), "example/demo", self.output)
        entries = {e["path"]: e for e in manifest["files"]}
        self.assertEqual(entries[".env"]["reason"], "sensitive_path")
        self.assertEqual(entries["node_modules/x.js"]["reason"], "dependency_or_generated")
        self.assertEqual(entries["asset.png"]["reason"], "binary")
        self.assertEqual(entries["lfs.txt"]["reason"], "lfs_content_not_fetched")
        self.assertEqual(manifest["coverage"]["statuses"], {"excluded": 4, "downloaded": 1})
        self.assertFalse((directory / "source/.env").exists())

    def test_original_line_numbers_use_lf_not_unicode_separators(self):
        data = 'x = "a\u2028b\u2029c"\r\nprint(x)\r\n'.encode("utf-8")
        directory, manifest = ingest(FakeClient({"source.py": data}), "example/demo", self.output)
        self.assertEqual(cite(directory, "source.py", 2, 2)["text"], "print(x)")
        self.assertEqual(manifest["files"][0]["line_count"], 2)

    def test_budget_is_visible_and_not_silently_complete(self):
        directory, manifest = ingest(FakeClient({"a.py": b"a\n", "b.py": b"b\n"}), "example/demo", self.output, max_files=1)
        self.assertEqual(manifest["coverage"]["exclusion_reasons"]["snapshot_budget"], 1)
        self.assertEqual(manifest["coverage"]["statuses"]["downloaded"], 1)
        with self.assertRaises(ValueError):
            cite(directory, "b.py", 1, 1)

    def test_tampered_local_content_is_rejected_then_repaired(self):
        client = FakeClient()
        directory, _ = ingest(client, "example/demo", self.output)
        target = directory / "source/src/sign.py"
        target.write_bytes(b"wrong\n")
        with self.assertRaises(ValueError):
            cite(directory, "src/sign.py", 1, 1)
        ingest(client, "example/demo", self.output, ref=SHA)
        self.assertEqual(cite(directory, "src/sign.py", 1, 1)["text"], "def sign(value):")

    def test_repeated_snapshot_reuses_verified_files_and_contributions(self):
        client = FakeClient()
        ingest(client, "example/demo", self.output)
        ingest(client, "example/demo", self.output, ref=SHA)
        self.assertEqual(client.archive_calls, 1)
        self.assertEqual(client.contribution_calls, 1)

    def test_missing_archive_member_falls_back_to_verified_blob(self):
        client = FakeClient(archive_sources={"README.md": b"omitted by export rules"})
        directory, _ = ingest(client, "example/demo", self.output)
        self.assertEqual(client.blob_calls, 1)
        self.assertEqual(cite(directory, "src/sign.py", 1, 1)["text"], "def sign(value):")

    def test_wrong_archive_content_is_partial_and_cannot_be_cited(self):
        client = FakeClient(archive_sources={"src/sign.py": b"wrong content"})
        directory, manifest = ingest(client, "example/demo", self.output)
        self.assertEqual(manifest["state"], "partial")
        self.assertEqual(manifest["files"][0]["status"], "failed")
        with self.assertRaises(ValueError):
            cite(directory, "src/sign.py", 1, 1)

    def test_unselected_zip_traversal_is_ignored_without_writing_outside(self):
        client = FakeClient(archive_sources={"../../outside.py": b"bad"})
        _, manifest = ingest(client, "example/demo", self.output)
        self.assertEqual(manifest["state"], "fetched_with_declared_scope")
        self.assertFalse((self.output / "outside.py").exists())

    def test_excluded_nonportable_name_does_not_block_other_files(self):
        sources = {"bad:name.py": b"ignored\n", "README.md": b"safe\n"}
        directory, manifest = ingest(FakeClient(sources), "example/demo", self.output)
        self.assertEqual(cite(directory, "README.md", 1, 1)["text"], "safe")
        self.assertEqual(manifest["coverage"]["exclusion_reasons"]["unsafe_path"], 1)

    def test_contribution_failure_after_changing_author_can_recover(self):
        class AuthorClient(FakeClient):
            def get_contributions(self, *args, author=None):
                self.contribution_calls += 1
                if author == "bob":
                    raise RuntimeError("offline failure")
                return {"status": "collected_with_scope", "author": author}
        client = AuthorClient()
        ingest(client, "example/demo", self.output, author="alice")
        _, partial = ingest(client, "example/demo", self.output, author="bob")
        self.assertEqual(partial["state"], "partial")
        self.assertEqual(partial["contribution_requested_author"], "bob")
        _, recovered = ingest(client, "example/demo", self.output, author="alice")
        self.assertEqual(recovered["state"], "fetched_with_declared_scope")
        self.assertEqual(recovered["contribution_status"], "collected_with_scope")

    def test_unsafe_paths_and_line_ranges_are_rejected(self):
        for path in ["../a", "/absolute", "x\\y", "x:y", "CON.txt", "x/../y", "x. /y", "x\ny"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(self.output, path)
        directory, _ = ingest(FakeClient(), "example/demo", self.output)
        for start, end in [(0, 1), (2, 1), (1, 999)]:
            with self.assertRaises(ValueError):
                cite(directory, "src/sign.py", start, end)

    def test_interrupt_can_resume_at_same_commit(self):
        class InterruptClient(FakeClient):
            def download_archive(self, *args):
                raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            ingest(InterruptClient(), "example/demo", self.output)
        manifest = json.loads(next(self.output.rglob("manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(manifest["state"], "interrupted")
        _, resumed = ingest(FakeClient(), "example/demo", self.output, ref=SHA)
        self.assertEqual(resumed["state"], "fetched_with_declared_scope")


if __name__ == "__main__":
    unittest.main()
