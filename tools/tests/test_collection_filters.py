#!/usr/bin/env python3
"""Per-platform collection filter pass-through for zhilian / 51job / liepin.

Covered here (no browser, no network):

- ``normalize_collection_filters`` keeps each platform's declared keys,
  preserves unknown keys instead of silently dropping them, and logs them;
- ``apply_collection_filters`` matches candidate fields against the requested
  values key by key, drops only on a confident mismatch, and keeps the
  candidate (reporting the reason) when a platform lacks a field or a request
  value is not parseable — never pretending to have filtered;
- the orchestrator normalizes filters for all platforms (the two old spots
  that zeroed non-BOSS filters are gone) and wires the candidate filters into
  both collection hooks;
- zhilian ``sort=newest`` is reported as not-applied instead of being
  accepted silently.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot.collection.models import (  # noqa: E402
    PLATFORM_FILTER_KEYS,
    JobCandidate,
    apply_collection_filters,
    normalize_collection_filters,
)
from offerpilot.collection.orchestrator import (  # noqa: E402
    CollectionOrchestrator,
    normalize_collection_options,
    validate_collection_options,
)

ALL_KEYS = {"education", "degree", "experience", "recruitment_type", "job_type", "salary", "scale", "industry"}


def _candidate(**overrides):
    base = dict(
        platform="zhilian", source_job_id="job-1", title="测试工程师",
        company="测试公司", salary="15-25K", education="本科",
        experience="3-5年", recruitment_type="unknown", jd="负责后端开发",
        company_size="100-499人", company_industry="互联网",
    )
    base.update(overrides)
    return JobCandidate(**base)


class NormalizeFiltersTests(unittest.TestCase):
    def test_declared_keys_survive_for_every_platform(self):
        for platform in ("zhilian", "51job", "liepin"):
            with self.subTest(platform=platform):
                self.assertEqual(
                    PLATFORM_FILTER_KEYS[platform], ALL_KEYS, platform,
                )

    def test_values_are_cleaned_into_lists(self):
        raw = {"education": "本科, 硕士", "experience": ["3-5年", "5-10年"], "job_type": "全职 实习"}
        normalized = normalize_collection_filters(raw, "zhilian")
        self.assertEqual(normalized["education"], ["本科", "硕士"])
        self.assertEqual(normalized["experience"], ["3-5年", "5-10年"])
        self.assertEqual(normalized["job_type"], ["全职", "实习"])

    def test_unknown_keys_are_preserved_and_logged_not_dropped(self):
        logged: list[str] = []
        normalized = normalize_collection_filters(
            {"degree": "本科", "mystery_key": "x"}, "zhilian", log=logged.append,
        )
        self.assertEqual(normalized["degree"], ["本科"])
        self.assertIn("mystery_key", normalized)
        self.assertTrue(any("未知过滤键" in line and "mystery_key" in line for line in logged))

    def test_non_dict_input_is_tolerated(self):
        self.assertEqual(normalize_collection_filters(None, "51job"), {})
        self.assertEqual(normalize_collection_filters("nope", "liepin"), {})

    def test_orchestrator_keeps_filters_for_non_boss_platforms(self):
        options = {
            "platform_order": ["zhilian", "51job", "liepin"],
            "platforms": {
                "zhilian": {
                    "keywords": ["测试"], "cities": ["北京"],
                    "city_codes": {"北京": "530"},
                    "max_pages": 1, "sort": "default",
                    "filters": {"degree": "本科", "experience": "3-5年"},
                },
                "51job": {
                    "keywords": ["测试"], "cities": ["北京"],
                    "city_codes": {"北京": "010000"},
                    "max_pages": 1, "sort": "default",
                    "filters": {"salary": "15-25K"},
                },
                "liepin": {
                    "keywords": ["测试"], "cities": ["北京"],
                    "city_codes": {"北京": "010"},
                    "max_pages": 1, "sort": "default",
                    "filters": {"recruitment_type": "社招"},
                },
            },
        }
        normalized = validate_collection_options(options)
        self.assertEqual(normalized["platforms"]["zhilian"]["filters"]["degree"], ["本科"])
        self.assertEqual(normalized["platforms"]["51job"]["filters"]["salary"], ["15-25K"])
        self.assertEqual(normalized["platforms"]["liepin"]["filters"]["recruitment_type"], ["社招"])

    def test_orchestrator_config_based_normalization_keeps_filters(self):
        config = {
            "_workbench_log": lambda *_: None,
            "platforms": {
                "zhilian": {"enabled": True, "search": {"keywords": ["测试"], "cities": ["北京"], "filters": {"degree": "本科"}}},
                "51job": {"enabled": True, "search": {"keywords": ["测试"], "cities": ["北京"], "filters": {"education": "大专"}}},
                "liepin": {"enabled": True, "search": {"keywords": ["测试"], "cities": ["北京"], "filters": {"experience": "1-3年"}}},
            },
            "collection": {"default_order": ["zhilian", "51job", "liepin"]},
        }
        options = normalize_collection_options(config, None)
        self.assertEqual(options["platforms"]["zhilian"]["filters"]["degree"], ["本科"])
        self.assertEqual(options["platforms"]["51job"]["filters"]["education"], ["大专"])
        self.assertEqual(options["platforms"]["liepin"]["filters"]["experience"], ["1-3年"])

    def test_boss_filters_still_use_the_boss_normalizer(self):
        options = {
            "platform_order": ["boss"],
            "platforms": {"boss": {"keywords": ["测试"], "cities": ["北京"], "max_pages": 1, "filters": {"job_type": "全职"}}},
        }
        normalized = validate_collection_options(options)
        self.assertEqual(normalized["platforms"]["boss"]["filters"]["job_type"], ["全职"])


class ApplyFilterTests(unittest.TestCase):
    def test_empty_filters_keep_everything(self):
        keep, applied, not_applied = apply_collection_filters(_candidate(), {}, "zhilian")
        self.assertTrue(keep)
        self.assertEqual(applied, set())
        self.assertEqual(not_applied, {})

    def test_education_match_and_mismatch(self):
        self.assertTrue(apply_collection_filters(_candidate(education="本科"), {"education": ["本科"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(_candidate(education="本科"), {"education": ["硕士"]}, "zhilian")[0])
        # "本科及以上" contains "本科" -> keep.
        self.assertTrue(apply_collection_filters(_candidate(education="本科及以上"), {"degree": ["本科"]}, "51job")[0])
        self.assertTrue(apply_collection_filters(_candidate(education="本科"), {"education": ["学历不限"]}, "liepin")[0])

    def test_education_missing_field_keeps_and_reports(self):
        keep, applied, not_applied = apply_collection_filters(
            _candidate(education=""), {"education": ["硕士"]}, "zhilian",
        )
        self.assertTrue(keep)
        self.assertNotIn("education", applied)
        self.assertIn("education", not_applied)

    def test_experience_overlap_matching(self):
        # 3-5年 inside 1-3年? No (bands are half-open). Inside 3-5年? Yes.
        self.assertTrue(apply_collection_filters(_candidate(experience="3-5年"), {"experience": ["3-5年"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(_candidate(experience="3-5年"), {"experience": ["1-3年"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(_candidate(experience="3-5年"), {"experience": ["5-10年"]}, "zhilian")[0])
        self.assertTrue(apply_collection_filters(_candidate(experience="3-5年"), {"experience": ["1-5年"]}, "zhilian")[0])
        # "经验不限" accepts any candidate.
        self.assertTrue(apply_collection_filters(_candidate(experience="1-3年"), {"experience": ["经验不限"]}, "51job")[0])
        # 51job "3-4年经验·本科" combined text parses the years.
        self.assertFalse(apply_collection_filters(_candidate(experience="3-4年经验·本科"), {"experience": ["1年以内"]}, "51job")[0])
        # Entry-level tokens match their own point, and "1年以内" includes fresh grads.
        self.assertTrue(apply_collection_filters(_candidate(experience="应届生"), {"experience": ["应届生"]}, "liepin")[0])
        self.assertTrue(apply_collection_filters(_candidate(experience="应届生"), {"experience": ["1年以内"]}, "liepin")[0])
        self.assertFalse(apply_collection_filters(_candidate(experience="应届生"), {"experience": ["3-5年"]}, "liepin")[0])

    def test_experience_unparseable_keeps_and_reports(self):
        keep, applied, not_applied = apply_collection_filters(
            _candidate(experience="经验随便写"), {"experience": ["3-5年"]}, "liepin",
        )
        self.assertTrue(keep)
        self.assertNotIn("experience", applied)
        self.assertIn("experience", not_applied)

    def test_recruitment_type_matching(self):
        campus = _candidate(title="管培生（应届）")
        self.assertTrue(apply_collection_filters(campus, {"recruitment_type": ["校招"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(campus, {"recruitment_type": ["社招"]}, "zhilian")[0])
        self.assertTrue(apply_collection_filters(_candidate(experience="5-10年"), {"recruitment_type": ["社招"]}, "zhilian")[0])
        keep, _, not_applied = apply_collection_filters(
            _candidate(title="工程师", experience="经验不限"), {"recruitment_type": ["社招"]}, "zhilian",
        )
        self.assertTrue(keep)
        self.assertIn("recruitment_type", not_applied)

    def test_job_type_matching(self):
        intern = _candidate(title="实习生（开发）")
        self.assertTrue(apply_collection_filters(intern, {"job_type": ["实习"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(intern, {"job_type": ["全职"]}, "zhilian")[0])
        full_time = _candidate(title="测试工程师")
        self.assertTrue(apply_collection_filters(full_time, {"job_type": ["全职", "实习"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(full_time, {"job_type": ["实习"]}, "zhilian")[0])

    def test_salary_band_matching(self):
        candidate = _candidate(salary="15-25K")
        self.assertTrue(apply_collection_filters(candidate, {"salary": ["15-25K"]}, "zhilian")[0])
        self.assertFalse(apply_collection_filters(candidate, {"salary": ["3-5K"]}, "zhilian")[0])
        self.assertTrue(apply_collection_filters(candidate, {"salary": ["10-20K"]}, "zhilian")[0])
        # A BOSS band code is not a parseable salary on other platforms -> keep + report.
        keep, _, not_applied = apply_collection_filters(candidate, {"salary": ["405"]}, "51job")
        self.assertTrue(keep)
        self.assertIn("salary", not_applied)

    def test_scale_and_industry(self):
        candidate = _candidate(company_size="100-499人", company_industry="互联网")
        self.assertTrue(apply_collection_filters(candidate, {"scale": ["100-499人"]}, "51job")[0])
        self.assertFalse(apply_collection_filters(candidate, {"scale": ["0-20人"]}, "51job")[0])
        self.assertTrue(apply_collection_filters(candidate, {"industry": ["互联网"]}, "51job")[0])
        self.assertFalse(apply_collection_filters(candidate, {"industry": ["金融"]}, "51job")[0])

    def test_scale_and_industry_missing_field_reports_not_dropped(self):
        candidate = _candidate(company_size="", company_industry="")
        keep, _, not_applied = apply_collection_filters(
            candidate, {"scale": ["100-499人"], "industry": ["互联网"]}, "liepin",
        )
        self.assertTrue(keep)
        self.assertIn("scale", not_applied)
        self.assertIn("industry", not_applied)

    def test_multi_key_filter_drops_on_any_mismatch(self):
        filters = {"education": ["本科"], "experience": ["3-5年"]}
        self.assertTrue(apply_collection_filters(_candidate(education="本科", experience="3-5年"), filters, "zhilian")[0])
        self.assertFalse(apply_collection_filters(_candidate(education="本科", experience="1-3年"), filters, "zhilian")[0])
        self.assertFalse(apply_collection_filters(_candidate(education="大专", experience="3-5年"), filters, "zhilian")[0])

    def test_51job_candidate_now_carries_education(self):
        from offerpilot.collection.platforms.job51 import Job51Collector

        item = {
            "jobId": "j1", "jobName": "测试", "fullCompanyName": "公司",
            "workYearString": "3-4年", "degreeString": "本科", "provideSalaryString": "15-25K",
            "jobAreaString": "北京", "companySizeString": "100-499人",
            "industryType1Str": "互联网", "jobDescribe": "开发",
        }
        candidate = Job51Collector._item_to_candidate(item, "北京", "010000", "测试")
        self.assertEqual(candidate.education, "本科")
        self.assertIn("3-4年", candidate.experience)


class OrchestratorHookWiringTests(unittest.TestCase):
    def test_hooks_wire_the_filter_wrappers(self):
        import inspect as _inspect

        source = _inspect.getsource(CollectionOrchestrator.run)
        self.assertIn("_keep_filtered", source)
        self.assertIn("on_list_candidate=_inspect_filtered", source)
        self.assertIn("on_candidate=_save_filtered", source)
        self.assertIn("apply_collection_filters", source)

    def test_boss_is_never_centrally_filtered(self):
        # _keep_filtered short-circuits True for boss; verify by sourcing the run body.
        import inspect as _inspect

        source = _inspect.getsource(CollectionOrchestrator.run)
        self.assertIn('if platform == "boss":', source)
        self.assertIn("return True", source)

    def test_zhilian_sort_newest_is_logged_not_silently_accepted(self):
        options = {
            "platform_order": ["zhilian"],
            "platforms": {"zhilian": {"keywords": ["测试"], "cities": ["北京"], "city_codes": {"北京": "530"}, "max_pages": 1, "sort": "newest"}},
        }
        # validate keeps the accepted value (contract unchanged)…
        normalized = validate_collection_options(options)
        self.assertEqual(normalized["platforms"]["zhilian"]["sort"], "newest")
        # …and the run loop logs that zhilian does not implement it.
        import inspect as _inspect

        source = _inspect.getsource(CollectionOrchestrator.run)
        self.assertIn("智联排序 newest 未生效", source)


if __name__ == "__main__":
    unittest.main()