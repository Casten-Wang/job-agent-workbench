#!/usr/bin/env python3
"""Offline tests for tools/evidence_checker.py (read-only number evidence check)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import evidence_checker as ec  # noqa: E402


FACTS = "项目经历：校园问卷工具 · 产品负责人。访谈了6名用户，回收500份问卷，评审时间缩短40%。"


class SupportedNumbersTests(unittest.TestCase):
    def test_numbers_present_in_facts_are_supported(self):
        result = ec.check_text_against_facts("我访谈过6名用户，评审时间缩短40%。", FACTS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["unsupported_claims"], [])
        self.assertEqual(len(result["claims"]), 2)
        self.assertTrue(all(c["has_evidence"] for c in result["claims"]))

    def test_number_formatting_differences_still_match(self):
        result = ec.check_text_against_facts("回收了500.0份问卷。", FACTS)
        self.assertTrue(result["ok"])

    def test_fullwidth_digits_are_normalized(self):
        result = ec.check_text_against_facts("缩短了４０％。", FACTS)
        self.assertTrue(result["ok"])


class UnsupportedNumbersTests(unittest.TestCase):
    def test_invented_number_is_flagged(self):
        result = ec.check_text_against_facts("我把转化率提升了80%。", FACTS)
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unsupported_claims"]), 1)
        claim = result["unsupported_claims"][0]
        self.assertEqual(claim["value"], "80")
        self.assertFalse(claim["has_evidence"])
        self.assertIn("80", claim["context"])

    def test_mixed_supported_and_unsupported(self):
        result = ec.check_text_against_facts("访谈6名用户，带领12人团队。", FACTS)
        self.assertFalse(result["ok"])
        values = [c["value"] for c in result["unsupported_claims"]]
        self.assertEqual(values, ["12"])

    def test_empty_facts_flags_every_quantified_claim(self):
        result = ec.check_text_against_facts("访谈6名用户。", "")
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["unsupported_claims"]), 1)


class NonClaimNumbersTests(unittest.TestCase):
    def test_bare_year_is_not_a_claim(self):
        result = ec.check_text_against_facts("2026年秋招，期待交流。", FACTS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claims"], [])

    def test_text_without_numbers_is_ok(self):
        result = ec.check_text_against_facts("您好，我对这个岗位很感兴趣。", FACTS)
        self.assertTrue(result["ok"])
        self.assertEqual(result["claims"], [])

    def test_none_and_empty_inputs_do_not_crash(self):
        self.assertTrue(ec.check_text_against_facts("", "")["ok"])
        self.assertTrue(ec.check_text_against_facts(None, None)["ok"])  # type: ignore[arg-type]


class ReadOnlyTests(unittest.TestCase):
    def test_result_never_echoes_full_generated_text(self):
        generated = "我把转化率提升了80%，并且很期待与您沟通。"
        result = ec.check_text_against_facts(generated, FACTS)
        self.assertNotIn("text", result)
        self.assertNotIn("generated", result)
        # Context snippets are short windows, never the whole message.
        for claim in result["claims"]:
            self.assertLess(len(claim["context"]), len(generated))


if __name__ == "__main__":
    unittest.main()
