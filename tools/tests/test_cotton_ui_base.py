"""「墨靛」基础层静态检查：只读文件，不起浏览器。

对应 web/COTTON-UI-SPEC.md 第 1、2、6 节里分给会话 A（mj-base.css）的验收项。
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / "web/static/mj-base.css"
HTML = (ROOT / "web/static/index.html").read_text(encoding="utf-8")

# 规格第 2 节要求 A 定义的全部 --mj-* 名
TOKEN_NAMES = (
    "mj-canvas", "mj-paper", "mj-paper-2", "mj-ink", "mj-text", "mj-text-2",
    "mj-mute", "mj-line", "mj-brand", "mj-brand-ink", "mj-brand-soft", "mj-spark",
    "mj-good", "mj-good-bg", "mj-warn", "mj-warn-bg", "mj-bad", "mj-bad-bg",
    "mj-serif", "mj-mono", "mj-r-stage", "mj-r-card", "mj-r-inner",
    "mj-r-control", "mj-r-tag", "mj-shadow-card", "mj-shadow-float", "mj-glass",
)

ALLOWED_PREFIXES = (
    "body.offer-ui:not(#wa-theme-off)",
    ':root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)',
    ":root:not([data-theme]) body.offer-ui:not(#wa-theme-off)",
)


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def selectors(css):
    """返回每个样式块的选择器组（不含 @media 等 at-rule 前导串）。"""
    found = []
    for prelude in re.findall(r"([^{}]+)\{", css):
        prelude = prelude.strip()
        if not prelude or prelude.startswith("@"):
            continue
        found.append(prelude)
    return found


def split_selectors(selector_group):
    """按顶层逗号切分，忽略 :is(...) / :not(...) 里的逗号。"""
    parts, depth, current = [], 0, []
    for ch in selector_group:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


class CottonBaseStylesheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = CSS_PATH.read_text(encoding="utf-8")
        cls.bare = strip_comments(cls.css)

    def test_file_exists_and_is_linked_after_sg_tools(self):
        self.assertTrue(CSS_PATH.exists())
        self.assertIn('/mj-base.css"', HTML)
        self.assertGreater(HTML.index("/mj-base.css"), HTML.index("/sg-tools.css"))
        self.assertLess(HTML.index("/mj-base.css"), HTML.index("/mj-pages.css"))

    def test_no_legacy_colors_and_no_important(self):
        for banned in ("#D2F53C", "#9BC21A", "#F2EEE4"):
            self.assertNotIn(banned.lower(), self.bare.lower())
        self.assertEqual(self.bare.count("!important"), 0)

    def test_no_font_below_12px(self):
        sizes = [float(v) for v in re.findall(r"font-size:\s*([\d.]+)px", self.bare)]
        self.assertTrue(sizes)
        self.assertGreaterEqual(min(sizes), 12)

    def test_every_selector_is_scoped(self):
        for group in selectors(self.bare):
            for one in split_selectors(group):
                self.assertTrue(
                    one.startswith(ALLOWED_PREFIXES),
                    msg=f"选择器未带前缀：{one}",
                )

    def test_all_spec_tokens_are_defined(self):
        for name in TOKEN_NAMES:
            self.assertRegex(self.bare, rf"--{re.escape(name)}\s*:")

    def test_light_dark_and_system_blocks_exist(self):
        self.assertRegex(self.bare, r"body\.offer-ui:not\(#wa-theme-off\)\s*\{")
        self.assertRegex(
            self.bare,
            r':root\[data-theme="dark"\] body\.offer-ui:not\(#wa-theme-off\)\s*\{',
        )
        self.assertIn("@media (prefers-color-scheme: dark)", self.bare)
        self.assertIn(":root:not([data-theme]) body.offer-ui:not(#wa-theme-off)", self.bare)
        self.assertGreaterEqual(self.bare.count("#111629"), 3)
        self.assertGreaterEqual(self.bare.count("#1A2140"), 3)
        self.assertGreaterEqual(self.bare.count("#ECEFFA"), 3)

    def test_old_tokens_are_remapped_on_all_three_blocks(self):
        for name in ("--bg:", "--surface:", "--ink:", "--sg:", "--sg-sg-mark:",
                     "--ui-signal:", "--wa-brand:", "--accent:", "--chart-grid:",
                     "--series-3:", "--stage-4:"):
            self.assertGreaterEqual(self.bare.count(name), 3, msg=name)
        self.assertNotIn("--mj-canvas:", self.bare.split("body.offer-ui:not(#wa-theme-off) {", 1)[0])

    def test_reduced_motion_block_exists(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.bare)
        tail = self.bare[self.bare.index("@media (prefers-reduced-motion: reduce)"):]
        self.assertIn("animation: none", tail)
        self.assertIn("transition: none", tail)

    def test_no_external_assets(self):
        self.assertNotIn("@import", self.bare)
        self.assertNotIn("url(", self.bare)

    def test_panel_is_a_window_with_a_title_bar(self):
        self.assertRegex(self.bare, r"\.panel-head \{[^}]*background: var\(--mj-paper-2\)")
        self.assertRegex(self.bare, r"\.panel \{[^}]*--mj-shadow-card")

    def test_home_task_stays_a_plain_row(self):
        block = re.search(r"\.home-task \{([^}]*)\}", self.bare).group(1)
        self.assertIn("border-radius: 0", block)
        self.assertIn("box-shadow: none", block)
        self.assertIn("background: transparent", block)

    def test_home_lede_is_the_ink_chapter(self):
        self.assertRegex(
            self.bare, r"\.home-today \.home-lede \{[^}]*background: var\(--mj-ink\)"
        )
        self.assertIn("--mj-r-stage", self.bare)
        self.assertIn("box-shadow: 14px 0 0", self.bare)  # 三点标识
        self.assertIn("width: 10px", self.bare)  # 茜红单点

    def test_agent_and_settings_sections_present(self):
        for anchor in ("#view-agent", "#view-data", ".home-today", "#status"):
            self.assertIn(anchor, self.bare)
        self.assertIn(".wa-composer", self.bare)
        self.assertIn(".sg-fold", self.bare)


if __name__ == "__main__":
    unittest.main()
