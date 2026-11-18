#!/usr/bin/env python3
"""Backend wiring for the additive job analysis keys.

``parse_jd`` returns the decorated job view; the stored row stays untouched so
recomputed analysis never goes stale in ``jobs.json``. Every test uses a
temporary data directory and a non-existent CV path.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "web"), str(PROJECT_ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402

JD_TEXT = """公司：虚构星河科技有限公司
岗位：产品经理
城市：上海
薪资：20-30K
岗位职责：
1. 负责需求分析与原型设计；
任职要求：
- 熟练使用 Axure 与 Visio 输出原型；
- 有电商订单与结算经验。
"""

ANALYSIS_KEYS = ("standard", "match", "dossier", "traceability")


class ParseJdDecorationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        patcher = patch.object(backend, "WEB_DIR", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        cv_patcher = patch.object(backend, "CV_PATH", self.root / "missing-resume.md")
        cv_patcher.start()
        self.addCleanup(cv_patcher.stop)

    def _parse(self) -> dict:
        return backend.parse_jd(
            {"mode": "user", "text": JD_TEXT, "id": "jd-analysis-1", "score": 72}
        )

    def test_parse_jd_returns_all_four_analysis_keys(self) -> None:
        result = self._parse()
        self.assertTrue(result["ok"])
        job = result["job"]
        for key in ANALYSIS_KEYS:
            self.assertIn(key, job)
        self.assertEqual(job["standard"]["title"], "产品经理")
        self.assertEqual(job["standard"]["location"], "上海")
        self.assertIsNone(job["standard"]["source_platform"])  # manual_paste is not a platform
        self.assertEqual(job["match"]["fit_score"], 72)
        self.assertIn(job["match"]["risk_level"], ("low", "medium", "high"))
        self.assertEqual(
            set(job["dossier"]),
            {"analysis_card", "resume_variant", "greeting", "checklist", "recommended_action"},
        )
        self.assertEqual(
            [row["requirement"] for row in job["traceability"]],
            ["熟练使用 Axure 与 Visio 输出原型；", "有电商订单与结算经验。"],
        )

    def test_stored_row_keeps_only_its_own_fields(self) -> None:
        self._parse()
        stored = backend.get_store("user").jobs()
        self.assertEqual(len(stored), 1)
        for key in ANALYSIS_KEYS:
            self.assertNotIn(key, stored[0])
        self.assertEqual(stored[0]["score"], 72)

    def test_duplicate_response_is_decorated_too(self) -> None:
        self._parse()
        again = self._parse()
        self.assertFalse(again["ok"])
        self.assertTrue(again["duplicate"])
        for key in ANALYSIS_KEYS:
            self.assertIn(key, again["job"])

    def test_missing_data_stays_null_instead_of_being_invented(self) -> None:
        text = "公司：虚构测试公司\n岗位：产品经理\n记录类型：JD\n"
        result = backend.parse_jd({"mode": "user", "text": text, "id": "jd-sparse-1"})
        job = result["job"]
        self.assertIsNone(job["standard"]["responsibilities"])
        self.assertIsNone(job["standard"]["salary_and_start"])
        self.assertIsNone(job["match"]["fit_score"])
        self.assertEqual(job["traceability"], [])
        self.assertIsNone(job["dossier"]["greeting"])

    def test_greeting_never_carries_contacts(self) -> None:
        result = self._parse()
        text = result["job"]["dossier"]["greeting"]
        if text:
            self.assertFalse(backend.job_dossier.contains_contact(text))


class SnapshotScopeTests(unittest.TestCase):
    """The analysis keys stay on parse-jd; /api/state output is unchanged."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for patcher in (
            patch.object(backend, "WEB_DIR", self.root),
            patch.object(backend, "CV_PATH", self.root / "missing-resume.md"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_snapshot_jobs_carry_analysis_keys_and_disk_is_untouched(self) -> None:
        store = backend.get_store("user")
        store.set_jobs([
            {
                "id": "j-snapshot-1",
                "company": "虚构星河科技有限公司",
                "title": "产品经理",
                "city": "上海",
                "raw_text": "任职要求：\n- 熟练使用 Axure 输出原型。",
                "source_channel": "boss",
                "score": 60,
                "score_coverage": 0.9,
                "mandatory_status": "pending",
                "hiring_status": "unknown",
                "mandatory_conditions": [
                    {"condition": "熟练使用 Axure 输出原型", "status": "待确认", "evidence": "部分"}
                ],
            }
        ])
        before = (self.root / "data" / "user" / "jobs.json").read_bytes()
        with patch.object(backend, "get_offerpilot_state", return_value={"ok": False}):
            state = backend.snapshot("user")
        # 契约改为只增不减：快照里的岗位带上只读派生的 standard/match/dossier/traceability，
        # 详情与核对面板才有数据可读；派生只发生在内存里，磁盘上的 jobs.json 不能被改写。
        for key in ANALYSIS_KEYS:
            self.assertIn(key, state["jobs"][0])
        self.assertEqual((self.root / "data" / "user" / "jobs.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
