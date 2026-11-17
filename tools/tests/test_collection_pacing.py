#!/usr/bin/env python3
"""Collection pacing and safety-limit contracts, aligned to BOSS.

BOSS is the reference (user-confirmed): 2.0–5.0 s between pages × the pace
multiplier, 60 search / 900 detail pages per day, 3 consecutive failures and a
5–10 minute risk cooldown.  The other platforms may stay slower but must never
get faster, and their existing delays must never be lowered.

Tests only read module constants and constructors; no browser, no network.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot.collection import pacing  # noqa: E402
from offerpilot.collection.platforms import boss, job51, liepin, zhilian  # noqa: E402

PACES = (1.0, 1.5, 3.0, 5.0)


def _config(multiplier: float) -> dict:
    return {"collection": {"collection_delay_multiplier": multiplier}}


class BossReferenceTests(unittest.TestCase):
    def test_default_reference_values(self):
        self.assertEqual(pacing.delay_multiplier({}), 1.5)
        self.assertEqual(pacing.page_delay_range({}), (3.0, 7.5))
        self.assertEqual(pacing.page_open_wait({}), 4.5)
        self.assertEqual(pacing.detail_open_wait({}), 3.0)
        self.assertEqual(pacing.per_minute_limit({}), 20)

    def test_pace_scales_the_reference(self):
        self.assertEqual(pacing.page_delay_range(_config(1.0)), (2.0, 5.0))
        self.assertEqual(pacing.per_minute_limit(_config(1.0)), 30)
        self.assertEqual(pacing.page_delay_range(_config(3.0)), (6.0, 15.0))
        self.assertEqual(pacing.per_minute_limit(_config(3.0)), 10)

    def test_multiplier_is_bounded(self):
        self.assertEqual(pacing.delay_multiplier(_config(0.1)), 1.0)
        self.assertEqual(pacing.delay_multiplier(_config(99)), 5.0)
        self.assertEqual(pacing.delay_multiplier({"collection": {"collection_delay_multiplier": "x"}}), 1.5)

    def test_default_safety_limits_match_boss(self):
        limits = pacing.collection_limits({})
        self.assertEqual(limits.daily_search_pages, 60)
        self.assertEqual(limits.daily_detail_pages, 900)
        self.assertEqual(limits.max_consecutive_failures, 3)
        self.assertEqual(limits.risk_pause_min_minutes, 5)
        self.assertEqual(limits.risk_pause_max_minutes, 10)

    def test_limits_read_config_with_sane_bounds(self):
        limits = pacing.collection_limits({
            "collection": {
                "daily_search_page_limit": 5,
                "daily_detail_page_limit": 0,
                "max_consecutive_page_failures": 7,
                "risk_pause_min_minutes": 2,
                "risk_pause_max_minutes": 9,
            }
        })
        self.assertEqual(limits.daily_search_pages, 5)
        self.assertEqual(limits.daily_detail_pages, 1)  # never below 1
        self.assertEqual(limits.max_consecutive_failures, 7)
        self.assertEqual(limits.risk_pause_min_minutes, 2)
        self.assertEqual(limits.risk_pause_max_minutes, 9)
        self.assertEqual(limits.pause_minutes(lambda a, b: 3), 3)

    def test_boss_collector_reads_the_shared_module(self):
        source = inspect.getsource(boss.BossCollector.collect)
        self.assertIn("pacing.delay_multiplier", source)
        self.assertIn("pacing.BASE_PAGE_DELAY_MIN", source)
        self.assertIn("pacing.collection_limits", source)

    def test_collection_guard_is_none_without_a_database(self):
        self.assertIsNone(pacing.collection_guard(None, {}, "zhilian"))


class RaiseOnlyFloorTests(unittest.TestCase):
    def test_floor_range_never_lowers_an_existing_delay(self):
        for pace in PACES:
            config = _config(pace)
            detail = pacing.floor_range((8.0, 15.0), config)
            liepin_detail = pacing.floor_range((10.0, 18.0), config)
            liepin_page = pacing.floor_range((20.0, 35.0), config)
            # Existing delays are never lowered.
            self.assertGreaterEqual(detail[0], 8.0)
            self.assertGreaterEqual(detail[1], 15.0)
            self.assertGreaterEqual(liepin_detail[0], 10.0)
            self.assertGreaterEqual(liepin_detail[1], 18.0)
            self.assertGreaterEqual(liepin_page[0], 20.0)
            self.assertGreaterEqual(liepin_page[1], 35.0)
            # And still never faster than BOSS at the same pace.
            boss_low, boss_high = pacing.page_delay_range(config)
            self.assertGreaterEqual(detail[0], boss_low)
            self.assertGreaterEqual(detail[1], boss_high)
            self.assertGreaterEqual(liepin_detail[0], boss_low)
            self.assertGreaterEqual(liepin_detail[1], boss_high)
            self.assertGreaterEqual(liepin_page[0], boss_low)
            self.assertGreaterEqual(liepin_page[1], boss_high)

    def test_floor_seconds_never_lower_than_boss_min(self):
        self.assertEqual(pacing.floor_seconds(1.5, {}), 3.0)
        self.assertEqual(pacing.floor_seconds(1.5, _config(1.0)), 2.0)
        self.assertEqual(pacing.floor_seconds(30.0, {}), 30.0)


class RateLimiterFloorTests(unittest.TestCase):
    def _assert_limiter_not_faster(self, factory, pace):
        config = _config(pace)
        boss_gap = pacing.page_delay_range(config)
        boss_limit = pacing.per_minute_limit(config)
        for total in (0, 100, 1000):
            with self.subTest(pace=pace, total=total):
                limiter = factory(total, boss_gap, boss_limit)
                self.assertGreaterEqual(limiter.gap_range[0], boss_gap[0])
                self.assertGreaterEqual(limiter.gap_range[1], boss_gap[1])
                self.assertLessEqual(limiter.per_min_limit, boss_limit)

    def test_zhilian_never_faster_than_boss(self):
        for pace in PACES:
            self._assert_limiter_not_faster(
                lambda total, gap, limit: zhilian._ApiRateLimiter(
                    total_requests=total, pacing_range=gap, per_min_limit=limit
                ),
                pace,
            )

    def test_51job_never_faster_than_boss(self):
        for pace in PACES:
            self._assert_limiter_not_faster(
                lambda total, gap, limit: job51._ApiRateLimiter(
                    total_requests=total, pacing_range=gap, per_min_limit=limit
                ),
                pace,
            )

    def test_slow_down_only_gets_slower(self):
        config = _config(1.5)
        limiter = job51._ApiRateLimiter(
            total_requests=0,
            pacing_range=pacing.page_delay_range(config),
            per_min_limit=pacing.per_minute_limit(config),
        )
        before = (limiter.gap_range, limiter.per_min_limit)
        limiter.slow_down()
        self.assertGreaterEqual(limiter.gap_range[0], before[0][0])
        self.assertLessEqual(limiter.per_min_limit, before[1])


class CollectorPacingTests(unittest.TestCase):
    def test_zhilian_detail_delay_is_not_lowered(self):
        for pace in PACES:
            collector = zhilian.ZhilianCollector(config=_config(pace))
            self.assertGreaterEqual(collector.delay_range[0], 8.0)
            self.assertGreaterEqual(collector.delay_range[1], 15.0)

    def test_liepin_delays_are_not_lowered(self):
        for pace in PACES:
            collector = liepin.LiepinCollector(config=_config(pace))
            self.assertGreaterEqual(collector.detail_delay_range[0], 10.0)
            self.assertGreaterEqual(collector.detail_delay_range[1], 18.0)
            self.assertGreaterEqual(collector.page_delay_range[0], 20.0)
            self.assertGreaterEqual(collector.page_delay_range[1], 35.0)

    def test_zhilian_post_click_wait_matches_boss_floor(self):
        source = inspect.getsource(zhilian)
        self.assertNotIn("stop_event.wait(1.5)", source)
        self.assertNotIn("self.sleep(1.5)", source)
        self.assertIn("pacing.floor_seconds", source)

    def test_collectors_wire_the_boss_guard_and_limits(self):
        for module, platform in ((zhilian, "zhilian"), (job51, "51job"), (liepin, "liepin")):
            with self.subTest(platform=platform):
                source = inspect.getsource(module)
                self.assertIn("pacing.collection_guard", source)
                self.assertIn("pacing.collection_limits", source)
                self.assertIn("_reserve_page", source)
                self.assertIn("_risk_blocked", source)
                self.assertIn("max_consecutive_failures", source)


if __name__ == "__main__":
    unittest.main()