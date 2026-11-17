#!/usr/bin/env python3
"""Tests for local greeting drafts on ready jobs.

Every test runs against a temporary data directory. No test touches
``web/data/user``, sends a message, opens a browser, or performs a network
request.
"""

from __future__ import annotations

import copy
import json
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

import backend  # noqa: E402  (local module in web/)


def _job(
    job_id: str,
    status: str = "ready",
    company: str = "星河科技",
    title: str = "产品经理",
    **extra: object,
) -> dict:
    row = {"id": job_id, "status": status, "company": company, "title": title, "city": "上海"}
    row.update(extra)
    return row


def _profile_with_skills() -> dict:
    profile = backend.default_profile()
    profile["basic"]["name"] = "演示应聘者"
    profile["basic"]["city"] = "上海"
    profile["basic"]["phone"] = "13800000000"  # 明显虚构的占位号码
    profile["basic"]["email"] = "demo@example.com"
    profile["basic"]["wechat"] = "demo_wechat"
    profile["job_intent"]["titles"] = ["产品经理"]
    profile["job_intent"]["cities"] = ["上海"]
    profile["skills"]["tools"] = ["需求分析", "数据分析", "Axure"]
    profile["skills"]["strengths"] = ["跨团队沟通"]
    return profile


class GenerateJobGreetingsTests(unittest.TestCase):
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
        self.store = backend.Store("user")
        self.store.set_profile(_profile_with_skills())
        self.addCleanup(patch.stopall)

    def _run(self, payload: dict) -> dict:
        with patch.object(
            backend, "get_store", side_effect=lambda mode, seed_if_empty=True: self.store
        ):
            return backend.generate_job_greetings(payload)

    def test_generates_for_ready_jobs_without_greeting(self) -> None:
        self.store.set_jobs(
            [
                _job("ready-a"),
                _job("ready-b", title="数据产品经理"),
                _job("ready-kept", greeting="已经写好的招呼语"),
                _job("filtered-a", status="filtered"),
                _job("sent-a", status="sent"),
            ]
        )
        result = self._run({"mode": "user"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["generated"], 2)
        self.assertEqual(result["skipped"], [])
        jobs = {row["id"]: row for row in self.store.jobs()}
        self.assertIn("星河科技", jobs["ready-a"]["greeting"])
        self.assertIn("产品经理", jobs["ready-a"]["greeting"])
        self.assertIn("需求分析", jobs["ready-a"]["greeting"])
        self.assertEqual(jobs["ready-kept"]["greeting"], "已经写好的招呼语")
        for job_id in ("filtered-a", "sent-a"):
            self.assertNotIn("greeting", jobs[job_id])

    def test_only_greeting_changes_and_queue_is_untouched(self) -> None:
        self.store.set_jobs(
            [
                _job("ready-a", score=88, raw_text="岗位原文"),
                _job("ready-b", city="北京"),
                _job("filtered-a", status="filtered"),
            ]
        )
        before = copy.deepcopy(self.store.jobs())
        self.store.set_queue([{"id": "ready-a", "status": "approved", "note": "不要动"}])
        queue_before = self.store.files["queue"].read_bytes()

        self._run({"mode": "user"})

        after = self.store.jobs()
        for old, new in zip(before, after):
            old_without = {key: value for key, value in old.items() if key != "greeting"}
            new_without = {key: value for key, value in new.items() if key != "greeting"}
            self.assertEqual(old_without, new_without)
            self.assertEqual(list(new.keys())[: len(old)], list(old.keys()))
        self.assertEqual(self.store.files["queue"].read_bytes(), queue_before)

    def test_contact_details_and_links_never_enter_drafts(self) -> None:
        self.store.set_jobs(
            [
                _job("ready-a"),
                _job("ready-link", company="星河科技 https://example.com/jobs"),
                _job("ready-phone", company="星河科技 电话 13800000000"),
            ]
        )
        result = self._run({"mode": "user"})
        jobs = {row["id"]: row for row in self.store.jobs()}
        skipped = {row["id"]: row["reason"] for row in result["skipped"]}
        self.assertIn("ready-link", skipped)
        self.assertNotIn("greeting", jobs["ready-link"])
        # A JD company with digits is blanked by tools/greeting.py, so the
        # phone can never reach the draft; the guard still rejects links.
        phone_greeting = jobs["ready-phone"]["greeting"]
        self.assertNotIn("13800000000", phone_greeting)
        self.assertNotRegex(phone_greeting, r"\d")
        greeting = jobs["ready-a"]["greeting"]
        for forbidden in (
            "13800000000",
            "demo@example.com",
            "demo_wechat",
            "http",
            "@",
        ):
            self.assertNotIn(forbidden, greeting)

    def test_ids_narrow_the_selection(self) -> None:
        self.store.set_jobs([_job("ready-a"), _job("ready-b")])
        result = self._run({"mode": "user", "ids": ["ready-b"]})
        self.assertEqual(result["generated"], 1)
        jobs = {row["id"]: row for row in self.store.jobs()}
        self.assertNotIn("greeting", jobs["ready-a"])
        self.assertIn("greeting", jobs["ready-b"])

    def test_empty_profile_and_missing_cv_are_rejected(self) -> None:
        self.store.set_profile(backend.default_profile())
        self.store.set_jobs([_job("ready-a")])
        with self.assertRaises(backend.ApiError) as raised:
            self._run({"mode": "user"})
        self.assertEqual(raised.exception.status, 409)
        self.assertNotIn("greeting", self.store.jobs()[0])

    def test_mode_is_a_compatibility_field(self) -> None:
        """``mode`` is ignored: there is one dataset, so every value works."""
        for mode in ("demo", "other", "user"):
            with self.subTest(mode=mode):
                self.store.set_jobs([_job("ready-a")])
                result = self._run({"mode": mode})
                self.assertEqual(result["generated"], 1)
                jobs = {row["id"]: row for row in self.store.jobs()}
                self.assertIn("greeting", jobs["ready-a"])

    def test_invalid_ids_are_rejected(self) -> None:
        for ids in ([], "ready-a", [""], ["  "]):
            with self.subTest(ids=ids):
                with self.assertRaises(backend.ApiError):
                    self._run({"mode": "user", "ids": ids})

    def test_action_is_registered(self) -> None:
        self.assertIs(
            backend.ACTIONS["generate-job-greetings"], backend.generate_job_greetings
        )

    def test_greeting_json_stays_serialisable(self) -> None:
        self.store.set_jobs([_job("ready-a")])
        self._run({"mode": "user"})
        raw = self.store.files["jobs"].read_text(encoding="utf-8")
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(json.loads(raw)[0]["id"], "ready-a")


if __name__ == "__main__":
    unittest.main()
