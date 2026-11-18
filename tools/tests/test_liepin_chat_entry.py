#!/usr/bin/env python3
"""Liepin chat entry: the www search page and its 「我的沟通」 drawer.

The messages used to live behind ``c.liepin.com/``, which only showed the home
page.  The entry now opens ``https://www.liepin.com/zhaopin/`` (no query string)
and ``JS_LIEPIN_ENSURE_DRAWER_WWW`` reads the drawer there.  If the drawer is
already expanded it is read as is; only a collapsed drawer gets one click.

These tests never touch a browser or the network.  They parse a local HTML
fixture (``fixtures/liepin_drawer.html``) with a small Python DOM + selector
helper that *mirrors* the selectors in ``JS_LIEPIN_CHAT_LIST`` /
``JS_LIEPIN_THREAD`` / ``JS_LIEPIN_ENSURE_DRAWER_WWW``, then feed the parsed
rows through a fake monitor into the real runtime functions.

What this proves: the runtime wiring (URL, ensure-drawer step, row shape,
unread flags, message senders, read-only gate) and that the fixture matches the
selectors the JS uses.  What it cannot prove: that the *live* drawer DOM uses
the same class names, or that the JS runs as written inside a real page
(``getBoundingClientRect``-based visibility and left/right geometry are not
simulated here).  ``reply_allowed`` stays ``False`` until sending is verified
separately on a real page.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _path in (str(WEB_DIR),):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime  # noqa: E402

FIXTURE = FIXTURES / "liepin_drawer.html"
WWW_URL = "https://www.liepin.com/zhaopin/"

# The drawer is expanded by default: the root and the list are already rendered.
EXPANDED_PAGE = (
    "<html><body><header><a class='im-ui-basic-entry' href='#im-basic-contact'>我的沟通</a>"
    "</header><div id='im-basic-contact'><div class='im-ui-contacts-wrap'></div></div></body></html>"
)

JOBS = [
    {
        "id": "j-liepin-1",
        "company": "虚构猎聘科技有限公司",
        "title": "产品经理",
        "hr_name": "王示例",
    },
]

# Deliberately minimal: no drawer, no 我的沟通 entry.
EMPTY_PAGE = "<html><body><div class='im-ui-chat-content'></div></body></html>"
# The entry exists but the drawer has not been rendered yet (it opens on click).
ENTRY_ONLY_PAGE = (
    "<html><body><header>"
    "<a class='im-ui-basic-entry' href='#im-basic-contact'>我的沟通</a>"
    "</header><main></main></body></html>"
)


# ---------------------------------------------------------------------------
# A tiny read-only DOM: enough of querySelector to mirror the JS selectors.
# ---------------------------------------------------------------------------


class _Node:
    VOID = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent=None):
        self.tag = tag.lower()
        self.attrs = dict(attrs or {})
        self.parent = parent
        self.children: list[_Node] = []
        self.text_chunks: list[str] = []

    @property
    def classes(self) -> list[str]:
        return str(self.attrs.get("class") or "").split()

    def matches(self, selector: str) -> bool:
        selector = selector.strip()
        if not selector:
            return False
        if selector.startswith("#"):
            return self.attrs.get("id") == selector[1:]
        if selector.startswith("."):
            return selector[1:] in self.classes
        attr = re.fullmatch(r"\[class\*=(['\"]?)(.+?)\1\]", selector)
        if attr:
            return attr.group(2) in str(self.attrs.get("class") or "")
        return self.tag == selector.lower()

    def descendants(self):
        for child in self.children:
            yield child
            yield from child.descendants()

    def find_all(self, selector: str) -> list[_Node]:
        parts = [part.strip() for part in selector.split(",") if part.strip()]
        return [node for node in self.descendants() if any(node.matches(p) for p in parts)]

    def find(self, selector: str) -> "_Node | None":
        found = self.find_all(selector)
        return found[0] if found else None

    def text_content(self) -> str:
        chunks: list[str] = []
        if self.text_chunks:
            chunks.append("".join(self.text_chunks))
        for child in self.children:
            if child.tag in {"script", "style"}:
                continue
            sub = child.text_content()
            if sub.strip():
                chunks.append(sub)
        return "\n".join(chunk for chunk in chunks if chunk.strip())

    def inner_text(self) -> str:
        return self.text_content().strip()


class _DocumentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if node.tag not in _Node.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag.lower():
                del self.stack[depth:]
                return

    def handle_data(self, data):
        self.stack[-1].text_chunks.append(data)


def _parse(html: str) -> _Node:
    parser = _DocumentParser()
    parser.feed(html)
    parser.close()
    return parser.root


def _read_fixture() -> _Node:
    return _parse(FIXTURE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Python mirrors of the three Liepin scripts (see module docstring).
# ---------------------------------------------------------------------------


def _ensure_drawer(document: _Node) -> dict:
    """Mirror of JS_LIEPIN_ENSURE_DRAWER_WWW's first two branches.

    The third branch scans visible short-text nodes for 我的沟通/我的消息; that
    depends on layout geometry and is not simulated here.
    """
    if document.find("#im-basic-contact") is not None:
        return {"available": True, "opened": False}
    known = document.find(".im-ui-basic-entry")
    if known is not None:
        return {"available": True, "opened": True}
    return {"available": False, "reason": "未找到猎聘「我的沟通」入口"}


def _list_rows(document: _Node) -> dict:
    """Mirror of JS_LIEPIN_CHAT_LIST."""
    drawer = document.find("#im-basic-contact")
    if drawer is None:
        return {"available": False, "reason": "未找到猎聘聊天抽屉"}
    root = drawer.find(".im-ui-contacts-wrap") or drawer

    def pick(el: _Node, selectors: list[str]) -> str:
        for selector in selectors:
            node = el.find(selector)
            if node is not None and node.inner_text():
                return node.inner_text()
        return ""

    rows = []
    for el in root.find_all(".im-ui-contact-list-item"):
        parts = [line.strip() for line in el.inner_text().split("\n") if line.strip()]
        company = re.sub(r"^招聘方[·・]\s*", "", pick(el, [".im-ui-company-info", "[class*=company]"]))
        hr_name = pick(el, [".im-ui-title", "[class*=name]"]) or (parts[0] if parts else "")
        last = pick(el, [
            ".im-ui-last-message-super", ".im-ui-last-message-special",
            ".im-ui-content", "[class*=last-message]",
        ])
        rows.append({
            "company": company,
            "hr_name": hr_name,
            "hr_title": "",
            "last_message": last or (parts[-2] if len(parts) > 2 else ""),
            "last_message_at": pick(el, ["[class*=time]"]) or (parts[-1] if parts else ""),
            "has_unread": el.find(".im-ui-unread-count-badge, [class*=unread]") is not None,
            "has_reply": bool(last),
        })
    return {"available": True, "rows": rows}


def _open_thread(document: _Node, script: str) -> dict:
    """Mirror of JS_LIEPIN_OPEN_THREAD (after __HR_NAME__/__COMPANY__ fill-in)."""
    hr_match = re.search(r'const hr = (".*?");', script)
    company_match = re.search(r'const company = (".*?");', script)
    hr = json.loads(hr_match.group(1)) if hr_match else ""
    company = json.loads(company_match.group(1)) if company_match else ""

    items = document.find_all(".im-ui-contact-list-item")

    def text(el: _Node) -> str:
        return el.inner_text()

    target = next((el for el in items if hr and hr in text(el) and (not company or company in text(el))), None)
    if target is None:
        target = next((el for el in items if hr and hr in text(el)), None)
    if target is None:
        return {"available": False, "reason": "未找到该联系人"}
    return {"available": True}


def _thread_rows(document: _Node) -> dict:
    """Mirror of JS_LIEPIN_THREAD (without the geometry fallback)."""
    root = (
        document.find(".im-ui-chat-content")
        or document.find("#im-basic-contact")
        or document
    )
    rows = []
    for el in root.find_all(".im-ui-message-wrapper"):
        body = el.find(".im-ui-message-body") or el.find(".im-ui-txt-content")
        node = body or el
        text = (node.inner_text() or el.inner_text()).strip()
        cls = f"{el.attrs.get('class', '')} {node.attrs.get('class', '')}"
        sender = "me" if re.search(r"(^|[^a-z])(self|mine|is-me|message-me|right)([^a-z]|$)", cls, re.I) else "hr"
        if re.search(r"tip|notice|system", cls, re.I):
            sender = "system"
        if text:
            rows.append({"sender": sender, "text": text})
    return {"available": True, "rows": rows}


# ---------------------------------------------------------------------------
# Fake monitor / backend seams
# ---------------------------------------------------------------------------


class _FakeGuard:
    limit = 3

    def __init__(self) -> None:
        self.consecutive_page_failures = 0

    def record_page_failure(self) -> None:
        self.consecutive_page_failures += 1

    def record_page_success(self) -> None:
        self.consecutive_page_failures = 0


class _FakeLiepinMonitor:
    """Serves the parsed fixture rows for the exact scripts the runtime runs."""

    MonitorSafetyGuard = _FakeGuard

    def __init__(self, document: _Node):
        self.document = document
        self.urls: list[str] = []
        self.scripts: list[str] = []
        self.closed: list[str] = []
        self.entry_clicks = 0
        self.document_after_click: _Node | None = None

    def get_page_targets(self):
        # The test browser has no pre-existing tabs: never let the real
        # browser module leak a user tab into the reader.
        return []

    def _open_monitor_tab(self, url, config, *, background=True):
        self.urls.append(url)
        return "tab-liepin"

    def _wait_or_stop(self, config, seconds):
        return False

    def _wait_for_page_or_stop(self, target_id, config, timeout=10):
        return True

    def _inspect_monitor_page(self, target_id, config):
        return None

    def _monitor_safety_guard(self, config):
        return _FakeGuard()

    def stop_requested(self, config):
        return False

    def close_tab(self, target_id):
        self.closed.append(target_id)

    def evaluate(self, target_id, script):
        self.scripts.append(script)
        if script == offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW:
            result = _ensure_drawer(self.document)
            if result.get("opened"):
                self.entry_clicks += 1  # the collapsed drawer is opened by one click
                if self.document_after_click is not None:
                    self.document = self.document_after_click  # the click renders the drawer
            return json.dumps(result, ensure_ascii=False)
        if "const contacts = []" in script:
            # This fixture only models the DOM; the interface read reports
            # unavailable so the reader exercises its documented fallback.
            return json.dumps({"available": False, "reason": "接口不可用"}, ensure_ascii=False)
        if script == offerpilot_runtime.JS_LIEPIN_CHAT_LIST:
            return json.dumps(_list_rows(self.document), ensure_ascii=False)
        if script == offerpilot_runtime.JS_LIEPIN_THREAD:
            return json.dumps(_thread_rows(self.document), ensure_ascii=False)
        if 'const hr = ' in script and "target.click()" in script:
            return json.dumps(_open_thread(self.document, script), ensure_ascii=False)
        raise AssertionError(f"unexpected script: {script[:120]}")


class _LiepinFixtureCase(unittest.TestCase):
    document_html: str | None = None  # None -> read the fixture file

    def setUp(self) -> None:
        offerpilot_runtime._reset_conversation_cache()
        self.addCleanup(offerpilot_runtime._reset_conversation_cache)
        self._hr_temp = tempfile.TemporaryDirectory(prefix="hr-store-")
        self.addCleanup(self._hr_temp.cleanup)
        store_patch = patch.object(offerpilot_runtime, "_hr_store_root", Path(self._hr_temp.name))
        store_patch.start()
        self.addCleanup(store_patch.stop)
        document = _read_fixture() if self.document_html is None else _parse(self.document_html)
        self.fake = _FakeLiepinMonitor(document)
        self.server = MagicMock()
        self.server.CONFIG_PATH = Path("config.yaml")
        self.server.DATA_DIR = Path("data")
        self.config = {"monitor": {}, "throttle": {"send_windows": ["09:00-16:00"]}}
        for patcher in (
            patch.object(offerpilot_runtime, "load_backend", return_value=self.server),
            patch.object(offerpilot_runtime, "_monitor", return_value=self.fake),
            patch.object(offerpilot_runtime, "_runtime_config", return_value=self.config),
            patch.object(offerpilot_runtime, "_store_jobs", return_value=JOBS),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


class LiepinEntryTests(_LiepinFixtureCase):
    def test_chat_entry_is_the_www_job_page_not_c_liepin(self):
        url = offerpilot_runtime.PLATFORM_CHAT_URLS["liepin"]
        self.assertEqual(url, WWW_URL)
        self.assertNotIn("c.liepin.com", url)

    def test_entry_url_is_the_search_page_with_no_query_string(self):
        url = offerpilot_runtime.PLATFORM_CHAT_URLS["liepin"]
        self.assertEqual(url, "https://www.liepin.com/zhaopin/")
        self.assertNotIn("?", url)
        self.assertNotIn("&", url)
        self.assertNotIn("{{", url)  # no unfilled secret placeholder in the entry

    def test_www_drawer_script_exists_and_the_old_one_is_kept(self):
        self.assertTrue(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER)
        self.assertTrue(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW)
        self.assertNotEqual(
            offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER,
            offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW,
        )
        # The old script only knew the class entry; the www one also falls back
        # to a visible 我的沟通/我的消息 text node.
        self.assertIn("我的沟通", offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW)
        self.assertNotIn("我的沟通", offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER)

    def test_listing_opens_the_www_page_and_runs_the_www_drawer_script(self):
        listing = offerpilot_runtime.list_liepin_conversations()
        self.assertTrue(listing["ok"])
        self.assertTrue(listing["available"])
        self.assertEqual(listing["platform"], "liepin")
        # One list page, plus a body read only for the unread conversation
        # (the incremental refresh); the other one is left for the user to open.
        self.assertEqual(self.fake.urls[0], WWW_URL)
        self.assertEqual(set(self.fake.urls), {WWW_URL})
        unread = sum(1 for row in listing["conversations"] if row["unread"])
        self.assertEqual(unread, 1)
        self.assertEqual(len(self.fake.urls), 1 + unread)
        self.assertIn(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW, self.fake.scripts)
        self.assertNotIn(offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER, self.fake.scripts)
        self.assertEqual(self.fake.closed, ["tab-liepin"] * (1 + unread))

    def test_list_liepin_conversations_is_the_same_reader_as_the_generic_one(self):
        named = offerpilot_runtime.list_liepin_conversations()
        self.assertEqual(named["count"], 2)
        self.assertTrue(named["conversations"])
        self.assertTrue(all(row["platform"] == "liepin" for row in named["conversations"]))


class DrawerParsingTests(_LiepinFixtureCase):
    def _listing(self):
        return offerpilot_runtime.list_liepin_conversations()

    def test_lists_both_conversations_with_company_hr_message_and_time(self):
        listing = self._listing()
        self.assertEqual(listing["count"], 2)
        first, second = listing["conversations"]
        self.assertEqual(first["company"], "虚构猎聘科技有限公司")
        self.assertEqual(first["hr_name"], "王示例")
        self.assertEqual(first["last_message"], "您好，方便发一份简历吗")
        self.assertEqual(first["last_message_at"], "11-16 10:20")
        self.assertEqual(second["company"], "示例数据服务有限公司")
        self.assertEqual(second["hr_name"], "李示例")
        self.assertEqual(second["last_message"], "期待您的回复")
        for row in (first, second):
            self.assertRegex(row["id"], r"^[0-9a-f]{32}$")
            self.assertEqual(row["platform"], "liepin")

    def test_unread_badge_marks_only_that_conversation(self):
        first, second = self._listing()["conversations"]
        self.assertTrue(first["unread"])
        self.assertFalse(second["unread"])

    def test_rows_match_the_job_pool_by_company_and_hr(self):
        first, second = self._listing()["conversations"]
        self.assertEqual(first["job_id"], "j-liepin-1")
        self.assertEqual(first["title"], "产品经理")
        self.assertIsNone(second["job_id"])
        self.assertEqual(second["title"], "")

    def test_drawer_is_opened_through_the_entry_when_not_yet_rendered(self):
        document = _parse(ENTRY_ONLY_PAGE)
        self.assertEqual(_ensure_drawer(document), {"available": True, "opened": True})
        # The drawer itself is still absent, so the list honestly says so.
        payload = _list_rows(document)
        self.assertFalse(payload["available"])
        self.assertIn("未找到猎聘聊天抽屉", payload["reason"])

    def test_entry_click_prefers_the_known_class_over_the_text_scan(self):
        script = offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW
        self.assertIn(".im-ui-basic-entry", script)
        self.assertIn("我的沟通", script)
        self.assertIn("我的消息", script)


class DrawerStateTests(_LiepinFixtureCase):
    """The drawer may be expanded by default or collapsed behind the entry."""

    def test_expanded_drawer_is_read_without_clicking_again(self):
        # Fixture: the drawer root is already rendered next to the entry.
        listing = offerpilot_runtime.list_liepin_conversations()
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["count"], 2)
        self.assertEqual(self.fake.entry_clicks, 0)
        self.assertEqual(
            _ensure_drawer(_read_fixture()),
            {"available": True, "opened": False},
        )

    def test_collapsed_drawer_is_opened_by_exactly_one_entry_click(self):
        # Collapsed: only the entry exists.  The fake models the click by
        # rendering the drawer, so the list reads it on the same page.
        self.fake.document = _parse(ENTRY_ONLY_PAGE)
        self.fake.document_after_click = _read_fixture()
        listing = offerpilot_runtime.list_liepin_conversations()
        self.assertEqual(self.fake.entry_clicks, 1)  # the refresh's page opens never click again
        self.assertTrue(listing["ok"])
        self.assertEqual(listing["count"], 2)
        self.assertEqual(self.fake.urls[0], WWW_URL)
        self.assertEqual(set(self.fake.urls), {WWW_URL})

    def test_expanded_page_script_returns_without_clicking(self):
        document = _parse(EXPANDED_PAGE)
        self.assertEqual(_ensure_drawer(document), {"available": True, "opened": False})

    def test_reply_stays_disallowed_in_both_drawer_states(self):
        for name, document in (
            ("expanded", _read_fixture()),
            ("collapsed", _parse(ENTRY_ONLY_PAGE)),
        ):
            with self.subTest(state=name):
                self.fake.document = document
                listing = offerpilot_runtime.list_liepin_conversations()
                if listing["conversations"]:
                    row = listing["conversations"][0]
                    thread = offerpilot_runtime.get_thread(row["id"], "liepin")
                    self.assertFalse(thread["reply_allowed"])
                else:
                    self.assertFalse(listing["ok"])


class ThreadReadingTests(_LiepinFixtureCase):
    def _first_thread(self):
        listing = offerpilot_runtime.list_liepin_conversations()
        row = listing["conversations"][0]
        return row, offerpilot_runtime.get_thread(row["id"], "liepin")

    def test_reads_the_three_messages_with_senders(self):
        row, thread = self._first_thread()
        self.assertTrue(thread["ok"])
        self.assertTrue(thread["available"])
        self.assertEqual(thread["platform"], "liepin")
        self.assertEqual(thread["conversation_id"], row["id"])
        self.assertEqual(thread["company"], "虚构猎聘科技有限公司")
        self.assertEqual(
            [message["sender"] for message in thread["messages"]],
            ["hr", "me", "system"],
        )
        self.assertEqual(
            [message["text"] for message in thread["messages"]],
            ["您好，方便发一份简历吗", "您好，我整理好简历后发您。", "对方已查看您的简历"],
        )

    def test_thread_opens_the_drawer_conversation_by_hr_name(self):
        row, thread = self._first_thread()
        open_scripts = [s for s in self.fake.scripts if "const hr = " in s]
        # The listing refresh opened each listed conversation once by its HR
        # name; serving the thread afterwards adds no further open.
        matching = [
            script for script in open_scripts
            if json.dumps(row["hr_name"], ensure_ascii=False) in script
            and json.dumps(row["company"], ensure_ascii=False) in script
        ]
        self.assertEqual(len(matching), 1)
        self.assertIn(json.dumps("王示例", ensure_ascii=False), matching[0])
        self.assertIn(json.dumps("虚构猎聘科技有限公司", ensure_ascii=False), matching[0])
        self.assertIn(offerpilot_runtime.JS_LIEPIN_THREAD, self.fake.scripts)
        self.assertTrue(thread["messages"])

    def test_thread_stays_read_only_for_liepin(self):
        _, thread = self._first_thread()
        self.assertFalse(thread["reply_allowed"])
        self.assertIn("只读", thread["reply_block_reason"])

    def test_missing_contact_is_reported_not_sent_anywhere(self):
        listing = offerpilot_runtime.list_liepin_conversations()
        # Ask to open a conversation whose HR is not in the drawer.
        entry = dict(listing["conversations"][0], hr_name="不存在的招聘官", company="")
        with self.assertRaises(offerpilot_runtime.OfferPilotUnavailable) as ctx:
            offerpilot_runtime._get_platform_thread(entry, "liepin")
        self.assertIn("未找到该联系人", str(ctx.exception))
        # Only the read-only entry/thread scripts ran; nothing typed or sent.
        self.assertFalse(any("typeof" in s or ".value =" in s for s in self.fake.scripts))


class UnavailableDrawerTests(_LiepinFixtureCase):
    document_html = EMPTY_PAGE

    def test_missing_drawer_and_missing_entry_reports_unavailable(self):
        listing = offerpilot_runtime.list_liepin_conversations()
        self.assertFalse(listing["ok"])
        self.assertFalse(listing["available"])
        self.assertEqual(listing["conversations"], [])
        self.assertEqual(listing["count"], 0)
        self.assertIn("我的沟通", listing["error"])
        self.assertEqual(self.fake.closed, ["tab-liepin"])


class FixtureContractTests(unittest.TestCase):
    """Guards so the fixture and the JS selectors cannot drift apart silently."""

    @classmethod
    def setUpClass(cls):
        cls.html = FIXTURE.read_text(encoding="utf-8")

    def test_fixture_contains_every_selector_the_chat_list_script_reads(self):
        selectors = [
            "im-basic-contact", "im-ui-contacts-wrap", "im-ui-contact-list-item",
            "im-ui-company-info", "im-ui-title", "im-ui-last-message-super",
            "im-ui-unread-count-badge",
        ]
        js = offerpilot_runtime.JS_LIEPIN_CHAT_LIST + offerpilot_runtime.JS_LIEPIN_ENSURE_DRAWER_WWW
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertIn(selector, js)
                self.assertIn(selector, self.html)
        # The time column is read with a class-substring selector.
        self.assertIn("[class*=time]", js)
        self.assertIn("im-ui-time", self.html)

    def test_fixture_contains_every_selector_the_thread_script_reads(self):
        for selector in ("im-ui-chat-content", "im-ui-message-wrapper",
                         "im-ui-message-body", "im-ui-txt-content"):
            with self.subTest(selector=selector):
                self.assertIn(selector, offerpilot_runtime.JS_LIEPIN_THREAD)
                self.assertIn(selector, self.html)

    def test_fixture_carries_no_contact_details(self):
        for pattern in (
            re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
            re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
            re.compile(r"微信|wechat|weixin", re.IGNORECASE),
        ):
            with self.subTest(pattern=pattern.pattern):
                self.assertIsNone(pattern.search(self.html))

    def test_fixture_people_and_companies_are_obviously_fictional(self):
        for marker in ("虚构", "示例"):
            self.assertIn(marker, self.html)


if __name__ == "__main__":
    unittest.main()
