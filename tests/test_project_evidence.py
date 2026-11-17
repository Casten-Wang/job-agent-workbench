from pathlib import Path
import tempfile
import unittest

from github_source.ingest import ingest
from interview_agent.project_evidence import project_evidence
from interview_agent.project_writing import writing_issues
from test_ingest import FakeClient


class ProjectEvidenceTests(unittest.TestCase):
    def test_context_does_not_crowd_out_implementation_beyond_imports(self):
        sources = {"README.md": b"# Workflow tool\n", "demo/sample.py": b"fictional_result = 1000\n"}
        sources.update({f"docs/plan-{i}.md": b"Future feature, not implemented\n" for i in range(20)})
        sources.update({f"src/module-{i}.py": ("import math\n" * 150 +
                        f"def run_{i}(value):\n    return value + 'implemented'\n").encode() for i in range(15)})
        sources["src/demo_only.py"] = ("def cmd_demo():\n" + "    print('synthetic')\n" * 60 +
                                       "def prepare(value):\n    return value + 'implemented'\n").encode()
        sources["web/app.js"] = b"function showProgress(value) { return value.status; }\n"
        with tempfile.TemporaryDirectory() as folder:
            directory, manifest = ingest(FakeClient(sources), "example/demo", Path(folder))
            evidence = project_evidence(directory, manifest)
            self.assertEqual(len(evidence), 12)
            self.assertEqual(sum(e["path"].endswith(".md") for e in evidence), 1)
            self.assertTrue(any(e["path"] == "web/app.js" for e in evidence))
            implementations = [e for e in evidence if e["path"].endswith(".py")]
            self.assertTrue(implementations)
            self.assertTrue(all("implemented" in e["text"] and "synthetic" not in e["text"] for e in implementations))
            self.assertTrue(any(e["line_start"] == 151 for e in implementations))
            self.assertFalse(any(e["path"].startswith(("docs/", "demo/")) for e in evidence))
            self.assertTrue(all("#L" in e["source_url"] for e in evidence))

    def test_source_character_budget_and_real_line_ranges(self):
        sources = {f"src/{i}.js": ("//" + "x" * 900 + "\n").encode() * 200 for i in range(4)}
        with tempfile.TemporaryDirectory() as folder:
            directory, manifest = ingest(FakeClient(sources), "example/demo", Path(folder))
            evidence = project_evidence(directory, manifest)
            self.assertTrue(evidence)
            self.assertLessEqual(sum(len(e["text"]) for e in evidence), 40000)
            self.assertTrue(all(e["line_start"] <= e["line_end"] <= 200 for e in evidence))

    def test_public_technologies_and_separate_source_ledger_remain_allowed(self):
        value = {"project_name": "求职工作台", "project_overview": "集中管理岗位与投递进度。", "claims": [
            {"pillar": "状态管理", "text": "使用 Python (3.11)、SQLite (WAL) 和 HTTP 组织任务，配合 CI/CD 检查变更。",
             "boundary": "来源 web/backend.py 需要核对个人职责", "evidence_ids": ["e1"]}]}
        self.assertEqual(writing_issues(value), [])
        value["project_overview"] = "证据见 README.md"
        self.assertEqual(writing_issues(value), ["project_overview"])
        for text in ("修改backend.py实现状态更新", "读取pipeline_status返回状态"):
            value["project_overview"] = text
            self.assertEqual(writing_issues(value), ["project_overview"])
