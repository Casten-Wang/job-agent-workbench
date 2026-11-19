"""Complete JD requirements must survive input validation and trace loading."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor/offerpilot/src"))
from offerpilot.ai import scorer


def payload(count):
    return {
        "dimensions": {k: {"coefficient": 0.75, "evidence": "测试证据"} for k in scorer.MATCH_WEIGHTS},
        "mandatory_conditions": [
            {"condition": f"任职要求 {i}", "status": "待确认", "evidence": "未知"}
            for i in range(count)
        ],
        "hiring_status": {"status": "unknown", "evidence": "未知"},
        "reason": "有相关项目证据；实习安排待确认",
    }


class ScoringMandatoryCapacityTests(unittest.TestCase):
    def test_eleven_conditions_are_retained(self):
        result = scorer.validate_structured_score_payload(payload(11))
        self.assertIsNotNone(result)
        self.assertEqual(len(result.mandatory_conditions), 11)
        trace = scorer.build_score_trace(result)
        self.assertEqual(len(trace["mandatory_conditions"]), 11)
        self.assertIsNotNone(scorer.sanitize_score_trace(trace))

    def test_capacity_is_bounded(self):
        self.assertIsNotNone(scorer.validate_structured_score_payload(payload(50)))
        self.assertIsNone(scorer.validate_structured_score_payload(payload(51)))

    def test_invalid_coefficient_status_and_evidence_stay_rejected(self):
        for mutate in (
            lambda p: p["dimensions"]["core_duties"].update(coefficient=0.9),
            lambda p: p["mandatory_conditions"][0].update(status="应该满足"),
            lambda p: p["mandatory_conditions"][0].update(evidence=None),
        ):
            p = payload(11)
            mutate(p)
            self.assertIsNone(scorer.validate_structured_score_payload(p))
