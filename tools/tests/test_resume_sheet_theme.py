#!/usr/bin/env python3
"""A4 简历纸在任何主题下都必须保持白底深字。

离线静态检查：只读 `web/static/*.css`，不发请求、不写文件。
第 3 轮（信号色改版）中，mj-pages.css 曾用 `--mj-paper` / `--mj-text`
覆盖 `.resume-sheet` 的底色与文字色，深色主题下纸张变深、纸上的深墨字
几乎不可见。纸张自身的墨色由 career-resume.css 的 `--resume-*` 提供，
其它样式文件不得再改它的 background / color。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
RESUME = STATIC_DIR / "career-resume.css"

OWNER = RESUME.name

RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
COLOR_DECL_RE = re.compile(
    r"(?:^|;)\s*(background(?:-color)?|color)\s*:\s*([^;]+)", re.I
)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css: str):
    for match in RULE_RE.finditer(_strip_comments(css)):
        selector = " ".join(match.group(1).split())
        yield selector, match.group(2)


class ResumeSheetThemeTests(unittest.TestCase):
    def test_paper_base_is_white_and_light(self):
        css = RESUME.read_text(encoding="utf-8")
        base = None
        for selector, body in _rules(css):
            if selector.strip() == ".resume-sheet":
                base = body
                break
        self.assertIsNotNone(base, ".resume-sheet 基础规则缺失")
        self.assertRegex(base, r"background\s*:\s*#fff(?:fff)?\b", "纸张底色必须是白色")
        self.assertRegex(base, r"color-scheme\s*:\s*light\b", "纸张必须固定浅色配色")

    def test_no_other_file_overrides_paper_background_or_color(self):
        offenders: list[str] = []
        for path in sorted(STATIC_DIR.glob("*.css")):
            if path.name == OWNER:
                continue
            for selector, body in _rules(path.read_text(encoding="utf-8")):
                if ".resume-sheet" not in selector:
                    continue
                for decl in COLOR_DECL_RE.finditer(body):
                    prop = decl.group(1).lower()
                    value = decl.group(2).strip()
                    offenders.append(f"{path.name}: {selector} {{ {prop}: {value} }}")
        self.assertEqual(
            offenders,
            [],
            "以下规则会给 A4 纸张换底/换字色，深色主题下会失去白纸：\n"
            + "\n".join(offenders),
        )

    def test_mj_pages_keeps_only_frame(self):
        """mj-pages 可以给纸张加外框，但不得再写 background/color。"""
        pages = (STATIC_DIR / "mj-pages.css").read_text(encoding="utf-8")
        for selector, body in _rules(pages):
            if ".resume-sheet" not in selector:
                continue
            self.assertIsNone(
                COLOR_DECL_RE.search(body),
                f"mj-pages.css 仍在改纸张颜色：{selector}",
            )


if __name__ == "__main__":
    unittest.main()
