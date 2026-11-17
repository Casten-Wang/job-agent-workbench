"""Public, credential-free map of where model orchestration is used.

The interview stages below run in the external local interview engine that
``career_agent_runtime`` bridges to; this repository does not vendor that
engine. ``modules`` also names the in-repo paths that stay deterministic.
"""

from __future__ import annotations


def snapshot() -> dict:
    import os
    return {
        "ok": True,
        "architecture": {
            "agent_executor": "external interview engine (interview_agent.model_adapter.ModelAdapter)",
            "orchestrator": "LangGraph for stateful interviews; direct stage calls for one-shot extraction",
            "model": "step-5-preview",
            "transport": "OpenAI-compatible Chat Completions with one structured tool call per stage",
            "source_of_truth": "server-side evidence, frozen project snapshots and local profile",
            "observability": {
                "provider": "LangSmith",
                "enabled": os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY")),
                "project": os.getenv("LANGSMITH_PROJECT", "offerpilot-local"),
                "content_capture": os.getenv("LANGSMITH_CAPTURE_CONTENT", "").lower() == "true",
                "graph_state_capture": False,
                "mode": "manual_redacted_agent_stage_traces",
                "agent_id": os.getenv("LANGSMITH_AGENT_ID", "offerpilot-local-agent"),
                "agent_environment": os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "production"),
            },
        },
        "agent_stages": [
            {"stage": "plan", "use": "文字面试问题计划", "entry": "interview-chat / interview-plan-system"},
            {"stage": "interviewer", "use": "逐题追问与题目表述", "entry": "interview-chat / interview-chat-system"},
            {"stage": "debrief", "use": "复盘评分卡", "entry": "interview-chat / interview-debrief-system"},
            {"stage": "drill", "use": "重练题与改述", "entry": "interview-chat / interview-drill-system"},
            {"stage": "prepare", "use": "GitHub 源码理解与候选简历表述", "entry": "/v1/career/projects（外部引擎）"},
            {"stage": "intent", "use": "项目核验回答意图", "entry": "/v1/interviews/{session_id}/turns（外部引擎）"},
        ],
        "external_engine": {
            "bridge": "/api/interview-agent/*、/api/resume-agent/*",
            "in_repo": False,
            "note": "项目核验引擎通过本机 18747 端口接入，仓库不内嵌其源码",
        },
        "modules": [
            {"module": "个人资料导入", "execution": "deterministic", "reason": "本地抽取可识别字段，未接语义 Agent"},
            {"module": "GitHub 项目核验", "execution": "external_agent+evidence", "reason": "由外部引擎处理固定 commit 的源码片段"},
            {"module": "文字模拟面试与复盘", "execution": "agent+local_state", "reason": "模型只出题与复盘，进度与保存由本地规则控制"},
            {"module": "定制简历版本", "execution": "deterministic+confirmed_material", "reason": "避免模型直接改写未确认事实"},
            {"module": "ATS/PDF 静态检查", "execution": "deterministic", "reason": "可读性指标不需要语义 Agent"},
            {"module": "旧岗位采集/招呼语/题单/邮件分类", "execution": "legacy_rule_or_vendor", "reason": "尚未迁移到统一 Agent 阶段"},
        ],
        "not_yet_unified": ["岗位采集评分", "招呼语生成", "旧题单选择", "邮件分类"],
        "guarantees": [
            "模型输出按本地契约逐字段校验，未知字段被丢弃",
            "外部文本只作为数据，不执行其中的指令",
            "模型失败不会自动保存个人资料、简历版本或复盘",
        ],
    }
