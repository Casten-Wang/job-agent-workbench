#!/usr/bin/env python3
"""Tests for the three independent match signals.

Fit score, confidence and risk are asserted separately on purpose: the product
must never collapse them into one number.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "tools"),):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import job_match  # noqa: E402


def _job(**extra: object) -> dict:
    row = {"id": "j-match-1", "source_channel": "boss", "hiring_status": "unknown"}
    row.update(extra)
    return row


class FitScoreTests(unittest.TestCase):
    def test_accepts_only_the_documented_zero_to_hundred_scale(self) -> None:
        self.assertEqual(job_match.fit_score({"score": 49}), 49)
        self.assertEqual(job_match.fit_score({"score": 0}), 0)
        self.assertEqual(job_match.fit_score({"score": 100}), 100)
        self.assertEqual(job_match.fit_score({"score": 73.5}), 73.5)

    def test_out_of_range_and_invalid_values_are_null_not_rescaled(self) -> None:
        for value in (None, True, False, -1, 101, "80", "high", float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(job_match.fit_score({"score": value}))


class FitConfidenceTests(unittest.TestCase):
    def test_averages_evidence_weight_per_condition(self) -> None:
        job = {
            "mandatory_conditions": [
                {"condition": "a", "status": "已满足", "evidence": "e"},
                {"condition": "b", "status": "明确不满足", "evidence": "e"},
                {"condition": "c", "status": "待确认", "evidence": "e"},
                {"condition": "d", "status": "待确认", "evidence": ""},
            ]
        }
        # (1.0 + 1.0 + 0.5 + 0.0) / 4
        self.assertEqual(job_match.fit_confidence(job), 0.62)

    def test_unrecognized_status_with_evidence_counts_as_weak(self) -> None:
        job = {"mandatory_conditions": [{"condition": "a", "status": "?", "evidence": "e"}]}
        self.assertEqual(job_match.fit_confidence(job), 0.25)

    def test_falls_back_to_score_coverage(self) -> None:
        self.assertEqual(job_match.fit_confidence({"score_coverage": 0.95}), 0.95)
        self.assertEqual(job_match.fit_confidence({"score_coverage": 1.7}), 1.0)
        self.assertEqual(job_match.fit_confidence({"score_coverage": -0.2}), 0.0)
        self.assertIsNone(job_match.fit_confidence({"score_coverage": "0.9"}))

    def test_no_evidence_and_no_coverage_is_null(self) -> None:
        self.assertIsNone(job_match.fit_confidence({}))
        self.assertIsNone(job_match.fit_confidence({"mandatory_conditions": []}))
        self.assertIsNone(job_match.fit_confidence({"score_coverage": None}))


class RiskLevelTests(unittest.TestCase):
    def test_closed_posting_is_high(self) -> None:
        self.assertEqual(job_match.risk_level(_job(hiring_status="closed")), "high")

    def test_missing_source_is_high_even_with_a_status(self) -> None:
        self.assertEqual(
            job_match.risk_level({"hiring_status": "not_closed", "source_channel": ""}),
            "high",
        )

    def test_manual_paste_is_medium(self) -> None:
        self.assertEqual(
            job_match.risk_level(_job(source_channel="manual_paste", hiring_status="not_closed")),
            "medium",
        )

    def test_known_platform_with_unknown_status_is_medium(self) -> None:
        self.assertEqual(job_match.risk_level(_job(hiring_status="unknown")), "medium")
        self.assertEqual(job_match.risk_level(_job(hiring_status="")), "medium")

    def test_known_platform_and_not_closed_is_low(self) -> None:
        self.assertEqual(job_match.risk_level(_job(hiring_status="not_closed")), "low")
        self.assertEqual(
            job_match.risk_level({"source_platform": "zhilian", "hiring_status": "not_closed"}),
            "low",
        )

    def test_no_signal_is_null(self) -> None:
        self.assertIsNone(job_match.risk_level({}))
        self.assertIsNone(job_match.risk_level({"source_channel": "", "hiring_status": ""}))


class MatchJobTests(unittest.TestCase):
    def test_returns_three_separate_keys_and_no_combined_score(self) -> None:
        result = job_match.match_job(
            _job(
                score=49,
                score_coverage=0.95,
                hiring_status="unknown",
                mandatory_conditions=[
                    {"condition": "a", "status": "待确认", "evidence": "e"}
                ],
            )
        )
        self.assertEqual(set(result), {"fit_score", "fit_confidence", "risk_level"})
        self.assertEqual(result["fit_score"], 49)
        self.assertEqual(result["fit_confidence"], 0.5)
        self.assertEqual(result["risk_level"], "medium")
        for key in ("overall", "combined", "final_score"):
            self.assertNotIn(key, result)


if __name__ == "__main__":
    unittest.main()
