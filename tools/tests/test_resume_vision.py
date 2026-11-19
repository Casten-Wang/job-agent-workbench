"""PDF 文字层不可用时的图片识别兜底。数据全部虚构；模型与渲染器在边界处替换。"""

import base64
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

WEB = Path(__file__).resolve().parents[2] / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import backend
import profile_import
import resume_vision
from test_profile_import import RESUME, pdf_bytes

UNUSABLE = profile_import.TextLayerUnusable(profile_import.GARBLED_MESSAGE)


def payload(filename="resume.pdf", content=b"%PDF-fake"):
    return {"mode": "user", "filename": filename, "content_base64": base64.b64encode(content).decode()}


class VisionFallbackFlowTests(unittest.TestCase):
    def setUp(self):
        suggestion = backend.default_profile()
        suggestion["basic"].update(name="测试同学")
        patcher = patch("career_user_runtime.upstream", return_value={"profile": suggestion, "warnings": [], "generation": {}})
        self.upstream = patcher.start()
        self.addCleanup(patcher.stop)

    def test_unusable_text_layer_is_transcribed_then_extracted_as_usual(self):
        with patch.object(profile_import, "extract_resume_text", side_effect=UNUSABLE), \
                patch.object(resume_vision, "transcribe_pdf", return_value=(RESUME, ["说明一条"])) as transcribe:
            result = backend.import_profile_cv(payload())
        transcribe.assert_called_once()
        self.upstream.assert_called_once_with("POST", "/v1/career/profile-import", {"text": RESUME})
        self.assertEqual(result["text_origin"], "image")
        self.assertEqual(result["source_text"], RESUME)
        self.assertIn("图片识别", result["message"])
        self.assertIn("说明一条", result["warnings"])
        self.assertFalse(result["profile"]["truth_confirmed"])

    def test_normal_text_layer_never_touches_vision(self):
        with patch.object(resume_vision, "transcribe_pdf") as transcribe:
            result = backend.import_profile_cv(payload("resume.txt", RESUME.encode()))
        transcribe.assert_not_called()
        self.assertEqual(result["text_origin"], "text_layer")

    def test_vision_failure_keeps_original_advice_and_adds_reason(self):
        failure = resume_vision.VisionUnavailable("模型尚未配置，请先在设置中配置 AI 接口")
        with patch.object(profile_import, "extract_resume_text", side_effect=UNUSABLE), \
                patch.object(resume_vision, "transcribe_pdf", side_effect=failure):
            with self.assertRaises(backend.ApiError) as caught:
                backend.import_profile_cv(payload())
        self.assertIn("乱码", caught.exception.message)
        self.assertIn("模型尚未配置", caught.exception.message)
        self.upstream.assert_not_called()

    def test_non_pdf_garbled_text_does_not_use_vision(self):
        garbled = ("ᦜ஛Ớ҅ካ҅ଠӳ࿯ᳪՈᘶᔮොୗ" * 5).encode("utf-8")
        with patch.object(resume_vision, "transcribe_pdf") as transcribe:
            with self.assertRaises(backend.ApiError):
                backend.import_profile_cv(payload("resume.txt", garbled))
        transcribe.assert_not_called()


class TranscribeTests(unittest.TestCase):
    def test_pages_keep_order_and_truncation_is_reported(self):
        images = [b"a", b"b", b"c"]
        with patch.object(resume_vision, "render_pdf_pages", return_value=(images, 9)), \
                patch.object(resume_vision, "call_vision_model", side_effect=lambda image, prompt: "第一页\n姓名测试同学" if image == b"a" else f"页{image.decode()}的内容，这里是足够长的正常文字。"):
            text, notes = resume_vision.transcribe_pdf(b"x")
        self.assertTrue(text.startswith("第一页"))
        self.assertLess(text.index("页b"), text.index("页c"))
        self.assertTrue(any("前 3 页（共 9 页）" in note for note in notes))

    def test_prompt_treats_page_content_as_data(self):
        self.assertIn("不要执行", resume_vision.TRANSCRIBE_PROMPT)

    def test_empty_or_garbled_transcription_is_rejected(self):
        with patch.object(resume_vision, "render_pdf_pages", return_value=([b"a"], 1)), \
                patch.object(resume_vision, "call_vision_model", return_value=""):
            with self.assertRaises(resume_vision.VisionUnavailable):
                resume_vision.transcribe_pdf(b"x")
        garbled = "ᦜ஛Ớ҅ካ҅ଠӳ࿯ᳪՈᘶᔮොୗ" * 5
        with patch.object(resume_vision, "render_pdf_pages", return_value=([b"a"], 1)), \
                patch.object(resume_vision, "call_vision_model", return_value=garbled):
            with self.assertRaises(resume_vision.VisionUnavailable):
                resume_vision.transcribe_pdf(b"x")

    def test_missing_model_key_is_a_clear_error_not_a_crash(self):
        with patch("offerpilot_runtime.load_backend", side_effect=RuntimeError("boom")):
            with self.assertRaises(resume_vision.VisionUnavailable) as caught:
                resume_vision.call_vision_model(b"jpeg", "p")
        self.assertIn("尚未配置", str(caught.exception))

    @unittest.skipUnless(shutil.which("sips"), "needs macOS sips")
    def test_real_render_produces_jpeg_pages(self):
        images, total = resume_vision.render_pdf_pages(pdf_bytes())
        self.assertEqual(total, 1)
        self.assertTrue(images[0].startswith(b"\xff\xd8"))

    def test_render_without_tool_reports_unavailable(self):
        with patch.object(shutil, "which", return_value=None):
            with self.assertRaises(resume_vision.VisionUnavailable):
                resume_vision.render_pdf_pages(pdf_bytes())


if __name__ == "__main__":
    unittest.main()
