#!/usr/bin/env python3
"""Manual collection re-collects finished (city, keyword) combos by default.

The user's rule: collection is triggered by hand in the foreground, so a combo
finished hours ago must never be skipped just because less than 24 hours have
passed.  ``resume_ttl_hours`` stays supported and, when explicitly set to a
positive number, restores the old windowed skip.  Page-level resume (stopping
mid-keyword and continuing at the saved page) is unaffected.

No browser, no network: sqlite runs in a temp file, browsers are stubs.
"""

from __future__ import annotations

import inspect
import re
import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot import db  # noqa: E402
from offerpilot.collection.base import CollectionBlockedError, CollectorHooks  # noqa: E402
from offerpilot.collection.models import PlatformCollectionRequest  # noqa: E402
from offerpilot.collection.platforms import job51, liepin, zhilian  # noqa: E402

# (module, platform id, collector attribute name)
PLATFORMS = (
    (job51, "51job", "Job51Collector"),
    (liepin, "liepin", "LiepinCollector"),
    (zhilian, "zhilian", "ZhilianCollector"),
)
CITY = "杭州"
KEYWORD = "产品经理"


def _collector(module, name, config):
    return module.__dict__[name](config=config, browser=SimpleNamespace())


class _Hooks:
    """CollectorHooks with captured events; never stops."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.hooks = CollectorHooks(
            stop_event=Event(),
            on_list_candidate=lambda candidate: False,
            on_candidate=lambda candidate: False,
            on_parse_failed=lambda message: None,
            on_event=self._on_event,
        )

    def _on_event(self, **values) -> None:
        self.events.append(values)

    def skipped_keywords(self) -> list[str]:
        return [str(e.get("message") or "") for e in self.events if "断点续采" in str(e.get("message") or "")]


class _StubBrowser:
    """Opens no tabs; optionally offers a ready 51job host page."""

    navigate_action = None

    def __init__(self, *, host: bool = False) -> None:
        self.host = host
        self.new_tab_calls = 0
        self.closed: list[str] = []

    def new_tab(self, url, background=True):
        self.new_tab_calls += 1
        return None  # opening fails: the run must report it

    def get_page_targets(self):
        if not self.host:
            return []
        return [{"url": "https://we.51job.com/pc/search?keyword=x", "targetId": "host-1"}]

    def evaluate(self, target_id, script, timeout=30):
        return '{"ok": true}'

    def close_tab(self, target_id):
        self.closed.append(target_id)
        return True


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="resume-window-")
        self.addCleanup(self.temp.cleanup)
        self.conn = db.get_db(Path(self.temp.name) / "offerpilot.db")
        self.addCleanup(self.conn.close)

    def _request(self) -> PlatformCollectionRequest:
        return PlatformCollectionRequest(
            platform="51job",
            keywords=[KEYWORD],
            cities=[CITY],
            city_codes={CITY: "020000"},
            max_pages=2,
        )

    def _patch_clock(self, module) -> None:
        # Collection no longer has a time window; only the random day off is
        # stubbed so the resume tests stay deterministic.
        patcher = patch.object(module, "should_take_day_off", lambda probability: False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _collect(self, module, name, config, browser):
        self._patch_clock(module)
        collector = module.__dict__[name](
            config=config,
            safety_conn=self.conn,
            browser=browser,
            sleep=lambda seconds: None,
        )
        hooks = _Hooks()
        try:
            result = collector.collect(self._request(), hooks.hooks)
        except CollectionBlockedError as exc:
            result = exc  # 51job re-raises when no host page can be opened
        return result, hooks


class ComboSkipHelperTests(_Case):
    """The shared decision: no window means no skip, whatever finished when."""

    def test_default_does_not_skip_a_combo_finished_just_now(self):
        db.mark_combo_collected(self.conn, "51job", CITY, KEYWORD)
        self.assertEqual(db.combos_to_skip(self.conn, "51job"), set())

    def test_default_does_not_skip_a_combo_finished_days_ago(self):
        db.mark_combo_collected(self.conn, "51job", CITY, KEYWORD)
        self.conn.execute("UPDATE collect_progress SET finished_at = datetime('now', '-72 hours')")
        self.conn.commit()
        self.assertEqual(db.combos_to_skip(self.conn, "51job"), set())

    def test_explicit_window_still_skips_a_recent_combo(self):
        db.mark_combo_collected(self.conn, "51job", CITY, KEYWORD)
        self.assertIn((CITY, KEYWORD), db.combos_to_skip(self.conn, "51job", 24))
        self.assertIn((CITY, KEYWORD), db.combos_to_skip(self.conn, "51job", 1))

    def test_explicit_window_lets_an_old_combo_be_recollected(self):
        db.mark_combo_collected(self.conn, "51job", CITY, KEYWORD)
        self.conn.execute("UPDATE collect_progress SET finished_at = datetime('now', '-30 hours')")
        self.conn.commit()
        self.assertNotIn((CITY, KEYWORD), db.combos_to_skip(self.conn, "51job", 24))

    def test_platforms_are_isolated(self):
        db.mark_combo_collected(self.conn, "51job", CITY, KEYWORD)
        self.assertIn((CITY, KEYWORD), db.combos_to_skip(self.conn, "51job", 24))
        self.assertEqual(db.combos_to_skip(self.conn, "zhilian", 24), set())

    def test_no_connection_never_skips(self):
        self.assertEqual(db.combos_to_skip(None, "51job"), set())
        self.assertEqual(db.combos_to_skip(None, "51job", 24), set())


class ResumeTtlConfigTests(unittest.TestCase):
    """Each platform reads resume_ttl_hours the same way."""

    def test_default_is_no_window_everywhere(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                self.assertIsNone(_collector(module, name, {})._resume_ttl_hours())

    def test_absent_key_is_no_window(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                config = {"platforms": {platform: {"search": {}}}}
                self.assertIsNone(_collector(module, name, config)._resume_ttl_hours())

    def test_explicit_positive_value_is_kept(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                config = {"platforms": {platform: {"search": {"resume_ttl_hours": 12}}}}
                self.assertEqual(_collector(module, name, config)._resume_ttl_hours(), 12)

    def test_legacy_global_search_block_is_kept(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                collector = _collector(module, name, {"search": {"resume_ttl_hours": 8}})
                self.assertEqual(collector._resume_ttl_hours(), 8)

    def test_zero_negative_and_garbage_disable_the_window(self):
        for module, platform, name in PLATFORMS:
            for raw in (0, -5, "", "abc", None):
                with self.subTest(platform=platform, raw=raw):
                    config = {"platforms": {platform: {"search": {"resume_ttl_hours": raw}}}}
                    self.assertIsNone(_collector(module, name, config)._resume_ttl_hours())

    def test_window_is_capped_at_720_hours(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                config = {"platforms": {platform: {"search": {"resume_ttl_hours": 9999}}}}
                self.assertEqual(_collector(module, name, config)._resume_ttl_hours(), 720)


class PageResumeUnaffectedTests(_Case):
    """Stopping mid-keyword still continues at the saved page."""

    def test_default_reads_back_the_saved_page(self):
        db.upsert_page_progress(self.conn, "liepin", CITY, KEYWORD, 4)
        self.assertEqual(db.get_page_progress(self.conn, "liepin", CITY, KEYWORD), 4)

    def test_explicit_window_still_reads_a_recent_saved_page(self):
        db.upsert_page_progress(self.conn, "liepin", CITY, KEYWORD, 4)
        self.assertEqual(db.get_page_progress(self.conn, "liepin", CITY, KEYWORD, within_hours=24), 4)

    def test_saved_page_survives_while_the_combo_is_recollected(self):
        # A finished combo no longer skips the keyword, but its page checkpoint
        # still decides where the new pass starts.
        db.mark_combo_collected(self.conn, "liepin", CITY, KEYWORD)
        db.upsert_page_progress(self.conn, "liepin", CITY, KEYWORD, 3)
        self.assertEqual(db.combos_to_skip(self.conn, "liepin"), set())
        self.assertEqual(db.get_page_progress(self.conn, "liepin", CITY, KEYWORD), 3)


class ManualCollectBehaviourTests(_Case):
    """collect() itself: default re-collects, explicit TTL skips."""

    def test_default_manual_run_attempts_a_finished_combo(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                db.mark_combo_collected(self.conn, platform, CITY, KEYWORD)
                browser = _StubBrowser()
                _result, hooks = self._collect(module, name, {}, browser)
                self.assertEqual(hooks.skipped_keywords(), [])
                self.assertGreaterEqual(browser.new_tab_calls, 1, "the collector must try, not skip")

    def test_explicit_window_still_skips_the_finished_combo(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                db.mark_combo_collected(self.conn, platform, CITY, KEYWORD)
                config = {"platforms": {platform: {"search": {"resume_ttl_hours": 24}}}}
                # 51job opens its API host page before the keyword loop; offering a
                # ready host keeps new_tab_calls at zero for the skip assertion.
                browser = _StubBrowser(host=True)
                result, hooks = self._collect(module, name, config, browser)
                self.assertEqual(len(hooks.skipped_keywords()), 1)
                self.assertIn(KEYWORD, hooks.skipped_keywords()[0])
                self.assertEqual(browser.new_tab_calls, 0)
                self.assertEqual(result.status, "completed")

    def test_default_run_is_not_a_false_success(self):
        # The stub browser cannot open a page, so the run must say so rather
        # than report a clean completion after silently skipping the keyword.
        db.mark_combo_collected(self.conn, "liepin", CITY, KEYWORD)
        result, _hooks = self._collect(liepin, "LiepinCollector", {}, _StubBrowser())
        self.assertNotEqual(result.status, "completed")


class WiringTests(unittest.TestCase):
    def test_each_collector_uses_the_shared_skip_helper(self):
        for module, platform, name in PLATFORMS:
            with self.subTest(platform=platform):
                source = inspect.getsource(module.__dict__[name].collect)
                self.assertRegex(source, r"combos_to_skip\(\s*self\.safety_conn")
                self.assertIn("_resume_ttl_hours()", source)
                self.assertNotIn("get_collected_combos", source)

    def test_liepin_passes_the_same_ttl_to_its_page_checkpoint(self):
        source = inspect.getsource(liepin.LiepinCollector.collect)
        self.assertIn("within_hours=ttl_hours", source)


if __name__ == "__main__":
    unittest.main()
