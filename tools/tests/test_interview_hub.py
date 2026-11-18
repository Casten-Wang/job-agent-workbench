"""The interview hub must render before any pipeline data has loaded."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


class InterviewHubStartupTests(unittest.TestCase):
    def test_empty_and_active_sessions_render_all_four_entry_cards(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable")
        source = (Path(__file__).resolve().parents[2] / "web/static/app.js").read_text(encoding="utf-8")
        block = source[source.index("const INTERVIEW_MODULES ="):source.index("function clearTransientResults()")]
        for session in (None, {"user_status": "in_progress"}):
            with self.subTest(session=session):
                script = """
const state = {snapshot: {}, interviewChat: {session: SESSION}};
const rows = [];
const dom = {interviewHub: {append(node) {rows.push(node.attrs['aria-label']);}}};
const clear = () => {rows.length = 0;};
const el = (tag, options) => ({...options, addEventListener() {}});
const remainingMinutesFromSession = () => 20;
""".replace("SESSION", json.dumps(session)) + block + "\nrenderInterviewHub(); console.log(JSON.stringify(rows));"
                result = subprocess.run([node, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
                rows = json.loads(result.stdout)
                self.assertEqual(len(rows), 4)
                for label in ("模拟面试", "Mock 题单", "面试复盘", "题库与面经"):
                    self.assertTrue(any(label in row for row in rows))
                self.assertNotIn("undefined", " ".join(rows))


if __name__ == "__main__":
    unittest.main()
