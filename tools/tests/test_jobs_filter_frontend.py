#!/usr/bin/env python3
"""岗位池「筛选」阶段：前端判定、展示与运行时读取的静态/行为测试。

覆盖审查项：
- #3 手动加入判定与后端一致（无文档评分 / 必备条件不满足 / 已关闭），
  并移除手填 0–5 分输入；
- #4 硬筛原因与警告统一走 ``reasonText``，不再出现 ``[object Object]``；
- #7 采集结果显示「显示前 N 条 / 共 M 条」，运行时返回 ``total``；
- #8 自动导入按 100 条分块，单块失败不拖垮整个任务；
- #10 评分按 ``x/5`` 与 ``x/100`` 两个尺度展示，0 分不显示成「—」；
- #13 批量入队混入手动岗位时先确认；
- #14 空表区分「岗位池为空」与「当前筛选为空」；
- #15 切换筛选保留已选岗位并提示未显示数量；
- #16 入队后只清掉真正处理过的岗位，被丢弃的保留勾选并就地显示原因。

静态断言只读仓库内文件；行为断言用 ``node`` 执行从 ``app.js`` 原样截取的
函数片段。没有任何网络访问，也不读写 ``web/data``。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
VENDOR_SRC = PROJECT_ROOT / "vendor" / "offerpilot" / "src"
for _path in (str(WEB_DIR), str(VENDOR_SRC)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import offerpilot_runtime  # noqa: E402

APP_JS = WEB_DIR / "static" / "app.js"
INDEX_HTML = WEB_DIR / "static" / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    return text[start:text.index(end_marker, start)]


def _node(script: str):
    if shutil.which("node") is None:
        raise unittest.SkipTest("node is not installed")
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=20, check=True
    )
    return json.loads(result.stdout)


class JobsFilterSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.script = _read(APP_JS)
        cls.html = _read(INDEX_HTML)

    # #3 ------------------------------------------------------------------
    def test_manual_enqueue_matches_backend_conditions(self) -> None:
        helper = _between(
            self.script, "function jobNeedsManualEnqueue(job)", "function formatJobScore(job)"
        )
        self.assertIn("job.mandatory_status === 'unsatisfied'", helper)
        self.assertIn("job.hiring_status === 'closed'", helper)
        self.assertIn("!jobHasDocumentScore(job)", helper)
        doc_helper = _between(
            self.script, "function jobHasDocumentScore(job)", "function jobNeedsManualEnqueue(job)"
        )
        self.assertIn("job.score_scale === DOC_SCORE_SCALE", doc_helper)
        self.assertIn("job.score_coverage > 0", doc_helper)

    def test_manual_score_input_is_removed(self) -> None:
        for marker in ('id="jd-score"', "评分（可选，0–5）"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.html)
        self.assertNotIn("dom.jdScore", self.script)
        self.assertNotIn("payload.score", self.script)

    # #4 ------------------------------------------------------------------
    def test_reason_text_is_used_everywhere_reasons_are_shown(self) -> None:
        self.assertIn("function reasonText(items)", self.script)
        node_helper = _between(self.script, "function hardFilterNode(", "/* jobs-dossier:start")
        self.assertIn("reasonText(reasons)", node_helper)
        jobs_block = _between(self.script, "function renderJobs(", "function renderQueue(")
        self.assertIn("reasonText(warnings)", jobs_block)
        submit_block = _between(
            self.script,
            "dom.jdForm.addEventListener('submit'",
            "dom.importForm.addEventListener('submit'",
        )
        self.assertIn("reasonText(warnings)", submit_block)
        self.assertIn("reasonText(reasons)", submit_block)
        for marker in ("warnings.join('；')", "reasons.join('；')"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.script)

    def test_reason_text_renders_objects_and_strings(self) -> None:
        start = self.script.index("function reasonText(items)")
        end = self.script.index("\n}\n", start) + 3
        script = self.script[start:end] + (
            "\nconsole.log(JSON.stringify(["
            "reasonText([{code:'city_not_allowed',message:'城市不在目标城市列表：北京'}]),"
            "reasonText(['旧字符串警告']),"
            "reasonText([{code:'salary_below_min'}, null, {code:'x',reason:'薪资过低'}]),"
            "reasonText(undefined)"
            "]));\n"
        )
        self.assertEqual(
            _node(script),
            ["城市不在目标城市列表：北京", "旧字符串警告", "salary_below_min；薪资过低", ""],
        )

    # #7 ------------------------------------------------------------------
    def test_collection_results_report_total_in_runtime_and_ui(self) -> None:
        runtime_source = _read(WEB_DIR / "offerpilot_runtime.py")
        self.assertIn("rows, total = query_jobs(", runtime_source)
        self.assertIn('"total": total', runtime_source)
        self.assertIn('"total": 0', runtime_source)
        self.assertIn("data.total", self.script)
        self.assertIn("显示前 ${jobs.length} 条 / 共 ${total} 条", self.script)

    # #8 ------------------------------------------------------------------
    def test_auto_import_is_chunked_and_isolates_failures(self) -> None:
        self.assertIn("const IMPORT_CHUNK_SIZE = 100;", self.script)
        block = _between(
            self.script, "async function maybeAutoImportCollected(task)", "\nasync function "
        )
        self.assertIn("for (const chunk of chunkList(ids))", block)
        self.assertIn("summary.failed += chunk.length", block)
        self.assertIn("if (!summary.processed)", block)
        self.assertIn("markTaskImported(task.id, false)", block)
        self.assertIn("另有 ${summary.failed} 条分块导入失败", block)
        # 只有全部失败才回退任务标记；部分失败保留已导入状态。
        self.assertLess(
            block.index("if (!summary.processed)"),
            block.index("markTaskImported(task.id, false)"),
        )

    def test_chunk_list_splits_at_one_hundred(self) -> None:
        start = self.script.index("const IMPORT_CHUNK_SIZE = 100;")
        end = self.script.index("\n}\n", self.script.index("function chunkList(", start)) + 3
        script = self.script[start:end] + (
            "\nconsole.log(JSON.stringify(chunkList(Array.from({length:250},(_,i)=>i))"
            ".map((chunk)=>chunk.length)));\n"
        )
        self.assertEqual(_node(script), [100, 100, 50])

    # #10 -----------------------------------------------------------------
    def test_score_scales_and_zero(self) -> None:
        jobs_block = _between(self.script, "function renderOfferPilotJobs()", "function syncOfferPilotSelection()")
        self.assertIn("`${Math.round(Number(job.score))}/100`", jobs_block)
        self.assertIn("? '—'", jobs_block)

        start = self.script.index("const DOC_SCORE_SCALE")
        end = self.script.index("\n}\n", self.script.index("function formatJobScore(job)")) + 3
        script = self.script[start:end] + (
            "\nconsole.log(JSON.stringify(["
            "formatJobScore({score:4.2}),"
            "formatJobScore({score:78}),"
            "formatJobScore({score:0}),"
            "formatJobScore({score:0,score_coverage:0.9,score_scale:DOC_SCORE_SCALE}),"
            "formatJobScore({score:0,score_coverage:0.9,score_scale:'100'}),"
            "formatJobScore({score:null}),"
            "formatJobScore({})"
            "]));\n"
        )
        self.assertEqual(
            _node(script),
            ["4.2/5", "78/100", "0/5", "0/100", "0/100", "未评分", "未评分"],
        )

    # #13 -----------------------------------------------------------------
    def test_bulk_enqueue_confirms_mixed_manual_jobs(self) -> None:
        handler = _between(
            self.script,
            "dom.jobsBulkEnqueue.addEventListener('click'",
            "if (dom.jobsBulkDelete)",
        )
        self.assertIn("selected.filter((job) => jobNeedsManualEnqueue(job))", handler)
        self.assertIn("window.confirm(", handler)
        self.assertIn("其中 ${manualJobs.length} 条将按手动加入处理", handler)
        self.assertIn("if (!ok) return;", handler)

    # #14 -----------------------------------------------------------------
    def test_empty_hint_distinguishes_empty_pool_from_empty_filter(self) -> None:
        self.assertIn('id="jobs-empty-hint"', self.html)
        self.assertIn('id="jobs-filter-empty-hint"', self.html)
        self.assertIn("filteredEmpty", self.script)
        self.assertIn("dom.jobsEmptyHint.hidden = jobs.length > 0 || filteredEmpty", self.script)
        self.assertIn("dom.jobsFilterEmptyHint.hidden = !filteredEmpty", self.script)

    # #15 -----------------------------------------------------------------
    def test_filter_switch_keeps_selection_and_reports_hidden_count(self) -> None:
        jobs_block = _between(self.script, "function renderJobs(", "function renderQueue(")
        self.assertNotIn("state.jobsSelection.forEach((id) => {", jobs_block)
        self.assertNotIn("if (!visibleIds.has(id))", jobs_block)
        sync_block = _between(self.script, "function syncJobsSelection(jobs)", "\nfunction ")
        self.assertIn("另有 ${hidden} 条已选未显示", sync_block)

    # #16 -----------------------------------------------------------------
    def test_enqueue_only_clears_processed_jobs_and_keeps_reasons(self) -> None:
        block = _between(self.script, "async function enqueueJobs(jobs, button, manual = false)", "async function jobsDeleteSelected")
        self.assertIn("['accepted', 'manual', 'duplicate'].forEach", block)
        self.assertIn("if (cleared.has(id)) state.jobsSelection.delete(id);", block)
        self.assertIn("state.jobsEnqueueNotes = enqueueNotesFromResult(data);", block)
        jobs_block = _between(self.script, "function renderJobs(", "function renderQueue(")
        self.assertIn("jobs-enqueue-note", jobs_block)
        notes_block = _between(self.script, "function enqueueNotesFromResult(data)", "async function enqueueJob(")
        self.assertIn("each(data.dropped,", notes_block)
        self.assertIn("each(data.risk_blocked,", notes_block)


class RuntimeJobsTotalTests(unittest.TestCase):
    """``get_jobs`` must report the untruncated total alongside the capped list."""

    def test_total_is_reported_when_list_is_capped(self) -> None:
        class FakeConnection:
            def close(self) -> None:
                pass

        class FakeServer:
            DATA_DIR = Path(tempfile.gettempdir())

            @staticmethod
            def get_db(path) -> FakeConnection:  # noqa: ARG004 - signature parity
                return FakeConnection()

        row = {
            "id": "rt-total-1",
            "title": "产品经理",
            "company": "虚构星河科技有限公司",
            "city": "上海",
            "salary": "20-30K",
            "score": 78,
            "score_coverage": 0.9,
            "mandatory_status": "pending",
            "hiring_status": "unknown",
            "source_platform": "boss",
            "created_at": "2026-11-16T09:00:00+08:00",
            "updated_at": "2026-11-17T10:00:00+08:00",
        }
        with patch.object(offerpilot_runtime, "load_backend", return_value=FakeServer()), patch(
            "offerpilot.db.query_jobs", return_value=([row], 137)
        ) as query:
            result = offerpilot_runtime.get_jobs(limit=100)
        query.assert_called_once()
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total"], 137)
        self.assertEqual(result["limit"], 100)

    def test_unavailable_backend_reports_zero_total(self) -> None:
        with patch.object(
            offerpilot_runtime,
            "load_backend",
            side_effect=offerpilot_runtime.OfferPilotUnavailable("未安装"),
        ):
            result = offerpilot_runtime.get_jobs()
        self.assertFalse(result["ok"])
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["total"], 0)


if __name__ == "__main__":
    unittest.main()
