#!/usr/bin/env python3
"""Tests for the job-detail "定制材料" (materials) block.

Offline only: reads the shipped static files, a fictional JSON fixture and runs
the pure materials helpers with node.  No endpoint is called, no platform is
opened and nothing is sent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
INDEX = STATIC_DIR / "index.html"
APP = STATIC_DIR / "app.js"
THEME = STATIC_DIR / "offer-theme.css"
FIXTURE = PROJECT_ROOT / "tools" / "tests" / "fixtures" / "job-materials-sample.json"

BLOCK_START = "/* jobs-dossier:start"
BLOCK_END = "/* jobs-dossier:end */"

EMPTY_TEXT = "尚未生成定制材料。在审批队列勾选已确认岗位后点「生成招呼语」。"

# 运行时拼出的测试号码，文件里不出现连续的 11 位数字。
MOBILE = "1" + "3" + "9" + "0" * 8
LANDLINE = "0" + "10" + "-" + "0" * 8


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _block(script: str) -> str:
    start = script.index(BLOCK_START)
    end = script.index(BLOCK_END, start) + len(BLOCK_END)
    return script[start:end]


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


class MaterialsMarkupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read(INDEX)
        cls.script = _read(APP)
        cls.theme = _read(THEME)
        cls.block = _block(cls.script)
        cls.render = _between(
            cls.script,
            "/* 定制材料：只增区块",
            "function dossierSections(",
        )

    def test_section_is_wired_into_the_shared_dossier(self):
        self.assertIn("dossierMaterialsSection(job),", self.script)
        self.assertIn("'定制材料'", self.render)
        # 原有详情段一个不删。
        sections = _between(self.script, "function dossierSections(", "function renderDossier(")
        for call in (
            "dossierStandardSection(job)",
            "dossierMatchSection(job)",
            "dossierTraceSection(job)",
            "dossierSectionText('简历改动'",
            "dossierSectionText('招呼语（确认前原文）'",
            "dossierGreetingEvidenceSection(job)",
            "dossierSectionList('剩余不确定项'",
            "dossierSectionText('建议动作'",
        ):
            with self.subTest(call=call):
                self.assertIn(call, sections)

    def test_null_materials_shows_the_exact_empty_state(self):
        self.assertIn(EMPTY_TEXT, self.render)
        # 空状态文案只出现一次，避免两套说法。
        self.assertEqual(self.script.count(EMPTY_TEXT), 1)
        self.assertNotIn("定制材料为空", self.render)
        self.assertNotIn("暂未生成", self.render)

    def test_three_greeting_variants_are_named(self):
        for label in ("简洁版", "项目成果版", "稳妥版"):
            with self.subTest(label=label):
                self.assertIn(label, self.block)
        self.assertIn("{ key: 'concise', label: '简洁版' }", self.block)
        self.assertIn("{ key: 'project', label: '项目成果版' }", self.block)
        self.assertIn("{ key: 'safe', label: '稳妥版' }", self.block)

    def test_materials_adds_no_action_or_send_button(self):
        self.assertNotIn("postAction(", self.render)
        self.assertNotIn("fetch(", self.render)
        self.assertNotIn("queue-delivery-start", self.render)
        self.assertNotIn("offerpilot-reply", self.render)
        self.assertNotIn("type=\"submit\"", self.render)
        # 版本切换与队列卡片共用「来源：…」标注，不新增动作。
        self.assertIn("`来源：${variant.label}`", self.render)

    def test_contact_fields_are_redacted_before_rendering(self):
        self.assertIn("MATERIALS_REDACTIONS", self.block)
        for marker in ("邮箱已隐藏", "链接已隐藏", "微信已隐藏", "电话已隐藏"):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.block)
        # 渲染只使用过滤后的值。
        self.assertIn("materialsSafeText(", self.block)
        self.assertNotIn("String(row.evidence || '')", self.render)

    def test_platforms_are_not_hardcoded_in_the_materials_block(self):
        for platform in ("'boss'", "'zhilian'", "'liepin'", "'51job'", "BOSS直聘", "智联", "猎聘"):
            with self.subTest(platform=platform):
                self.assertNotIn(platform, self.render)

    def test_conditions_have_three_distinct_status_tones(self):
        self.assertIn("if (status === '已满足') return 'met';", self.block)
        self.assertIn("if (status === '明确不满足') return 'unmet';", self.block)
        self.assertIn("if (status === '待确认') return 'pending';", self.block)
        for tone in ("met", "unmet", "pending", "unknown"):
            with self.subTest(tone=tone):
                self.assertIn(f"jobs-materials-status--${{tone}}", self.render)

    def test_resume_rows_carry_labels_for_narrow_screens(self):
        self.assertIn("attrs: { 'data-label': cell.label }", self.render)
        self.assertIn("['简历原文', '建议改法']", self.render)
        self.assertIn("label: '原文'", self.render)
        self.assertIn("label: '建议'", self.render)

    def test_styles_follow_the_offer_ui_layer(self):
        for selector in (
            "body.offer-ui .jobs-materials {",
            "body.offer-ui .jobs-materials-status--met {",
            "body.offer-ui .jobs-materials-status--unmet {",
            "body.offer-ui .jobs-materials-status--pending {",
            "body.offer-ui .jobs-materials-greeting-text {",
            "body.offer-ui .jobs-materials-table td[data-label]::before {",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, self.theme)
        met = _between(self.theme, "body.offer-ui .jobs-materials-status--met {", "}")
        unmet = _between(self.theme, "body.offer-ui .jobs-materials-status--unmet {", "}")
        pending = _between(self.theme, "body.offer-ui .jobs-materials-status--pending {", "}")
        self.assertIn("var(--good)", met)
        self.assertIn("var(--bad)", unmet)
        self.assertIn("var(--warn)", pending)

    def test_narrow_screens_stack_the_tables(self):
        mobile = _between(self.theme, "/* 岗位详情：定制材料", "/* 首页：今天要做的事")
        self.assertIn("body.offer-ui .jobs-materials-table td", mobile)
        self.assertIn("display: block", mobile)
        self.assertIn("content: attr(data-label)", mobile)


class MaterialsModelTests(unittest.TestCase):
    @staticmethod
    def _run(job):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过定制材料校验")
        harness = (
            _block(_read(APP))
            + "\nconst fs = require('fs');\n"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "process.stdout.write(JSON.stringify({\n"
            "  materials: materialsOf(input.job),\n"
            "  tones: ['已满足', '明确不满足', '待确认', '其他'].map(materialsStatusTone),\n"
            "  safe: input.text === undefined ? null : materialsSafeText(input.text)\n"
            "}));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps({"job": job}, ensure_ascii=False),
            text=True, encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行定制材料失败：{completed.stderr[:800]}")
        return json.loads(completed.stdout)

    def _safe(self, text):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node 不可用，跳过定制材料校验")
        harness = (
            _block(_read(APP))
            + "\nconst fs = require('fs');\n"
            "const input = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
            "process.stdout.write(String(materialsSafeText(input.text)));\n"
        )
        completed = subprocess.run(
            [node, "-e", harness],
            input=json.dumps({"text": text}, ensure_ascii=False),
            text=True, encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"node 执行联系方式过滤失败：{completed.stderr[:800]}")
        return completed.stdout

    def test_null_or_missing_materials_returns_null(self):
        for job in ({}, {"materials": None}, {"materials": "text"}, None):
            with self.subTest(job=job):
                self.assertIsNone(self._run(job)["materials"])

    def test_fixture_normalises_every_field(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = self._run(fixture)["materials"]
        self.assertEqual(len(result["mapping"]), 2)  # 空行被丢弃，不伪造内容。
        self.assertIsNone(result["mapping"][1]["evidence"])
        self.assertEqual(result["mapping"][0]["source"], "简历项目一")
        self.assertEqual(len(result["conditions"]), 4)
        self.assertEqual([row["status"] for row in result["conditions"]],
                         ["已满足", "明确不满足", "待确认", None])
        self.assertEqual(result["unknownFields"], ["团队规模", "汇报对象"])
        self.assertEqual(len(result["resumeSuggestions"]), 2)
        self.assertEqual(result["confirmItems"],
                         ["确认到岗时间", "确认薪资范围", "确认是否接受远程"])
        self.assertEqual(result["selected"], "project")

    def test_fixture_contacts_and_links_never_survive(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        result = self._run(fixture)["materials"]
        rendered = json.dumps(result, ensure_ascii=False)
        for secret in (
            "hr-demo@example.com", "demo@example.com",
            "https://example.com/job", "demo_wechat_dummy",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, rendered)
        for marker in ("邮箱已隐藏", "链接已隐藏", "微信已隐藏"):
            with self.subTest(marker=marker):
                self.assertIn(marker, rendered)

    def test_phone_numbers_are_redacted(self):
        for number in (MOBILE, LANDLINE):
            with self.subTest(number=number):
                safe = self._safe(f"请联系 {number} 沟通")
                self.assertNotIn(number, safe)
                self.assertIn("电话已隐藏", safe)

    def test_missing_fields_degrade_to_empty_lists(self):
        result = self._run({"id": 1, "materials": {}})["materials"]
        self.assertEqual(result["mapping"], [])
        self.assertEqual(result["conditions"], [])
        self.assertEqual(result["unknownFields"], [])
        self.assertEqual(result["resumeSuggestions"], [])
        self.assertEqual(result["confirmItems"], [])
        self.assertEqual(result["greetings"], {"concise": None, "project": None, "safe": None})
        self.assertEqual(result["selected"], "")

    def test_selection_reuses_the_existing_greeting_selection(self):
        materials = {"greetings": {"concise": "短版", "project": "项目版", "safe": "稳妥版"}}
        cases = [
            ("项目成果版", "project"),
            ("safe", "safe"),
            ("简洁版", "concise"),
            ("未标注", "concise"),
        ]
        for label, expected in cases:
            with self.subTest(label=label):
                job = {"materials": materials, "greeting": {"selection": label}}
                self.assertEqual(self._run(job)["materials"]["selected"], expected)
        # 只有部分版本有文本时，从有文本的版本里选。
        partial = {"materials": {"greetings": {"safe": "稳妥版"}},
                   "greeting": {"selection": "简洁版"}}
        self.assertEqual(self._run(partial)["materials"]["selected"], "safe")

    def test_status_tones_stay_distinct(self):
        self.assertEqual(
            self._run({})["tones"],
            ["met", "unmet", "pending", "unknown"],
        )


if __name__ == "__main__":
    unittest.main()
