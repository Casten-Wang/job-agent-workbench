#!/usr/bin/env python3
"""Offline tests for tools/resume_quality.py (read-only quality hints)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import resume_quality as rq  # noqa: E402


class StarStructureTests(unittest.TestCase):
    def test_full_four_stage_text_is_detected(self):
        text = "背景：A。问题：B。动作：C。结果：D。"
        result = rq.check_experience_text(text)
        self.assertTrue(result["has_star_structure"])
        self.assertTrue(all(result["star_stages"].values()))

    def test_three_of_four_stages_still_counts_as_star(self):
        text = "背景：A。问题：B。动作：C。"
        result = rq.check_experience_text(text)
        self.assertTrue(result["has_star_structure"])

    def test_single_stage_is_not_star(self):
        text = "负责需求分析与竞品研究，参与跨部门沟通协调推进项目落地。"
        result = rq.check_experience_text(text)
        self.assertFalse(result["has_star_structure"])
        self.assertIn("背景-问题-动作-结果", result["hints"][0])

    def test_english_star_labels_are_recognized(self):
        text = "Situation: team lacked a shared doc. Task: cut review time. Action: built a template. Result: time dropped by 40%."
        result = rq.check_experience_text(text)
        self.assertTrue(result["has_star_structure"])


class QuantifiedResultTests(unittest.TestCase):
    def test_percentage_counts_as_quantified(self):
        result = rq.check_experience_text("转化率提升了25%。")
        self.assertTrue(result["has_quantified_result"])

    def test_bare_year_does_not_count_as_quantified(self):
        result = rq.check_experience_text("2026年参加了一次竞赛。")
        self.assertFalse(result["has_quantified_result"])

    def test_count_with_unit_counts_as_quantified(self):
        result = rq.check_experience_text("访谈了6名用户，完成500份问卷。")
        self.assertTrue(result["has_quantified_result"])

    def test_no_number_at_all_is_not_quantified(self):
        result = rq.check_experience_text("效果有所改善，反馈比较积极。")
        self.assertFalse(result["has_quantified_result"])


class SkillSectionTests(unittest.TestCase):
    def test_explicit_ai_tool_usage_is_detected(self):
        result = rq.check_skill_section(
            "AI 工具使用：用 AI 辅助生成初稿，人工核对后采用"
        )
        self.assertTrue(result["has_ai_skill_mention"])
        self.assertEqual(result["hints"], [])

    def test_missing_ai_mention_returns_hint_not_invented_tool(self):
        result = rq.check_skill_section("Axure 熟练，Figma 掌握，SQL 基础查询")
        self.assertFalse(result["has_ai_skill_mention"])
        self.assertEqual(len(result["hints"]), 1)
        # The hint must only point out the gap, never name a specific tool
        # on the user's behalf (that would be inventing a skill for them).
        for tool_name in ("Axure", "Figma", "ChatGPT", "Claude"):
            self.assertNotIn(tool_name, result["hints"][0])


class NeverRewritesInputTests(unittest.TestCase):
    def test_check_functions_do_not_mutate_or_echo_modified_text(self):
        original = "背景：A。问题：B。动作：C。结果：无量化。"
        result = rq.check_experience_text(original)
        # The function must not return the input text anywhere in its
        # output (it is a read-only checker, not a rewriter).
        self.assertNotIn("text", result)
        self.assertIsInstance(result["hints"], list)
        for hint in result["hints"]:
            self.assertIsInstance(hint, str)


if __name__ == "__main__":
    unittest.main()
