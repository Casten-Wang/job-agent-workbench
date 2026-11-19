"""个人资料页「导入简历」的失败体验：结构、文案与不覆盖已填内容的约束。

只做静态断言，不启动服务；真实交互在浏览器里用桩数据自检。
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "web" / "static"

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def profile_view() -> str:
    start = HTML.index('id="view-profile"')
    end = HTML.index('<section class="view"', start + 10)
    return HTML[start:end]


def function_body(name: str) -> str:
    start = APP.index(f"function {name}(")
    tail = APP[start + 1:]
    match = re.search(r"\n(?:async\s+)?function\s+\w+\(", tail)
    end = start + 1 + match.start() if match else len(APP)
    return APP[start:end]


def constant_block(name: str) -> str:
    start = APP.index(f"const {name} = ")
    end = APP.index("\n};", start)
    return APP[start:end]


class ProfileImportUxTest(unittest.TestCase):
    def test_profile_view_hosts_import_outcome_regions(self):
        view = profile_view()
        for marker in (
            'id="profile-import-status"',
            'id="profile-cv-suggest"',
            'id="profile-import-preview"',
            'id="profile-import-paragraphs"',
            'id="profile-import-text"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, view)
        # 段落容器与提示在可折叠原文面板里，默认收起。
        self.assertIn('按空行分段', view)

    def test_resume_import_entry_stays_unique(self):
        self.assertEqual(HTML.count('id="profile-import"'), 1)
        self.assertEqual(HTML.count('id="profile-import-file"'), 1)
        self.assertIn('id="profile-import"', profile_view())

    def test_placeholders_read_as_examples_not_defaults(self):
        view = profile_view()
        for forbidden in (
            'placeholder="15000"',
            'placeholder="25000"',
            'placeholder="产品经理, 产品助理"',
            'placeholder="上海, 杭州"',
            'placeholder="Axure, Visio, Excel"',
            'placeholder="需求分析, 用户调研, 数据分析"',
            'placeholder="外包, 驻场"',
            'placeholder="一个月内 / 随时"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, view)
        self.assertIn('placeholder="例如 15000"', view)
        self.assertIn('placeholder="例如 产品经理, 产品助理"', view)
        # 列表行的日期等占位同样带「例如」。
        self.assertIn("placeholder: '例如 2018-09'", APP)
        self.assertNotIn("placeholder: '2018-09'", APP)

    def test_saved_values_are_explained_next_to_the_form(self):
        view = profile_view()
        self.assertIn('输入框里的灰字只是格式示例', view)
        self.assertIn('已保存的资料会直接显示在框里', view)
        self.assertIn('来自简历', view)

    def test_failure_hints_cover_known_reason_codes(self):
        block = constant_block("PROFILE_CV_FAILURE_HINTS")
        for code in (
            "model_unconfigured",
            "truncated",
            "invalid_output",
            "timeout",
            "no_supported_fields",
            "empty_text",
            "invalid_response",
        ):
            with self.subTest(code=code):
                self.assertIn(code, block)
        self.assertIn("PROFILE_CV_FALLBACK_HINT", APP)

    def test_raw_fetch_keeps_failure_and_source_text(self):
        body = function_body("requestProfileImport")
        self.assertIn("data.failure", body)
        self.assertIn("data.source_text", body)
        self.assertIn("response.ok", body)
        self.assertIn("error.failure", body)
        self.assertIn("error.sourceText", body)

    def test_failed_import_keeps_form_values_and_offers_source(self):
        body = function_body("importProfileFromCv")
        self.assertIn("renderResumeSourcePanel(source", body)
        self.assertIn("renderProfileImportFailure(", body)
        self.assertIn("applyProfileSuggestion(", body)
        # 失败分支不能重新填充表单（populateProfileForm 会把已填内容覆盖成快照值）。
        self.assertNotIn("populateProfileForm(", body)
        self.assertIn("表单里的内容没有改动", APP)

    def test_source_panel_splits_paragraphs_and_copies(self):
        self.assertIn(r"split(/\n\s*\n+/)", APP)
        self.assertIn("复制第 ${index + 1} 段", APP)
        self.assertIn("function copyTextButton", APP)
        self.assertIn("copyTextWithFallback", APP)
        self.assertIn("profile-import-paragraph", APP)

    def test_suggestion_fills_only_empty_fields_and_marks_them(self):
        body = function_body("applyProfileSuggestion")
        self.assertIn("if (!current)", body)
        self.assertIn("state.profileCvPending[entry.path] = entry.value", body)
        self.assertIn("state.profileCvListPending[kind] = rows", body)
        self.assertIn("来自简历", APP)
        self.assertIn("profile-cv-tag", APP)
        self.assertIn("采用全部建议", APP)
        self.assertIn("text: '采用'", APP)
        self.assertIn("text: '追加'", APP)
        # 用户一改字段，标记就消失。
        clearing = function_body("bindProfileCvTagClearing")
        self.assertIn("tag.remove()", clearing)

    def test_partial_success_lists_unmatched_sections(self):
        self.assertIn("normalizeUnmatchedSections", APP)
        self.assertIn("data.unmatched_sections", APP)
        self.assertIn("这几段没能自动填入，请手动补充", APP)
        self.assertIn("复制这一段", APP)

    def test_unconfigured_model_routes_to_ai_settings(self):
        body = function_body("openAiSettingsFromProfile")
        self.assertIn("showView('data')", body)
        self.assertIn("ai-settings-panel", body)
        self.assertIn("去设置 AI 接口", APP)
        self.assertIn("settings: failure === 'model_unconfigured'", APP)

    def test_save_clears_stale_import_state(self):
        body = function_body("saveProfileForm")
        self.assertIn("clearProfileCvImportState()", body)
        clearing = function_body("clearProfileCvImportState")
        self.assertIn("profileCvPending = {}", clearing)
        self.assertIn("profileImportPreview.hidden = true", clearing)

    def test_auto_prefill_reuses_suggestion_path(self):
        body = function_body("autoPrefillProfileFromCv")
        self.assertIn("applyProfileSuggestion(", body)
        self.assertIn("renderProfileCvSuggest()", body)
        self.assertNotIn("populateProfileForm(", body)


if __name__ == "__main__":
    unittest.main()
