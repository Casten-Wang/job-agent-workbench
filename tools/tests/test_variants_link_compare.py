#!/usr/bin/env python3
"""Optional job links and read-only master comparison for experience variants.

Every test uses a temporary directory and obvious test data. Nothing reads
``workspace/``, writes a master resume, sends a message or touches the network.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = str(PROJECT_ROOT / "tools")
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)
sys.dont_write_bytecode = True

import variants  # noqa: E402

NOW = dt.datetime(2026, 11, 17, 9, 15, tzinfo=dt.timezone.utc)
VARIANT_TEXT = "测试数据项目：负责 A/B 实验与指标复盘。\n"
OTHER_TEXT = "测试数据项目：负责用户访谈与需求梳理。\n"
MASTER_TEXT = (
    "测试数据主简历\n\n"
    "工作经历：负责用户访谈与需求梳理。\n\n"
    "技能：Axure 原型设计。\n"
)


class _TempCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="t03-variant-extra-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store_path = self.root / "variants.json"
        self.legacy_dir = self.root / "legacy-variants"
        self.config = {
            "variants_store": str(self.store_path),
            "variants_dir": str(self.legacy_dir),
        }
        self._counter = 0

    def _stored_rows(self) -> list[dict]:
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _text_file(self, text: str) -> Path:
        self._counter += 1
        path = self.root / f"variant-{self._counter}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def _add(self, project: str, text: str, job_id: str | None = None) -> dict:
        return variants.add_variant(
            project, self._text_file(text), self.config, now=NOW, job_id=job_id
        )


class JobLinkTests(_TempCase):
    def test_job_id_is_not_written_when_absent(self) -> None:
        outcome = self._add("测试数据甲项目", VARIANT_TEXT)
        stored = self._stored_rows()
        self.assertEqual(len(stored), 1)
        self.assertNotIn("job_id", stored[0])
        self.assertNotIn("job_id", outcome["record"])
        self.assertEqual(outcome["path"], str(self.store_path))
        listed = variants.list_variants("测试数据甲项目", self.config)
        self.assertEqual(len(listed), 1)
        self.assertIsNone(listed[0]["job_id"])

    def test_linked_job_id_is_stored_and_listed(self) -> None:
        outcome = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-abc123")
        stored = self._stored_rows()
        self.assertEqual(stored[0]["job_id"], "jd-abc123")
        self.assertEqual(stored[0]["text"], VARIANT_TEXT)
        listed = variants.list_variants("测试数据甲项目", self.config)
        self.assertEqual(listed[0]["job_id"], "jd-abc123")
        self.assertEqual(listed[0]["id"], variants.record_id("测试数据甲项目", VARIANT_TEXT, "jd-abc123"))

    def test_invalid_job_id_is_ignored_instead_of_stored(self) -> None:
        for index, value in enumerate(("   ", 123, "bad\nid")):
            with self.subTest(value=value):
                text = f"测试数据第 {index} 条：负责需求梳理。\n"
                outcome = self._add("测试数据乙项目", text, job_id=value)
                self.assertNotIn("job_id", outcome["record"])

    def test_same_text_for_two_jobs_stays_two_records(self) -> None:
        first = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-one")
        second = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-two")
        self.assertEqual(first["path"], second["path"])
        self.assertNotEqual(first["record"]["id"], second["record"]["id"])
        self.assertEqual(len(self._stored_rows()), 2)
        everything = variants.list_variants("测试数据甲项目", self.config)
        self.assertEqual(len(everything), 2)
        self.assertEqual(
            [row["job_id"] for row in variants.list_variants("测试数据甲项目", self.config, job_id="jd-one")],
            ["jd-one"],
        )

    def test_records_written_before_job_id_stay_readable(self) -> None:
        directory = Path(self.config["variants_dir"])
        directory.mkdir(parents=True, exist_ok=True)
        old_record = {
            "project": "测试数据丁项目",
            "created_at": NOW.isoformat(),
            "text": OTHER_TEXT,
            "sha256": "0" * 64,
        }
        (directory / "old-record.json").write_text(
            json.dumps(old_record, ensure_ascii=False), encoding="utf-8"
        )
        listed = variants.list_variants("测试数据丁项目", self.config)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["text"], OTHER_TEXT)
        self.assertIsNone(listed[0]["job_id"])
        self.assertEqual(variants.list_variants_for_job("jd-one", self.config), [])

    def test_cross_project_lookup_finds_every_linked_variant(self) -> None:
        self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-shared")
        self._add("测试数据乙项目", OTHER_TEXT, job_id="jd-shared")
        self._add("测试数据丙项目", VARIANT_TEXT, job_id="jd-other")
        rows = variants.list_variants_for_job("jd-shared", self.config)
        self.assertEqual({row["project"] for row in rows}, {"测试数据甲项目", "测试数据乙项目"})
        self.assertEqual(variants.list_variants_for_job("jd-missing", self.config), [])

    def test_job_filter_rejects_blank_or_non_string_values(self) -> None:
        self._add("测试数据甲项目", VARIANT_TEXT)
        for value in ("", "   ", 7):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    variants.list_variants("测试数据甲项目", self.config, job_id=value)
        with self.assertRaises(ValueError):
            variants.list_variants_for_job("", self.config)


class SharedStoreTests(_TempCase):
    """One local store for the CLI and the web backend."""

    def test_default_store_is_the_web_dataset(self) -> None:
        default_path = variants.variants_store_path({})
        self.assertEqual(default_path, PROJECT_ROOT / "web" / "data" / "user" / "variants.json")
        self.assertEqual(variants.variants_store_path(None), default_path)

    def test_store_is_one_json_array_across_adds(self) -> None:
        self._add("测试数据甲项目", VARIANT_TEXT)
        self._add("测试数据乙项目", OTHER_TEXT)
        rows = self._stored_rows()
        self.assertIsInstance(rows, list)
        self.assertEqual([row["project"] for row in rows], ["测试数据甲项目", "测试数据乙项目"])
        self.assertTrue(all(row["id"].startswith("variant-") for row in rows))
        self.assertFalse(self.legacy_dir.exists())

    def test_duplicate_add_returns_the_existing_record(self) -> None:
        first = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-dup")
        before = self.store_path.read_bytes()
        second = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-dup")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["record"]["id"], second["record"]["id"])
        self.assertEqual(self.store_path.read_bytes(), before)

    def test_same_text_without_job_id_is_still_a_duplicate(self) -> None:
        self._add("测试数据甲项目", VARIANT_TEXT)
        again = self._add("测试数据甲项目", VARIANT_TEXT)
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(self._stored_rows()), 1)

    def test_legacy_and_shared_records_are_listed_together(self) -> None:
        self.legacy_dir.mkdir(parents=True, exist_ok=True)
        (self.legacy_dir / "old-a.json").write_text(
            json.dumps(
                {
                    "project": "测试数据甲项目",
                    "created_at": "2026-11-01T08:00:00+00:00",
                    "text": OTHER_TEXT,
                    "sha256": "0" * 64,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-new")
        listed = variants.list_variants("测试数据甲项目", self.config)
        self.assertEqual([item["text"] for item in listed], [OTHER_TEXT, VARIANT_TEXT])
        self.assertEqual(listed[0]["path"], str(self.legacy_dir / "old-a.json"))
        self.assertIsNone(listed[0]["id"])
        self.assertEqual([item["job_id"] for item in listed], [None, "jd-new"])

    def test_a_record_written_by_the_backend_is_readable(self) -> None:
        # Shape written by web/backend.py's add_variant before this change.
        self.store_path.write_text(
            json.dumps(
                [
                    {
                        "id": "variant-abc123",
                        "project": "测试数据戊项目",
                        "created_at": "2026-11-02T08:00:00+00:00",
                        "text": OTHER_TEXT,
                        "sha256": "1" * 64,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        listed = variants.list_variants("测试数据戊项目", self.config)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "variant-abc123")
        self.assertIsNone(listed[0]["job_id"])

    def test_damaged_store_is_reported_not_overwritten(self) -> None:
        self.store_path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._add("测试数据甲项目", VARIANT_TEXT)
        with self.assertRaises(ValueError):
            variants.list_variants("测试数据甲项目", self.config)
        self.assertEqual(self.store_path.read_text(encoding="utf-8"), "{not json")


class CompareTests(unittest.TestCase):
    def test_added_paragraph_is_echoed_verbatim(self) -> None:
        variant = MASTER_TEXT + "\n新增段落：负责结算流程梳理。\n"
        result = variants.compare_variant(variant, MASTER_TEXT)
        self.assertFalse(result["identical"])
        self.assertEqual(
            result["segments"], [{"kind": "added", "text": "新增段落：负责结算流程梳理。"}]
        )
        self.assertEqual(result["summary"], {"added": 1, "removed": 0, "changed": 0, "unchanged": 3})

    def test_removed_paragraph_is_echoed_verbatim(self) -> None:
        variant = "测试数据主简历\n\n工作经历：负责用户访谈与需求梳理。\n"
        result = variants.compare_variant(variant, MASTER_TEXT)
        self.assertEqual(
            result["segments"], [{"kind": "removed", "text": "技能：Axure 原型设计。"}]
        )
        self.assertEqual(result["summary"]["removed"], 1)

    def test_changed_paragraph_keeps_both_originals(self) -> None:
        variant = MASTER_TEXT.replace("Axure 原型设计", "Figma 原型设计")
        result = variants.compare_variant(variant, MASTER_TEXT)
        self.assertEqual(
            result["segments"],
            [
                {
                    "kind": "changed",
                    "before": "技能：Axure 原型设计。",
                    "after": "技能：Figma 原型设计。",
                }
            ],
        )
        self.assertEqual(result["summary"]["changed"], 1)

    def test_extra_variant_paragraph_in_a_replace_block_becomes_added(self) -> None:
        variant = "测试数据主简历\n\n工作经历：负责用户访谈与需求梳理。\n\n技能：Figma 原型设计。\n\n补充：负责数据看板。\n"
        result = variants.compare_variant(variant, MASTER_TEXT)
        kinds = [segment["kind"] for segment in result["segments"]]
        self.assertEqual(kinds, ["changed", "added"])
        self.assertEqual(result["segments"][1]["text"], "补充：负责数据看板。")

    def test_identical_text_has_no_segments(self) -> None:
        result = variants.compare_variant(MASTER_TEXT, MASTER_TEXT)
        self.assertTrue(result["identical"])
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["summary"], {"added": 0, "removed": 0, "changed": 0, "unchanged": 3})

    def test_whitespace_and_fullwidth_only_differences_are_not_edits(self) -> None:
        variant = "测试数据主简历\n\n工作经历：负责用户访谈与需求梳理。\n\n技能：Ａxure  原型设计。\n"
        result = variants.compare_variant(variant, MASTER_TEXT)
        self.assertTrue(result["identical"], result["segments"])

    def test_empty_variant_reports_every_master_paragraph_as_removed(self) -> None:
        result = variants.compare_variant("", MASTER_TEXT)
        self.assertEqual(result["summary"]["removed"], 3)
        self.assertTrue(all(segment["kind"] == "removed" for segment in result["segments"]))

    def test_every_segment_text_comes_from_one_of_the_inputs(self) -> None:
        variant = (
            "测试数据主简历\n\n工作经历：负责用户访谈、需求梳理与数据看板。\n\n"
            "技能：Axure 原型设计。\n\n新增：负责结算流程梳理。\n"
        )
        result = variants.compare_variant(variant, MASTER_TEXT)
        allowed = set(variants._paragraphs(variant)) | set(variants._paragraphs(MASTER_TEXT))
        self.assertTrue(result["segments"])
        for segment in result["segments"]:
            for key in ("text", "before", "after"):
                if key in segment:
                    self.assertIn(segment[key], allowed)


class MasterUntouchedTests(_TempCase):
    def test_add_and_compare_leave_the_master_file_byte_identical(self) -> None:
        master = self.root / "master-resume.md"
        master.write_text(MASTER_TEXT, encoding="utf-8")
        before = master.read_bytes()

        outcome = self._add("测试数据甲项目", VARIANT_TEXT, job_id="jd-keep")
        result = variants.compare_variant(VARIANT_TEXT, master.read_text(encoding="utf-8"))

        self.assertFalse(result["identical"])
        self.assertEqual(master.read_bytes(), before)
        stored = Path(outcome["path"])
        self.assertTrue(stored.is_file())
        self.assertEqual(stored, self.store_path)
        # Only the temp input file and the shared store were added at root.
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()),
            ["master-resume.md", "variant-1.txt", "variants.json"],
        )

    def test_compare_alone_writes_no_file_at_all(self) -> None:
        variants.compare_variant(OTHER_TEXT, MASTER_TEXT)
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
