#!/usr/bin/env python3
"""Tests for the job dossier detail and the read-only queue review panel.

Every check is offline: it reads the shipped static files or runs the dossier
helpers with node.  No endpoint is called and nothing is sent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
INDEX = STATIC_DIR / "index.html"
APP = STATIC_DIR / "app.js"
THEME = STATIC_DIR / "offer-theme.css"

BLOCK_START = "/* jobs-dossier:start"
BLOCK_END = "/* jobs-dossier:end */"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(script: str) -> str:
    start = script.index(BLOCK_START)
    end = script.index(BLOCK_END, start) + len(BLOCK_END)
    return script[start:end]


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class DossierMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.jobs = _between(cls.html, 'id="view-jobs"', 'id="view-queue"')
        cls.queue = _between(cls.html, 'id="view-queue"', 'id="view-mail"')

    def test_job_detail_panel_lives_in_the_jobs_view(self):
        self.assertIn('class="panel jobs-dossier" id="jobs-dossier"', self.jobs)
        for marker in ('id="jobs-dossier-body"', 'id="jobs-dossier-close"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.jobs)

    def test_review_panel_lives_in_the_queue_view(self):
        self.assertIn('class="panel queue-review" id="queue-review"', self.queue)
        for marker in ('id="queue-review-body"', 'id="queue-review-close"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.queue)

    def test_review_panel_adds_no_new_write_controls(self):
        review = _between(self.queue, 'id="queue-review"', '<section class="panel" aria-labelledby="approved-title"')
        for forbidden in ("queue-confirm-button", "offerpilot-reply", "queue-delivery-start", "type=\"submit\""):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, review)
        self.assertIn('id="queue-review-close"', review)

    def test_three_match_values_stay_separate(self):
        block = _block(self.script)
        for label in ("适配分", "判断依据", "岗位风险等级"):
            with self.subTest(label=label):
                self.assertIn(label, block)
        # fit_score / fit_confidence / risk_level 各自一项，不合并成一个分数。
        self.assertIn("{ key: 'fit_score'", block)
        self.assertIn("{ key: 'fit_confidence'", block)
        self.assertIn("{ key: 'risk_level'", block)
        self.assertNotIn("fit_score + ", block)

    def test_standard_fields_cover_the_contract(self):
        block = _block(self.script)
        for key in (
            "title", "location", "responsibilities", "must_have", "nice_to_have",
            "salary_and_start", "hiring_status", "source_platform", "source_updated_at",
        ):
            with self.subTest(key=key):
                self.assertIn(f"['{key}',", block)

    def test_renderers_are_wired_into_jobs_and_queue(self):
        self.assertIn("renderDossier(dom.jobsDossierBody, dossierJob);", self.script)
        self.assertIn("renderDossier(dom.queueReviewBody, reviewJob);", self.script)
        self.assertIn("openQueueReview(snapshot, row)", self.script)
        self.assertIn("openJobDossier(job)", self.script)
        self.assertIn("'核对'", self.script)
        self.assertIn("'查看详情'", self.script)
        # 队列两张表各有一个核对按钮和一列列头。
        self.assertEqual(self.script.count("'核对'"), 4)

    def test_missing_values_render_as_unknown(self):
        self.assertIn("value || '未知'", self.script)
        self.assertIn("项目证据：未知", self.script)
        self.assertIn("来源：未知", self.script)

    def test_styles_use_the_dossier_prefixes(self):
        self.assertIn(".jobs-dossier-fields", self.theme)
        self.assertIn(".jobs-dossier-match-item", self.theme)
        self.assertIn(".jobs-dossier-greeting", self.theme)
        self.assertIn("@media (max-width: 560px)", self.theme)


class DossierModelTests(unittest.TestCase):
    @staticmethod
    def _run(payload):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过岗位详情校验")
        script = _read(APP)
        harness = (
            _block(script)
            + "\nconst fs = require('fs');\n"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify({\n"
            "  standard: dossierStandard(input.job),\n"
            "  match: dossierMatch(input.job),\n"
            "  trace: dossierTraceability(input.job),\n"
            "  parts: dossierParts(input.job),\n"
            "  review: queueReviewJob(input.snapshot, input.review_id)\n"
            "}));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行岗位详情失败：{completed.stderr[:800]}")
        return json.loads(completed.stdout)

    def test_missing_standard_and_match_render_as_null(self):
        result = self._run({"job": {}, "snapshot": {}, "review_id": None})
        self.assertEqual(len(result["standard"]), 9)
        self.assertEqual([item["value"] for item in result["standard"]], [None] * 9)
        self.assertEqual(
            [(item["label"], item["value"]) for item in result["match"]],
            [("适配分", None), ("判断依据", None), ("岗位风险等级", None)],
        )
        self.assertEqual(result["trace"], [])
        self.assertEqual(result["parts"]["checklist"], [])

    def test_standard_and_match_values_pass_through_unmerged(self):
        job = {
            "standard": {
                "title": " 后端开发 ",
                "location": "上海",
                "must_have": ["Python", "SQL"],
                "source_updated_at": None,
            },
            "match": {"fit_score": 86, "fit_confidence": "中", "risk_level": "低"},
        }
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        values = {item["key"]: item["value"] for item in result["standard"]}
        self.assertEqual(values["title"], "后端开发")
        self.assertEqual(values["location"], "上海")
        self.assertEqual(values["must_have"], "Python\nSQL")
        self.assertIsNone(values["source_updated_at"])
        self.assertEqual(
            [item["value"] for item in result["match"]],
            ["86", "中", "低"],
        )

    def test_real_snapshot_shapes_are_translated_not_dumped(self):
        # 真实快照里薪资是对象、招聘状态与平台是枚举、判断依据是 0–1 小数。
        job = {
            "standard": {
                "title": "产品经理",
                "salary_and_start": {"salary": "20-24K", "start": None},
                "hiring_status": "unknown",
                "source_platform": "boss",
            },
            "match": {"fit_score": 49, "fit_confidence": 0.92, "risk_level": "medium"},
        }
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        values = {item["key"]: item["value"] for item in result["standard"]}
        self.assertEqual(values["salary_and_start"], "薪资 20-24K")
        self.assertIsNone(values["hiring_status"])
        self.assertEqual(values["source_platform"], "BOSS直聘")
        self.assertEqual(
            [item["value"] for item in result["match"]],
            ["49", "92%", "中"],
        )
        both = self._run({
            "job": {"standard": {"salary_and_start": {"salary": "20-24K", "start": "尽快"}, "hiring_status": "closed"}},
            "snapshot": {},
            "review_id": None,
        })
        both_values = {item["key"]: item["value"] for item in both["standard"]}
        self.assertEqual(both_values["salary_and_start"], "薪资 20-24K；到岗 尽快")
        self.assertEqual(both_values["hiring_status"], "已停止招聘")
        empty = self._run({"job": {"standard": {"salary_and_start": {"salary": None, "start": None}}}, "snapshot": {}, "review_id": None})
        self.assertIsNone({i["key"]: i["value"] for i in empty["standard"]}["salary_and_start"])

    def test_traceability_keeps_partial_rows_and_drops_empty_ones(self):
        job = {
            "traceability": [
                {"requirement": "熟悉 Python", "project_evidence": "订单服务", "source": "简历项目一"},
                {"requirement": "英语流利"},
                None,
                {"project_evidence": ""},
            ]
        }
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        self.assertEqual(len(result["trace"]), 2)
        self.assertEqual(result["trace"][0]["evidence"], "订单服务")
        self.assertEqual(result["trace"][1]["requirement"], "英语流利")
        self.assertIsNone(result["trace"][1]["evidence"])

    def test_dossier_parts_and_checklist_shapes(self):
        job = {
            "dossier": {
                "analysis_card": "岗位偏后端，项目匹配。",
                "resume_variant": "突出订单服务。",
                "greeting": "您好，我在订单服务做过 Python 开发。",
                "checklist": ["确认到岗时间", "确认薪资范围"],
                "recommended_action": "先确认，再发送。",
            }
        }
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        parts = result["parts"]
        self.assertEqual(parts["analysis"], "岗位偏后端，项目匹配。")
        self.assertEqual(parts["resume"], "突出订单服务。")
        self.assertEqual(parts["greeting"], "您好，我在订单服务做过 Python 开发。")
        self.assertEqual(parts["checklist"], ["确认到岗时间", "确认薪资范围"])
        self.assertEqual(parts["action"], "先确认，再发送。")

    def test_checklist_accepts_a_newline_string(self):
        job = {"dossier": {"checklist": "确认到岗时间\n\n确认薪资范围"}}
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        self.assertEqual(result["parts"]["checklist"], ["确认到岗时间", "确认薪资范围"])

    def test_greeting_falls_back_to_the_existing_preview(self):
        job = {"greeting": {"greeting": "您好，想聊聊这个岗位。"}}
        result = self._run({"job": job, "snapshot": {}, "review_id": None})
        self.assertEqual(result["parts"]["greeting"], "您好，想聊聊这个岗位。")

    def test_queue_review_merges_the_job_record_by_id(self):
        snapshot = {
            "jobs": [{"id": 7, "company": "甲公司", "standard": {"location": "杭州"}}],
            "queue": [{"id": 7, "company": "甲", "title": "后端工程师", "status": "pending"}],
        }
        result = self._run({"job": {}, "snapshot": snapshot, "review_id": 7})
        self.assertEqual(result["review"]["title"], "后端工程师")
        self.assertEqual(result["review"]["company"], "甲")
        self.assertEqual(result["review"]["standard"], {"location": "杭州"})
        self.assertEqual(result["review"]["status"], "pending")

    def test_queue_review_returns_null_for_unknown_ids(self):
        result = self._run({"job": {}, "snapshot": {"jobs": [], "queue": []}, "review_id": 99})
        self.assertIsNone(result["review"])
        result = self._run({"job": {}, "snapshot": {}, "review_id": None})
        self.assertIsNone(result["review"])


if __name__ == "__main__":
    unittest.main()
