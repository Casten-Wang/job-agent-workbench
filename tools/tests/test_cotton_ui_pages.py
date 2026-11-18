#!/usr/bin/env python3
"""Static checks for the 「墨靛」 page layer (mj-pages.css).

Offline only: reads the shipped static files. No endpoint is called and
nothing is sent. See web/COTTON-UI-SPEC.md §1, §2, §3 and §6.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "web" / "static"
INDEX = STATIC_DIR / "index.html"
PAGES = STATIC_DIR / "mj-pages.css"
BASE = STATIC_DIR / "mj-base.css"

ALLOWED_PREFIXES = (
    "body.offer-ui:not(#wa-theme-off)",
    ':root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)',
    ":root:not([data-theme]) body.offer-ui:not(#wa-theme-off)",
)

PAGE_VIEWS = (
    "#view-collect",
    "#view-jobs",
    "#view-queue",
    "#view-mail",
    "#view-profile",
    "#view-resume",
    "#view-interview",
    "#view-push",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _read_block(css: str, start: int) -> tuple[str, int]:
    """Return the text inside the braces starting at ``start`` and the next index."""
    depth = 0
    i = start
    n = len(css)
    while i < n:
        ch = css[i]
        if ch in "\"'":
            i += 1
            while i < n and css[i] != ch:
                if css[i] == "\\":
                    i += 1
                i += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return css[start + 1 : i], i + 1
        i += 1
    raise AssertionError("unbalanced braces in css")


def _split_selectors(prelude: str) -> list[str]:
    """Split a selector list on top-level commas (ignoring :is(...) etc.)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(prelude)
    while i < n:
        ch = prelude[i]
        if ch in "\"'":
            j = i + 1
            while j < n and prelude[j] != ch:
                if prelude[j] == "\\":
                    j += 1
                j += 1
            buf.append(prelude[i : j + 1])
            i = j + 1
            continue
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _iter_rules(css: str) -> list[tuple[str, bool]]:
    """Return (selector, inside_media) pairs for every style rule."""
    out: list[tuple[str, bool]] = []

    def walk(text: str, inside_media: bool) -> None:
        i = 0
        n = len(text)
        prelude: list[str] = []
        while i < n:
            ch = text[i]
            if ch in "\"'":
                j = i + 1
                while j < n and text[j] != ch:
                    if text[j] == "\\":
                        j += 1
                    j += 1
                prelude.append(text[i : j + 1])
                i = j + 1
                continue
            if ch == ";":
                prelude = []
                i += 1
                continue
            if ch == "{":
                body, i = _read_block(text, i)
                head = "".join(prelude).strip()
                prelude = []
                if head.startswith("@"):
                    if head.startswith("@media"):
                        walk(body, True)
                else:
                    for selector in _split_selectors(head):
                        out.append((selector, inside_media))
                continue
            prelude.append(ch)
            i += 1

    walk(css, False)
    return out


class CottonPagesFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _read(PAGES)
        cls.clean = _strip_comments(cls.css)
        cls.index = _read(INDEX)
        cls.rules = _iter_rules(cls.clean)

    def test_file_is_linked_after_sg_tools_and_base_layers(self):
        def position(href: str) -> int:
            marker = f'href="/{href}"'
            self.assertIn(marker, self.index)
            return self.index.index(marker)

        self.assertLess(position("sg-tools.css"), position("mj-base.css"))
        self.assertLess(position("mj-base.css"), position("mj-pages.css"))
        self.assertTrue(PAGES.is_file())
        self.assertTrue(BASE.is_file())

    def test_no_yellow_green_or_warm_paper_residue(self):
        for forbidden in ("#D2F53C", "#9BC21A", "#F2EEE4"):
            with self.subTest(color=forbidden):
                self.assertNotIn(forbidden.lower(), self.clean.lower())

    def test_only_mj_tokens_are_used_for_color(self):
        # 页面层不自带色值，全部引用 mj-base.css 定义的 --mj-* token。
        hex_colors = re.findall(r"#[0-9a-fA-F]{3,8}\b", self.clean)
        self.assertEqual(hex_colors, [])
        self.assertIn("var(--mj-line)", self.clean)
        self.assertIn("var(--mj-brand-soft)", self.clean)

    def test_no_token_definitions_in_pages_layer(self):
        definitions = re.findall(r"--mj-[a-z0-9-]+\s*:", self.clean)
        self.assertEqual(definitions, [], "页面层只引用 --mj-*，定义留给 mj-base.css")

    def test_important_is_not_abused(self):
        hits = [line for line in self.clean.splitlines() if "!important" in line]
        self.assertLessEqual(len(hits), 3)
        for line in hits:
            with self.subTest(line=line):
                self.assertIn("/*", line, "每处 !important 必须在同一行注明覆盖对象")

    def test_every_selector_is_scoped_to_the_offer_ui_shell(self):
        self.assertGreater(len(self.rules), 80)
        for selector, _inside_media in self.rules:
            with self.subTest(selector=selector):
                self.assertTrue(
                    selector.startswith(ALLOWED_PREFIXES),
                    f"未加作用域的选择器：{selector}",
                )

    def test_no_font_size_below_twelve_pixels(self):
        sizes = re.findall(r"font-size\s*:\s*([0-9]*\.?[0-9]+)\s*px", self.clean)
        self.assertTrue(sizes)
        below = [value for value in sizes if float(value) < 12]
        self.assertEqual(below, [], f"存在小于 12px 的字号：{below}")

    def test_no_remote_assets_or_imports(self):
        self.assertNotIn("@import", self.clean)
        self.assertNotIn("url(", self.clean)
        self.assertNotIn("https://", self.clean)
        self.assertNotIn("http://", self.clean)

    def test_reduced_motion_disables_transitions(self):
        block = re.search(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\}",
            self.clean,
            flags=re.S,
        )
        self.assertIsNotNone(block)
        self.assertIn("transition: none", block.group(1))

    def test_covers_all_eight_page_views(self):
        for view in PAGE_VIEWS:
            with self.subTest(view=view):
                self.assertIn(view, self.clean)

    def test_dark_theme_and_follow_system_are_mirrored(self):
        self.assertIn(
            ':root[data-theme="dark"] body.offer-ui:not(#wa-theme-off)', self.clean
        )
        self.assertIn("@media (prefers-color-scheme: dark)", self.clean)
        self.assertIn(
            ":root:not([data-theme]) body.offer-ui:not(#wa-theme-off)", self.clean
        )


class CottonPagesComponentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = _read(PAGES)
        cls.clean = _strip_comments(cls.css)

    def rule(self, fragment: str) -> str:
        """Return the body of the first rule whose selector ends with ``fragment``."""
        needle = fragment.strip().rstrip("{").strip()
        pattern = re.compile(re.escape(needle) + r"[^{}]*\{([^{}]*)\}", flags=re.S)
        match = pattern.search(self.clean)
        self.assertIsNotNone(match, f"未找到规则：{fragment}")
        return match.group(1)

    def test_pipeline_tabs_use_brand_track_and_ink_active(self):
        body = self.rule(".ui-hub-tabs {")
        self.assertIn("background: var(--mj-brand-soft)", body)
        self.assertIn("border-radius: var(--mj-r-control)", body)
        active = self.rule(".ui-hub-tab.is-active")
        self.assertIn("background: var(--mj-ink)", active)
        self.assertIn("color: var(--mj-brand-ink)", active)

    def test_pipeline_tables_follow_the_shared_table_rules(self):
        header = self.rule(".data-table thead th")
        self.assertIn("background: var(--mj-paper-2)", header)
        self.assertIn("font-size: 12px", header)
        row = self.rule(".data-table tbody tr {")
        self.assertIn("height: 48px", row)
        selected = self.rule("tr.is-selected")
        self.assertIn("var(--mj-spark)", selected)

    def test_hr_inbox_marks_unread_in_spark_and_active_conversation(self):
        dot = self.rule(".hr-unread-dot")
        self.assertIn("width: 8px", dot)
        self.assertIn("background: var(--mj-spark)", dot)
        active = self.rule(".hr-conversation.is-active")
        self.assertIn("var(--mj-brand-soft)", active)
        self.assertIn("inset 3px 0 0 var(--mj-spark)", active)

    def test_hr_bubbles_and_composer_use_paper_language(self):
        mine = self.rule(".hr-message-me")
        self.assertIn("background: var(--mj-brand-soft)", mine)
        hr = self.rule(".hr-message-hr")
        self.assertIn("background: var(--mj-paper-2)", hr)
        composer = self.rule(".hr-composer {")
        self.assertIn("background: var(--mj-paper)", composer)

    def test_hr_confirm_dialog_is_a_floating_window(self):
        overlay = self.rule("#hr-reply-confirm-panel {")
        self.assertIn("backdrop-filter", overlay)
        dialog = self.rule("#hr-reply-confirm-panel .hr-reply-dialog")
        self.assertIn("var(--mj-r-stage)", dialog)
        self.assertIn("var(--mj-shadow-float)", dialog)
        title = self.rule(".hr-reply-head h3")
        self.assertIn("var(--mj-serif)", title)

    def test_collect_checks_and_score_strip_use_status_bars(self):
        check = self.rule(".collect-check {")
        self.assertIn("border-left: 3px solid var(--mj-line)", check)
        good = self.rule(".collect-check:has(.badge-good)")
        self.assertIn("var(--mj-good)", good)
        warn = self.rule(".collect-check:has(.badge-warn)")
        self.assertIn("var(--mj-warn)", warn)
        bad = self.rule(".collect-check:has(.badge-bad)")
        self.assertIn("var(--mj-bad)", bad)

    def test_jobs_score_is_monospace_and_quiet(self):
        score = self.rule(".jobs-score {")
        self.assertIn("var(--mj-mono)", score)
        self.assertIn("tabular-nums", score)
        empty = self.rule(".jobs-score-empty")
        self.assertIn("var(--mj-text-2)", empty)

    def test_profile_progress_uses_brand_and_good(self):
        fill = self.rule(".profile-meter-bar > span")
        self.assertIn("var(--mj-brand)", fill)
        done = self.rule(".profile-chip.is-done")
        self.assertIn("var(--mj-good)", done)
        nav_done = self.rule(".sg-profile-nav-item.is-done .sg-profile-nav-state")
        self.assertIn("var(--mj-good)", nav_done)

    def test_resume_source_cards_mark_selection_with_brand(self):
        selected = self.rule(
            ":is(.cu-source-choice, .cu-template-choice) > label:has(input:checked)"
        )
        self.assertIn("1.5px solid var(--mj-brand)", selected)
        self.assertIn("background: var(--mj-brand-soft)", selected)

    def test_interview_hub_cards_are_product_windows(self):
        node = self.rule("#interview-hub .pipeline-node {")
        self.assertIn("var(--mj-shadow-card)", node)
        self.assertIn("var(--mj-r-card)", node)
        name = self.rule(".pipeline-name")
        self.assertIn("var(--mj-serif)", name)
        turn = self.rule(".chat-turn-candidate")
        self.assertIn("var(--mj-brand-soft)", turn)

    def test_push_output_uses_paper_and_mono(self):
        block = self.rule(".code-block {")
        self.assertIn("var(--mj-paper-2)", block)
        self.assertIn("var(--mj-mono)", block)
        self.assertIn("font-size: 12px", block)


if __name__ == "__main__":
    unittest.main()
