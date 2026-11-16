#!/usr/bin/env python3
"""City gate tests for the embedded OfferPilot runtime.

All data here is fictional.  The tests only exercise pure functions: no
config.yaml is read or written, no browser is opened and no network call is
made.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
WEB_DIR = PROJECT_ROOT / "web"
for _path in (str(VENDOR_SRC), str(WEB_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime  # noqa: E402  (local module in web/)
from offerpilot.ai.prefilter import quick_score  # noqa: E402


def _job(**overrides: object) -> dict:
    job = {
        "title": "示例产品助理",
        "company": "示例科技有限公司",
        "city": "上海·长宁",
        "salary": "10-15K",
        "jd": "负责需求整理与数据看板。",
    }
    job.update(overrides)
    return job


def _config(**profile_overrides: object) -> dict:
    profile = {
        "target_cities": ["上海"],
        "salary_min": 0,
        "salary_max": 0,
        "allow_internship": False,
        "deal_breakers": [],
        "jd_deal_breakers": [],
        "blocked_companies": [],
    }
    profile.update(profile_overrides)
    return {"profile": profile}


class QuickScoreCityTests(unittest.TestCase):
    def test_city_outside_targets_is_rejected_with_city_name(self):
        score, reason = quick_score(_job(city="广州"), _config())
        self.assertEqual(score, 0)
        self.assertEqual(reason, "城市不在目标城市内: 广州")

    def test_missing_city_passes(self):
        self.assertEqual(quick_score(_job(city=""), _config()), (100, "预筛通过"))
        self.assertEqual(quick_score(_job(city=None), _config()), (100, "预筛通过"))

    def test_empty_target_list_passes(self):
        self.assertEqual(quick_score(_job(city="广州"), _config(target_cities=[])), (100, "预筛通过"))

    def test_substring_city_matches_target(self):
        self.assertEqual(quick_score(_job(city="上海·长宁"), _config(target_cities=["上海"])), (100, "预筛通过"))
        self.assertEqual(quick_score(_job(city="上海"), _config(target_cities=["上海"])), (100, "预筛通过"))

    def test_existing_rejection_keeps_its_reason(self):
        # The city gate is appended after the existing branches, so an earlier
        # rejection still reports its own reason.
        config = _config(blocked_companies=["示例科技"])
        score, reason = quick_score(_job(city="广州"), config)
        self.assertEqual(score, 0)
        self.assertEqual(reason, "触发公司屏蔽: 示例科技")

        score, reason = quick_score(_job(city="广州", salary="3-4K"), _config(salary_min=10))
        self.assertEqual(score, 0)
        self.assertTrue(reason.startswith("薪资低于硬性要求"), reason)


class RuntimeCityOverrideTests(unittest.TestCase):
    def test_task_option_cities_override_runtime_target_cities(self):
        config = _config(target_cities=["北京"])
        options = {
            "platform_order": ["boss"],
            "platforms": {"boss": {"cities": ["上海"]}},
        }
        overridden = offerpilot_runtime._with_collection_cities(config, options)
        self.assertEqual(overridden["profile"]["target_cities"], ["上海"])
        # Only the in-memory copy changes; the loaded config is untouched.
        self.assertEqual(config["profile"]["target_cities"], ["北京"])
        self.assertEqual(quick_score(_job(city="广州"), overridden)[0], 0)
        self.assertEqual(quick_score(_job(city="上海·长宁"), overridden), (100, "预筛通过"))

    def test_option_cities_are_deduped_across_platforms(self):
        options = {
            "platform_order": ["boss", "zhilian"],
            "platforms": {
                "boss": {"cities": ["上海", "杭州"]},
                "zhilian": {"cities": ["上海"]},
            },
        }
        overridden = offerpilot_runtime._with_collection_cities(_config(), options)
        self.assertEqual(overridden["profile"]["target_cities"], ["上海", "杭州"])

    def test_no_option_cities_keeps_runtime_config(self):
        config = _config(target_cities=["北京"])
        self.assertIs(offerpilot_runtime._with_collection_cities(config, None), config)
        self.assertEqual(
            offerpilot_runtime._with_collection_cities(
                config, {"platform_order": ["boss"], "platforms": {"boss": {"cities": []}}}
            )["profile"]["target_cities"],
            ["北京"],
        )


if __name__ == "__main__":
    unittest.main()
