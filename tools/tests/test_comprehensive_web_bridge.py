"""OfferPilot Web BFF 同源桥接与综合模拟面试前端静态契约测试。"""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import backend  # noqa: E402
import career_user_runtime as personal  # noqa: E402
import server  # noqa: E402


class ComprehensiveWebBridgeTests(unittest.TestCase):
    def test_comprehensive_routes_require_user_mode_and_valid_ids(self):
        with patch.object(personal, "upstream", return_value={"session_id": "ci_1"}) as upstream:
            for method, path, query, payload in (
                ("POST", "/api/career-user/comprehensive-interviews", {"mode": "demo"}, {"role_family": "engineering"}),
                ("GET", "/api/career-user/comprehensive-interviews/ci_1", {"mode": "user", "owner": "evil"}, {}),
                ("POST", "/api/career-user/comprehensive-interviews/../etc/turns", {"mode": "user"}, {}),
                ("GET", "/api/career-user/comprehensive-interviews/ci_1/export", {"mode": "user", "format": "html"}, {}),
            ):
                upstream.reset_mock()
                with self.assertRaises(backend.ApiError):
                    personal.dispatch(method, path, query, payload)
                upstream.assert_not_called()

    def test_start_enriches_profile_job_and_local_jingyan(self):
        fake_store = MagicMock()
        fake_store.profile.return_value = {"basic": {"name": "张三"}, "skills": ["Python"], "truth_confirmed": True}
        fake_store.snapshot.return_value = {
            "jobs": [{"id": "job_9", "company": "Acme", "title": "AI Agent 工程师", "jd": "负责 Agent 编排"}]
        }
        fake_store.interview_materials.return_value = [
            {"id": "m1", "kind": "jingyan", "company": "Acme", "role": "Agent", "title": "一面实录", "body": "重点考幂等锁"},
            {"id": "m2", "kind": "jingyan", "company": "OtherCo", "role": "Agent", "title": "别家", "body": "不匹配公司应跳过"},
        ]

        with patch.object(backend, "get_store", return_value=fake_store), \
             patch.object(backend, "profile_public", side_effect=lambda p: p), \
             patch.object(personal, "upstream", return_value={"session_id": "ci_enriched"}) as upstream:
            res, status = personal.dispatch(
                "POST",
                "/api/career-user/comprehensive-interviews",
                {"mode": "user"},
                {"role_family": "engineering", "round": "first", "duration_minutes": 30, "job_id": "job_9"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(res["view"]["session_id"], "ci_enriched")
            sent_payload = upstream.call_args.args[2]
            self.assertEqual(sent_payload["profile_snapshot"]["basic"]["name"], "张三")
            self.assertEqual(sent_payload["job_snapshot"]["company"], "Acme")
            self.assertEqual(len(sent_payload["external_materials"]), 1)
            self.assertEqual(sent_payload["external_materials"][0]["ref_id"], "m1")

    def test_turns_finish_recap_export_and_drill_forwarding(self):
        with patch.object(personal, "upstream") as upstream:
            upstream.return_value = {"ok_stub": True}
            _, st1 = personal.dispatch(
                "POST",
                "/api/career-user/comprehensive-interviews/ci_abc/turns",
                {"mode": "user"},
                {"event_id": "ev1", "text": "我的回答"},
            )
            self.assertEqual(st1, 200)
            self.assertEqual(upstream.call_args.args[:2], ("POST", "/v1/comprehensive-interviews/ci_abc/turns"))

            _, st2 = personal.dispatch(
                "POST",
                "/api/career-user/comprehensive-interviews/ci_abc/finish",
                {"mode": "user"},
                {"early": False},
            )
            self.assertEqual(st2, 200)
            self.assertEqual(upstream.call_args.args[:2], ("POST", "/v1/comprehensive-interviews/ci_abc/finish"))

            res_recap, st3 = personal.dispatch(
                "GET",
                "/api/career-user/comprehensive-interviews/ci_abc/recap",
                {"mode": "user"},
            )
            self.assertEqual(st3, 200)
            self.assertIn("recap", res_recap)

            _, st4 = personal.dispatch(
                "POST",
                "/api/career-user/comprehensive-interviews/ci_abc/drill",
                {"mode": "user"},
                {"event_id": "d1", "question_id": "q1", "answer": "重练回答"},
            )
            self.assertEqual(st4, 200)

            upstream.return_value = {"markdown": "# 报告", "filename": "mock-interview-ci_abc.md"}
            raw, fname = personal.export_comprehensive_markdown(
                "/api/career-user/comprehensive-interviews/ci_abc/export",
                {"mode": "user", "format": "markdown"},
            )
            self.assertEqual(raw.decode("utf-8"), "# 报告")
            self.assertEqual(fname, "mock-interview-ci_abc.md")

    def test_static_assets_and_html_markers_are_registered(self):
        self.assertIn("/comprehensive-interview.js", server.STATIC_FILES)
        self.assertIn("/comprehensive-interview.css", server.STATIC_FILES)
        html = (WEB_DIR / "static" / "index.html").read_text(encoding="utf-8")
        js = (WEB_DIR / "static" / "comprehensive-interview.js").read_text(encoding="utf-8")
        self.assertIn('id="ci-panel"', html)
        self.assertIn('id="ci-drill-form"', html)
        self.assertIn("compositionstart", js)
        self.assertIn("compositionend", js)
        self.assertIn("keyCode === 229", js)


if __name__ == "__main__":
    unittest.main()
