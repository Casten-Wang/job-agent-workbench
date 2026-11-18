#!/usr/bin/env python3
"""Single-job apply (招呼语投递) contracts for zhilian / 51job / liepin.

The browser is a fake: it records the scripts it was asked to run and returns
canned JSON.  No tab is opened, no network is touched, nothing is sent.

The platform button texts and DOM selectors are *assumptions* (see apply.py);
these tests lock the control flow and the pre-send validation, not the live DOM.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))
sys.dont_write_bytecode = True

from offerpilot.collection import apply as apply_module  # noqa: E402

JOB = {
    "id": "zhilian-1001",
    "company": "虚构智联有限公司",
    "title": "产品经理",
    "url": "https://www.zhaopin.com/jobdetail/CC000000001.htm",
}
GREETING = "您好，我对贵司的产品经理岗位很感兴趣，期待进一步沟通。"


def _queue(*values):
    """Successive evaluate results; the last one repeats."""
    items = list(values)

    class _Q:
        def next(self):
            if not items:
                return None
            return items.pop(0) if len(items) > 1 else items[0]

    return _Q()


class _FakeBrowser:
    def __init__(self, *, page="ready", click=None, fill=None, confirm=None,
                 sent=None, new_tab_ok=True, wait_ok=True):
        self.page = _queue(*(page if isinstance(page, list) else [page]))
        self.click = click if click is not None else {"found": True, "text": "立即投递"}
        self.fill = fill if fill is not None else {"filled": True}
        self.confirm = confirm if confirm is not None else {"clicked": True}
        self.sent = sent if sent is not None else {"sent": True}
        self.new_tab_ok = new_tab_ok
        self.wait_ok = wait_ok
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.scripts: list[str] = []
        self.target = "tab-apply-1"

    def new_tab(self, url, background=True):
        self.opened.append(url)
        return self.target if self.new_tab_ok else None

    def wait_for_load(self, target_id, timeout=20.0):
        return self.wait_ok

    def close_tab(self, target_id):
        self.closed.append(target_id)
        return True

    def evaluate(self, target_id, script):
        self.scripts.append(script)
        if "offerpilot.apply.page" in script:
            value = self.page.next()
            if isinstance(value, str):
                value = {"stage": value}
            return json.dumps(value, ensure_ascii=False)
        if "offerpilot.apply.click" in script:
            return json.dumps(self.click, ensure_ascii=False)
        if "offerpilot.apply.fill" in script:
            return json.dumps(self.fill, ensure_ascii=False)
        if "offerpilot.apply.confirm" in script:
            return json.dumps(self.confirm, ensure_ascii=False)
        if "offerpilot.apply.sent" in script:
            return json.dumps(self.sent, ensure_ascii=False)
        raise AssertionError(f"unexpected script: {script[:80]}")

    def ran(self, sentinel):
        return any(sentinel in script for script in self.scripts)


def _run(platform_fn, browser, **kwargs):
    greeting = kwargs.pop("greeting", GREETING)
    params = dict(queue_status="approved", expected_greeting=GREETING, browser=browser,
                  config={"apply_step_wait_seconds": 0})
    params.update(kwargs)
    return platform_fn(JOB, greeting, **params)


class ValidationTests(unittest.TestCase):
    def test_pending_status_is_refused_before_opening_a_page(self):
        browser = _FakeBrowser()
        out = _run(apply_module.apply_zhilian, browser, queue_status="pending")
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "queue_not_approved")
        self.assertEqual(browser.opened, [])

    def test_ready_status_is_allowed(self):
        browser = _FakeBrowser()
        out = _run(apply_module.apply_zhilian, browser, queue_status="ready")
        self.assertEqual(out["status"], "sent")

    def test_empty_greeting_is_refused(self):
        browser = _FakeBrowser()
        out = _run(apply_module.apply_zhilian, browser, greeting="   ")
        self.assertEqual(out["error"], "empty_greeting")
        self.assertEqual(browser.opened, [])

    def test_greeting_must_match_confirmed_text(self):
        browser = _FakeBrowser()
        out = _run(apply_module.apply_zhilian, browser, expected_greeting="另一段文本")
        self.assertEqual(out["error"], "greeting_not_confirmed")
        self.assertEqual(browser.opened, [])

    def test_missing_job_id_is_refused(self):
        browser = _FakeBrowser()
        out = apply_module.apply_zhilian({}, GREETING, queue_status="approved",
                                         expected_greeting=GREETING, browser=browser,
                                         config={"apply_step_wait_seconds": 0})
        self.assertEqual(out["error"], "missing_job_id")
        self.assertEqual(browser.opened, [])

    def test_missing_url_is_refused(self):
        browser = _FakeBrowser()
        job = dict(JOB, url="")
        out = apply_module.apply_zhilian(job, GREETING, queue_status="approved",
                                         expected_greeting=GREETING, browser=browser,
                                         config={"apply_step_wait_seconds": 0})
        self.assertEqual(out["error"], "missing_job_url")

    def test_missing_browser_is_refused(self):
        out = apply_module.apply_zhilian(JOB, GREETING, queue_status="approved",
                                         expected_greeting=GREETING, browser=None,
                                         config={"apply_step_wait_seconds": 0})
        self.assertEqual(out["error"], "browser_unavailable")


class FlowTests(unittest.TestCase):
    def test_happy_path_sends_and_closes_the_tab(self):
        browser = _FakeBrowser()
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "sent")
        self.assertEqual(out["platform"], "zhilian")
        self.assertEqual(out["job_id"], "zhilian-1001")
        self.assertTrue(browser.ran("offerpilot.apply.click"))
        self.assertTrue(browser.ran("offerpilot.apply.fill"))
        self.assertTrue(browser.ran("offerpilot.apply.confirm"))
        self.assertEqual(browser.closed, [browser.target])

    def test_captcha_on_the_job_page_returns_immediately_without_clicking(self):
        browser = _FakeBrowser(page={"stage": "captcha"})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "captcha")
        self.assertFalse(browser.ran("offerpilot.apply.click"))
        self.assertEqual(browser.closed, [browser.target])

    def test_captcha_after_clicking_the_button_returns_captcha(self):
        browser = _FakeBrowser(page=[{"stage": "ready"}, {"stage": "captcha"}])
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "captcha")
        self.assertTrue(browser.ran("offerpilot.apply.click"))
        self.assertFalse(browser.ran("offerpilot.apply.fill"))

    def test_login_wall_returns_needs_login(self):
        browser = _FakeBrowser(page={"stage": "needs_login"})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "needs_login")
        self.assertFalse(browser.ran("offerpilot.apply.click"))

    def test_closed_job_is_failed_not_sent(self):
        browser = _FakeBrowser(page={"stage": "job_closed"})
        out = _run(apply_module.apply_51job, browser)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "job_unavailable")

    def test_unknown_button_returns_unknown(self):
        browser = _FakeBrowser(click={"found": False, "already": False})
        out = _run(apply_module.apply_liepin, browser)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["error"], "apply_button_not_found")

    def test_already_applied_is_failed_not_resent(self):
        browser = _FakeBrowser(click={"found": False, "already": True})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "already_applied")
        self.assertFalse(browser.ran("offerpilot.apply.fill"))

    def test_fill_mismatch_stops_before_confirming(self):
        browser = _FakeBrowser(fill={"filled": False, "stage": "fill_mismatch"})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["error"], "greeting_fill_mismatch")
        self.assertFalse(browser.ran("offerpilot.apply.confirm"))

    def test_no_dialog_site_reports_sent_from_result_markers(self):
        browser = _FakeBrowser(fill={"filled": False, "stage": "no_dialog"}, sent={"sent": True})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "sent")
        self.assertFalse(browser.ran("offerpilot.apply.confirm"))

    def test_missing_confirm_button_returns_unknown(self):
        browser = _FakeBrowser(confirm={"clicked": False})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["error"], "confirm_button_not_found")

    def test_rejected_send_is_failed(self):
        browser = _FakeBrowser(sent={"sent": False, "rejected": True})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "send_rejected")

    def test_unconfirmed_result_is_unknown(self):
        browser = _FakeBrowser(sent={"sent": False})
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "unknown")
        self.assertEqual(out["error"], "send_result_unconfirmed")

    def test_new_tab_failure_is_failed(self):
        browser = _FakeBrowser(new_tab_ok=False)
        out = _run(apply_module.apply_zhilian, browser)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(out["error"], "open_page_failed")
        self.assertEqual(browser.closed, [])

    def test_every_result_carries_status_platform_and_job_id(self):
        for fn in (apply_module.apply_zhilian, apply_module.apply_51job, apply_module.apply_liepin):
            with self.subTest(fn=fn.__name__):
                out = _run(fn, _FakeBrowser())
                self.assertIn(out["status"], apply_module.RESULT_STATUSES)
                self.assertEqual(out["platform"], fn.__name__.removeprefix("apply_"))
                self.assertEqual(out["job_id"], "zhilian-1001")


class PlatformVocabularyTests(unittest.TestCase):
    def test_button_vocabularies(self):
        self.assertIn("立即投递", apply_module.BUTTON_PATTERNS["zhilian"])
        self.assertIn("立即投递", apply_module.BUTTON_PATTERNS["51job"])
        self.assertIn("立即沟通", apply_module.BUTTON_PATTERNS["liepin"])

    def test_liepin_click_script_uses_its_own_vocabulary(self):
        script = apply_module.click_button_script(apply_module.BUTTON_PATTERNS["liepin"])
        self.assertIn("立即沟通", script)
        self.assertIn("offerpilot.apply.click", script)

    def test_fill_script_embeds_the_greeting_and_a_sentinel(self):
        script = apply_module.fill_greeting_script(GREETING)
        self.assertIn("offerpilot.apply.fill", script)
        self.assertIn(json.dumps(GREETING, ensure_ascii=False), script)

    def test_capabilities_keep_deliver_locked(self):
        from offerpilot.collection.capabilities import platform_supports

        # 智联、猎聘的投递已在真实账号上验证并开放；前程无忧没有站内聊天，仍锁定。
        self.assertTrue(platform_supports("zhilian", "deliver"))
        self.assertTrue(platform_supports("liepin", "deliver"))
        self.assertFalse(platform_supports("51job", "deliver"))


if __name__ == "__main__":
    unittest.main()
