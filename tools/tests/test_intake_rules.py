#!/usr/bin/env python3
"""Intake rules for the job pool: manual-override reasons and the 30-day duplicate hold.

Fictional data only. Each test runs against an isolated temp copy of the local
dataset, so nothing reads or writes web/data/user.
"""

from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
TOOLS_DIR = PROJECT_ROOT / "tools"
for _path in (str(WEB_DIR), str(TOOLS_DIR), str(TOOLS_DIR / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402  (local module in web/)
import local_fixtures  # noqa: E402  (test-only seed helper)


class IntakeRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = patch.object(backend, "WEB_DIR", Path(self._tmp.name))
        self._patch.start()
        local_fixtures.seed_local_data(backend.get_store("user"))
        self.store = backend.get_store("user")
        self.today = dt.datetime.now(dt.timezone.utc).astimezone().date()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _add_job(self, job_id: str, company: str, title: str, city: str = "上海", score=86) -> None:
        rows = self.store.jobs()
        rows.append({
            "id": job_id,
            "company": company,
            "title": title,
            "city": city,
            "score": score,
            "score_raw": score,
            "score_coverage": 0.9 if score is not None else None,
            "score_scale": backend.MATCH_SCORE_SCALE_LABEL if score is not None else None,
            "scoring_model": backend.MATCH_SCORE_MODEL if score is not None else None,
            "mandatory_status": "satisfied",
            "hiring_status": "unknown",
            "source_channel": "manual_paste",
            "raw_text": "测试数据：普通岗位。",
        })
        self.store.set_jobs(rows)

    def _days_ago(self, days: int) -> str:
        return (self.today - dt.timedelta(days=days)).isoformat()

    def _mark_sent(self, job_id: str, day: str) -> None:
        self.store.set_deliveries([{
            "batch_id": f"dlv-test-{job_id}",
            "created_at": f"{day}T10:00:00+08:00",
            "items": [{
                "job_id": job_id,
                "status": "sent",
                "started_at": f"{day}T10:00:00+08:00",
                "finished_at": f"{day}T10:00:30+08:00",
            }],
        }])

    # --- manual override reason ---

    def test_manual_low_score_requires_a_dropdown_reason(self):
        before = list(self.store.queue())
        with self.assertRaises(backend.ApiError) as ctx:
            backend.enqueue({"mode": "user", "ids": ["demo-job-003"], "allow_low_score": True})
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("下拉框", str(ctx.exception))
        # Validation runs before any write: the queue is unchanged.
        self.assertEqual(self.store.queue(), before)

    def test_manual_reason_outside_the_dropdown_is_rejected(self):
        with self.assertRaises(backend.ApiError):
            backend.enqueue({
                "mode": "user",
                "ids": ["demo-job-003"],
                "allow_low_score": True,
                "override_reason": "随便写一句",
            })

    def test_manual_reason_is_stored_on_the_queue_row(self):
        result = backend.enqueue({
            "mode": "user",
            "ids": ["demo-job-003"],
            "allow_low_score": True,
            "override_reason": "有内推或熟人渠道",
        })
        self.assertIn("demo-job-003", result["manual"])
        row = next(item for item in self.store.queue() if item["id"] == "demo-job-003")
        self.assertEqual(row["override_reason"], "有内推或熟人渠道")
        self.assertTrue(row["override_at"])
        self.assertTrue(row["manual_override"])

    def test_normal_enqueue_does_not_need_a_reason(self):
        self._add_job("plain-score-job", "虚构普通有限公司", "产品助理", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["plain-score-job"]})
        self.assertIn("plain-score-job", result["accepted"] + result["approved"])

    # --- 30-day duplicate hold ---

    def test_same_job_already_sent_within_30_days_is_held_on_enqueue(self):
        self._add_job("dup-new-job", "虚构重复有限公司", "产品助理", score=86)
        self._add_job("dup-old-job", "虚构重复有限公司", "产品助理", score=86)
        self._mark_sent("dup-old-job", self._days_ago(5))
        result = backend.enqueue({"mode": "user", "ids": ["dup-new-job"]})
        self.assertEqual(result["accepted"], [])
        self.assertEqual([item["id"] for item in result["recent_duplicates"]], ["dup-new-job"])
        self.assertIn("30 天内已发送过", result["recent_duplicates"][0]["reason"])
        self.assertFalse(any(row["id"] == "dup-new-job" for row in self.store.queue()))

    def test_same_job_outside_30_days_is_not_held(self):
        self._add_job("old-dup-job", "虚构过期有限公司", "产品助理", score=86)
        self._add_job("old-sent-job", "虚构过期有限公司", "产品助理", score=86)
        self._mark_sent("old-sent-job", self._days_ago(31))
        result = backend.enqueue({"mode": "user", "ids": ["old-dup-job"]})
        self.assertEqual(result["recent_duplicates"], [])
        self.assertIn("old-dup-job", result["accepted"])

    def test_day_30_is_still_inside_the_window(self):
        self._add_job("edge-new-job", "虚构边界有限公司", "产品助理", score=86)
        self._add_job("edge-old-job", "虚构边界有限公司", "产品助理", score=86)
        self._mark_sent("edge-old-job", self._days_ago(30))
        result = backend.enqueue({"mode": "user", "ids": ["edge-new-job"]})
        self.assertEqual([item["id"] for item in result["recent_duplicates"]], ["edge-new-job"])

    def test_different_city_is_not_a_duplicate(self):
        self._add_job("city-a-job", "虚构城市有限公司", "产品助理", city="上海", score=86)
        self._add_job("city-b-job", "虚构城市有限公司", "产品助理", city="北京", score=86)
        self._mark_sent("city-b-job", self._days_ago(3))
        result = backend.enqueue({"mode": "user", "ids": ["city-a-job"]})
        self.assertEqual(result["recent_duplicates"], [])
        self.assertIn("city-a-job", result["accepted"])

    def test_placeholder_company_never_matches_as_duplicate(self):
        self._add_job("placeholder-a", "未填写公司", "产品助理", score=86)
        self._add_job("placeholder-b", "未填写公司", "产品助理", score=86)
        self._mark_sent("placeholder-b", self._days_ago(2))
        result = backend.enqueue({"mode": "user", "ids": ["placeholder-a"]})
        self.assertEqual(result["recent_duplicates"], [])

    def test_confirm_holds_a_row_whose_job_was_sent_recently(self):
        self._add_job("confirm-new-job", "虚构确认有限公司", "产品助理", score=86)
        self._add_job("confirm-old-job", "虚构确认有限公司", "产品助理", score=86)
        self._mark_sent("confirm-old-job", self._days_ago(4))
        rows = self.store.queue()
        rows.append({
            "id": "confirm-new-job",
            "score": 86,
            "company": "虚构确认有限公司",
            "title": "产品助理",
            "status": "pending",
            "Source_Channel": "manual_paste",
            "created_at": self.today.isoformat(),
        })
        self.store.set_queue(rows)
        result = backend.confirm_queue({"mode": "user", "ids": ["confirm-new-job"]})
        self.assertEqual(result["confirmed"], [])
        self.assertEqual([item["id"] for item in result["recent_duplicates"]], ["confirm-new-job"])
        row = next(item for item in self.store.queue() if item["id"] == "confirm-new-job")
        self.assertEqual(row["status"], "pending")

    def test_confirm_does_not_hold_a_row_against_its_own_queue_entry(self):
        rows = self.store.queue()
        for row in rows:
            row["status"] = "pending"
        self.store.set_queue(rows)
        result = backend.confirm_queue({"mode": "user", "ids": ["demo-job-001"]})
        self.assertEqual(result["confirmed"], ["demo-job-001"])
        self.assertEqual(result["recent_duplicates"], [])


    # --- city gate (profile.json job_intent.cities is the source of truth) ---

    def _set_profile_cities(self, cities: list[str]) -> None:
        profile = self.store.profile()
        profile["job_intent"]["cities"] = cities
        self.store.set_profile(profile)

    def test_job_outside_profile_cities_is_rejected_even_when_manual(self):
        self._set_profile_cities(["上海"])
        self._add_job("beijing-job", "虚构北京有限公司", "产品助理", city="北京", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["beijing-job"]})
        self.assertEqual([item["id"] for item in result["city_blocked"]], ["beijing-job"])
        self.assertIn("目标城市", result["city_blocked"][0]["reason"])
        self.assertFalse(any(row["id"] == "beijing-job" for row in self.store.queue()))

        manual = backend.enqueue({
            "mode": "user",
            "ids": ["beijing-job"],
            "allow_low_score": True,
            "override_reason": "值得沟通，人工判断",
        })
        self.assertEqual([item["id"] for item in manual["city_blocked"]], ["beijing-job"])
        self.assertFalse(any(row["id"] == "beijing-job" for row in self.store.queue()))

    def test_job_inside_profile_cities_passes(self):
        self._set_profile_cities(["上海"])
        self._add_job("shanghai-job", "虚构上海有限公司", "产品助理", city="上海·长宁", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["shanghai-job"]})
        self.assertEqual(result["city_blocked"], [])
        self.assertIn("shanghai-job", result["accepted"] + result["approved"])

    def test_missing_job_city_passes_with_no_guess(self):
        self._set_profile_cities(["上海"])
        self._add_job("no-city-job", "虚构无城市有限公司", "产品助理", city="", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["no-city-job"]})
        self.assertEqual(result["city_blocked"], [])
        self.assertIn("no-city-job", result["accepted"] + result["approved"])

    def test_collect_prefill_uses_workbench_cities_not_stale_offerpilot_cities(self):
        user_store = backend.get_store("user")
        profile = user_store.profile()
        profile["job_intent"]["cities"] = ["上海"]
        user_store.set_profile(profile)
        fake_state = {
            "ok": True,
            "preferences": {"keywords": ["产品经理"], "cities": ["北京"]},
        }
        with patch.object(backend.offerpilot_runtime, "get_state", return_value=fake_state):
            state = backend.get_offerpilot_state("user")
        self.assertEqual(state["preferences"]["cities"], ["上海"])
        self.assertEqual(state["preferences"]["keywords"], ["产品经理"])

    def test_empty_profile_cities_falls_back_to_config(self):
        self._set_profile_cities([])
        self._add_job("config-city-job", "虚构回退有限公司", "产品助理", city="北京", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["config-city-job"]})
        self.assertEqual([item["id"] for item in result["city_blocked"]], ["config-city-job"])


    def test_missing_education_and_experience_pass_with_warning(self):
        self._set_profile_cities(["上海"])
        self._add_job("no-edu-job", "虚构学历空有限公司", "产品助理", city="上海", score=86)
        result = backend.enqueue({"mode": "user", "ids": ["no-edu-job"]})
        self.assertEqual(result["city_blocked"], [])
        self.assertIn("no-edu-job", result["accepted"] + result["approved"])
        self.assertEqual(result["incomplete"], [{"id": "no-edu-job", "missing": ["学历", "经验"]}])
        self.assertIn("已放行并提示", result["message"])

    def test_recorded_education_and_experience_raise_no_warning(self):
        self._set_profile_cities(["上海"])
        self._add_job("full-edu-job", "虚构学历全有限公司", "产品助理", city="上海", score=86)
        rows = self.store.jobs()
        for row in rows:
            if row["id"] == "full-edu-job":
                row["education"] = "本科"
                row["experience"] = "1-3 年"
        self.store.set_jobs(rows)
        result = backend.enqueue({"mode": "user", "ids": ["full-edu-job"]})
        self.assertEqual(result["incomplete"], [])


if __name__ == "__main__":
    unittest.main()
