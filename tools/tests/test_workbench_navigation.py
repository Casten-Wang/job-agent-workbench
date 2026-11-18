"""Reopening an interview must use the service that owns its session."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "web/static/workbench.js"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class WorkbenchInterviewNavigationTests(unittest.TestCase):
    def open_interview(self, options):
        source = SCRIPT.read_text(encoding="utf-8")
        start = source.index("  async function openCapability(")
        function = source[start:source.index("  function showArtifact(", start)]
        harness = """
const calls = {contexts: [], comprehensive: [], project: []};
const capability = () => ({available: true});
const navigate = () => {};
const window = {
  OfferPilotAgent: {selectContext: async value => {
    calls.contexts.push(value);
    if (value.interview_id && value.interview_id.startsWith('ci_')) {
      throw new Error('Comprehensive sessions are not project-interview contexts');
    }
  }},
  OfferPilotComprehensive: {openSession: async id => calls.comprehensive.push(id)},
  OfferPilotCareer: {openInterview: async id => calls.project.push(id)}
};
""" + function + """
openCapability('interview', OPTIONS).then(() => {
  process.stdout.write(JSON.stringify(calls));
}).catch(error => {console.error(error.message); process.exitCode = 1;});
""".replace("OPTIONS", json.dumps(options))
        result = subprocess.run(
            [shutil.which("node"), "-e", harness], capture_output=True,
            text=True, encoding="utf-8", timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_comprehensive_reopens_without_binding_a_project_interview(self):
        result = self.open_interview({
            "interview_kind": "comprehensive", "interview_id": "ci_owned",
        })
        self.assertEqual(result, {
            "contexts": [], "comprehensive": ["ci_owned"], "project": [],
        })

    def test_comprehensive_keeps_the_selected_job_context(self):
        result = self.open_interview({
            "interview_kind": "comprehensive", "interview_id": "ci_owned",
            "job_id": "job_owned",
        })
        self.assertEqual(result["contexts"], [{"job_id": "job_owned"}])
        self.assertEqual(result["comprehensive"], ["ci_owned"])

    def test_project_interview_still_binds_its_agent_context(self):
        result = self.open_interview({
            "interview_kind": "project", "interview_id": "opuser_owned",
        })
        self.assertEqual(result, {
            "contexts": [{"interview_id": "opuser_owned"}],
            "comprehensive": [], "project": ["opuser_owned"],
        })
