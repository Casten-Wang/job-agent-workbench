import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from github_source.ingest import blob_sha
from github_source.understand import validate_understanding


SHA = "a" * 40


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.ua = self.root / "ua"
        self.ua.mkdir()
        self.files = {"src/demo.py": b"def sign(value):\n    return value\n", "README.md": b"Demo project\n"}
        entries = []
        for name, data in self.files.items():
            path = self.snapshot / "source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            entries.append({"path": name, "status": "downloaded", "sha": blob_sha(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
        self.write(self.snapshot / "manifest.json", {"repository_id": 123, "repository_url": "https://github.com/example/demo",
                                                    "commit_sha": SHA, "files": entries})
        self.graph = {"project": {"gitCommitHash": SHA},
                      "nodes": [{"id": "file:src/demo.py", "filePath": "src/demo.py", "lineRange": [1, 2], "summary": "Not a source quote"},
                                {"id": "document:README.md", "filePath": "README.md", "lineRange": [1, 1]}],
                      "edges": [{"source": "document:README.md", "target": "file:src/demo.py", "type": "documents"}],
                      "layers": [{"id": "layer:core", "nodeIds": ["file:src/demo.py", "document:README.md"]}],
                      "tour": [{"order": 1, "nodeIds": ["file:src/demo.py"]}]}
        self.lessons = {"files": {"src/demo.py": {"overview": "Some explanation", "sections": [
            {"lineRange": [1, 2], "tourOrder": 1, "explanation": "A summary, not the source"}]}}}

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def validate(self):
        self.write(self.ua / "knowledge-graph.json", self.graph)
        self.write(self.ua / "code-lessons.json", self.lessons)
        return validate_understanding(self.snapshot, self.ua)

    def codes(self, result):
        return {item["code"] for item in result["issues"]}

    def test_valid_source_references_do_not_assess_semantics_or_a_person(self):
        before = (self.snapshot / "manifest.json").read_bytes()
        result = self.validate()
        self.assertTrue(result["valid"])
        self.assertEqual(result["role"], "reference_validation_only")
        self.assertFalse(result["semantic_accuracy_assessed"])
        self.assertFalse(result["ability_assessed"])
        self.assertEqual(result["personal_contribution"], "unconfirmed")
        self.assertEqual(result["counts"]["references_verified"], 3)
        self.assertEqual(result["evidence"][0]["text"], "def sign(value):\n    return value")
        self.assertNotIn("Not a source quote", result["evidence"][0]["text"])
        self.assertEqual((self.snapshot / "manifest.json").read_bytes(), before)
        self.assertNotIn("ability_verdict", result)

    def test_wrong_commit_blocks_all_source_evidence(self):
        self.graph["project"]["gitCommitHash"] = "b" * 40
        result = self.validate()
        self.assertIn("commit_mismatch", self.codes(result))
        self.assertEqual(result["evidence"], [])

    def test_missing_coordinates_remain_navigation_only(self):
        del self.graph["nodes"][0]["lineRange"]
        self.graph["nodes"].append({"id": "concept:signing", "summary": "Something inferred"})
        result = self.validate()
        self.assertTrue(result["valid"])
        self.assertEqual(result["counts"]["navigation_only_nodes"], 2)
        self.assertEqual(sum(item["origin"]["kind"] == "node" for item in result["evidence"]), 1)
        self.assertEqual(len(result["warnings"]), 2)

    def test_line_range_must_be_real_integer_and_inside_source(self):
        for value in [[True, 2], [1, False], [0, 1], [2, 1], [1.0, 2], "1-2", [1, 99]]:
            with self.subTest(value=value):
                self.graph["nodes"][0]["lineRange"] = value
                result = self.validate()
                self.assertFalse(result["valid"])
                self.assertTrue(self.codes(result) & {"invalid_line_range", "invalid_source_reference"})

    def test_path_traversal_and_non_downloaded_sources_are_rejected(self):
        for path, code in [("../outside.py", "unsafe_source_path"), ("C:/outside.py", "unsafe_source_path"),
                           ("src\\demo.py", "unsafe_source_path"), ("missing.py", "source_not_downloaded")]:
            with self.subTest(path=path):
                self.graph["nodes"][0]["filePath"] = path
                self.assertIn(code, self.codes(self.validate()))

    def test_invalid_range_is_rejected_even_when_node_has_no_file_path(self):
        self.graph["nodes"].append({"id": "concept:bad", "lineRange": [True, 2]})
        result = self.validate()
        self.assertIn("invalid_line_range", self.codes(result))
        self.assertFalse(any(e["origin"].get("node_id") == "concept:bad" for e in result["evidence"]))

    def test_changed_original_source_is_rejected_even_for_navigation_node(self):
        (self.snapshot / "source/src/demo.py").write_bytes(b"changed source\n")
        del self.graph["nodes"][0]["lineRange"]
        result = self.validate()
        self.assertIn("source_content_changed", self.codes(result))
        self.assertFalse(any(e["path"] == "src/demo.py" for e in result["evidence"]))

    def test_dangling_edge_layer_and_tour_are_reported(self):
        self.graph["edges"][0]["target"] = "missing:node"
        self.graph["layers"][0]["nodeIds"].append("missing:node")
        self.graph["tour"][0]["nodeIds"].append("missing:node")
        result = self.validate()
        self.assertIn("dangling_edge", self.codes(result))
        self.assertEqual(sum(i["code"] == "dangling_node_reference" for i in result["issues"]), 2)

    def test_duplicate_ids_and_tour_order_are_reported(self):
        self.graph["nodes"].append(copy.deepcopy(self.graph["nodes"][0]))
        self.graph["layers"].append(copy.deepcopy(self.graph["layers"][0]))
        self.graph["tour"].append(copy.deepcopy(self.graph["tour"][0]))
        result = self.validate()
        self.assertTrue({"duplicate_node_id", "duplicate_layer_id", "duplicate_tour_order"} <= self.codes(result))

    def test_lessons_cannot_reference_an_unrelated_or_missing_tour_step(self):
        section = self.lessons["files"]["src/demo.py"]["sections"][0]
        for order in [True, 99]:
            section["tourOrder"] = order
            self.assertIn("invalid_lesson_tour_order", self.codes(self.validate()))
        section["tourOrder"] = 1
        self.graph["tour"][0]["nodeIds"] = ["document:README.md"]
        self.assertIn("lesson_tour_file_mismatch", self.codes(self.validate()))

    def test_lesson_source_ranges_are_checked_without_tour_anchors(self):
        section = self.lessons["files"]["src/demo.py"]["sections"][0]
        del section["tourOrder"]
        section["lineRange"] = [1, 999]
        self.assertIn("invalid_source_reference", self.codes(self.validate()))

    def test_optional_lessons_are_reported_without_inventing_content(self):
        self.write(self.ua / "knowledge-graph.json", self.graph)
        result = validate_understanding(self.snapshot, self.ua)
        self.assertTrue(result["valid"])
        self.assertEqual(result["counts"]["lesson_sections_checked"], 0)
        self.assertEqual(result["warnings"][0]["code"], "missing_code_lessons")

    def test_unreadable_graph_has_a_safe_exception(self):
        (self.ua / "knowledge-graph.json").write_text("sensitive arbitrary invalid text", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Cannot read a JSON object from knowledge-graph.json") as error:
            validate_understanding(self.snapshot, self.ua)
        self.assertNotIn("sensitive", str(error.exception))


if __name__ == "__main__":
    unittest.main()
