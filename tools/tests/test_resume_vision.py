"""PDF 文字层不可用时的图片识别兜底。数据全部虚构；模型与渲染器在边界处替换。"""

import base64
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


def png_bytes(size=(40, 30)):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", size, "white").save(buffer, "PNG")
    return buffer.getvalue()


class ImageResumeTests(unittest.TestCase):
    def setUp(self):
        suggestion = backend.default_profile()
        suggestion["basic"].update(name="测试同学")
        patcher = patch("career_user_runtime.upstream", return_value={"profile": suggestion, "warnings": [], "generation": {}})
        self.upstream = patcher.start()
        self.addCleanup(patcher.stop)

    def test_image_file_has_no_text_layer(self):
        for name in ("a.png", "a.JPG", "a.jpeg", "a.webp"):
            with self.subTest(name=name), self.assertRaises(profile_import.TextLayerUnusable):
                profile_import.extract_resume_text(name, png_bytes())

    def test_image_resume_is_transcribed_and_flagged(self):
        with patch.object(resume_vision, "call_vision_model", return_value=RESUME) as model:
            result = backend.import_profile_cv(payload("resume.png", png_bytes()))
        sent = model.call_args.args[0]
        self.assertTrue(sent.startswith(b"\xff\xd8"), "送给模型的应是规整后的 JPEG")
        self.upstream.assert_called_once_with("POST", "/v1/career/profile-import", {"text": RESUME})
        self.assertEqual(result["text_origin"], "image")
        self.assertIn("图片简历", result["message"])
        self.assertNotIn("PDF", result["message"])
        self.assertFalse(result["profile"]["truth_confirmed"])
        self.assertTrue(any("多页" in note for note in result["warnings"]))

    def test_image_failures_are_clear_and_do_not_reach_the_agent(self):
        with patch.object(resume_vision, "call_vision_model", side_effect=resume_vision.VisionUnavailable("模型读图失败，该模型可能不支持图片输入")):
            with self.assertRaises(backend.ApiError) as caught:
                backend.import_profile_cv(payload("resume.png", png_bytes()))
        self.assertIn("模型读图失败", caught.exception.message)
        self.upstream.assert_not_called()

    def test_fake_or_oversized_images_are_rejected_before_the_model(self):
        with patch.object(resume_vision, "call_vision_model") as model:
            with self.assertRaises(resume_vision.VisionUnavailable):
                resume_vision.prepare_image(b"not an image")
            with patch.object(resume_vision, "MAX_IMAGE_PIXELS", 10):
                with self.assertRaises(resume_vision.VisionUnavailable):
                    resume_vision.prepare_image(png_bytes())
        model.assert_not_called()

    def test_wide_images_are_downscaled(self):
        import io
        from PIL import Image
        out = resume_vision.prepare_image(png_bytes((resume_vision.RENDER_WIDTH + 400, 100)))
        with Image.open(io.BytesIO(out)) as picture:
            self.assertEqual(picture.width, resume_vision.RENDER_WIDTH)


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

    def test_real_render_produces_jpeg_pages(self):
        images, total = resume_vision.render_pdf_pages(pdf_bytes())
        self.assertEqual(total, 1)
        self.assertTrue(images[0].startswith(b"\xff\xd8"))

    def test_scanned_pdf_renders_in_order_and_obeys_page_limit(self):
        import io
        from PIL import Image
        stream = io.BytesIO()
        pages = [Image.new("RGB", (200, 280), color) for color in ("red", "green", "blue")]
        pages[0].save(stream, "PDF", save_all=True, append_images=pages[1:])
        content = stream.getvalue()
        with self.assertRaises(profile_import.TextLayerUnusable):
            profile_import.extract_resume_text("scan.pdf", content)
        images, total = resume_vision.render_pdf_pages(content, max_pages=2)
        self.assertEqual(total, 3)
        self.assertEqual(len(images), 2)
        for data, channel in zip(images, (0, 1)):
            with Image.open(io.BytesIO(data)) as image:
                self.assertEqual(image.width, resume_vision.RENDER_WIDTH)
                pixel = image.getpixel((10, 10))
                self.assertEqual(pixel.index(max(pixel)), channel)
        with patch.object(resume_vision, "call_vision_model", return_value=RESUME) as model:
            text, notes = resume_vision.transcribe_pdf(content)
        self.assertEqual(model.call_count, 3)
        self.assertIn(RESUME, text)

    def test_invalid_pdf_reports_clear_render_error(self):
        with self.assertRaises(resume_vision.VisionUnavailable):
            resume_vision.render_pdf_pages(b"not a PDF")

    def test_render_without_tool_reports_unavailable(self):
        with patch.dict(sys.modules, {"pypdfium2": None}):
            with self.assertRaises(resume_vision.VisionUnavailable):
                resume_vision.render_pdf_pages(pdf_bytes())


if __name__ == "__main__":
    unittest.main()
