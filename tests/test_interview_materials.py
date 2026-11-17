import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from github_source.ingest import blob_sha, cite, write_json
from interview_hub.materials import import_demo
from interview_hub.store import Store


class InterviewMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.ua = self.root / "ua"
        self.readiness = self.root / "readiness.json"
        source = b"def sign(value):\n    return value\n"
        (self.snapshot / "source/src").mkdir(parents=True)
        (self.snapshot / "source/src/sign.py").write_bytes(source)
        sha = "a" * 40
        write_json(self.snapshot / "manifest.json", {"commit_sha": sha, "repository_id": 1,
            "repository": "example/demo", "repository_url": "https://github.com/example/demo",
            "files": [{"path": "src/sign.py", "status": "downloaded", "sha": blob_sha(source),
                       "sha256": hashlib.sha256(source).hexdigest()}]})
        self.evidence = cite(self.snapshot, "src/sign.py", 1, 2)
        node = {"id": "file:src/sign.py", "type": "file", "name": "sign.py", "filePath": "src/sign.py",
                "lineRange": [1, 2], "summary": "A source fixture", "tags": ["signing"], "complexity": "simple"}
        write_json(self.ua / "knowledge-graph.json", {"project": {"gitCommitHash": sha}, "nodes": [node], "edges": [],
            "layers": [{"id": "layer:core", "nodeIds": [node["id"]]}],
            "tour": [{"order": 1, "nodeIds": [node["id"]]}]})
        section = {"title": "Signing", "lineRange": [1, 2], "tourOrder": 1, "explanation": "Returns the value in this fixture."}
        write_json(self.ua / "code-lessons.json", {"files": {"src/sign.py": {"overview": "Fixture", "sections": [section]}}})
        self.bundle = {"mode": "public_project_demonstration_not_user_experience", "commit_sha": sha,
            "claim_id": "claim_fixture", "project_fact": "Source fixture contains a sign function", "evidence": [self.evidence],
            "questions": [{"question_id": "q1", "text": "Explain the return statement", "evidence_ids": [self.evidence["evidence_id"]],
                "expected_facts": ["Returns value"], "ua_learning_support": [{"path": "src/sign.py", "section_index": 0,
                     **section, "evidence_id": self.evidence["evidence_id"], "source_url": self.evidence["source_url"]}]}]}
        self.store = Store(self.root / "interview.db")

    def tearDown(self):
        self.temp.cleanup()

    def load(self, bundle=None):
        write_json(self.readiness, self.bundle if bundle is None else bundle)
        return import_demo(self.store, "fixture-owner", self.snapshot, self.ua, self.readiness)

    def test_verified_import_is_repeatable_and_does_not_claim_authorship(self):
        first = self.load()
        second = self.load()
        self.assertEqual(first, second)
        self.assertTrue(first["payload"]["is_demo"])
        self.assertIsNone(first["payload"]["resume_version_id"])
        self.assertEqual(first["payload"]["claims"][0]["personal_contribution"], "unconfirmed")
        self.assertEqual(first["payload"]["evidence"][0]["text"], self.evidence["text"])

    def test_cached_course_text_or_tour_cannot_masquerade_as_validated_ua(self):
        for field, value in [("explanation", "Different unverified explanation"), ("tourOrder", 999)]:
            altered = copy.deepcopy(self.bundle)
            altered["questions"][0]["ua_learning_support"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(altered)
        self.assertEqual(self.store.list_materials("fixture-owner"), [])

    def test_tampered_source_or_version_blocks_import(self):
        altered = copy.deepcopy(self.bundle)
        altered["commit_sha"] = "b" * 40
        with self.assertRaises(ValueError):
            self.load(altered)
        (self.snapshot / "source/src/sign.py").write_bytes(b"changed\n")
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.store.list_materials("fixture-owner"), [])


if __name__ == "__main__":
    unittest.main()
