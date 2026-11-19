"""Entity-aware extraction: structure-aware chunking, skeleton outline, per-entity fills.

Every sample below is synthetic; no real person, employer or contact is involved.
"""

import re
import unittest

from interview_agent.model_adapter import ModelError
from interview_agent.resume_profile import extract_profile, split_resume

HEADING = re.compile(r"^(\d{4}\.\d{2})-(\d{4}\.\d{2}) (\S+) (\S+)", re.MULTILINE)
SECTIONS = {"教育经历": "education", "工作经历": "experience", "实习经历": "experience",
            "项目经历": "project"}
BULLET = "负责合成模块的数据核对与接口联调，记录问题清单并补充测试用例。"


def extraction(experiences=(), projects=()):
    return {"basic": {}, "job_intent": {}, "skills": {}, "education": [],
            "experiences": list(experiences), "projects": list(projects), "summary": ""}


def chunk_rows(chunk):
    rows = []
    for match in HEADING.finditer(chunk):
        start, end, company, title = match.groups()
        rows.append({"company": company, "title": title, "start": start, "end": end,
                     "summary": "", "source_quote": match.group(0)})
    return extraction(rows)


def outline_from(text):
    """Skeleton answer derived from heading lines, the way a model would read them."""
    entities, kind = [], None
    for line in text.splitlines():
        line = line.strip()
        if line in SECTIONS:
            kind = SECTIONS[line]
            continue
        match = HEADING.match(line)
        if not match or not kind:
            continue
        start, end, first, second = match.groups()
        entities.append({
            "kind": kind, "start": start, "end": end, "anchor": line,
            "name": first if kind != "experience" else "",
            "org": first if kind == "experience" else "",
            "role": second,
        })
    return {"entities": entities}


def detail_from(text):
    first = text.splitlines()[0].strip()
    match = HEADING.match(first)
    if not match:
        return {"source_quote": first}
    start, end, first_name, second = match.groups()
    return {"school": first_name, "major": second, "company": first_name, "title": second,
            "name": first_name, "role": second, "start": start, "end": end,
            "source_quote": first}


def misc_answer():
    return {"basic": {}, "job_intent": {}, "skills": {}, "summary": ""}


class StageAgent:
    """Answers by decision stage; records each call's stage and input length."""

    generation = {"provider": "test", "model": "scripted"}

    def __init__(self, outline=None, misc=None, entity=None, extract=None):
        self.outline = outline or (lambda text: outline_from(text))
        self.misc = misc or (lambda text: misc_answer())
        self.entity = entity or (lambda text, kind: detail_from(text))
        self.extract = extract or chunk_rows
        self.calls = []

    async def decide(self, stage, value):
        text = value.get("outline_text") or value.get("entity_text") or value.get("resume_text") or ""
        self.calls.append((stage, text))
        if stage == "profile_outline":
            return self.outline(text)
        if stage == "profile_misc":
            return self.misc(text)
        if stage == "profile_entity":
            return self.entity(text, value.get("kind"))
        return self.extract(text)

    def texts(self, stage):
        return [text for called, text in self.calls if called == stage]


def oversized_entity_resume(bullets=200):
    body = "\n".join(f"- 第{index}项：{BULLET}" for index in range(bullets))
    return ("姓名：测试同学\n上海\n求职意向：后端开发\n\n工作经历\n"
            "2023.06-2023.09 合成公司 后端实习生\n" + body + "\n")


def long_resume(blocks=8, body_lines=40):
    parts = ["姓名：测试同学\n上海\n求职意向：后端开发\n\n教育经历\n"
             "2020.09-2024.06 合成大学 计算机科学 本科\n\n工作经历"]
    body = "\n".join("- " + BULLET for _ in range(body_lines))
    for index in range(blocks):
        parts.append(f"2023.06-2023.09 合成公司{index} 后端实习生\n{body}")
    return "\n\n".join(parts)


def mixed_resume(body_lines=60):
    """About three pages: three internships and four projects, each with its own bullets."""
    parts = ["姓名：测试同学\n上海\n求职意向：后端开发\n\n教育经历",
             "2020.09-2024.06 合成大学 计算机科学 本科"]
    internships = [("2023.06", "2023.09", "合成甲公司", "后端实习生", "实习甲"),
                   ("2022.06", "2022.09", "合成乙公司", "数据实习生", "实习乙"),
                   ("2021.07", "2021.09", "合成丙公司", "测试实习生", "实习丙")]
    projects = [("2024.03", "2024.06", "合成项目甲", "负责人", "项目甲"),
                ("2024.01", "2024.02", "合成项目乙", "开发", "项目乙"),
                ("2023.10", "2023.12", "合成项目丙", "开发", "项目丙"),
                ("2023.03", "2023.05", "合成项目丁", "参与者", "项目丁")]
    parts.append("\n\n工作经历")
    for start, end, company, title, tag in internships:
        bullets = "\n".join(f"- {tag}第{index}条：核对数据口径并记录问题清单。" for index in range(body_lines))
        parts.append(f"{start}-{end} {company} {title}\n{bullets}")
    parts.append("\n\n项目经历")
    for start, end, name, role, tag in projects:
        bullets = "\n".join(f"- {tag}第{index}条：拆分接口并补充单元测试。" for index in range(body_lines))
        parts.append(f"{start}-{end} {name} {role}\n{bullets}")
    return "\n".join(parts)


class StructureAwareChunkingTests(unittest.TestCase):
    def test_heading_and_bullets_stay_together_when_length_forces_a_split(self):
        text = oversized_entity_resume()
        self.assertGreater(len(text), 7000)
        chunks = split_resume(text)
        self.assertGreater(len(chunks), 1)
        # Only the preamble stays on its own; every chunk carrying bullets repeats the heading.
        for chunk in chunks[1:]:
            self.assertTrue(chunk.startswith("2023.06-2023.09 合成公司 后端实习生"))
        joined = "".join(chunks)
        for index in range(200):
            self.assertIn(f"第{index}项", joined)

    def test_no_chunk_exceeds_the_size_limit(self):
        text = oversized_entity_resume()
        self.assertTrue(all(len(chunk) <= 6000 for chunk in split_resume(text)))


class EntityExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_entity_split_by_length_is_still_one_record(self):
        text = oversized_entity_resume()

        def fail_outline(value):
            raise ModelError("invalid_model_decision")

        agent = StageAgent(outline=fail_outline)
        result = await extract_profile(agent, text)
        self.assertEqual(result["diagnostics"]["mode"], "chunks")
        experiences = result["profile"]["experiences"]
        self.assertEqual(len(experiences), 1)
        self.assertEqual(experiences[0]["company"], "合成公司")
        self.assertEqual(experiences[0]["title"], "后端实习生")
        chunks = agent.texts("profile_extract")
        self.assertGreater(len(chunks), 1)
        for chunk in chunks[1:]:
            self.assertIn("2023.06-2023.09 合成公司 后端实习生", chunk)

    async def test_skeleton_failure_falls_back_to_the_chunk_path(self):
        text = long_resume()

        def fail_outline(value):
            raise ModelError("invalid_model_decision")

        agent = StageAgent(outline=fail_outline)
        result = await extract_profile(agent, text)
        self.assertEqual(result["diagnostics"]["mode"], "chunks")
        companies = [row["company"] for row in result["profile"]["experiences"]
                     if row["company"].startswith("合成公司")]
        self.assertEqual(companies, [f"合成公司{index}" for index in range(8)])
        self.assertIsNone(result["failure"])
        self.assertTrue(agent.texts("profile_extract"))

    async def test_unattributed_bullets_are_reported_not_guessed(self):
        text = long_resume(blocks=6)

        def partial_outline(value):
            answer = outline_from(value)
            kept = [entity for entity in answer["entities"]
                    if entity["kind"] == "education" or "合成公司0" in entity["anchor"]]
            return {"entities": kept}

        agent = StageAgent(outline=partial_outline)
        result = await extract_profile(agent, text)
        self.assertEqual(result["diagnostics"]["mode"], "entities")
        self.assertEqual(result["diagnostics"]["skeleton_entities"], 2)
        self.assertEqual([row["company"] for row in result["profile"]["experiences"]],
                         ["合成公司0"])
        self.assertTrue(result["partial"])
        reported = "".join(item["text"] for item in result["unmatched_sections"])
        self.assertIn("合成公司1", reported)
        self.assertIn("合成公司2", reported)
        self.assertTrue(all(item["section"] == "工作经历" for item in result["unmatched_sections"]))

    async def test_truncated_entity_is_split_and_retried_with_the_heading(self):
        bullets = "\n".join(f"- 第{index}项：{BULLET}" for index in range(200))
        text = ("姓名：测试同学\n上海\n\n项目经历\n"
                "2023.03-2023.06 合成项目 负责人\n" + bullets + "\n")
        self.assertGreater(len(text), 7000)

        def entity(value, kind):
            if len(value) > 4500:
                raise ModelError("model_output_truncated")
            return detail_from(value)

        agent = StageAgent(entity=entity)
        result = await extract_profile(agent, text)
        self.assertEqual(result["diagnostics"]["mode"], "entities")
        self.assertGreaterEqual(result["diagnostics"]["retries"], 1)
        projects = result["profile"]["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual((projects[0]["name"], projects[0]["role"]), ("合成项目", "负责人"))
        calls = agent.texts("profile_entity")
        self.assertGreater(len(calls), 1)
        for call in calls[1:]:
            self.assertTrue(call.lstrip().startswith("2023.03-2023.06 合成项目 负责人"))

    async def test_three_internships_and_four_projects_keep_their_own_bullets(self):
        text = mixed_resume()
        self.assertGreater(len(text), 7000)
        result = await extract_profile(StageAgent(), text)
        self.assertEqual(result["diagnostics"]["mode"], "entities")
        self.assertEqual(result["diagnostics"]["entities"], 8)
        self.assertGreater(result["diagnostics"]["chunks"], 1)
        self.assertEqual(result["diagnostics"]["failed_entities"], 0)
        self.assertEqual(result["diagnostics"]["retries"], 0)
        self.assertIsNone(result["failure"])
        self.assertFalse(result["partial"])

        experiences = result["profile"]["experiences"]
        self.assertEqual([row["company"] for row in experiences],
                         ["合成甲公司", "合成乙公司", "合成丙公司"])
        for row, tag in zip(experiences, ("实习甲", "实习乙", "实习丙")):
            self.assertIn(f"{tag}第0条", row["summary"])
            self.assertIn(f"{tag}第59条", row["summary"])
            for other in ("实习甲", "实习乙", "实习丙"):
                if other != tag:
                    self.assertNotIn(other, row["summary"])

        projects = result["profile"]["projects"]
        self.assertEqual([row["name"] for row in projects],
                         ["合成项目甲", "合成项目乙", "合成项目丙", "合成项目丁"])
        for row, tag in zip(projects, ("项目甲", "项目乙", "项目丙", "项目丁")):
            self.assertIn(f"{tag}第0条", row["summary"])
            self.assertIn(f"{tag}第59条", row["summary"])
            for other in ("项目甲", "项目乙", "项目丙", "项目丁"):
                if other != tag:
                    self.assertNotIn(other, row["summary"])

    async def test_misc_failure_marks_partial_without_losing_successful_entities(self):
        def fail_misc(text):
            raise ModelError("invalid_model_decision")
        result = await extract_profile(StageAgent(misc=fail_misc), mixed_resume())
        self.assertEqual(result["diagnostics"]["mode"], "entities")
        self.assertEqual(result["diagnostics"]["misc"], "failed")
        self.assertTrue(result["partial"])
        self.assertTrue(result["profile"]["projects"])
        self.assertTrue(any("基本信息" in warning for warning in result["warnings"]))

    async def test_return_keys_are_backward_compatible(self):
        short = ("姓名：测试同学\n上海\n\n工作经历\n"
                 "2023.06-2023.09 合成公司 后端实习生\n- " + BULLET + "\n")
        result = await extract_profile(StageAgent(), short)
        self.assertEqual(set(result), {"profile", "warnings", "generation", "failure",
                                       "failures", "partial", "unmatched_sections", "diagnostics"})
        self.assertEqual(set(result["profile"]),
                         {"basic", "job_intent", "education", "experiences", "projects",
                          "skills", "summary", "truth_confirmed"})
        diagnostics = result["diagnostics"]
        self.assertEqual(diagnostics["mode"], "single")
        self.assertEqual(diagnostics["chunks"], 1)
        for key in ("entities", "skeleton_entities", "unlocated_entities", "failed_entities",
                    "model_calls", "retries"):
            self.assertIsInstance(diagnostics[key], int)
        self.assertEqual(len(result["profile"]["experiences"]), 1)


class DisplacedEducationSchoolTests(unittest.IsolatedAsyncioTestCase):
    """Markdown 导出常把学校名挪到教育条目之外；只有一条教育记录时仍应保留，并提示核对。"""

    TEXT = ("姓名：测试同学\n上海\n\n教育背景\n · 计算机科学与技术（本科） 2024.09 - 2028.06（预计）\n"
            "专业技能\nPython SQL\n测试大学\n")

    @staticmethod
    def education_row(school="测试大学"):
        return {"school": school, "major": "计算机科学与技术", "degree": "本科", "start": "2024.09",
                "end": "2028.06", "summary": "",
                "source_quote": "· 计算机科学与技术（本科） 2024.09 - 2028.06（预计）"}

    def agent(self, *rows):
        data = extraction()
        data["education"] = list(rows)
        return StageAgent(extract=lambda text: data)

    async def test_single_education_keeps_a_school_found_elsewhere_in_the_source(self):
        result = await extract_profile(self.agent(self.education_row()), self.TEXT)
        education = result["profile"]["education"]
        self.assertEqual(len(education), 1)
        self.assertEqual(education[0]["school"], "测试大学")
        self.assertEqual(education[0]["major"], "计算机科学与技术")
        self.assertTrue(any("不在该条目附近" in warning for warning in result["warnings"]))

    async def test_school_missing_from_the_source_is_still_rejected(self):
        result = await extract_profile(self.agent(self.education_row("虚构不存在的大学")), self.TEXT)
        # 校名核对不上时整条记录进入「未解析段落」，不留下编造的学校。
        self.assertEqual(result["profile"]["education"], [])
        self.assertTrue(any("无法在对应原文中核对" in warning for warning in result["warnings"]))
        self.assertTrue(any(item["section"] == "教育经历" for item in result["unmatched_sections"]))
        self.assertNotIn("虚构不存在的大学", str(result["profile"]))

    async def test_school_appearing_twice_is_not_guessed(self):
        text = self.TEXT + "曾参加测试大学的暑期项目\n"
        result = await extract_profile(self.agent(self.education_row()), text)
        self.assertEqual(result["profile"]["education"], [])
        self.assertTrue(any(item["section"] == "教育经历" for item in result["unmatched_sections"]))

    async def test_two_education_rows_never_borrow_each_others_school(self):
        second = self.education_row("别的大学")
        second["source_quote"] = "· 另一门专业（硕士） 2028.09 - 2031.06（预计）"
        text = self.TEXT.replace("专业技能", " · 另一门专业（硕士） 2028.09 - 2031.06（预计）\n专业技能", 1) + "别的大学\n"
        result = await extract_profile(self.agent(self.education_row(), second), text)
        self.assertEqual(result["profile"]["education"], [])
        self.assertNotIn("测试大学", str(result["profile"]["education"]))


if __name__ == "__main__":
    unittest.main()
