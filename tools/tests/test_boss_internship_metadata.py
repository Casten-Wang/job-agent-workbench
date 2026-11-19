"""Internship schedules must not occupy the education field."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor/offerpilot/src"))
from offerpilot.collection.platforms.boss import JS_EXTRACT_LIST, JS_EXTRACT_DETAIL


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for the extractors")
class BossInternshipMetadataTests(unittest.TestCase):
    def extract(self, script, tags):
        harness = """
const tags=TAGS.map(textContent=>({textContent}));
const window={location:{pathname:'/job_detail/test.html'}};
const node={textContent:'测试',getAttribute:()=>'/job_detail/test.html'};
const wrap={querySelector:s=>s==='.job-card-box'?null:node,querySelectorAll:()=>tags};
const document={title:'测试 - BOSS',body:{innerText:''},
 querySelectorAll:s=>s==='.job-card-wrap'?[wrap]:s==='.info-primary .tag-list span'?tags:[],
 querySelector:()=>null};
console.log(SCRIPT);
""".replace("TAGS", json.dumps(tags, ensure_ascii=False)).replace("SCRIPT", script)
        result = subprocess.run([shutil.which("node"), "-e", harness], capture_output=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        return data[0] if isinstance(data, list) else data

    def test_internship_keeps_schedule_and_actual_degree(self):
        for script in (JS_EXTRACT_LIST, JS_EXTRACT_DETAIL):
            with self.subTest(script=script[:30]):
                row = self.extract(script, ["3天/周", "3个月", "本科"])
                self.assertEqual(row["education"], "本科")
                self.assertEqual(row["experience"], "3天/周 · 3个月")

    def test_full_time_experience_and_degree_are_unchanged(self):
        for script in (JS_EXTRACT_LIST, JS_EXTRACT_DETAIL):
            row = self.extract(script, ["1-3年", "本科"])
            self.assertEqual(row["education"], "本科")
            self.assertEqual(row["experience"], "1-3年")

    def test_missing_degree_is_left_unknown(self):
        for script in (JS_EXTRACT_LIST, JS_EXTRACT_DETAIL):
            row = self.extract(script, ["4天/周", "6个月"])
            self.assertEqual(row["education"], "")
            self.assertEqual(row["experience"], "4天/周 · 6个月")
