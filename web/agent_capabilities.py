"""Public, credential-free map of where model orchestration is used.

The interview stages below run in the external local interview engine that
``career_agent_runtime`` bridges to; this repository does not vendor that
engine. ``modules`` also names the in-repo paths that stay deterministic.
"""

from __future__ import annotations


def snapshot() -> dict:
    import os
    try:
        from interview_agent.langfuse_monitor import status as langfuse_status
        langfuse = langfuse_status()
    except ImportError:
        langfuse = {"provider": "Langfuse", "enabled": False, "configured": False}
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
                "enabled": os.getenv("LANGFUSE_TRACING", "").lower() != "true" and os.getenv("LANGSMITH_TRACING", "").lower() == "true" and bool(os.getenv("LANGSMITH_API_KEY")),
                "project": os.getenv("LANGSMITH_PROJECT", "offerpilot-local"),
                "content_capture": False,
                "graph_state_capture": False,
                "mode": "manual_redacted_agent_stage_traces",
                "agent_id": os.getenv("LANGSMITH_AGENT_ID", "offerpilot-local-agent"),
                "agent_environment": os.getenv("LANGSMITH_AGENT_ENVIRONMENT", "production"),
            },
            "langfuse": langfuse,
        },
        "agent_stages": [
            {"stage": "profile_extract", "use": "整份简历抽取与经历分类", "entry": "/v1/career/profile-import（外部引擎）"},
            {"stage": "plan", "use": "文字面试问题计划", "entry": "interview-chat / interview-plan-system"},
            {"stage": "interviewer", "use": "逐题追问与题目表述", "entry": "interview-chat / interview-chat-system"},
            {"stage": "debrief", "use": "复盘评分卡", "entry": "interview-chat / interview-debrief-system"},
            {"stage": "drill", "use": "重练题与改述", "entry": "interview-chat / interview-drill-system"},
            {"stage": "prepare", "use": "GitHub 源码理解与候选简历表述", "entry": "/v1/career/projects（外部引擎）"},
            {"stage": "intent", "use": "项目核验回答意图", "entry": "/v1/interviews/{session_id}/turns（外部引擎）"},
            {"stage": "observation", "use": "逐题回答待复核观察", "entry": "/v1/interviews/{session_id}/turns（外部引擎）"},
            {"stage": "hint", "use": "提供源码证据提示", "entry": "/v1/interviews/{session_id}/turns（外部引擎）"},
        ],
        "external_engine": {
            "bridge": "/api/interview-agent/*、/api/resume-agent/*、/api/career-user/*、/api/workbench-agent/*",
            "in_repo": False,
            "note": "样例与个人引擎通过本机 18747/18748 端口接入，仓库不内嵌其源码",
        },
        "modules": [
            {"module": "个人资料导入", "execution": "agent", "reason": "文件解析在本机完成，语义抽取由已配置的外部引擎执行"},
            {"module": "GitHub 项目核验", "execution": "external_agent+evidence", "reason": "由外部引擎处理固定 commit 的源码片段"},
            {"module": "文字模拟面试与复盘", "execution": "agent+local_state", "reason": "模型只出题与复盘，进度与保存由本地规则控制"},
            {"module": "项目与版本面试", "execution": "langgraph+agent", "reason": "外部本机引擎隔离状态、检查点与逐题决策"},
            {"module": "定制简历版本", "execution": "deterministic+confirmed_material", "reason": "避免模型直接改写未确认事实"},
            {"module": "ATS/PDF 静态检查", "execution": "deterministic", "reason": "可读性指标不需要语义 Agent"},
            {"module": "旧岗位采集/招呼语/题单/邮件分类", "execution": "legacy_rule_or_vendor", "reason": "尚未迁移到统一 Agent 阶段"},
        ],
        "not_yet_unified": ["岗位采集评分", "招呼语生成", "旧题单选择", "邮件分类"],
        "workbench_agent": {
            "entry": "/api/workbench-agent/conversations", "mode_isolation": True,
            "orchestrator": "bounded LangGraph workflow", "max_tool_calls_per_turn": 12,
            "decision_format": "strict JSON schema plus local validation",
            "approval_before": ["confirm_material", "save_profile", "save_resume"],
            "external_send": False, "greeting_delivery": "reviewed sync and existing explicit delivery confirmation",
            "business_catalog": "/api/workbench/overview?mode=user", "gui_and_conversation": True,
        },
        "guarantees": [
            "模型输出按所属模块契约校验；全局 Agent 使用 Pydantic 严格校验并拒绝未知字段",
            "外部文本只作为数据，不执行其中的指令",
            "模型失败不会自动保存个人资料、简历版本或复盘",
        ],
    }
