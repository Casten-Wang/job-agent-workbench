#!/usr/bin/env python3
"""Offline tests for tools/quota_planner.py (daily contact quota planner)."""

from __future__ import annotations

import datetime
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
sys.dont_write_bytecode = True

import quota_planner as qp  # noqa: E402


TODAY = datetime.date(2025, 6, 30)


def cand(cid, company="示例科技有限公司", title="产品经理实习生", score=4.0, **extra):
    item = {"id": cid, "company": company, "title": title, "score": score}
    item.update(extra)
    return item


def plan(candidates, **kwargs):
    kwargs.setdefault("daily_quota", 5)
    kwargs.setdefault("history", [])
    kwargs.setdefault("today", TODAY)
    return qp.plan_contact_queue(candidates, **kwargs)


def ranked_ids(result):
    return [r["id"] for r in result["ranked"]]


def deferred_map(result):
    return {d["id"]: d["reason"] for d in result["deferred"]}


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


class QuotaCapTests(unittest.TestCase):
    def test_ranked_capped_by_quota(self):
        cands = [cand(f"j{i}", company=f"示例公司{i}", score=4.0 - i * 0.1) for i in range(5)]
        result = plan(cands, daily_quota=2)
        self.assertEqual(result["remaining_quota"], 2)
        self.assertEqual(ranked_ids(result), ["j0", "j1"])
        self.assertEqual([r["rank"] for r in result["ranked"]], [1, 2])
        deferred = deferred_map(result)
        self.assertEqual(set(deferred), {"j2", "j3", "j4"})
        self.assertEqual(deferred["j2"], "超出今日额度 2，顺延到下一批")

    def test_ranked_reason_is_chinese_and_short(self):
        result = plan([cand("j1", score=4.4)], daily_quota=2)
        self.assertEqual(result["ranked"][0]["reason"], "评分 4.4，风险低，排第 1；今日额度 2")

    def test_quota_larger_than_candidates(self):
        result = plan([cand("j1")], daily_quota=10)
        self.assertEqual(ranked_ids(result), ["j1"])
        self.assertEqual(result["deferred"], [])


class ExclusionTests(unittest.TestCase):
    def test_high_risk_excluded(self):
        result = plan([cand("j1", risk_level="high"), cand("j2", company="示例公司乙")])
        self.assertEqual(ranked_ids(result), ["j2"])
        self.assertEqual(deferred_map(result)["j1"], "风险等级高，不进入推荐队列")

    def test_active_company_deferred(self):
        result = plan(
            [cand("j1", company="示例科技有限公司"), cand("j2", company="示例公司乙")],
            active_companies={" 示例科技有限公司 "},
        )
        self.assertEqual(ranked_ids(result), ["j2"])
        self.assertEqual(deferred_map(result)["j1"], "同公司已有面试/笔试流程，默认降权")

    def test_missing_score_deferred_not_crash(self):
        result = plan([cand("j1", score=None), {"id": "j2", "company": "示例公司乙", "title": "运营"}])
        self.assertEqual(result["ranked"], [])
        self.assertEqual(deferred_map(result), {"j1": "未评分，先人工判断", "j2": "未评分，先人工判断"})

    def test_invalid_candidates_skipped(self):
        result = plan([{"company": "示例科技有限公司"}, {"id": ""}, None, "x", cand("j1")])  # type: ignore[list-item]
        self.assertEqual(ranked_ids(result), ["j1"])
        self.assertEqual(result["deferred"], [])


class HistoryDedupeTests(unittest.TestCase):
    def history(self, n, **overrides):
        item = {"company": "示例科技有限公司", "title": "产品经理实习生", "contacted_at": days_ago(n)}
        item.update(overrides)
        return [item]

    def test_exactly_window_days_ago_is_excluded(self):
        result = plan([cand("j1")], history=self.history(30))
        self.assertEqual(result["ranked"], [])
        self.assertEqual(deferred_map(result)["j1"], "近 30 天已沟通过同一岗位")

    def test_window_plus_one_is_not_excluded(self):
        result = plan([cand("j1")], history=self.history(31))
        self.assertEqual(ranked_ids(result), ["j1"])

    def test_custom_window(self):
        result = plan([cand("j1")], history=self.history(8), window_days=7)
        self.assertEqual(ranked_ids(result), ["j1"])
        result = plan([cand("j1")], history=self.history(7), window_days=7)
        self.assertEqual(deferred_map(result)["j1"], "近 7 天已沟通过同一岗位")

    def test_normalization_matches_case_width_and_spaces(self):
        history = self.history(5, company="示例  科技有限公司 ", title="产品经理实习生")
        result = plan([cand("j1", company="示例 科技有限公司")], history=history)
        self.assertEqual(ranked_ids(result), [])
        history = [{"company": "Example Co", "title": "ＰＭ  Intern", "contacted_at": days_ago(3)}]
        result = plan([cand("j1", company="example co", title="pm intern")], history=history)
        self.assertEqual(ranked_ids(result), [])

    def test_different_title_same_company_not_excluded(self):
        result = plan([cand("j1", title="运营实习生")], history=self.history(5))
        self.assertEqual(ranked_ids(result), ["j1"])

    def test_datetime_string_uses_date_part(self):
        history = self.history(5, contacted_at=days_ago(5) + "T09:30:00")
        result = plan([cand("j1")], history=history)
        self.assertEqual(ranked_ids(result), [])


class OrderingTests(unittest.TestCase):
    def test_score_descending_none_never_ranked(self):
        cands = [
            cand("a", company="甲", score=3.5),
            cand("b", company="乙", score=4.6),
            cand("c", company="丙", score=None),
            cand("d", company="丁", score=4.1),
        ]
        result = plan(cands)
        self.assertEqual(ranked_ids(result), ["b", "d", "a"])

    def test_risk_breaks_score_tie(self):
        cands = [
            cand("a", company="甲", score=4.0, risk_level="verify"),
            cand("b", company="乙", score=4.0, risk_level="low"),
        ]
        self.assertEqual(ranked_ids(plan(cands)), ["b", "a"])

    def test_recency_breaks_risk_tie_missing_is_oldest(self):
        cands = [
            cand("a", company="甲", posted_at="2025-06-01"),
            cand("b", company="乙", posted_at="2025-06-20"),
            cand("c", company="丙"),
        ]
        self.assertEqual(ranked_ids(plan(cands)), ["b", "a", "c"])

    def test_ties_broken_by_id(self):
        cands = [cand("c", company="丙"), cand("a", company="甲"), cand("b", company="乙")]
        self.assertEqual(ranked_ids(plan(cands)), ["a", "b", "c"])
        self.assertEqual(ranked_ids(plan(list(reversed(cands)))), ["a", "b", "c"])

    def test_score_outranks_risk(self):
        cands = [
            cand("a", company="甲", score=4.5, risk_level="verify"),
            cand("b", company="乙", score=3.0, risk_level="low"),
        ]
        self.assertEqual(ranked_ids(plan(cands)), ["a", "b"])


class QuotaUsageTests(unittest.TestCase):
    def test_contacts_today_reduce_remaining(self):
        history = [
            {"company": "示例公司甲", "title": "岗位甲", "contacted_at": TODAY.isoformat()},
            {"company": "示例公司乙", "title": "岗位乙", "contacted_at": TODAY.isoformat() + " 10:00:00"},
            {"company": "示例公司丙", "title": "岗位丙", "contacted_at": days_ago(1)},
        ]
        cands = [cand(f"j{i}", company=f"公司{i}", score=4.0 - i * 0.1) for i in range(3)]
        result = plan(cands, daily_quota=3, history=history)
        self.assertEqual(result["remaining_quota"], 1)
        self.assertEqual(ranked_ids(result), ["j0"])
        self.assertEqual(deferred_map(result)["j1"], "超出今日额度 1，顺延到下一批")

    def test_quota_fully_used_today(self):
        history = [{"company": "甲", "title": "乙", "contacted_at": TODAY.isoformat()}] * 3
        result = plan([cand("j1")], daily_quota=3, history=history)
        self.assertEqual(result["remaining_quota"], 0)
        self.assertEqual(result["ranked"], [])
        self.assertEqual(deferred_map(result), {"j1": "今日额度已用完"})

    def test_zero_and_negative_quota(self):
        for quota in (0, -2):
            result = plan([cand("j1", risk_level="high"), cand("j2", company="乙")], daily_quota=quota)
            self.assertEqual(result["remaining_quota"], 0)
            self.assertEqual(result["ranked"], [])
            self.assertEqual(deferred_map(result), {"j1": "今日额度已用完", "j2": "今日额度已用完"})


class PurityTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        cands = [cand("b", company="乙"), cand("a", company="甲")]
        before = [dict(c) for c in cands]
        plan(cands)
        self.assertEqual(cands, before)

    def test_empty_inputs(self):
        result = plan([], history=[])
        self.assertEqual(result, {"remaining_quota": 5, "ranked": [], "deferred": []})


if __name__ == "__main__":
    unittest.main()
