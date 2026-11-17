#!/usr/bin/env python3
"""find_zhilian_tab must prefer a job-search page over the message center.

The browser is faked: ``get_page_targets`` is replaced with a canned tab list,
so no Chrome is touched and no network is used.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vendor" / "offerpilot" / "src"))

from offerpilot.browser import find_zhilian_tab  # noqa: E402


def _tabs(*urls: str) -> list[dict]:
    return [{"targetId": f"T{i}", "url": url} for i, url in enumerate(urls)]


class FindZhilianTabTests(unittest.TestCase):
    def _find(self, *urls: str) -> dict | None:
        with mock.patch("offerpilot.browser.get_page_targets", return_value=_tabs(*urls)):
            return find_zhilian_tab()

    def test_prefers_search_page_over_message_center(self) -> None:
        tab = self._find(
            "https://i.zhaopin.com/im?refcode=4017",
            "https://www.zhaopin.com/jobs/?jl=538",
        )
        self.assertEqual(tab["url"], "https://www.zhaopin.com/jobs/?jl=538")

    def test_accepts_sou_search_path(self) -> None:
        tab = self._find(
            "https://i.zhaopin.com/im?refcode=4017",
            "https://www.zhaopin.com/sou/jl538/",
        )
        self.assertEqual(tab["url"], "https://www.zhaopin.com/sou/jl538/")

    def test_falls_back_to_any_zhaopin_tab_when_no_search_page(self) -> None:
        tab = self._find(
            "https://www.liepin.com/zhaopin/",
            "https://i.zhaopin.com/im?refcode=4017",
        )
        self.assertEqual(tab["url"], "https://i.zhaopin.com/im?refcode=4017")

    def test_returns_none_without_zhaopin_tab(self) -> None:
        self.assertIsNone(self._find("https://www.liepin.com/zhaopin/"))


if __name__ == "__main__":
    unittest.main()
