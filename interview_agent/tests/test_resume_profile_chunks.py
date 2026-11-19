"""Long-resume extraction: chunking, partial failure isolation and normalization.

Every sample below is synthetic; no real person, employer or contact is involved.
"""

import re
import unittest

from interview_agent.model_adapter import ModelError
from interview_agent.resume_profile import extract_profile

HEADING = re.compile(r"^\d{4}\.\d{2}-\d{4}\.\d{2} \S+ \S+$", re.MULTILINE)
BODY = "使用 Python 编写数据导入接口，补充错误处理与单元测试；核对报表口径并记录问题清单；"


def extraction(experiences=()):
    return {
        "basic": {}, "job_intent": {}, "skills": {},
        "education": [], "experiences": list(experiences), "projects": [], "summary": "",
    }


def records_in(chunk):
    rows = []
    for line in HEADING.findall(chunk):
        start_end, company, title = line.split()
        start, end = start_end.split("-")
        rows.append({"company": company, "title": title, "start": start, "end": end,
                     "summary": "", "source_quote": line})
    return extraction(rows)


def long_resume(blocks=10, body=BODY * 25):
    parts = ["姓名：测试同学\n上海\n求职意向：后端开发\n\n教育经历\n2020.09-2024.06 测试大学 计算机科学 本科\n\n工作经历"]
    for index in range(blocks):
        parts.append(f"2023.06-2023.09 合成公司{index} 后端实习生\n{body}")
    return "\n\n".join(parts)


class ScriptedAgent:
    """Answers each bounded call from a script; records chunk lengths only."""

    generation = {"provider": "test", "model": "scripted"}

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def decide(self, stage, value):
        chunk = value["resume_text"]
        self.calls.append(len(chunk))
        return self.answer(chunk)


class ChunkedResumeTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_resume_is_split_and_still_extracted_whole(self):
        text = long_resume()
        self.assertGreater(len(text), 7000)
        agent = ScriptedAgent(records_in)
        result = await extract_profile(agent, text)
        self.assertGreater(len(agent.calls), 1)
        self.assertTrue(all(size <= 6000 for size in agent.calls))
        companies = [row["company"] for row in result["profile"]["experiences"]]
        self.assertEqual(companies, [f"合成公司{index}" for index in range(10)])
        self.assertIsNone(result["failure"])
        self.assertEqual(result["failures"], [])
        self.assertFalse(result["partial"])

    async def test_truncated_chunk_is_split_and_merged_instead_of_failing(self):
        text = long_resume()

        def answer(chunk):
            if len(chunk) > 4000:
                raise ModelError("model_output_truncated")
            return records_in(chunk)

        agent = ScriptedAgent(answer)
        result = await extract_profile(agent, text)
        self.assertGreater(len(agent.calls), 2)
        self.assertEqual(len(result["profile"]["experiences"]), 10)
        self.assertIsNone(result["failure"])
        self.assertEqual(result["failures"], [])
        self.assertFalse(result["partial"])

    async def test_one_failing_chunk_keeps_the_others(self):
        text = long_resume()

        def answer(chunk):
            if "合成公司3" in chunk:
                raise ModelError("invalid_model_decision")
            return records_in(chunk)

        result = await extract_profile(ScriptedAgent(answer), text)
        companies = [row["company"] for row in result["profile"]["experiences"]]
        self.assertGreaterEqual(len(companies), 7)
        self.assertEqual(companies, [name for name in (f"合成公司{index}" for index in range(10)) if name in companies])
        self.assertEqual(result["failures"], ["invalid_model_decision"])
        self.assertTrue(result["partial"])
        self.assertIsNone(result["failure"])
        self.assertTrue(result["unmatched_sections"])
        self.assertIn("合成公司3", "".join(item["text"] for item in result["unmatched_sections"]))
        self.assertTrue(any("未能完整解析" in warning for warning in result["warnings"]))

    async def test_every_chunk_failing_returns_source_text_and_failure(self):
        text = long_resume()

        def answer(chunk):
            raise ModelError("model_output_truncated")

        result = await extract_profile(ScriptedAgent(answer), text)
        self.assertEqual(result["profile"]["experiences"], [])
        self.assertEqual(result["failure"], "model_output_truncated")
        self.assertEqual(result["failures"], ["model_output_truncated"])
        self.assertTrue(result["partial"])
        self.assertTrue(result["unmatched_sections"])
        total = sum(len(item["text"]) for item in result["unmatched_sections"])
        self.assertGreater(total, 0)
        self.assertLessEqual(total, 20000)
        for item in result["unmatched_sections"]:
            self.assertLessEqual(len(item["text"]), 6000)

    async def test_unmatched_quote_is_reported_not_silently_dropped(self):
        text = long_resume(1)
        agent = ScriptedAgent(lambda chunk: extraction([{
            "company": "合成公司9", "title": "后端实习生", "start": "2023.06", "end": "2023.09",
            "summary": "", "source_quote": "2019.01-2019.02 不存在的单位 实习生"}]))
        result = await extract_profile(agent, text)
        self.assertEqual(result["profile"]["experiences"], [])
        self.assertTrue(result["partial"])
        self.assertEqual(result["unmatched_sections"],
                         [{"section": "工作经历", "text": "2019.01-2019.02 不存在的单位 实习生"}])

    async def test_no_supported_fields_is_a_failure_code(self):
        text = long_resume(1)
        result = await extract_profile(ScriptedAgent(lambda chunk: extraction()), text)
        self.assertEqual(result["failure"], "resume_no_supported_fields")
        self.assertTrue(result["partial"])


class NormalizedEvidenceTests(unittest.IsolatedAsyncioTestCase):
    """PDF-style line breaks, bullets and full-width digits no longer drop records."""

    TEXT = """姓名：测试同学
上海
求职意向：后端开发

工作经历
• ２０２３．０６-２０２３．０９ 合成科技 后端实习生
使用 Python 编写数据导-
入接口，并补充错误处理。
"""

    def answer(self, chunk):
        return extraction([{
            "company": "合成科技", "title": "后端实习生", "start": "2023.06", "end": "2023.09",
            "summary": "使用 Python 编写数据导入接口，并补充错误处理。",
            "source_quote": "2023.06-2023.09 合成科技\n后端实习生"}])

    async def test_record_kept_when_quote_differs_only_in_layout(self):
        result = await extract_profile(ScriptedAgent(self.answer), self.TEXT)
        self.assertEqual(len(result["profile"]["experiences"]), 1)
        row = result["profile"]["experiences"][0]
        self.assertEqual((row["company"], row["title"], row["start"], row["end"]),
                         ("合成科技", "后端实习生", "2023.06", "2023.09"))
        self.assertEqual(row["summary"], "使用 Python 编写数据导入接口，并补充错误处理。")
        self.assertFalse(result["partial"])

    async def test_anchor_only_quote_still_yields_the_original_paragraph(self):
        def answer(chunk):
            return extraction([{
                "company": "合成科技", "title": "后端实习生", "start": "2023.06", "end": "2023.09",
                "summary": "", "source_quote": "2023.06-2023.09 合成科技 后端实习生"}])

        result = await extract_profile(ScriptedAgent(answer), self.TEXT)
        row = result["profile"]["experiences"][0]
        self.assertIn("数据导-", row["summary"])
        self.assertIn("并补充错误处理", row["summary"])

    async def test_short_resume_model_error_returns_failure_without_local_fallback(self):
        def answer(chunk):
            raise ModelError("model_timeout")

        result = await extract_profile(ScriptedAgent(answer), self.TEXT)
        self.assertEqual(result["failure"], "model_timeout")
        self.assertEqual(result["profile"]["experiences"], [])
        self.assertFalse(result["profile"]["truth_confirmed"])


if __name__ == "__main__":
    unittest.main()
