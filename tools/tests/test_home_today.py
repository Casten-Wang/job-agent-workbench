#!/usr/bin/env python3
"""Tests for the task-first homepage.

The homepage answers one question: what needs doing today.  Every check here is
offline and reads the shipped static files or runs the homepage helpers with
node.  No endpoint is called and nothing is sent.
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

HOME_START = "/* home-today:start"
HOME_END = "/* home-today:end */"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _home_block(script: str) -> str:
    start = script.index(HOME_START)
    end = script.index(HOME_END, start) + len(HOME_END)
    return script[start:end]


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class HomeMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.home = _between(cls.html, 'id="view-workbench"', 'id="view-collect"')

    def test_home_opens_with_today_and_three_tasks(self):
        self.assertIn('id="home-today"', self.home)
        self.assertIn(">今天<", self.home)
        for label in ("待处理岗位", "待确认招呼语", "待回复的 HR 邮件"):
            with self.subTest(label=label):
                self.assertIn(label, self.home)
        for marker in (
            'id="home-jobs-count"',
            'id="home-greetings-count"',
            'id="home-replies-count"',
            'id="home-send-summary"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.home)

    def test_each_task_has_a_button_to_its_page(self):
        self.assertEqual(self.home.count('data-view-link="queue"'), 2)
        self.assertEqual(self.home.count('data-view-link="mail"'), 1)
        self.assertIn('id="home-jobs-action"', self.home)
        self.assertIn('id="home-greetings-action"', self.home)
        self.assertIn('id="home-replies-action"', self.home)

    def test_explanation_is_demoted_to_a_details_block(self):
        self.assertIn('<details class="home-more" id="home-more">', self.home)
        self.assertIn("这个工作台怎么用", self.home)
        # 旧的说明式面板不再占据首屏。
        for removed in ('id="home-intro"', 'id="home-steps"', 'id="home-progress"'):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.html)

    def test_home_copy_avoids_developer_jargon(self):
        for token in ("ATS", "批次", "dlv-", "approved", "ledger"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.home)
        self.assertNotIn("批次", self.script)
        self.assertIn("今天已发送", self.script)
        self.assertIn("最近一次发送", self.script)
        self.assertIn("成功 ${sent} 条，失败 ${failed} 条", self.script)

    def test_mode_switch_is_gone(self):
        for removed in ('data-mode=', 'id="mode-banner"', "演示 demo", "我的 user"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.html)
        self.assertNotIn("switchMode", self.script)
        self.assertNotIn("syncModeButtons", self.script)
        self.assertNotIn("state.mode === 'demo'", self.script)

    def test_renderer_fills_the_three_counts_and_summary(self):
        renderer = _between(self.script, "function renderHomeToday", "/* 六段契约")
        for marker in (
            "homeTaskCounts(snapshot)",
            "dom.homeJobsCount",
            "dom.homeGreetingsCount",
            "dom.homeRepliesCount",
            "homeDeliveryLine(snapshot)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, renderer)
        self.assertIn("renderHomeToday(snapshot);", self.script)
        self.assertNotIn("renderWorkbenchNextStep", self.script)

    def test_home_styles_are_plain_rows_not_cards(self):
        for selector in (".home-today", ".home-tasks", ".home-task", ".home-summary", ".home-more"):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.theme)
        block = self.theme[self.theme.index("/* 首页：今天要做的事"):]
        self.assertIn('font-family: "Songti SC"', block)
        self.assertNotIn("border-radius", block)
        self.assertNotIn("box-shadow", block)
        self.assertIn("@media (max-width: 560px)", block)


class HomeModelTests(unittest.TestCase):
    @staticmethod
    def _run(snapshot, now="2026-11-17T12:00:00"):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过首页计数校验")
        script = _read(APP)
        harness = (
            _home_block(script)
            + "\nconst fs = require('fs');\n"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify({\n"
            "  counts: homeTaskCounts(input.snapshot),\n"
            "  line: homeDeliveryLine(input.snapshot, new Date(input.now))\n"
            "}));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps({"snapshot": snapshot, "now": now}, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行首页计数失败：{completed.stderr[:800]}")
        return json.loads(completed.stdout)

    def test_counts_pending_jobs_ready_greetings_and_hr_mail(self):
        snapshot = {
            "queue": [
                {"status": "pending"},
                {"status": "approved", "greeting": {"greeting": "您好，我想了解这个岗位。"}},
                {"status": "approved", "greeting": {"greeting": "您好"}, "delivery": {"status": "sent"}},
                {"status": "approved", "greeting": {"greeting": "   "}},
                {"status": "approved"},
                {"status": "rejected"},
            ],
            "mails": [
                {"classification": {"intent": "interview_invite"}},
                {"classification": {"intent": "assessment"}},
                {"classification": {"intent": "offer"}},
                {"classification": {"intent": "rejection"}},
                {"classification": {"intent": "other"}},
                {},
            ],
        }
        result = self._run(snapshot)
        self.assertEqual(result["counts"], {"jobs": 1, "greetings": 1, "replies": 3})

    def test_empty_snapshot_is_all_zero(self):
        result = self._run({})
        self.assertEqual(result["counts"], {"jobs": 0, "greetings": 0, "replies": 0})
        self.assertEqual(result["line"], "还没有发送记录。")

    def test_today_batches_are_summed(self):
        snapshot = {
            "pipeline": {
                "delivery": {
                    "batches": [
                        {"finished_at": "2026-11-17T09:00:00", "items": [
                            {"status": "sent"}, {"status": "sent"}, {"status": "failed"},
                        ]},
                        {"finished_at": "2026-11-17 10:30:00", "items": [{"status": "sent"}]},
                        {"finished_at": "2026-11-10T09:00:00", "items": [{"status": "failed"}]},
                    ]
                }
            }
        }
        result = self._run(snapshot)
        self.assertEqual(result["line"], "今天已发送 3 条，失败 1 条。")

    def test_older_batches_fall_back_to_the_latest_one(self):
        snapshot = {
            "pipeline": {
                "delivery": {
                    "batches": [
                        {"finished_at": "2026-11-10T09:00:00", "items": [{"status": "sent"}]},
                        {"finished_at": "2026-11-11T09:00:00", "items": [
                            {"status": "sent"}, {"status": "failed"}, {"status": "deferred"},
                        ]},
                    ]
                }
            }
        }
        result = self._run(snapshot)
        self.assertEqual(result["line"], "最近一次发送：成功 1 条，失败 1 条。")

    def test_batches_without_dates_still_read_as_latest(self):
        snapshot = {
            "pipeline": {
                "delivery": {
                    "batches": [{"batch_id": "dlv-test", "items": [{"status": "sent"}]}]
                }
            }
        }
        result = self._run(snapshot)
        self.assertEqual(result["line"], "最近一次发送：成功 1 条，失败 0 条。")


if __name__ == "__main__":
    unittest.main()
