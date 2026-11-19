"""A BOSS tab URL alone must not turn a Chrome network error into a pass."""

from pathlib import Path
import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor/offerpilot/src"))
from offerpilot.web import preflight
from offerpilot.browser import diagnostics


class BossConnectionReadinessTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the page-state script")
    def test_page_script_recognizes_browser_errors_without_matching_job_description_text(self):
        for uri, text, expected in (
            ("chrome-error://chromewebdata/", "网页无法访问 ERR_CONNECTION_CLOSED", "network_error"),
            ("https://www.zhipin.com/web/geek/jobs", "岗位要求：排查 ERR_CONNECTION_CLOSED", "ready"),
            ("https://www.zhipin.com/web/geek/jobs", "", "loading"),
        ):
            with self.subTest(uri=uri, text=text):
                doc = {"documentURI": uri, "readyState": "complete", "body": {"innerText": text}}
                script = "const document=" + json.dumps(doc, ensure_ascii=False) + ";document.querySelector=()=>null;console.log(" + diagnostics.BOSS_PAGE_STATE_SCRIPT + ")"
                done = subprocess.run([shutil.which("node"), "-e", script], capture_output=True,
                                      encoding="utf-8", check=True, timeout=10)
                result = json.loads(done.stdout)
                self.assertEqual(result["status"], expected)
                if expected == "network_error":
                    self.assertEqual(result["code"], "ERR_CONNECTION_CLOSED")

    def test_failed_inspection_is_reported_as_unknown(self):
        with patch.object(diagnostics, "evaluate", side_effect=RuntimeError("private diagnostic detail")):
            state = diagnostics.inspect_boss_page({"targetId": "test"})
        self.assertEqual(state["status"], "unknown")
        self.assertNotIn("private", json.dumps(state))

    def checks(self, page, url="https://www.zhipin.com/web/geek/recommend"):
        diagnostics = {"node": {"available": True}, "runtime": True, "chrome": True,
                       "browser_name": "Google Chrome", "browser_product": "Chrome/158",
                       "boss_tab": {"targetId": "test", "url": url}, "boss_page": page}
        with patch.object(preflight, "run_browser_diagnostics", return_value=diagnostics):
            return preflight.check_browser_connection({})

    def test_chrome_connection_does_not_hide_a_boss_network_error(self):
        checks = self.checks({"status": "network_error", "code": "ERR_CONNECTION_CLOSED"})
        self.assertTrue(any(row["id"] == "chrome_connection" and row["status"] == "pass" for row in checks))
        boss = [row for row in checks if row["id"].startswith("boss_")]
        self.assertTrue(any(row["status"] == "error" for row in boss))
        self.assertFalse(any(row["status"] == "pass" for row in boss))
        self.assertIn("ERR_CONNECTION_CLOSED", " ".join(preflight.error_messages(checks)))

    def test_unreadable_or_loading_page_is_not_reported_as_ready(self):
        for status in ("unknown", "loading"):
            with self.subTest(status=status):
                boss = [row for row in self.checks({"status": status}) if row["id"].startswith("boss_")]
                self.assertTrue(boss)
                self.assertFalse(any(row["status"] == "pass" for row in boss))

    def test_loaded_page_and_login_warning_keep_their_distinct_meanings(self):
        checks = self.checks({"status": "ready"})
        self.assertTrue(any(row["id"] == "boss_tab" and row["status"] == "pass" for row in checks))
        checks = self.checks({"status": "ready"}, "https://www.zhipin.com/web/user/?ka=header-login")
        self.assertTrue(any(row["id"] == "boss_login" and row["status"] == "warning" for row in checks))


if __name__ == "__main__":
    unittest.main()
