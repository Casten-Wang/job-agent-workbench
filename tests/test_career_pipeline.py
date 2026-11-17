import base64
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from interview_agent.api import create_app
from interview_hub.career_store import CareerRecords
from interview_hub.store import ConflictError
from test_ingest import FakeClient, SHA

TOKEN = "personal-career-integration-test-token"


class FakeAuthorization:
    def status(self):
        return {"configured": True, "connected": True, "login": "synthetic-user"}
    def token(self):
        return "synthetic-read-token"
    def close(self):
        pass


class RepositoryClient(FakeClient):
    authenticated = True
    def resolve_repository(self, repo, ref=None):
        value = super().resolve_repository(repo, ref)
        value["repository"].update(full_name=repo, html_url="https://github.com/"+repo)
        return value
    def get_json(self, path, params=None):
        if path == "/user/repos":
            count = 50 if params["page"] == 1 else 1
            return [{"id": i, "full_name": f"example/project-{i}", "private": True} for i in range(count)]
        if "/contents/" in path:
            text = next(iter(self.sources.values()))
            return {"type": "file", "encoding": "base64", "size": len(text), "content": base64.b64encode(text).decode()}
        return super().get_json(path)


class CareerAgent:
    generation = {"provider": "test", "model": "contract", "kind": "contract_test"}
    foreign = False
    def __init__(self):
        self.calls = []
    async def decide(self, stage, value):
        self.calls.append(stage)
        if stage == "prepare":
            return {"project_name": "签名校验工具", "project_overview": "为调用方提供统一的签名输入处理。",
                "positioning": "面向后端岗位的输入校验与签名链路实现", "summary": "合成项目：签名函数示例", "claims": [
                {"pillar": "数据校验", "text": "围绕签名输入的边界问题，在签名函数中拼接固定后缀并保留源码证据。", "fit_reason": "对应后端输入校验要求", "boundary": "个人职责待确认", "risk": "未确认是否独立完成", "evidence_ids": ["foreign" if self.foreign else value["evidence"][0]["evidence_id"]]}]}
        if stage == "plan":
            c = value["material"]["claims"][0]
            return {"questions": [{"question_id": "pi_q1", "claim_id": c["claim_id"], "text": "解释返回值与失败边界", "evidence_ids": c["evidence_ids"], "intent": "implementation", "reason": "合成契约验证"}]}
        if stage == "intent":
            return {"intent": "answer", "reason": "合成回答", "clarification": ""}
        if stage == "hint":
            return {"text": "定位返回值", "evidence_ids": value["question"]["evidence_ids"]}
        return {"status": "partial", "gap_type": "understanding", "notes": "合成反馈：需要补充失败场景", "evidence_ids": value["question"]["evidence_ids"]}


class CareerPipelineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.agent = CareerAgent()
        self.client = TestClient(create_app(self.root / "data.db", self.root / "checkpoints.db", "personal-test", TOKEN,
            self.agent, career_root=self.root / "runtime", career_options={"authorization": FakeAuthorization(), "client_factory": RepositoryClient}))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.folder.cleanup()

    def call(self, method, path, data=None, expected=200):
        response = self.client.request(method, path, json=data, headers={"Authorization": "Bearer " + TOKEN})
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def prepare(self):
        project = self.call("POST", "/v1/career/projects", {"repository": "example/demo", "role": "初级后端",
            "jd": "合成 JD：实现与边界说明", "contribution": "测试数据：负责示例函数，使用 AI 辅助完成。",
            "confirmed": True, "model_consent": True}, 202)
        for _ in range(100):
            result = self.call("GET", "/v1/career/projects/" + project["project_id"])
            if result["status"] != "preparing":
                return result
            time.sleep(0.01)
        self.fail("Preparation did not complete")

    def session(self, material, sid, kind):
        return self.call("POST", "/v1/career/interviews", {"material_id": material, "session_id": sid,
                         "mode": kind, "target": {"role": "初级后端"}}, 201)

    def finish(self, sid):
        for eid, command, text in [("answer", None, "合成技术回答"), ("finish", "finish", "/finish")]:
            self.call("POST", f"/v1/interviews/{sid}/turns", {"event_id": eid, "text": text, **({"command":command} if command else {})})

    def test_full_pipeline_private_repo_to_frozen_resume_formal_interview_and_recap(self):
        repositories = self.call("GET", "/v1/career/github/repositories?page=1")
        self.assertEqual(repositories["next_page"], 2)
        self.assertTrue(repositories["items"][0]["private"])
        self.assertIsNone(self.call("GET", "/v1/career/github/repositories?page=2")["next_page"])
        tree = self.call("GET", "/v1/career/github/tree?repository=example/demo")
        self.assertEqual(tree["source_commit"], SHA)
        file = self.call("GET", f"/v1/career/github/file?repository=example/demo&commit={SHA}&path=src/sign.py")
        self.assertIn("def sign", file["text"])
        project = self.prepare()
        self.assertEqual(project["status"], "ready")
        self.assertTrue(set(project['claims'][0]['evidence_ids']) <= {e['evidence_id'] for e in project['evidence']})
        self.assertTrue(all(not ref.startswith('E') for ref in project['claims'][0]['evidence_ids']))
        self.assertEqual(project["positioning"], "面向后端岗位的输入校验与签名链路实现")
        self.assertEqual(project["claims"][0]["pillar"], "数据校验")
        self.assertEqual(project["claims"][0]["fit_reason"], "对应后端输入校验要求")
        self.assertEqual(project["claims"][0]["personal_contribution"], "unconfirmed")
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                             {"claim_ids":[project["claims"][0]["claim_id"]], "confirmed":True})["material_id"]
        self.assertIsNone(self.session(material, "opuser_readiness", "resume_readiness")["resume_version_id"])
        self.finish("opuser_readiness")
        profile = {"truth_confirmed":True,"basic":{"name":"测试候选人","email":"synthetic@example.invalid"},
                   "education":[{"school":"虚构学院","major":"计算机","degree":"本科"}],"skills":{"tools":["Python"],"strengths":[]}}
        draft = self.call("POST", "/v1/career/resume-drafts", {"session_id":"opuser_readiness", "profile":profile},201)
        self.assertIn("测试候选人", draft["markdown"])
        self.assertIn("AI 辅助", draft["contribution_statement"])
        self.assertNotIn("测试数据", draft["markdown"])
        self.assertTrue(draft["needs_review"])
        version = self.call("POST", f"/v1/career/resume-drafts/{draft['draft_id']}/save", {"confirmed":True},201)
        repeated = self.call("POST", f"/v1/career/resume-drafts/{draft['draft_id']}/save", {"confirmed":True},201)
        self.assertEqual(repeated["created_at"], version["created_at"])
        self.assertEqual(repeated["resume_version_id"], version["resume_version_id"])
        saved = self.call("GET", "/v1/career/resumes/"+version["resume_version_id"])
        self.assertEqual(saved["markdown_sha256"], draft["markdown_sha256"])
        opened = self.session(version["interview_material_id"], "opuser_formal", "mock_interview")
        self.assertEqual(opened["resume_version_id"], version["resume_version_id"])
        self.assertEqual(opened["interview_mode"], "mock_interview")
        frozen = self.client.app.state.career.repo.store.get_material("personal-test", version["interview_material_id"])["payload"]
        self.assertIn("resume_context", frozen)
        self.assertNotIn("synthetic@example.invalid", str(frozen["resume_context"]))
        self.assertNotIn("测试候选人", str(frozen["resume_context"]))
        self.finish("opuser_formal")
        recap = self.call("GET", "/v1/sessions/opuser_formal/recap")["payload"]
        self.assertEqual(recap["resume_version_id"], version["resume_version_id"])
        self.assertFalse(recap["applied_to_resume"])
        self.assertTrue(recap["improvement_tasks"])
        self.assertEqual(self.call("GET", "/v1/career/resumes/"+version["resume_version_id"])["markdown"], draft["markdown"])
        updated_profile = {**profile, "skills": {"tools": ["Python", "SQL"]}}
        updated_draft = self.call("POST", "/v1/career/resume-drafts", {"material_id": material, "profile": updated_profile}, 201)
        updated_version = self.call("POST", f"/v1/career/resume-drafts/{updated_draft['draft_id']}/save", {"confirmed": True}, 201)
        self.assertNotEqual(updated_version["resume_version_id"], version["resume_version_id"])
        self.assertNotIn("SQL", self.call("GET", "/v1/career/resumes/"+version["resume_version_id"])["markdown"])

    def test_project_consent_foreign_evidence_and_claim_confirmation(self):
        self.call("POST", "/v1/career/projects", {"repository":"example/demo","role":"初级后端","contribution":"test","confirmed":True},400)
        self.agent.foreign=True
        project=self.prepare()
        self.assertEqual(project["status"], "failed")
        self.assertEqual(project["error_code"], "material_validation_failed")
        self.assertIn("source_commit", project)
        self.assertEqual(project["contribution"], "测试数据：负责示例函数，使用 AI 辅助完成。")
        self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm", {"claim_ids":["foreign"],"confirmed":True},400)

    def test_confirmed_project_can_generate_and_save_resume_without_interview(self):
        project = self.prepare()
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                             {"claim_ids": [project["claims"][0]["claim_id"]], "confirmed": True})["material_id"]
        calls_before = list(self.agent.calls)
        profile = {"truth_confirmed": True, "basic": {"name": "测试候选人"}, "skills": {"tools": ["Python"]}}
        draft = self.call("POST", "/v1/career/resume-drafts", {"material_id": material, "profile": profile}, 201)
        self.assertIsNone(draft["session_id"])
        self.assertEqual(draft["assessment_status"], "not_assessed")
        self.assertIn(project["claims"][0]["text"], draft["markdown"])
        self.assertIn("### 签名校验工具\n\n为调用方提供统一的签名输入处理。", draft["markdown"])
        self.assertIn("- 数据校验：", draft["markdown"])
        self.assertNotIn("### example/demo", draft["markdown"])
        frozen = self.client.app.state.career.repo.store.get_material("personal-test", material)["payload"]
        self.assertTrue(frozen["evidence"])
        self.assertEqual(frozen["project_name"], project["project_name"])
        version = self.call("POST", f"/v1/career/resume-drafts/{draft['draft_id']}/save", {"confirmed": True}, 201)
        self.assertEqual(self.agent.calls, calls_before)
        self.assertIn("no interview assessment", version["confirmation_scope"])
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.root / "data.db")) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0)
        self.assertEqual(self.call("GET", "/v1/career/resumes/"+version["resume_version_id"])["markdown"], draft["markdown"])

    def test_import_keeps_all_basic_fields_existing_projects_and_repository_link(self):
        project = self.prepare()
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
            {"claim_ids": [project['claims'][0]['claim_id']], "confirmed": True})['material_id']
        profile = {"truth_confirmed": True, "basic": {"name": "字段核对样例", "phone": "000-0000-0000",
            "email": "candidate@example.invalid", "city": "上海", "wechat": "sample_wechat",
            "links": "https://portfolio.example.invalid/work https://blog.example.invalid"},
            "summary": "个人简介原文，仅供字段传递测试。", "projects": [
                {"name": "已保存的作品项目", "role": "产品设计", "start": "2025.01", "end": "2025.06",
                 "summary": "作品说明与验证记录：https://portfolio.example.invalid/case"},
                {"name": project['project_name'], "role": "重复条目", "summary": "被本次选定项目替代"}]}
        draft = self.call("POST", "/v1/career/resume-drafts", {"material_id": material, "profile": profile}, 201)
        for text in ("字段核对样例", "000-0000-0000", "candidate@example.invalid", "上海", "微信：sample_wechat",
                     "https://portfolio.example.invalid/work", "https://blog.example.invalid", "## 个人简介",
                     profile['summary'], "已保存的作品项目", "产品设计", "2025.01 - 2025.06",
                     "https://portfolio.example.invalid/case", "项目链接：https://github.com/example/demo"):
            self.assertIn(text, draft['markdown'])
        self.assertEqual(draft['markdown'].count('## 项目经历\n'), 1)
        self.assertEqual(draft['markdown'].count('### '+project['project_name']), 1)
        self.assertNotIn('被本次选定项目替代', draft['markdown'])

    def test_unconfirmed_or_demo_material_cannot_generate_direct_resume(self):
        project = self.prepare()
        material = self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                             {"claim_ids": [project["claims"][0]["claim_id"]], "confirmed": True})["material_id"]
        original = self.client.app.state.career.repo.store.get_material("personal-test", material)["payload"]
        changed = {**original, "material_id": "unconfirmed_material", "claims": [{**original["claims"][0], "personal_contribution": "unconfirmed"}]}
        self.client.app.state.career.repo.store.put_material("personal-test", "unconfirmed_material", changed)
        self.call("POST", "/v1/career/resume-drafts", {"material_id": "unconfirmed_material", "profile": {"truth_confirmed": True,"basic":{"name":"测试"}}}, 400)

    def test_preparing_same_project_again_can_confirm_the_same_material(self):
        materials = []
        for _ in range(2):
            project = self.prepare()
            materials.append(self.call("POST", f"/v1/career/projects/{project['project_id']}/confirm",
                {"claim_ids": [project['claims'][0]['claim_id']], "confirmed": True})['material_id'])
        self.assertEqual(materials[0], materials[1])

    def test_artifact_owner_isolation_and_immutability(self):
        one=CareerRecords(self.root/'data.db','one');two=CareerRecords(self.root/'data.db','two')
        one.put('resume','same',{'text':'one'});two.put('resume','same',{'text':'two'})
        self.assertEqual(one.get('resume','same')['text'],'one')
        with self.assertRaises(ConflictError):
            one.put('resume','same',{'text':'changed'})
