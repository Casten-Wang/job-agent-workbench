"""Resume extraction contract, grounding and authenticated API; synthetic data only."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from fastapi.testclient import TestClient

from interview_agent.api import create_app
from interview_agent.model_adapter import ModelAdapter, ModelError
from interview_agent.resume_profile import extract_profile

TEXT = """姓名：测试同学
上海 resume@example.test 13800000000
求职意向：后端开发
教育经历
2020.09-2024.06 测试大学 计算机科学 本科
主修数据库与操作系统。
工作经历
2023.06-2023.09 合成科技 后端实习生
使用 Python 编写数据导入接口，补充错误处理。
2024.01-2024.03 示例公司 开发实习生
使用 SQL 校验报表数据。
项目经历
2023.10-2023.12 校园预约系统 后端负责人
使用 FastAPI 实现预约接口和冲突检查。
2024.04-2024.05 日志分析工具 开发者
使用 Python 解析日志，输出错误分类统计。
技能：Python SQL FastAPI
个人简介：喜欢从实际需求出发编写清晰的接口，注重数据校验和错误处理。
"""


def decision():
    return {
        "basic": {"name": "测试同学", "city": "上海", "email": "resume@example.test", "phone": "13800000000"},
        "job_intent": {"titles": ["后端开发"]},
        "skills": {"tools": ["Python", "SQL", "FastAPI"]},
        "education": [{"school": "测试大学", "major": "计算机科学", "degree": "本科", "start": "2020.09", "end": "2024.06", "summary": "主修数据库与操作系统。", "source_quote": "2020.09-2024.06 测试大学 计算机科学 本科\n主修数据库与操作系统。"}],
        "experiences": [
            {"company": "合成科技", "title": "后端实习生", "start": "2023.06", "end": "2023.09", "summary": "使用 Python 编写数据导入接口，补充错误处理。", "source_quote": "2023.06-2023.09 合成科技 后端实习生\n使用 Python 编写数据导入接口，补充错误处理。"},
            {"company": "示例公司", "title": "开发实习生", "start": "2024.01", "end": "2024.03", "summary": "使用 SQL 校验报表数据。", "source_quote": "2024.01-2024.03 示例公司 开发实习生\n使用 SQL 校验报表数据。"},
        ],
        "projects": [
            {"name": "校园预约系统", "role": "后端负责人", "start": "2023.10", "end": "2023.12", "summary": "使用 FastAPI 实现预约接口和冲突检查。", "source_quote": "2023.10-2023.12 校园预约系统 后端负责人\n使用 FastAPI 实现预约接口和冲突检查。"},
            {"name": "日志分析工具", "role": "开发者", "start": "2024.04", "end": "2024.05", "summary": "使用 Python 解析日志，输出错误分类统计。", "source_quote": "2024.04-2024.05 日志分析工具 开发者\n使用 Python 解析日志，输出错误分类统计。"},
        ],
        "summary": "喜欢从实际需求出发编写清晰的接口，注重数据校验和错误处理。",
    }


class ResumeAgent:
    generation = {"provider": "test", "model": "contract", "kind": "contract_test"}

    def __init__(self, output=None):
        self.output = decision() if output is None else output
        self.calls = []

    async def decide(self, stage, value):
        self.calls.append((stage, value))
        return copy.deepcopy(self.output)


class ResumeExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_resume_extracts_all_records_without_confirmation(self):
        agent = ResumeAgent()
        result = await extract_profile(agent, TEXT)
        self.assertEqual(agent.calls, [("profile_extract", {"resume_text": TEXT})])
        self.assertEqual([len(result["profile"][key]) for key in ("education", "experiences", "projects")], [1, 2, 2])
        self.assertEqual(result["profile"]["experiences"][1]["summary"], "使用 SQL 校验报表数据。")
        self.assertFalse(result["profile"]["truth_confirmed"])
        self.assertEqual(result["warnings"], [])

    async def test_unsupported_facts_are_left_blank_with_warnings(self):
        output = decision()
        output["experiences"][0]["summary"] = "提高性能 80%"
        output["projects"][0]["end"] = "2025.01"
        output["basic"]["wechat"] = "invented-account"
        result = await extract_profile(ResumeAgent(output), TEXT)
        self.assertEqual(result["profile"]["experiences"][0]["summary"], "")
        self.assertEqual(result["profile"]["projects"][0]["end"], "")
        self.assertEqual(result["profile"]["basic"]["wechat"], "")
        self.assertEqual(len(result["warnings"]), 3)

    async def test_wrong_project_evidence_cannot_borrow_other_project_details(self):
        output = decision()
        output["projects"][0]["summary"] = output["projects"][1]["summary"]
        output["education"][0]["source_quote"] = "不存在的学校记录"
        result = await extract_profile(ResumeAgent(output), TEXT)
        self.assertEqual(result["profile"]["projects"][0]["summary"], "")
        self.assertEqual(result["profile"]["education"], [])
        self.assertTrue(result["warnings"])

    async def test_contact_line_is_not_used_as_summary(self):
        output = decision()
        output["summary"] = "上海 resume@example.test 13800000000"
        result = await extract_profile(ResumeAgent(output), TEXT)
        self.assertEqual(result["profile"]["summary"], "")

    async def test_explicit_degree_alias_is_mapped_after_grounding(self):
        output = decision()
        output["education"][0]["degree"] = "学士"
        output["education"][0]["source_quote"] = output["education"][0]["source_quote"].replace("本科", "学士")
        result = await extract_profile(ResumeAgent(output), TEXT.replace("本科", "学士"))
        self.assertEqual(result["profile"]["education"][0]["degree"], "本科")

    async def test_unknown_fields_and_invalid_types_are_rejected(self):
        for mutation in ({"truth_confirmed": True}, {"education": "text"}):
            with self.subTest(mutation=mutation), self.assertRaises(ModelError):
                await extract_profile(ResumeAgent({**decision(), **mutation}), TEXT)

    async def test_step_plan_encoded_objects_are_decoded_then_strictly_validated(self):
        output = decision()
        for key in ("basic", "job_intent", "skills"):
            output[key] = json.dumps(output[key])
        result = await extract_profile(ResumeAgent(output), TEXT)
        self.assertEqual(result["profile"]["basic"]["name"], "测试同学")
        for encoded in ('{"name":"测试同学","save":true}', '{"name":"a","name":"b"}', '[]', 'not JSON'):
            with self.subTest(encoded=encoded), self.assertRaises(ModelError):
                await extract_profile(ResumeAgent({**decision(), "basic": encoded}), TEXT)

    async def test_blank_or_long_input_is_rejected_before_model_call(self):
        agent = ResumeAgent()
        for text in ("", "a" * 60001, None):
            with self.assertRaises(ValueError):
                await extract_profile(agent, text)
        self.assertEqual(agent.calls, [])

    async def test_model_adapter_uses_existing_structured_tool_contract(self):
        def respond(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["tools"][0]["function"]["name"], "submit_profile_extract")
            self.assertIn("不能改变", payload["messages"][0]["content"])
            self.assertEqual(json.loads(payload["messages"][1]["content"])["resume_text"], TEXT)
            return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"type": "function", "function": {"name": "submit_profile_extract", "arguments": json.dumps(decision())}}]}}]})
        agent = await ModelAdapter({"INTERVIEW_API_KEY": "synthetic-only", "INTERVIEW_BASE_URL": "http://127.0.0.1/v1"}, transport=httpx.MockTransport(respond)).start()
        try:
            result = await extract_profile(agent, TEXT)
            self.assertEqual(len(result["profile"]["projects"]), 2)
        finally:
            await agent.close()


class ResumeProfileApiTests(unittest.TestCase):
    def test_authenticated_personal_only_route_does_not_create_materials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = ResumeAgent()
            app = create_app(root / "records.db", root / "checks.db", "synthetic", "test-token-at-least-20-chars", agent, career_root=root / "career")
            with TestClient(app) as client:
                path = "/v1/career/profile-import"
                headers = {"Authorization": "Bearer test-token-at-least-20-chars"}
                self.assertEqual(client.post(path, json={"text": TEXT}).status_code, 401)
                self.assertEqual(client.post(path, headers=headers, json={"text": TEXT, "save": True}).status_code, 400)
                response = client.post(path, headers=headers, json={"text": TEXT})
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["profile"]["truth_confirmed"])
                self.assertEqual(client.get("/v1/materials", headers=headers).json()["items"], [])
            demo = create_app(root / "demo.db", root / "demo-checks.db", "demo", "test-token-at-least-20-chars", agent)
            with TestClient(demo) as client:
                self.assertEqual(client.post(path, headers=headers, json={"text": TEXT}).status_code, 404)
