#!/usr/bin/env python3
"""Test-only fixture for the product's single local dataset.

The workbench has one dataset (``web/data/user``); the ``mode`` parameter is a
compatibility field that is ignored.  Tests that need representative records
point ``backend.WEB_DIR`` at a temporary directory and call
``seed_local_data(store)``, so real user data is never read or written.

The fixture rebuilds the records that the removed demo seed used to produce,
reading the repository's fictional ``demo/`` files.  Every name, company and
number there is invented for testing.  This module is not a test suite: its
name does not match the ``test*.py`` discovery pattern.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(PROJECT_ROOT / "web"), str(PROJECT_ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import backend  # noqa: E402  (local module in web/)
import interview_debrief  # noqa: E402
import jd_intake  # noqa: E402
import mail_classifier  # noqa: E402

DEMO_DIR = PROJECT_ROOT / "demo"

SCORES = {
    "demo-job-001": 4.7,
    "demo-job-002": 4.2,
    "demo-job-003": 3.5,
    "demo-job-004": 4.1,
    "demo-job-005": 3.8,
    "demo-job-006": 4.4,
}


def _jobs() -> list[dict[str, Any]]:
    rows = []
    for index, path in enumerate(sorted(DEMO_DIR.glob("demo-job-*.md")), start=1):
        parsed = jd_intake.parse_jd_text(path.read_text(encoding="utf-8-sig"), path.stem)
        job = backend._normalize_job(parsed, index, "manual_paste")
        job["score"] = SCORES.get(str(job["id"]))
        rows.append(job)
    return rows


def _queue(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for job in jobs:
        score = SCORES.get(str(job["id"]))
        if score is None or score < 4.0:
            continue
        rows.append({
            "id": job["id"],
            "score": score,
            "company": job["company"],
            "title": job["title"],
            "status": "approved",
            "Source_Channel": job["source_channel"],
            "created_at": "2026-11-14T09:00:00+08:00",
            "high_confidence": score >= 4.5,
        })
    return rows


def _mails() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(DEMO_DIR.glob("mail-*.json")):
        mail = mail_classifier.load_mail(path)
        result = mail_classifier.classify(mail)
        rows.append({
            "id": str(mail.get("message_id") or path.stem),
            "source_file": path.name,
            "mail": mail,
            "classification": result,
        })
    return rows


def _debriefs(store: backend.Store) -> list[dict[str, Any]]:
    text = (DEMO_DIR / "transcript-01.md").read_text(encoding="utf-8-sig")
    card = interview_debrief.debrief(
        text,
        "fixture-transcript",
        bank_path=store.files["bank"],
        config={
            **interview_debrief.load_config(),
            "question_bank_path": str(store.files["bank"]),
            "interview_dir": str(store.files["downloads"]),
        },
    )
    card["id"] = "fixture-debrief"
    card["source"] = "demo/transcript-01.md"
    return [card]


def _events() -> list[dict[str, Any]]:
    return [
        {"job_id": "demo-job-001", "from": "已采集", "to": "已过滤", "note": "测试状态", "recorded_at": "2026-11-10T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "已过滤", "to": "简历已定制", "note": "测试状态", "recorded_at": "2026-11-11T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "简历已定制", "to": "已投递/已沟通", "note": "人工投递后记录", "recorded_at": "2026-11-12T09:00:00+08:00"},
        {"job_id": "demo-job-001", "from": "已投递/已沟通", "to": "一面", "note": "测试状态", "recorded_at": "2026-11-13T09:00:00+08:00"},
        {"job_id": "demo-job-002", "from": "已采集", "to": "已过滤", "note": "测试状态", "recorded_at": "2026-11-11T09:00:00+08:00"},
    ]


def _variants() -> list[dict[str, Any]]:
    return [{
        "id": "fixture-variant-001",
        "project": "虚构官网项目",
        "created_at": "2026-11-10T10:00:00+08:00",
        "text": "测试数据：用户手动改写的项目描述原文，未经模型生成或补充数字。",
        "sha256": hashlib.sha256("fixture".encode("utf-8")).hexdigest(),
    }]


def _profile() -> dict[str, Any]:
    """Obviously fictional profile, matching demo/demo-resume-002.md."""
    return backend.normalize_profile({
        "truth_confirmed": True,
        "basic": {
            "name": "虚构应聘者乙",
            "phone": "demo_only_phone",
            "email": "demo@example.invalid",
            "city": "上海",
            "wechat": "demo_only",
            "links": "https://example.invalid/portfolio",
        },
        "job_intent": {
            "titles": ["AI 产品经理", "产品助理"],
            "cities": ["上海", "杭州", "北京"],
            "salary_min": 12000,
            "salary_max": 20000,
            "job_type": "全职",
            "availability": "2027 届校招，2027 年 6 月毕业",
        },
        "education": [{
            "school": "虚构理工大学",
            "major": "信息管理与信息系统",
            "degree": "本科",
            "start": "2023-09",
            "end": "2027-06",
            "summary": "主修数据库原理、统计学、用户研究方法、产品设计基础、Python 程序设计；自学线性代数与概率论、机器学习入门。",
        }],
        "experiences": [
            {
                "company": "虚构智能科技有限公司（A）",
                "title": "AI 产品经理实习生",
                "start": "2025-09",
                "end": "2026-03",
                "summary": "负责智能内容审核工作台的产品设计，结合图像分类与文字识别降低人工审核成本。访谈 8 名审核员并归纳 4 类痛点；通过 A/B 测试选定模型方案；输出 PRD，上线后机审覆盖率提升至 90%，人工审核效率提升 40%，获部门季度创新奖。",
            },
            {
                "company": "虚构科技有限公司（B）",
                "title": "AI 产品助理实习生",
                "start": "2025-02",
                "end": "2025-08",
                "summary": "参与 AI 面试官产品设计，参与 5 场 HR 访谈并整理 12 项需求，设计候选人端、面试官与管理后台流程。单场面试耗时由 40 分钟降到 20 分钟，评估报告自动生成率达到 90%，需求澄清时间由 3 天缩短到 1 天。",
            },
        ],
        "projects": [
            {
                "name": "虚构英语学习浏览器插件",
                "role": "产品设计 / MVP",
                "start": "2025-09",
                "end": "2025-09",
                "summary": "访谈 5 名英语学习者并完成竞品分析，用提示词工程与 AI coding 工具搭建 MVP；组织 10 人参与 A/B 实验，学习步骤减少 60%。",
            },
            {
                "name": "虚构角色聊天 Agent 搭建",
                "role": "RAG / 提示词工程",
                "start": "2025-08",
                "end": "2025-08",
                "summary": "搭建带检索增强的角色聊天 Agent 并设计评测指标，召回率提升 30%，检索相关性提升 25%。",
            },
        ],
        "skills": {
            "tools": ["Figma", "Axure", "墨刀", "XMind", "SQL", "Excel", "Python", "AI coding 工具"],
            "strengths": ["需求分析", "PRD 撰写", "用户访谈", "竞品分析", "RAG 流程与基础评测"],
        },
        "summary": "信息管理背景的本科生，做过两段 AI 方向产品实习与 0-1 的 MVP，习惯先访谈、再出方案、用数据复盘，能与研发、测试对齐需求与排期。",
        "excluded_terms": ["外包", "驻场", "培训贷"],
    })


def _bank() -> dict[str, Any]:
    return {
        "version": 1,
        "questions": [
            {"id": "q-fixture-1", "question": "请解释一次需求分析？", "section": "业务拆解", "source": "user_fixture"},
            {"id": "q-fixture-2", "question": "如何复盘量化不足与逻辑漏洞？", "section": "项目深挖", "source": "user_fixture"},
        ],
    }


def seed_local_data(store: backend.Store) -> None:
    """Write the representative fixture records into ``store``.

    Callers must point ``backend.WEB_DIR`` at a temporary directory first.
    """
    jobs = _jobs()
    store.set_jobs(jobs)
    store.set_queue(_queue(jobs))
    store.set_mails(_mails())
    store.set_debriefs(_debriefs(store))
    store.set_variants(_variants())
    store.set_question_bank(_bank())
    profile = _profile()
    profile["updated_at"] = "2026-11-14T09:00:00+08:00"
    store.set_profile(profile)
    store.files["events"].write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in _events()),
        encoding="utf-8",
    )
    store.files["pipeline"].write_text("", encoding="utf-8")
    store.files["activity"].write_text("", encoding="utf-8")
    for path in store.files["downloads"].glob("*"):
        if path.is_file():
            path.unlink()
    store.log("载入测试数据", "3 条虚构 JD、2 封虚构邮件、1 份虚构复盘")


def clear_local_data(store: backend.Store) -> None:
    """Remove every JSON/JSONL record so a test starts from an empty dataset."""
    for key, path in store.files.items():
        if key == "downloads":
            for child in path.glob("*"):
                if child.is_file():
                    child.unlink()
            continue
        if path.is_file():
            path.unlink()
