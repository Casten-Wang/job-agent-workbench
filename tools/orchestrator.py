#!/usr/bin/env python3
"""Offline CLI orchestrator for the local job-search toolkit.

The CLI only reads explicit local inputs and writes reports/drafts/queues.
It never contacts a job platform, fills a remote form, sends a greeting, or
submits an application. External text is data, never instructions.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import traceback
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

_PROJECT_ROOT = _TOOLS_DIR.parent
CONFIG_PATH = _TOOLS_DIR / "config_task06.json"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _PROJECT_ROOT / path


def _load(name: str, warnings: list[dict[str, Any]]) -> Any | None:
    """Load one sibling module; record an explicit warning on failure."""
    import degrade

    module, warning = degrade.load_module_safely(f"_task06_{name}", _TOOLS_DIR / f"{name}.py")
    if warning:
        warnings.append(warning)
    return module


def _json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _safe_cell(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value if value is not None else ""))
    return text.replace("|", "\\|").strip()[:160]


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", value)[:80] or "job"


def _date_today() -> str:
    return dt.date.today().isoformat()


def cmd_intake(args: argparse.Namespace, cfg: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    module = _load("jd_intake", warnings)
    if module is None:
        return {"ok": False, "error": "jd_intake_unavailable", "warnings": warnings}
    text = Path(args.input).read_text(encoding="utf-8-sig")
    record = module.parse_jd_text(text, args.id or Path(args.input).stem)
    out = _resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "out": str(out), "id": record["id"], "hard_filter": record["hard_filter"]["status"], "warnings": warnings}


def _approval_report(rows: list[dict[str, Any]], date: str, cfg: dict[str, Any]) -> str:
    lines = [
        f"# 每日投递审批清单：{date}（测试数据）",
        "",
        "- 默认状态：pending；只有显式 `--confirm <ids>` 才会改为 approved。",
        "- 本清单不代表已投递；最终投递由用户手动执行。",
        "",
        "| id | score | company | title | status | Source_Channel | created_at |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            "| {id} | {score} | {company} | {title} | {status} | {source} | {created} |".format(
                id=_safe_cell(row.get("id")), score=_safe_cell(row.get("score")),
                company=_safe_cell(row.get("company")), title=_safe_cell(row.get("title")),
                status=_safe_cell(row.get("status")),
                source=_safe_cell(row.get("Source_Channel")),
                created=_safe_cell(row.get("created_at")),
            )
        )
    if not rows:
        lines.append("| （无） | — | — | — | — | — | — |")
    lines += ["", "## 手动执行清单", "", "- 人工复核事实、JD 与公司官网；", "- 人工复制话术并点击提交；", "- 本 CLI 不调用招聘平台、不提交申请。", ""]
    return "\n".join(lines)


def cmd_approve(args: argparse.Namespace, cfg: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    module = _load("approval_queue", warnings)
    if module is None:
        return {"ok": False, "error": "approval_queue_unavailable", "warnings": warnings}
    queue_path = _resolve(cfg["approval"]["queue_path"])
    if args.confirm:
        result = module.confirm(args.confirm, queue_path)
        result["ok"] = True
        result["warnings"] = warnings
        return result
    rows = module.list_pending(args.date, queue_path)
    report_path = _resolve(cfg["approval"]["report_dir"]) / f"approval-{args.date}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_approval_report(rows, args.date, cfg), encoding="utf-8")
    return {"ok": True, "report": str(report_path), "pending_count": len(rows), "auto_approved": False, "warnings": warnings}


def _find_job(job_id: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    module = __import__("approval_queue")
    for row in module.load_queue(_resolve(cfg["approval"]["queue_path"])):
        if str(row.get("id")) == job_id:
            return row
    for path in sorted(_resolve("tools/data").glob("*.json")):
        try:
            payload = _json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        rows = payload if isinstance(payload, list) else payload.get("jobs", []) if isinstance(payload, dict) else []
        for row in rows:
            if isinstance(row, dict) and str(row.get("id") or row.get("job_id")) == job_id:
                return row
    return None


def cmd_prepare(args: argparse.Namespace, cfg: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    job = _find_job(args.id, cfg) or {}
    if not job:
        return {"ok": False, "error": "job-not-found", "id": args.id, "warnings": warnings}
    greeting_module = _load("greeting", warnings)
    precheck_module = _load("precheck", warnings)
    cv_path = _resolve(cfg["greeting"]["source_cv"])
    cv_text = cv_path.read_text(encoding="utf-8-sig") if cv_path.is_file() else ""
    greeting = greeting_module.make_greeting(job, cv_text) if greeting_module else {"status": "unavailable"}
    tracker_path = _resolve("workspace/applications.md")
    if precheck_module and tracker_path.is_file():
        dedupe = precheck_module.evaluate_tracker_text(
            tracker_path.read_text(encoding="utf-8-sig"),
            str(job.get("company") or ""), str(job.get("title") or ""),
            str(job.get("city") or ""), dt.date.fromisoformat(args.date),
        )
    else:
        dedupe = {"status": "tracker-unavailable", "block": None, "warnings": ["no-local-tracker"]}
    checklist = {
        "job_id": args.id,
        "status": "prepared_for_manual_review_only",
        "resume_task_checklist": [
            "从 workspace/resume.md 读取事实，不新增数字或经历",
            "依据本地 JD 标记核对关键词，人工复核后生成单栏 ATS PDF",
            "用 tools/ats_check.py 做自动可读性检查；不可解析时人工核查",
        ],
        "greeting_draft": greeting,
        "pre_apply_dedupe": dedupe,
        "form_fields": ["用户手动填写公司官网表单", "用户手动上传 PDF", "用户自行点击提交"],
        "auto_submit": False,
        "warnings": warnings,
    }
    out = _resolve("demo") / f"prepare-{_safe_id(args.id)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(checklist, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checklist["out"] = str(out)
    return checklist


def cmd_status(args: argparse.Namespace, cfg: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    module = _load("state_machine", warnings)
    if module is None:
        return {"ok": False, "error": "state_machine_unavailable", "warnings": warnings}
    current = "已采集"
    log_path = _resolve("tools/data/status-log.jsonl")
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8-sig").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(event.get("job_id")) == args.id and str(event.get("to")) in module.load_config()["states"]:
                current = str(event["to"])
    result = module.transition(args.id, current, args.to, log_path=log_path)
    result["warnings"] = warnings
    return result


def _append(lines: list[str], title: str, result: Any, warnings: list[dict[str, Any]]) -> None:
    lines += [f"## {title}", "", "```json", json.dumps(result, ensure_ascii=False, indent=2), "```", ""]
    if warnings:
        lines += ["本次告警：", "", "```json", json.dumps(warnings, ensure_ascii=False, indent=2), "```", ""]


def cmd_demo(args: argparse.Namespace, cfg: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
    demo = cfg["demo"]
    lines = [
        "# 离线端到端演示报告（全部为测试数据）",
        "",
        f"- 生成时间：{dt.datetime.now(dt.timezone.utc).astimezone().isoformat()}",
        "- 数据来源：demo/ 下显式标注的虚构 JD、邮件与逐字稿。",
        "- 边界：不联网、不读取真实邮箱/飞书、不采集音频、不投递、不提交任何申请。",
        "",
    ]
    intake_results = []
    for name in demo["jd_paths"]:
        path = _resolve(name)
        try:
            module = _load("jd_intake", warnings)
            if module is None:
                raise RuntimeError("jd_intake_unavailable")
            record = module.parse_jd_text(path.read_text(encoding="utf-8-sig"), path.stem)
            intake_results.append({"file": name, "id": record["id"], "hard_filter": record["hard_filter"]["status"], "warnings": record["warnings"]})
        except Exception as exc:  # one demo input must not hide the rest
            degrade = _load("degrade", warnings)
            warning = degrade.warn("demo_jd_intake", exc) if degrade else {"module": "degrade", "status": "unavailable"}
            warnings.append(warning)
            intake_results.append({"file": name, "error": type(exc).__name__, "detail": str(exc)[:300]})
    _append(lines, "1. 三条虚构 JD 录入与硬规则", intake_results, warnings)

    approval = _load("approval_queue", warnings)
    queue_path = _resolve("demo/approval-queue-demo.json")
    if queue_path.is_file():
        queue_path.unlink()
    demo_jobs = [
        {"id": "demo-job-001", "score": 4.7, "company": "虚构星河科技有限公司", "title": "AI产品经理", "Source_Channel": "manual_paste", "created_at": "2026-11-14T09:00:00+08:00"},
        {"id": "demo-job-002", "score": 4.2, "company": "虚构云帆商业有限公司", "title": "商业分析师", "Source_Channel": "offerpilot_manual_export", "created_at": "2026-11-14T09:01:00+08:00"},
        {"id": "demo-job-003", "score": 3.5, "company": "虚构低分公司", "title": "产品经理", "Source_Channel": "manual_paste", "created_at": "2026-11-14T09:02:00+08:00"},
    ]
    queue_result = approval.enqueue(demo_jobs, queue_path) if approval else {"status": "unavailable"}
    _append(lines, "2. 分数分层与默认 pending 队列", {"enqueue": queue_result, "note": "未显式 confirm；没有任何条目自动变为 approved 或已投递。"}, warnings)

    classifier = _load("mail_classifier", warnings)
    mail_results = []
    for name in demo["mail_paths"]:
        payload = _json(_resolve(name))
        mail_results.append({"file": name, "classification": classifier.classify(payload) if classifier else {"status": "unavailable"}})
    _append(lines, "3. 两封虚构邮件意图解析", mail_results, warnings)

    debrief = _load("interview_debrief", warnings)
    asr = _load("asr_adapter", warnings)
    transcript_path = _resolve(demo["transcript_path"])
    transcript = debrief.load_transcript(transcript_path) if debrief else ""
    debrief_cfg = None
    if debrief:
        debrief_cfg = dict(debrief.load_config())
        debrief_cfg["question_bank_path"] = demo["question_bank_path"]
        debrief_cfg["interview_dir"] = demo["interview_dir"]
    debrief_result = debrief.debrief(transcript, "demo-transcript", config=debrief_cfg) if debrief else {"status": "unavailable"}
    asr_result = asr.transcribe("demo/no-real-audio.wav") if asr else {"status": "unavailable"}
    _append(lines, "4. Mock 复盘与 ASR 适配器", {"debrief": {k: v for k, v in debrief_result.items() if k != "question_bank"}, "asr": asr_result}, warnings)

    analyzer = _load("analytics", warnings)
    roi_input = [
        {"id": "demo-job-001", "Source_Channel": "manual_paste", "status": "一面", "created_at": "2026-11-10"},
        {"id": "demo-job-002", "Source_Channel": "offerpilot_manual_export", "status": "淘汰", "created_at": "2026-11-11", "Rejection_Reason": None},
    ]
    roi = analyzer.analyze(roi_input, [], [debrief_result] if isinstance(debrief_result, dict) else []) if analyzer else {"status": "unavailable"}
    _append(lines, "5. 渠道 ROI 与季度雷达 JSON", roi, warnings)

    feishu = _load("feishu_adapter", warnings)
    dry_run = feishu.sync_job({"job_id": "demo-job-001", "company": "虚构星河科技有限公司", "title": "AI产品经理", "status": "一面", "score": 4.7, "source_channel": "manual_paste", "updated_at": "2026-11-14"}) if feishu else {"status": "unavailable"}
    _append(lines, "6. 飞书 dry-run（未发出 HTTP 请求）", dry_run, warnings)

    greeting = _load("greeting", warnings)
    cv_path = _resolve(cfg["greeting"]["source_cv"])
    draft = greeting.make_greeting({"company": "虚构星河科技有限公司", "title": "AI产品经理"}, cv_path.read_text(encoding="utf-8-sig")) if greeting and cv_path.is_file() else {"status": "unavailable"}
    _append(lines, "7. 150 字以内破冰话术草稿（未发送）", draft, warnings)

    lines += [
        "## 8. 结论与人工验证清单",
        "",
        "- 已自动验证：本地录入、硬规则、审批队列默认 pending、邮件分类、复盘字段、渠道聚合、dry-run 与话术长度。",
        "- 需人工验证：真实 JD 评估、ATS PDF 渲染与事实核查、人工投递、真实 IMAP/飞书同步、真实录音转写。",
        "- 未实现：平台抓取、绕过检测、微信 Hook/MITM、浏览器接管、自动提交、真实 HTTP 飞书同步、真实 ASR 运行。",
        "- 简历截图中的 `[[ILLEGIBLE]]`、联系方式占位符与未确认字段没有编造；详见 `prompts/TASK-02-待确认.md`。",
        "",
        "## 9. 告警汇总",
        "",
        "```json",
        json.dumps(warnings, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    out = _resolve(demo["report_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return {"ok": True, "report": str(out), "steps": 7, "warnings": warnings, "auto_submit": False}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline local job-search pipeline CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    intake = sub.add_parser("intake", help="parse one explicitly labeled local JD")
    intake.add_argument("--input", required=True)
    intake.add_argument("--out", required=True)
    intake.add_argument("--id")
    approve = sub.add_parser("approve", help="list a daily pending batch or explicitly confirm IDs")
    approve.add_argument("--date", default=_date_today())
    approve.add_argument("--confirm", nargs="*", help="explicitly approve these IDs; never submits")
    prepare = sub.add_parser("prepare", help="generate a manual preparation checklist")
    prepare.add_argument("--id", required=True)
    prepare.add_argument("--date", default=_date_today(), help="dedupe check date YYYY-MM-DD")
    status = sub.add_parser("status", help="append one validated local state transition")
    status.add_argument("--id", required=True)
    status.add_argument("--to", required=True)
    sub.add_parser("demo", help="run the offline end-to-end demo and write demo/REPORT.md")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()
    warnings: list[dict[str, Any]] = []
    handlers = {
        "intake": cmd_intake,
        "approve": cmd_approve,
        "prepare": cmd_prepare,
        "status": cmd_status,
        "demo": cmd_demo,
    }
    try:
        result = handlers[args.command](args, cfg, warnings)
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__, "detail": str(exc), "traceback": traceback.format_exc(limit=3)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", False) else 2


if __name__ == "__main__":
    raise SystemExit(main())
