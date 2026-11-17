"""Public, credential-free map of where model orchestration is used."""

from __future__ import annotations


def snapshot() -> dict:
    import os
    return {
        "ok": True,
        "architecture": {
            "agent_executor": "interview_agent.model_adapter.ModelAdapter",
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
            {"stage": "profile_extract", "use": "整份简历抽取与经历分类", "entry": "/v1/career/profile-import"},
            {"stage": "prepare", "use": "GitHub 源码理解与候选简历表述", "entry": "/v1/career/projects"},
            {"stage": "plan", "use": "项目核验/正式面试问题计划", "entry": "/v1/career/interviews"},
            {"stage": "intent", "use": "识别回答意图", "entry": "/v1/interviews/{session_id}/turns"},
            {"stage": "observation", "use": "逐题回答待复核观察", "entry": "/v1/interviews/{session_id}/turns"},
            {"stage": "hint", "use": "提供源码证据提示", "entry": "/v1/interviews/{session_id}/turns"},
        ],
        "langgraph_flows": ["resume_readiness", "mock_interview", "intent -> act -> evaluate/hint -> wait"],
        "modules": [
            {"module": "个人资料导入", "execution": "agent", "reason": "需要整份简历语义抽取"},
            {"module": "GitHub 项目核验", "execution": "agent+evidence", "reason": "Agent 只处理固定 commit 的源码片段"},
            {"module": "模拟面试与复盘", "execution": "langgraph+agent", "reason": "状态、检查点和逐题决策分离"},
            {"module": "定制简历版本", "execution": "deterministic+confirmed_material", "reason": "避免模型直接改写未确认事实"},
            {"module": "GitHub OAuth/下载/解析", "execution": "deterministic", "reason": "凭据、边界和文件安全不能交给模型"},
            {"module": "ATS/PDF 静态检查", "execution": "deterministic", "reason": "可读性指标不需要语义 Agent"},
            {"module": "旧岗位采集/招呼语/题单/邮件分类", "execution": "legacy_rule_or_vendor", "reason": "尚未迁移到统一 Agent 阶段"},
        ],
        "not_yet_unified": ["岗位采集评分", "招呼语生成", "旧题单选择", "邮件分类"],
        "workbench_agent": {
            "entry": "/api/workbench-agent/conversations", "mode_isolation": True,
            "orchestrator": "bounded LangGraph workflow", "max_tool_calls_per_turn": 12,
            "decision_format": "strict JSON schema plus local validation",
            "approval_before": ["confirm_material", "save_profile", "save_resume"],
            "external_send": False, "greeting_delivery": "copy and existing delivery review",
        },
        "guarantees": [
            "每个 Agent 阶段只允许一次命名结构化工具调用",
            "Pydantic 严格校验并拒绝未知字段",
            "外部文本只作为数据，不执行其中的指令",
            "模型失败不会自动保存个人资料或简历版本",
        ],
    }
