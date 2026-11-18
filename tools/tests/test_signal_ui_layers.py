"""「信号」打磨层：三个样式文件已接入页面并由本机服务提供。"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

LAYERS = ("sg-base.css", "sg-pipeline.css", "sg-tools.css")


class SignalLayerTests(unittest.TestCase):
    def test_layers_are_linked_after_existing_styles_in_order(self):
        html = (ROOT / "web/static/index.html").read_text(encoding="utf-8")
        positions = [html.index(f'href="/{name}"') for name in LAYERS]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(html.index('href="/career-resume.css"'), positions[0])

    def test_layers_are_served_as_static_files(self):
        import server  # noqa: WPS433

        for name in LAYERS:
            self.assertIn(f"/{name}", server.STATIC_FILES)
            self.assertTrue((ROOT / "web/static" / name).is_file())


if __name__ == "__main__":
    unittest.main()
