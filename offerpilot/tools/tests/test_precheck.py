"""Tests for the local, read-only 30-day application deduplication precheck."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

# Importing precheck from tools/ must not create tools/__pycache__: only
# tools/precheck.py and tools/tests/* are allowed to be written.
sys.dont_write_bytecode = True

TOOLS_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = TOOLS_DIR.parent
TEST_DIR = Path(__file__).resolve().parent
SAMPLE_TRACKER = TEST_DIR / "applications.sample.md"
PRECHECK = TOOLS_DIR / "precheck.py"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import precheck  # noqa: E402  (path is set above for isolated mode)

CHECK_DATE = date(2026, 11, 14)
COMPANY = "测试数据甲公司"
TITLE = "后端工程师"
CITY = "上海"

HEADER = (
    "| # | Date | Company | Role | Location | Score | Status | PDF | Report | Notes |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)

ROW_31_DAYS = "| 1 | 2026-10-14 | 测试数据甲有限公司 | 后端工程师 | 上海 | 4.0/5 | Applied | — | — | 测试数据：同指纹 31 天前（应放行） |"
ROW_10_DAYS = "| 2 | 2026-11-04 | 测试数据甲公司 | 后端工程师 | 上海 | 4.0/5 | Applied | — | — | 测试数据：同指纹 10 天前（应拦截） |"
ROW_DISCARDED = "| 3 | 2026-11-04 | 测试数据甲有限公司 | 后端工程师 | 上海 | 4.0/5 | Discarded | — | — | 测试数据：同指纹 10 天前但状态为 Discarded（应放行） |"
ROW_OTHER_COMPANY = "| 4 | 2026-11-04 | 测试数据乙公司 | 后端工程师 | 上海 | 4.0/5 | Applied | — | — | 测试数据：不同公司（应放行） |"
ROW_MISSING_DATE = "| 5 |  | 测试数据甲有限公司 | 后端工程师 | 上海 | 4.0/5 | Applied | — | — | 测试数据：日期缺失（应放行并产生 warning） |"


def evaluate_one(row: str) -> dict:
    return precheck.evaluate_tracker_text(
        tracker_text=HEADER + row + "\n",
        company=COMPANY,
        title=TITLE,
        city=CITY,
        check_date=CHECK_DATE,
    )


class PrecheckScenarioTests(unittest.TestCase):
    def test_same_fingerprint_31_days_ago_is_allowed(self) -> None:
        result = evaluate_one(ROW_31_DAYS)
        self.assertFalse(result["block"])
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            result["fingerprint"],
            precheck.compute_fingerprint(COMPANY, TITLE, CITY),
        )

    def test_same_fingerprint_10_days_ago_is_blocked(self) -> None:
        result = evaluate_one(ROW_10_DAYS)
        self.assertTrue(result["block"])
        self.assertEqual(len(result["matches"]), 1)
        match = result["matches"][0]
        self.assertEqual(match["company"], "测试数据甲公司")
        self.assertEqual(match["title"], "后端工程师")
        self.assertEqual(match["role"], "后端工程师")
        self.assertEqual(match["date"], "2026-11-04")
        self.assertEqual(match["status"], "Applied")
        self.assertEqual(match["line"], 3)

    def test_same_fingerprint_10_days_ago_discarded_is_allowed(self) -> None:
        result = evaluate_one(ROW_DISCARDED)
        self.assertFalse(result["block"])
        self.assertEqual(result["matches"], [])

    def test_different_company_is_allowed(self) -> None:
        result = evaluate_one(ROW_OTHER_COMPANY)
        self.assertFalse(result["block"])
        self.assertEqual(result["matches"], [])

    def test_missing_date_is_allowed_with_warning(self) -> None:
        result = evaluate_one(ROW_MISSING_DATE)
        self.assertFalse(result["block"])
        self.assertEqual(result["matches"], [])
        self.assertEqual(len(result["warnings"]), 1)
        warning = result["warnings"][0]
        self.assertEqual(warning["reason"], "missing-date")
        self.assertEqual(warning["line"], 3)
        self.assertIn("测试数据：日期缺失", warning["raw_line"])

    def test_company_normalization_and_fingerprint_stability(self) -> None:
        self.assertEqual(precheck.normalize_company("ＡＣＭＥ　Ｉｎｃ．"), "acme")
        self.assertEqual(precheck.normalize_company("Acme Co., Ltd."), "acme")
        self.assertEqual(precheck.normalize_company("测试数据甲股份有限公司"), "测试数据甲")
        self.assertEqual(
            precheck.compute_fingerprint(
                "Acme, Inc.", "Backend　Engineer", "Shanghai"
            ),
            precheck.compute_fingerprint("ACME LTD", "backend engineer", "SHANGHAI"),
        )

    def test_cli_json_contract_and_read_only_behavior(self) -> None:
        before = SAMPLE_TRACKER.read_bytes()
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(PRECHECK),
                "--tracker",
                str(SAMPLE_TRACKER),
                "--company",
                COMPANY,
                "--title",
                TITLE,
                "--city",
                CITY,
                "--date",
                "2026-11-14",
                "--json",
            ],
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        after = SAMPLE_TRACKER.read_bytes()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(after, before, "precheck must not modify the tracker")
        payload = json.loads(completed.stdout)
        self.assertEqual(
            set(payload), {"block", "fingerprint", "matches", "warnings"}
        )
        self.assertTrue(payload["block"])
        self.assertEqual(len(payload["matches"]), 1)
        self.assertEqual(payload["matches"][0]["line"], 6)
        self.assertEqual(len(payload["warnings"]), 1)
        self.assertEqual(payload["warnings"][0]["reason"], "missing-date")
        self.assertEqual(payload["warnings"][0]["line"], 9)


if __name__ == "__main__":
    unittest.main()
