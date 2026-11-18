#!/usr/bin/env python3
"""HR 回复与采集运行时：发送安全、会话定位、本地回显与后台任务收尾。

覆盖本轮 11 项修复：

1. 发送前只允许「姓名+公司」精确定位，公司级兜底与同名多行都拒绝；
2. 同一列表里 id 冲突的行改用平台会话主键（或行号）并标记 ``ambiguous``；
3. 发送成功后先写一条 ``local`` 回显，平台回读后 10 分钟内去重；
4. 后台任务 running/stopping 期间禁止发送；
5. 后台列表刷新不再从 DOM 读正文；
6. 聚合刷新按平台合并，缺失的平台保留原记录；
7. 正文合并/失败标记只覆盖正文相关字段，元数据取锁内当前记录；
8. 智联、51job 采集开标签页不再切到前台；
9. 每日发送上限按本地自然日统计；
10. 后台任务只保留最近 20 个已结束任务，停止超时 90 秒释放准入；
11. 前端 HR 轮询只读本地，平台同步至少间隔 5 分钟。

全部使用虚构数据、内存假对象与临时目录；不联网、不读写 ``web/data``。
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import offerpilot_runtime as runtime  # noqa: E402
from offerpilot.web import tasks as tasks_module  # noqa: E402

APP_JS = WEB_DIR / "static" / "app.js"
MONITOR_PY = VENDOR_SRC / "offerpilot" / "executor" / "monitor.py"
SENDER_PY = VENDOR_SRC / "offerpilot" / "executor" / "sender.py"
ZHILIAN_PY = VENDOR_SRC / "offerpilot" / "collection" / "platforms" / "zhilian.py"
JOB51_PY = VENDOR_SRC / "offerpilot" / "collection" / "platforms" / "job51.py"

COMPANY = "虚构星河科技有限公司"
HR_NAME = "示例招聘官"
HR_TITLE = "招聘HR"


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start)]


def _boss_row(group_id: str, **extra: object) -> dict:
    row = {
        "company": COMPANY,
        "hr_name": HR_NAME,
        "hr_title": HR_TITLE,
        "last_message": "你好",
        "last_message_at": "11-18 09:00",
        "has_unread": False,
        "last_direction": "hr",
        "has_reply": True,
        "_boss_params": {"boss_id": "b-" + group_id, "group_id": group_id, "security_id": "s"},
    }
    row.update(extra)
    return row


class _EmptyJobs:
    def __enter__(self) -> None:
        self._patch = patch.object(runtime, "_store_jobs", return_value=[])
        self._patch.start()

    def __exit__(self, *exc: object) -> None:
        self._patch.stop()


# ---------------------------------------------------------------------------
# 1–2. 会话定位与会话 id 冲突
# ---------------------------------------------------------------------------


class ConversationIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(runtime._reset_conversation_cache)
        runtime._reset_conversation_cache()
        runtime._boss_history_params.clear()
        self.empty_jobs = _EmptyJobs()
        self.empty_jobs.__enter__()
        self.addCleanup(self.empty_jobs.__exit__, None, None, None)

    def test_monitor_only_allows_company_fallback_when_asked(self) -> None:
        source = MONITOR_PY.read_text(encoding="utf-8")
        self.assertIn("allow_company_only: bool = True", source)
        self.assertIn("exactMatches.length >= 2 && !allowCompanyOnly", source)
        self.assertIn("allowCompanyOnly ? companyOnlyMatch : null", source)
        self.assertIn("error: 'ambiguous'", source)

    def test_send_reply_disables_the_company_only_fallback(self) -> None:
        source = (WEB_DIR / "offerpilot_runtime.py").read_text(encoding="utf-8")
        block = source[source.index("def send_reply("):]
        self.assertIn("allow_company_only=False", block)
        self.assertIn("该会话缺少 HR 姓名，无法安全定位，请到平台发送", block)
        self.assertIn("同一公司有同名 HR，无法安全定位，请到平台发送", block)

    def test_platform_keys_are_read_from_each_listing(self) -> None:
        self.assertEqual(
            runtime._platform_conversation_key({"_boss_params": {"group_id": "g1"}}, "boss"), "g1"
        )
        self.assertEqual(
            runtime._platform_conversation_key({"_zhilian_params": {"peer_id": "p1"}}, "zhilian"), "p1"
        )
        self.assertEqual(
            runtime._platform_conversation_key(
                {"_liepin_params": {"opposite_im_id": "i1"}}, "liepin"
            ),
            "i1",
        )
        self.assertEqual(runtime._platform_conversation_key({}, "boss"), "")

    def test_colliding_rows_get_distinct_ids_and_ambiguous_flag(self) -> None:
        original = runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE, "boss")
        rows = [_boss_row("g1"), _boss_row("g2"), _boss_row("g3", hr_name="另一位招聘官")]
        items = runtime._boss_conversation_items(rows, with_params=True)

        self.assertEqual(items[2]["id"], runtime._conversation_id(COMPANY, "另一位招聘官", HR_TITLE, "boss"))
        self.assertNotIn("ambiguous", items[2])

        first, second = items[0], items[1]
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["id"], original)
        self.assertNotEqual(second["id"], original)
        self.assertTrue(first["ambiguous"])
        self.assertTrue(second["ambiguous"])
        self.assertEqual(first["id"], runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE + "\x1fg1", "boss"))
        self.assertEqual(second["id"], runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE + "\x1fg2", "boss"))
        # 历史读取参数要挂在最终 id 上，不能还留在旧 id。
        self.assertEqual(runtime._boss_history_params[first["id"]]["group_id"], "g1")
        self.assertEqual(runtime._boss_history_params[second["id"]]["group_id"], "g2")
        self.assertNotIn(original, runtime._boss_history_params)

    def test_dom_rows_without_keys_fall_back_to_row_index(self) -> None:
        rows = [
            {"company": COMPANY, "hr_name": HR_NAME, "hr_title": HR_TITLE},
            {"company": COMPANY, "hr_name": HR_NAME, "hr_title": HR_TITLE},
        ]
        items = runtime._conversation_items("zhilian", rows)
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0]["id"], items[1]["id"])
        self.assertTrue(all(item.get("ambiguous") for item in items))
        self.assertEqual(items[0]["id"], runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE + "\x1f0", "zhilian"))
        self.assertEqual(items[1]["id"], runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE + "\x1f1", "zhilian"))

    def test_ambiguous_entry_is_cached_and_refused_by_send(self) -> None:
        rows = [_boss_row("g1"), _boss_row("g2")]
        items = runtime._boss_conversation_items(rows, with_params=True)
        runtime._remember_conversations(items, "boss")
        entry = runtime._cached_conversation(items[0]["id"])
        self.assertTrue(entry["ambiguous"])
        self.assertEqual(entry["hr_name"], HR_NAME)

        monitor = _SendMonitor()
        with _send_env(_StatusServer({}), monitor):
            with self.assertRaises(ValueError) as ctx:
                _send(items[0]["id"])
        self.assertIn("同一公司有同名 HR", str(ctx.exception))
        self.assertEqual(monitor.opened, [])


# ---------------------------------------------------------------------------
# 3. 本地回显与去重
# ---------------------------------------------------------------------------


class _SendMonitor:
    def __init__(self, send_result: bool = True) -> None:
        self.send_result = send_result
        self.opened: list[dict] = []
        self.sent: list[tuple[str, str]] = []
        self.closed: list[str] = []

    def _open_conversation_from_chat_list(
        self, job, config, *, background=True, allow_company_only=True,
    ):
        self.opened.append({
            "job": dict(job),
            "background": background,
            "allow_company_only": allow_company_only,
        })
        return "tab-thread"

    def _send_message_in_chat(self, target_id, message, config=None):
        self.sent.append((target_id, message))
        return self.send_result

    def close_tab(self, target_id):
        self.closed.append(target_id)


class _TaskRunner:
    def __init__(self, status):
        self._status = status

    def status(self):
        if isinstance(self._status, Exception):
            raise self._status
        return self._status


class _StatusServer:
    def __init__(self, status):
        self.task_runner = _TaskRunner(status)


class _send_env:
    """Patch the runtime's browser/server seams for one send."""

    def __init__(self, server, monitor):
        self.server = server
        self.monitor = monitor
        self._patchers = []

    def __enter__(self):
        for patcher in (
            patch.object(runtime, "load_backend", return_value=self.server),
            patch.object(runtime, "_runtime_config", return_value={}),
            patch.object(runtime, "_stop_requested", return_value=False),
            patch.object(runtime, "_risk_lock_reason", return_value=None),
            patch.object(runtime, "_monitor", return_value=self.monitor),
        ):
            patcher.start()
            self._patchers.append(patcher)
        return self

    def __exit__(self, *exc):
        for patcher in self._patchers:
            patcher.stop()


def _send(conversation_id: str, text: str = "您好，方便沟通") -> dict:
    return runtime.send_reply(
        conversation_id,
        text,
        confirm=runtime.REPLY_CONFIRM_PHRASE,
        risk_acknowledged=True,
    )


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)
        self.temp = tempfile.TemporaryDirectory(prefix="hr-send-safety-")
        self.addCleanup(self.temp.cleanup)
        self.store_root = Path(self.temp.name)
        patcher = patch.object(runtime, "_hr_store_root", self.store_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self) -> dict:
        return json.loads(
            (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")
        )["conversations"]

    def seed_cache(self) -> dict:
        item = {
            "id": runtime._conversation_id(COMPANY, HR_NAME, HR_TITLE, "boss"),
            "platform": "boss",
            "company": COMPANY,
            "title": "产品经理",
            "hr_name": HR_NAME,
            "hr_title": HR_TITLE,
            "last_message": "你好",
            "last_message_at": "11-18 09:00",
            "last_direction": "hr",
        }
        runtime._remember_conversations([item], "boss")
        return item


class LocalEchoTests(_StoreCase):
    def test_successful_send_appends_a_local_message(self) -> None:
        item = self.seed_cache()
        monitor = _SendMonitor()
        with _send_env(_StatusServer({}), monitor):
            result = _send(item["id"])

        self.assertTrue(result["ok"])
        self.assertEqual(monitor.opened[0]["allow_company_only"], False)
        self.assertIs(monitor.opened[0]["background"], True)
        self.assertEqual(monitor.sent, [("tab-thread", "您好，方便沟通")])
        self.assertEqual(monitor.closed, ["tab-thread"])

        message = result["message"]
        self.assertEqual(message["sender"], "me")
        self.assertEqual(message["text"], "您好，方便沟通")
        self.assertTrue(message["local"])

        record = self.store()["boss:" + item["id"]]
        self.assertEqual(record["messages"][-1], message)
        self.assertEqual(record["last_message"], "您好，方便沟通")
        self.assertEqual(record["last_message_at"], message["time"])
        self.assertEqual(record["last_direction"], "me")

        cached = runtime._cached_conversation(item["id"])
        self.assertEqual(cached["last_direction"], "me")
        self.assertEqual(cached["last_message"], "您好，方便沟通")

    def test_local_echo_keeps_existing_messages_and_other_fields(self) -> None:
        item = self.seed_cache()
        key = "boss:" + item["id"]
        record = runtime._hr_store_record(
            {**item, "signature": "sig-1"},
            messages=[{"sender": "hr", "text": "你好", "time": "11-18 09:00"}],
            signature="sig-1",
            fetched_at="2026-11-18T01:00:00+00:00",
            body_read=True,
        )
        runtime._save_hr_store({key: record})

        with _send_env(_StatusServer({}), _SendMonitor()):
            _send(item["id"])

        stored = self.store()[key]
        self.assertEqual(len(stored["messages"]), 2)
        self.assertEqual(stored["messages"][0]["text"], "你好")
        self.assertTrue(stored["messages"][1]["local"])
        self.assertEqual(stored["signature"], "sig-1")
        self.assertEqual(stored["fetched_at"], "2026-11-18T01:00:00+00:00")
        self.assertTrue(stored["body_read"])

    def test_merge_drops_the_local_echo_when_the_platform_echoes_it(self) -> None:
        local = {"sender": "me", "text": "您好", "time": "11-18 10:00", "local": True}
        same_minute = runtime._hr_merge_messages(
            [local], [{"sender": "me", "text": "您好", "time": "11-18 10:00"}],
        )
        self.assertEqual(same_minute, [{"sender": "me", "text": "您好", "time": "11-18 10:00"}])

        within_ten = runtime._hr_merge_messages(
            [local], [{"sender": "me", "text": "您好", "time": "11-18 10:07"}],
        )
        self.assertEqual([m.get("local") for m in within_ten], [None])

        far_apart = runtime._hr_merge_messages(
            [local], [{"sender": "me", "text": "您好", "time": "11-18 12:30"}],
        )
        self.assertEqual(len(far_apart), 2, "超出 10 分钟不当作同一条，避免误删")

    def test_timestampless_page_reads_still_drop_a_recent_echo(self) -> None:
        local = {
            "sender": "me",
            "text": "您好",
            "time": datetime.datetime.now().strftime("%m-%d %H:%M"),
            "local": True,
        }
        merged = runtime._hr_merge_messages(
            [local], [{"sender": "me", "text": "您好", "time": ""}],
        )
        self.assertEqual(len(merged), 1)
        self.assertNotIn("local", merged[0])
        self.assertEqual(merged[0]["sender"], "me")

    def test_different_text_is_never_treated_as_the_echo(self) -> None:
        local = {"sender": "me", "text": "您好", "time": "11-18 10:00", "local": True}
        merged = runtime._hr_merge_messages(
            [local], [{"sender": "me", "text": "您好，请问", "time": "11-18 10:01"}],
        )
        self.assertEqual(len(merged), 2)

    def test_local_flag_survives_storage_and_thread_reads(self) -> None:
        stored = runtime._hr_stored_message({"sender": "me", "text": "您好", "time": "", "local": True})
        self.assertTrue(stored["local"])
        messages = runtime._stored_thread_messages(
            {"messages": [{"sender": "me", "text": "您好", "time": "", "local": True}]}, "boss",
        )
        self.assertTrue(messages[0]["local"])

    def test_message_time_parses_platform_and_local_labels(self) -> None:
        self.assertEqual(
            runtime._hr_message_datetime("11-18 10:00").strftime("%m-%d %H:%M"), "11-18 10:00"
        )
        self.assertIsNotNone(runtime._hr_message_datetime("2026-11-18T10:00:00+08:00"))
        self.assertIsNotNone(runtime._hr_message_datetime("2026-11-18 10:00:00"))
        self.assertIsNotNone(runtime._hr_message_datetime("1763424000000"))
        self.assertIsNone(runtime._hr_message_datetime(""))


# ---------------------------------------------------------------------------
# 4. 后台任务运行中不发送
# ---------------------------------------------------------------------------


class RunningTaskGuardTests(_StoreCase):
    def _assert_refused(self, status, monitor) -> None:
        with _send_env(_StatusServer(status), monitor):
            with self.assertRaises(ValueError) as ctx:
                _send(self.seed_cache()["id"])
        self.assertIn("后台任务运行中，结束后再发送回复", str(ctx.exception))
        self.assertEqual(monitor.opened, [])
        self.assertEqual(monitor.sent, [])

    def test_running_task_blocks_send(self) -> None:
        self._assert_refused({"active": None, "tasks": [{"status": "running"}]}, _SendMonitor())

    def test_stopping_task_blocks_send(self) -> None:
        self._assert_refused(
            {"active": {"status": "stopping"}, "tasks": [{"status": "stopping"}]}, _SendMonitor()
        )

    def test_finished_tasks_do_not_block_send(self) -> None:
        item = self.seed_cache()
        monitor = _SendMonitor()
        with _send_env(
            _StatusServer({"active": None, "tasks": [{"status": "completed"}, {"status": "failed"}]}),
            monitor,
        ):
            result = _send(item["id"])
        self.assertTrue(result["ok"])
        self.assertEqual(len(monitor.sent), 1)

    def test_unreadable_status_does_not_block_send(self) -> None:
        self.assertFalse(runtime._background_task_running(_StatusServer(RuntimeError("boom"))))
        self.assertFalse(runtime._background_task_running(_StatusServer(MagicMock())))
        self.assertTrue(runtime._background_task_running(_StatusServer({"active": {"id": "x"}})))


class MissingHrNameTests(_StoreCase):
    def test_missing_hr_name_is_refused_before_opening_a_page(self) -> None:
        item = self.seed_cache()
        cached = runtime._cached_conversation(item["id"])
        cached["hr_name"] = ""
        monitor = _SendMonitor()
        with _send_env(_StatusServer({}), monitor):
            with self.assertRaises(ValueError) as ctx:
                _send(item["id"])
        self.assertIn("该会话缺少 HR 姓名", str(ctx.exception))
        self.assertEqual(monitor.opened, [])


# ---------------------------------------------------------------------------
# 5–7. 后台刷新、聚合缓存与正文元数据
# ---------------------------------------------------------------------------


class BackgroundRefreshTests(unittest.TestCase):
    def test_dom_listing_refresh_never_allows_body_reads(self) -> None:
        source = (WEB_DIR / "offerpilot_runtime.py").read_text(encoding="utf-8")
        block = _between(source, "def _refresh_platform_store(", "def _merge_live_thread(")
        self.assertIn("allow_dom = False", block)
        self.assertNotIn("allow_dom = True", block)


class AggregateCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        runtime._reset_conversation_cache()
        self.addCleanup(runtime._reset_conversation_cache)

    def test_aggregate_refresh_keeps_platforms_missing_from_it(self) -> None:
        boss_item = {"id": "a" * 32, "platform": "boss", "company": COMPANY, "hr_name": HR_NAME}
        zhilian_item = {"id": "z" * 32, "platform": "zhilian", "company": "虚构智联", "hr_name": "乙"}
        runtime._remember_conversations([boss_item, zhilian_item])
        zhilian_listed_at = runtime._conversation_listed_at_by_platform["zhilian"]

        new_boss = {"id": "b" * 32, "platform": "boss", "company": COMPANY, "hr_name": HR_NAME}
        runtime._remember_conversations([new_boss])

        self.assertIn("b" * 32, runtime._conversation_cache)
        self.assertIn("z" * 32, runtime._conversation_cache)
        self.assertNotIn("a" * 32, runtime._conversation_cache, "本次读到的平台整体替换")
        self.assertEqual(runtime._conversation_listed_at_by_platform["zhilian"], zhilian_listed_at)
        self.assertIsNotNone(runtime._conversation_listed_at_by_platform["boss"])

    def test_aggregate_refresh_with_only_one_platform_leaves_others_alone(self) -> None:
        boss_item = {"id": "c" * 32, "platform": "boss", "company": COMPANY, "hr_name": HR_NAME}
        zhilian_item = {"id": "y" * 32, "platform": "zhilian", "company": "虚构智联", "hr_name": "乙"}
        runtime._remember_conversations([boss_item, zhilian_item])
        runtime._remember_conversations([boss_item])
        self.assertEqual(runtime._conversation_cache["y" * 32]["platform"], "zhilian")


class BodyMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="hr-body-meta-")
        self.addCleanup(self.temp.cleanup)
        self.store_root = Path(self.temp.name)
        patcher = patch.object(runtime, "_hr_store_root", self.store_root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self) -> dict:
        return json.loads(
            (self.store_root / "hr" / "conversations.json").read_text(encoding="utf-8")
        )["conversations"]

    def _seed(self) -> str:
        key = "boss:" + "d" * 32
        record = runtime._hr_store_record(
            {
                "platform": "boss",
                "id": "d" * 32,
                "company": COMPANY,
                "hr_name": HR_NAME,
                "hr_title": HR_TITLE,
                "last_message": "列表里的最新一条",
                "last_message_at": "11-18 12:00",
                "last_direction": "hr",
                "unread": True,
                "unread_count": 2,
            },
            messages=[{"sender": "hr", "text": "旧正文", "time": "11-18 11:00"}],
            signature="sig-current",
            fetched_at="2026-11-18T03:00:00+00:00",
            body_read=True,
            source="api",
        )
        runtime._save_hr_store({key: record})
        return key

    def test_live_read_keeps_the_current_listing_metadata(self) -> None:
        key = self._seed()
        stale_entry = {
            "id": "d" * 32,
            "platform": "boss",
            "company": COMPANY,
            "hr_name": HR_NAME,
            "hr_title": HR_TITLE,
            "last_message": "调用方开始时看到的旧列表",
            "last_message_at": "11-18 09:00",
            "last_direction": "me",
            "unread": False,
            "unread_count": 0,
        }
        runtime._merge_live_thread(
            stale_entry,
            "boss",
            [{"sender": "hr", "text": "新正文", "time": "11-18 12:00"}],
            "sig-live",
        )
        record = self.store()[key]
        self.assertEqual(record["last_message"], "列表里的最新一条")
        self.assertEqual(record["last_message_at"], "11-18 12:00")
        self.assertEqual(record["last_direction"], "hr")
        self.assertTrue(record["unread"])
        self.assertEqual(record["unread_count"], 2)
        self.assertEqual(record["signature"], "sig-current")
        self.assertEqual(record["body_signature"], "sig-live")
        self.assertFalse(record["stale"])
        self.assertIsNone(record["error"])
        self.assertEqual([m["text"] for m in record["messages"]], ["旧正文", "新正文"])

    def test_failed_read_keeps_the_current_listing_metadata(self) -> None:
        key = self._seed()
        stale_entry = {
            "id": "d" * 32,
            "platform": "boss",
            "company": COMPANY,
            "hr_name": HR_NAME,
            "hr_title": HR_TITLE,
            "last_message": "调用方开始时看到的旧列表",
            "last_message_at": "11-18 09:00",
            "last_direction": "me",
        }
        response = runtime._stale_or_error(stale_entry, "boss", "读取失败")
        record = self.store()[key]
        self.assertEqual(record["last_message"], "列表里的最新一条")
        self.assertEqual(record["last_direction"], "hr")
        self.assertTrue(record["stale"])
        self.assertIn("读取失败", record["error"])
        self.assertEqual(record["messages"][0]["text"], "旧正文")
        self.assertTrue(response["stale"])


# ---------------------------------------------------------------------------
# 8–9. 采集不抢焦点、每日上限按本地日
# ---------------------------------------------------------------------------


class CollectionAndQuotaTests(unittest.TestCase):
    def test_collection_host_tabs_stay_in_the_background(self) -> None:
        for path in (ZHILIAN_PY, JOB51_PY):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertIn("self.browser.new_tab(tmp_url, background=True)", source)
                self.assertNotIn("self.browser.new_tab(tmp_url, background=False)", source)

    def test_daily_limit_counts_local_calendar_days(self) -> None:
        source = SENDER_PY.read_text(encoding="utf-8")
        self.assertIn("datetime(created_at,'localtime') >= datetime('now','localtime','start of day')", source)
        self.assertNotIn("date(created_at)=date('now')", source)


# ---------------------------------------------------------------------------
# 10. 后台任务保留与停止超时
# ---------------------------------------------------------------------------


class _BlockingExecutor:
    def __init__(self) -> None:
        self.release = threading.Event()

    def __call__(self, task, config) -> None:
        self.release.wait(10)


class TaskRunnerRetentionTests(unittest.TestCase):
    def test_only_the_latest_twenty_finished_tasks_are_kept(self) -> None:
        runner = tasks_module.WorkbenchTaskRunner({"monitor": lambda task, config: None})
        ids = []
        for _ in range(25):
            task = runner.start("monitor", {})
            ids.append(task["id"])
            runner._threads[task["id"]].join(5)
        status = runner.status()
        self.assertEqual(len(status["tasks"]), tasks_module.TASKS_KEPT)
        self.assertEqual(
            [task["id"] for task in status["tasks"]], ids[-tasks_module.TASKS_KEPT:],
        )
        self.assertEqual(runner._threads, {})

    def test_running_task_is_never_pruned(self) -> None:
        executor = _BlockingExecutor()
        runner = tasks_module.WorkbenchTaskRunner({"monitor": executor})
        try:
            active = runner.start("monitor", {})
            # 直接塞入已结束任务，模拟长时间运行期间积累的历史。
            for index in range(25):
                finished = tasks_module.WorkbenchTask(
                    id=f"finished-{index}", mode="monitor", label="单独监测",
                    status="completed",
                )
                runner._tasks[finished.id] = finished
            runner.status()
            self.assertIn(active["id"], runner._tasks)
            self.assertEqual(
                len([t for t in runner._tasks.values() if t.status in tasks_module.TERMINAL_STATUSES]),
                tasks_module.TASKS_KEPT,
            )
        finally:
            executor.release.set()
            runner.wait(5)

    def test_stop_records_the_request_time(self) -> None:
        executor = _BlockingExecutor()
        runner = tasks_module.WorkbenchTaskRunner({"monitor": executor})
        try:
            task = runner.start("monitor", {})
            snapshot = runner.stop(task["id"])
            self.assertEqual(snapshot["status"], "stopping")
            self.assertTrue(snapshot["stop_requested_at"])
        finally:
            executor.release.set()
            runner.wait(5)

    def test_stop_timeout_releases_admission(self) -> None:
        executor = _BlockingExecutor()
        runner = tasks_module.WorkbenchTaskRunner({"monitor": executor})
        try:
            task = runner.start("monitor", {})
            runner.stop(task["id"])
            # 未到 90 秒：仍然占用浏览器。
            self.assertIsNotNone(runner.status()["active"])

            with runner._lock:
                runner._tasks[task["id"]].stop_requested_at = (
                    datetime.datetime.now() - datetime.timedelta(seconds=91)
                ).isoformat(timespec="seconds")

            status = runner.status()
            self.assertIsNone(status["active"])
            expired = next(row for row in status["tasks"] if row["id"] == task["id"])
            self.assertEqual(expired["status"], "failed")
            self.assertEqual(expired["stop_reason"], "stop_timeout")
            # 准入已释放，可以再启动一个任务。
            second = runner.start("monitor", {})
            self.assertEqual(second["status"], "running")
        finally:
            executor.release.set()
            runner.wait(5)


# ---------------------------------------------------------------------------
# 11. 前端轮询间隔
# ---------------------------------------------------------------------------


class FrontendPollingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = APP_JS.read_text(encoding="utf-8")

    def test_poll_interval_stays_one_minute(self) -> None:
        self.assertIn("const HR_POLL_INTERVAL = 60000;", self.script)

    def test_platform_sync_is_throttled_to_five_minutes(self) -> None:
        block = _between(self.script, "async function hrPollTick()", "\nfunction hrStartPolling()")
        self.assertIn("await hrLoadSummary();", block)
        self.assertIn("await loadHrConversations({ quiet: true, refreshThread: true });", block)
        self.assertIn("HR_POLL_INTERVAL * 5", block)
        self.assertIn("hrPollTick.lastPlatformSyncAt", block)
        self.assertLess(
            block.index("HR_POLL_INTERVAL * 5"),
            block.index("await hrTriggerSync()"),
            "先判断间隔再触发平台同步",
        )
        # 手动「刷新会话」不受 5 分钟节流影响。
        manual = _between(self.script, "function hrRefreshAll(manual = true)", "// 进入 HR 页")
        self.assertIn("hrTriggerSync({ manual })", manual)
        self.assertNotIn("lastPlatformSyncAt", manual)

    def test_poll_behavior_over_five_minutes(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        block = _between(self.script, "async function hrPollTick()", "\nfunction hrStartPolling()")
        script = (
            "const HR_POLL_INTERVAL = 60000;\n"
            "let now = 1000000;\nDate.now = () => now;\n"
            "const state = {hrPollBusy: false};\n"
            "const calls = {summary: 0, local: 0, sync: 0};\n"
            "function hrPageVisible() { return true; }\n"
            "function hrOnMailView() { return true; }\n"
            "async function hrLoadSummary() { calls.summary += 1; }\n"
            "async function loadHrConversations() { calls.local += 1; }\n"
            "async function hrTriggerSync() { calls.sync += 1; }\n"
            + block
            + "\n(async () => {\n"
            "  await hrPollTick();\n"
            "  now += 60000; await hrPollTick();\n"
            "  now += 240000; await hrPollTick();\n"
            "  now += 60000; await hrPollTick();\n"
            "  console.log(JSON.stringify(calls));\n"
            "})();\n"
        )
        result = subprocess.run(
            ["node", "-e", script], capture_output=True, text=True, timeout=20, check=True
        )
        self.assertEqual(json.loads(result.stdout), {"summary": 4, "local": 4, "sync": 2})


if __name__ == "__main__":
    unittest.main()
