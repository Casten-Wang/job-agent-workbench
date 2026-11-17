"""Non-code experience must work without GitHub and preserve source boundaries."""
from copy import deepcopy
import time
import unittest

import test_career_pipeline as pipeline


INPUT = {"kind": "internship", "name": "用户反馈闭环", "organization": "虚构产品公司", "position": "产品实习生",
         "start": "2026.06", "end": "2026.08", "role": "产品经理", "jd": "需求分析与跨团队协作",
         "context": "客服反馈分散，产品团队难以判断优先级。", "contribution": "整理访谈与客服反馈，按使用场景归类，维护需求优先级并参与评审。",
         "outcome": "形成需求清单与评审记录，团队按清单跟进。", "source_text": "访谈记录：访谈了12位用户，归纳注册环节的问题。",
         "portfolio_url": "https://example.com/portfolio", "confirmed": True, "model_consent": True}


class ExperienceAgent:
    generation = {"provider": "test", "model": "experience", "kind": "contract_test"}
    def __init__(self):
        self.bad = None
    async def decide(self, stage, value):
        assert stage == "prepare_experience"
        evidence = next(e for e in value["evidence"] if e["path"].endswith("contribution.txt"))
        return {"summary": "用户反馈归类与需求评审", "positioning": "产品需求分析",
                "project_name": INPUT["name"], "project_overview": INPUT["context"], "claims": [
                    {"pillar": "需求梳理", "text": "整理访谈与客服反馈，按使用场景归类，维护需求优先级并参与评审。" + ("效率提升80%。" if self.bad == "metric" else ""),
                     "source_quote": "材料未提供的内容" if self.bad == "quote" else evidence["text"],
                     "evidence_ids": ["foreign" if self.bad == "reference" else evidence["evidence_id"]],
                     "boundary": "参与评审，不推断主导", "risk": "用户陈述，未经独立核验", "fit_reason": "对应需求分析"}]}


class ExperienceImportTests(unittest.TestCase):
    call = pipeline.CareerPipelineTests.call
    tearDown = pipeline.CareerPipelineTests.tearDown

    def setUp(self):
        pipeline.CareerPipelineTests.setUp(self)
        self.agent = ExperienceAgent()
        self.client.app.state.career.agent = self.agent

    def prepare_experience(self, data=None):
        project = self.call("POST", "/v1/career/experience-import", data or deepcopy(INPUT), 202)
        for _ in range(100):
            value = self.call("GET", "/v1/career/projects/" + project["project_id"])
            if value["status"] != "preparing":
                return value
            time.sleep(0.01)
        self.fail("Experience preparation did not complete")

    def test_experience_preview_save_and_source_version_without_github(self):
        def no_github(*args):
            self.fail("Manual import must never access GitHub")
        self.client.app.state.career.client_factory = no_github
        self.client.app.state.career.auth.token = no_github
        project = self.prepare_experience()
        self.assertEqual(project["status"], "ready")
        self.assertEqual(project["source_type"], "manual")
        self.assertEqual(project["experience"]["kind"], "internship")
        self.assertTrue(all(e["verification_scope"] == "user_supplied" for e in project["evidence"]))
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                             {"claim_ids": [project["claims"][0]["claim_id"]], "confirmed": True})["material_id"]
        draft = self.call("POST", "/v1/career/resume-drafts", {"material_id": material,
            "profile": {"truth_confirmed": True, "basic": {"name": "虚构产品候选人"}}}, 201)
        self.assertIn("## 实习与工作经历", draft["markdown"])
        self.assertIn("虚构产品公司 · 产品实习生", draft["markdown"])
        self.assertIn("2026.06 - 2026.08", draft["markdown"])
        self.assertNotIn("## 项目经历", draft["markdown"])
        self.assertIn(INPUT["portfolio_url"], draft["markdown"])
        self.assertEqual(draft["source_type"], "manual")
        version = self.call("POST", f"/v1/career/resume-drafts/{draft['draft_id']}/save", {"confirmed": True}, 201)
        changed = self.prepare_experience({**INPUT, "outcome": "新增第二轮评审记录。"})
        self.assertNotEqual(changed["source_commit"], project["source_commit"])
        saved = self.call("GET", "/v1/career/resumes/" + version["resume_version_id"])
        self.assertEqual(saved["markdown"], draft["markdown"])
        self.assertNotIn("源码", " ".join(saved["review_notes"]))

    def test_portfolio_uses_its_own_section(self):
        project = self.prepare_experience({**INPUT, "kind": "portfolio"})
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                             {"claim_ids": [project["claims"][0]["claim_id"]], "confirmed": True})["material_id"]
        draft = self.call("POST", "/v1/career/resume-drafts", {"material_id": material,
            "profile": {"truth_confirmed": True, "basic": {"name": "虚构候选人", "wechat": "sample_wechat",
                "links": "https://portfolio.example.invalid"}, "projects": [
                    {"name": "已有个人项目", "role": "产品", "summary": "已确认的项目说明"}]}}, 201)
        self.assertIn("## 作品集", draft["markdown"])
        self.assertNotIn("## 实习与工作经历", draft["markdown"])
        self.assertIn("微信：sample_wechat", draft["markdown"])
        self.assertIn("## 项目经历", draft["markdown"])
        self.assertIn("已有个人项目", draft["markdown"])
        self.assertIn(INPUT['portfolio_url'], draft['markdown'])
        self.assertNotIn('https://github.com/', draft['markdown'])

    def test_missing_consent_unsafe_link_or_unknown_kind_rejected(self):
        for changes in ({"confirmed": False}, {"model_consent": False}, {"kind": "random"},
                        {"portfolio_url": "javascript:alert(1)"}, {"contribution": ""}):
            self.call("POST", "/v1/career/experience-import", {**INPUT, **changes}, 400)

    def test_fabricated_quote_metric_and_reference_rejected(self):
        for kind in ("quote", "metric", "reference"):
            self.agent.bad = kind
            self.assertEqual(self.prepare_experience()["status"], "failed")
