"""综合模拟面试 LangGraph 运行时工作流：全双工状态机、静默检索、SSE 流式与单题重练。"""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from interview_hub.career_store import CareerRecords
from interview_hub.store import ConflictError, NotFoundError

from .brief_assembler import BriefAssembler
from .comprehensive_contracts import (
    Blueprint,
    BlueprintQuestion,
    ComprehensiveDebrief,
    ComprehensiveDrillRequest,
    ComprehensiveStreamRequest,
    ComprehensiveTurn,
    DrillFeedback,
    InterviewBrief,
    NextMoveDecision,
    SilentRetrievalQuery,
    StartComprehensiveInterview,
)
from .comprehensive_policy import (
    apply_skip_or_advance,
    build_fallback_blueprint,
    build_rules_text,
    build_section_template,
    build_sliding_window_context,
    classify_turn_command,
    create_timer_state,
    export_debrief_markdown,
    freeze_candidate_window,
    get_active_elapsed_seconds,
    get_remaining_seconds,
    is_time_exceeded,
    normalize_blueprint,
    open_candidate_window,
    pick_next_after_answer,
    sanitize_debrief,
    sanitize_drill_feedback,
    sanitize_offer_text,
    should_enter_candidate_qa,
    wrap_untrusted_data,
)
from .model_adapter import ModelError


class ComprehensiveState(TypedDict, total=False):
    """LangGraph 检查点持久化的内部状态字典。"""

    data: dict[str, Any]
    pending_event: dict[str, Any] | None


def _current_question(blueprint: Blueprint, question_id: str | None) -> BlueprintQuestion | None:
    if not question_id:
        return None
    for q in list(blueprint.main_questions) + list(blueprint.overflow_questions):
        if q.question_id == question_id:
            return q
    return None


def _question_section(blueprint: Blueprint, section_id: str) -> dict[str, Any]:
    for sec in blueprint.sections:
        if sec.section_id == section_id:
            return sec.model_dump()
    return {"section_id": section_id, "title": section_id, "requires_clarify": False, "requires_code_box": False}


class ComprehensiveInterviewWorkflow:
    """综合模拟面试服务运行时：按 session_id 隔离锁与 LangGraph SQLite 线程。"""

    def __init__(
        self,
        repo: Any,
        agent: Any,
        saver: Any,
        *,
        knowledge: Any = None,
        notes: Any = None,
        records: CareerRecords | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.repo = repo
        self.agent = agent
        self.saver = saver
        self.knowledge = knowledge
        self.notes = notes
        self.records = records or CareerRecords(repo.store.db_path, repo.owner)
        self.assembler = BriefAssembler(repo, knowledge=knowledge, notes=notes, records=self.records)
        self.clock = clock or time.monotonic
        self._locks: dict[str, asyncio.Lock] = {}
        # 仅在当前 SSE 请求存活期间透传流式 token，绝不写入 checkpoint
        self._stream_sinks: dict[tuple[str, str], Callable[[str], Awaitable[None]]] = {}
        self.graph = self._build_graph().compile(checkpointer=saver)

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    def _config(self, session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"ci:{self.repo.owner}:{session_id}"}}

    def _generation(self) -> dict[str, Any]:
        return dict(getattr(self.agent, "generation", None) or {"provider": "unknown", "model": "unknown"})

    async def _call_model(
        self,
        stage: str,
        payload: dict[str, Any],
        *,
        on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        if on_text is not None and callable(getattr(self.agent, "decide_stream", None)):
            result = await self.agent.decide_stream(stage, payload, on_text)
        else:
            result = await self.agent.decide(stage, payload)
            if on_text is not None and isinstance(result, dict):
                preview = result.get("interviewer_prompt")
                if isinstance(preview, str) and preview:
                    await on_text(preview)
        if not isinstance(result, dict):
            raise ValueError(f"Expected dict response from stage {stage}")
        return result

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ComprehensiveState)
        builder.add_node("bootstrap", self._node_bootstrap)
        builder.add_node("wait", self._node_wait)
        builder.add_node("stream_gen", self._node_stream_gen)
        builder.add_node("act_turn", self._node_act_turn)
        builder.add_node("finalize", self._node_finalize)

        builder.add_edge(START, "bootstrap")
        builder.add_edge("bootstrap", "wait")
        builder.add_conditional_edges(
            "wait",
            self._route_after_wait,
            {
                "stream_gen": "stream_gen",
                "act_turn": "act_turn",
                "finalize": "finalize",
                "wait": "wait",
            },
        )
        builder.add_edge("stream_gen", "wait")
        builder.add_conditional_edges(
            "act_turn",
            self._route_after_act,
            {"wait": "wait", "finalize": "finalize"},
        )
        builder.add_edge("finalize", END)
        return builder

    async def _node_bootstrap(self, state: ComprehensiveState) -> dict[str, Any]:
        data = copy.deepcopy(state["data"])
        brief = InterviewBrief.model_validate(data["brief"])
        template = build_section_template(brief)

        plan_payload = {
            "rules_text": build_rules_text(brief),
            "brief": {
                "brief_id": brief.brief_id,
                "role_family": brief.role_family,
                "round": brief.round,
                "duration_minutes": brief.duration_minutes,
                "generic_role": brief.generic_role,
                "has_project_evidence": brief.has_project_evidence,
                "cold_start_warmup": not brief.has_project_evidence,
                "job": {
                    "company": brief.job.company,
                    "role": brief.job.role,
                    "jd_data": wrap_untrusted_data("jd", brief.job.jd, max_chars=1200),
                    "risk_signals": brief.job.risk_signals,
                },
                "projects": [
                    {
                        "project_id": p.project_id,
                        "name": p.name,
                        "knowledge_snapshot_id": p.knowledge_snapshot_id,
                        "available_source_kinds": p.available_source_kinds,
                        "claims": [{"claim_id": c.claim_id, "text": c.text[:120], "confirmed": c.confirmed} for c in p.claims[:3]],
                    }
                    for p in brief.projects[:3]
                ],
                "history_agenda": [item.model_dump() for item in brief.history_agenda[:3]],
                "external_references": [
                    {"ref_id": r.ref_id, "kind": r.kind, "title": r.title, "body_data": wrap_untrusted_data("ref", r.body, max_chars=200)}
                    for r in brief.external_references[:2]
                ],
            },
            "section_template": template,
            "blueprint": build_fallback_blueprint(brief).model_dump(),
        }

        raw_blueprint: dict[str, Any] | None = None
        try:
            # Keep a bounded opening fallback independent of the adapter's 120s budget.
            raw_blueprint = await asyncio.wait_for(self._call_model("ci_plan", plan_payload), timeout=25.0)
        except (TimeoutError, asyncio.TimeoutError, ModelError, ValueError, TypeError, KeyError):
            # 模型超时、异常或结构校验失败时退回到二维确定性保底考纲，绝不卡死开场
            raw_blueprint = build_fallback_blueprint(brief).model_dump()

        blueprint = normalize_blueprint(brief, raw_blueprint)
        first_q = blueprint.main_questions[0]
        cold_notice = ""
        if not brief.has_project_evidence:
            cold_notice = "这次还没有关联代码或项目文档，我们就先从你平时做过的项目聊起，边聊边深挖。"

        data.update(
            {
                "blueprint": blueprint.model_dump(),
                "status": "awaiting_first",
                "current_question_id": first_q.question_id,
                "asked_ids": [first_q.question_id],
                "skipped_ids": [],
                "question_states": {first_q.question_id: {"followup_count": 0, "skip_count": 0, "used_scaffold": False}},
                "section_summaries": {},
                "turns": [],
                "retrieved_chunks": [],
                "last_interviewer_prompt": "",
                "last_move": None,
                "assistance_modes": {},
                "timer": create_timer_state(brief.duration_minutes),
                "processed_events": {},
                "stream_cache": {},
                "incomplete_stream": None,
                "qa_completed": False,
                "early_terminated": False,
                "cold_start_notice": cold_notice,
                "debrief": None,
                "route": "wait",
            }
        )
        return {"data": data, "pending_event": None}

    async def _node_wait(self, state: ComprehensiveState) -> dict[str, Any]:
        payload = interrupt({"status": state["data"]["status"], "question_id": state["data"].get("current_question_id")})
        return {"pending_event": payload}

    def _route_after_wait(self, state: ComprehensiveState) -> str:
        ev = state.get("pending_event") or {}
        kind = ev.get("kind")
        if kind == "stream":
            return "stream_gen"
        if kind == "finish":
            return "finalize"
        if kind == "turn":
            return "act_turn"
        return "wait"

    def _route_after_act(self, state: ComprehensiveState) -> str:
        route = state["data"].get("route", "wait")
        return "finalize" if route == "finalize" else "wait"

    async def _node_stream_gen(self, state: ComprehensiveState) -> dict[str, Any]:
        data = copy.deepcopy(state["data"])
        ev = state.get("pending_event") or {}
        event_id = ev["event_id"]
        intent = ev["intent"]
        brief = InterviewBrief.model_validate(data["brief"])
        blueprint = Blueprint.model_validate(data["blueprint"])
        cur_q = _current_question(blueprint, data.get("current_question_id")) or blueprint.main_questions[0]

        now = self.clock()
        data["timer"] = freeze_candidate_window(data["timer"], now, "model_streaming")

        sink = self._stream_sinks.get((brief.session_id, event_id))
        partial_holder = {"text": ""}

        async def _forward_text(text: str) -> None:
            partial_holder["text"] = text
            if sink is not None:
                await sink(text)

        ctx = build_sliding_window_context(
            brief=brief,
            blueprint=blueprint,
            current_question=cur_q,
            turns=data.get("turns", []),
            section_summaries=data.get("section_summaries", {}),
            retrieved_chunks=data.get("retrieved_chunks", []),
            question_states=data.get("question_states", {}),
            timer_state=data["timer"],
            now=now,
        )
        ctx["stream_intent"] = intent
        if intent == "retry" and data.get("incomplete_stream"):
            ctx["previous_incomplete_draft"] = data["incomplete_stream"].get("partial_text", "")

        try:
            raw_move = await self._call_model("ci_next_move", ctx, on_text=_forward_text)
            decision = NextMoveDecision.model_validate(raw_move)
            prompt = sanitize_offer_text(decision.interviewer_prompt)
            move_label = "opening" if data["status"] == "awaiting_first" else decision.move
        except (ModelError, ValueError, TypeError, KeyError) as err:
            # 保留未完成半截草稿，允许客户端用 intent="retry" 断点重生成，计时保持冻结
            partial = partial_holder["text"]
            data["timer"] = freeze_candidate_window(data["timer"], self.clock(), "retry")
            data["incomplete_stream"] = {
                "event_id": event_id,
                "intent": intent,
                "partial_text": partial,
                "error": str(err),
            }
            data["stream_cache"][event_id] = {
                "request": {"event_id": event_id, "intent": intent},
                "status": "error",
                "partial_text": partial,
                "error": str(err),
            }
            return {"data": data, "pending_event": None}

        # 流式完整推送完毕后：清理残余草稿、追加面试官回合、开启候选人有效作答计时窗口
        data["incomplete_stream"] = None
        data["last_interviewer_prompt"] = prompt
        data["last_move"] = move_label
        data["turns"].append(
            {
                "role": "interviewer",
                "question_id": cur_q.question_id,
                "move": move_label,
                "text": prompt,
            }
        )
        if data["status"] == "awaiting_first":
            data["status"] = "active"
        data["timer"] = open_candidate_window(data["timer"], self.clock())
        data["stream_cache"][event_id] = {
            "request": {"event_id": event_id, "intent": intent},
            "status": "done",
            "text": prompt,
            "move": move_label,
        }
        return {"data": data, "pending_event": None}

    async def _silent_retrieve(
        self,
        brief: InterviewBrief,
        cur_q: BlueprintQuestion,
        user_text: str,
        recent_turns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """在后台静默按需检索已绑定的源码、PDF/PPTX 知识库或外部参考，绝不直接展示给候选人。"""
        if self.knowledge is None or not brief.knowledge_snapshot_ids:
            return []
        try:
            q_decision_raw = await self._call_model(
                "ci_retrieve",
                {
                    "current_question": cur_q.model_dump(),
                    "user_answer_data": wrap_untrusted_data("answer", user_text, max_chars=800),
                    "available_snapshot_ids": brief.knowledge_snapshot_ids,
                    "preferred_source_kind": cur_q.preferred_source_kind,
                    "recent_count": len(recent_turns),
                },
            )
            q_decision = SilentRetrievalQuery.model_validate(q_decision_raw)
        except Exception:
            return []

        if not q_decision.should_retrieve or not q_decision.queries:
            return []

        seen_ids: set[str] = set()
        hits: list[dict[str, Any]] = []
        target_snapshots = [cur_q.knowledge_snapshot_id] if cur_q.knowledge_snapshot_id in brief.knowledge_snapshot_ids else brief.knowledge_snapshot_ids
        source_kind = q_decision.source_kind or cur_q.preferred_source_kind

        for query in q_decision.queries[:3]:
            res = self.knowledge.search(
                {
                    "snapshot_ids": target_snapshots,
                    "query": query,
                    "top_k": 3,
                    "source_kind": source_kind,
                }
            )
            for item in res.get("items") or []:
                eid = item.get("evidence_id")
                if eid and eid not in seen_ids:
                    seen_ids.add(eid)
                    hits.append(item)
                    if len(hits) >= 3:
                        return hits
        return hits

    async def _node_act_turn(self, state: ComprehensiveState) -> dict[str, Any]:
        data = copy.deepcopy(state["data"])
        ev = state.get("pending_event") or {}
        req = ComprehensiveTurn.model_validate(ev["payload"])
        brief = InterviewBrief.model_validate(data["brief"])
        blueprint = Blueprint.model_validate(data["blueprint"])
        cur_q = _current_question(blueprint, data.get("current_question_id")) or blueprint.main_questions[0]

        now = self.clock()
        cmd = classify_turn_command(req.text, req.command)

        # 暂停与恢复必须最先处理，并正确冻结/重启有效作答计时
        if cmd == "pause":
            data["timer"] = freeze_candidate_window(data["timer"], now, "paused")
            data["status"] = "paused"
            reply = "好，我们先暂停一下，计时已经停住。你整理下思路或喝口水，准备好了点“继续面试”就行。"
            return self._record_turn_settled(data, req, cur_q.question_id, "pause", reply)

        if cmd == "resume":
            if data["status"] != "paused":
                reply = "现在本来就在面试中呀，直接接着说就行。"
                return self._record_turn_settled(data, req, cur_q.question_id, "resume", reply)
            data["status"] = "active"
            data["timer"] = open_candidate_window(data["timer"], now, force_resume=True)
            reply = "欢迎回来，计时继续，咱们接着刚才那块往下聊吧。"
            return self._record_turn_settled(data, req, cur_q.question_id, "resume", reply)

        if data["status"] == "paused":
            reply = "现在还在暂停中哦，先点一下“继续面试”，我们再接着聊。"
            return self._record_turn_settled(data, req, cur_q.question_id, "paused_guard", reply)

        # 进入模型检索/思考前冻结有效计时，不消耗候选人有效时长
        data["timer"] = freeze_candidate_window(data["timer"], now, "retrieving")

        if cmd in {"finish", "early_terminate"}:
            if req.text.strip():
                data["turns"].append(
                    {
                        "role": "user",
                        "question_id": cur_q.question_id,
                        "text": req.text.strip(),
                        "command": cmd,
                        "input_channel": req.input_channel,
                    }
                )
            data["early_terminated"] = cmd == "early_terminate" or len(
                [t for t in data["turns"] if t.get("role") == "user" and not t.get("command")]
            ) < 2
            data["processed_events"][req.event_id] = {"request": req.model_dump(), "status": "finalizing"}
            data["route"] = "finalize"
            return {"data": data, "pending_event": None}

        if cmd in {"open_book", "ai_assisted"}:
            data["assistance_modes"][cur_q.question_id] = cmd
            reply = (
                "好的，知道你翻了下资料，复盘时会分开备注，你继续往下讲就行。"
                if cmd == "open_book"
                else "明白，知道你参考了辅助工具，复盘时会单独标明，请继续说说你的思路。"
            )
            data["timer"] = open_candidate_window(data["timer"], self.clock())
            return self._record_turn_settled(data, req, cur_q.question_id, cmd, reply)

        if cmd in {"correct_contribution", "correct_version"}:
            data["turns"].append(
                {
                    "role": "user",
                    "question_id": cur_q.question_id,
                    "text": req.text.strip() or cmd,
                    "command": cmd,
                    "input_channel": req.input_channel,
                }
            )
            reply = "收到，那块之前归因确实不太准，后面复盘不会错算在你头上。你继续说说当时自己实际负责的部分吧。"
            data["timer"] = open_candidate_window(data["timer"], self.clock())
            return self._record_turn_settled(data, req, cur_q.question_id, cmd, reply)

        # 若为首次开场尚未流式拉取，也允许直接通过 turns 提交自述
        if data["status"] == "awaiting_first":
            data["status"] = "active"

        # 记录本轮用户输入
        user_entry = {
            "role": "user",
            "question_id": cur_q.question_id,
            "text": req.text.strip(),
            "command": cmd,
            "input_channel": req.input_channel,
        }
        data["turns"].append(user_entry)

        # 三层跳过策略（skip / force_skip / request_hint）
        if cmd in {"skip", "force_skip", "request_hint"}:
            force = cmd == "force_skip"
            rem = get_remaining_seconds(data["timer"], now)
            if cmd == "request_hint":
                force = False
            plan = apply_skip_or_advance(
                blueprint=blueprint,
                current_question_id=cur_q.question_id,
                asked_ids=data["asked_ids"],
                skipped_ids=data["skipped_ids"],
                question_states=data["question_states"],
                force_skip=force,
                remaining_seconds=rem,
                qa_completed=bool(data.get("qa_completed")),
            )
            data["question_states"][cur_q.question_id] = plan["question_state_patch"]
            if plan["marked_skipped_id"] and plan["marked_skipped_id"] not in data["skipped_ids"]:
                data["skipped_ids"].append(plan["marked_skipped_id"])

            if plan["should_end"]:
                data["processed_events"][req.event_id] = {"request": req.model_dump(), "status": "finalizing"}
                data["route"] = "finalize"
                return {"data": data, "pending_event": None}

            target_q_dict = plan["next_question"] or cur_q.model_dump()
            target_q = BlueprintQuestion.model_validate(target_q_dict)
            if target_q.question_id not in data["asked_ids"]:
                data["asked_ids"].append(target_q.question_id)
                data["question_states"].setdefault(
                    target_q.question_id, {"followup_count": 0, "skip_count": 0, "used_scaffold": False}
                )
            data["current_question_id"] = target_q.question_id

            # 调用模型生成贴合当前语境的 scaffold 提示或自然转场句（模型异常则走保底话术）
            prompt = await self._generate_move_prompt(
                brief=brief,
                blueprint=blueprint,
                target_q=target_q,
                data=data,
                now=now,
                forced_move=plan["move"],
                fallback_prompt=(
                    f"先别急，我们可以换个小切入点：先不用铺开全貌，就从「{target_q.focus[:45]}」里最核心的一步开始聊聊？"
                    if plan["move"] == "scaffold"
                    else f"没关系，这题我们先放一边。聊聊下一块——围绕「{target_q.focus[:60]}」，说说你平时的做法？"
                ),
            )
            data["timer"] = open_candidate_window(data["timer"], self.clock())
            return self._record_turn_settled(data, req, target_q.question_id, plan["move"], prompt)

        # 普通回答（或 clarify_case）：先后台静默按需检索，再调用 ci_next_move 并走熔断与状态流转
        hits = await self._silent_retrieve(brief, cur_q, req.text, data["turns"])
        if hits:
            data["retrieved_chunks"] = hits

        rem = get_remaining_seconds(data["timer"], now)
        ctx = build_sliding_window_context(
            brief=brief,
            blueprint=blueprint,
            current_question=cur_q,
            turns=data["turns"],
            section_summaries=data["section_summaries"],
            retrieved_chunks=data["retrieved_chunks"],
            question_states=data["question_states"],
            timer_state=data["timer"],
            now=now,
        )
        if cmd == "clarify_case":
            ctx["candidate_requested_clarify"] = True

        try:
            raw_decision = await self._call_model("ci_next_move", ctx)
            decision = NextMoveDecision.model_validate(raw_decision)
        except (ModelError, ValueError, TypeError, KeyError):
            decision = NextMoveDecision(
                move="advance_topic",
                interviewer_prompt="收到，你这段思路我记录下来了。我们顺着下一个核心关注点继续往下看。",
            )

        if cur_q.origin_type == "candidate_qa":
            data["qa_completed"] = True

        routing = pick_next_after_answer(
            blueprint=blueprint,
            current_question=cur_q,
            decision=decision,
            asked_ids=data["asked_ids"],
            question_states=data["question_states"],
            remaining_seconds=rem,
            duration_minutes=brief.duration_minutes,
            qa_completed=bool(data.get("qa_completed")),
        )

        # 若当前问题继续追问，递增 followup_count；若切出旧板块，压缩一句板块总结进滑动窗口
        cur_state = dict(data["question_states"].get(cur_q.question_id) or {"followup_count": 0, "skip_count": 0})
        if routing["should_end"]:
            data["section_summaries"][cur_q.section_id] = f"已完成 {cur_q.section_id} 考察。"
            data["processed_events"][req.event_id] = {"request": req.model_dump(), "status": "finalizing"}
            data["route"] = "finalize"
            return {"data": data, "pending_event": None}

        next_q = BlueprintQuestion.model_validate(routing["next_question"])
        if next_q.question_id == cur_q.question_id:
            cur_state["followup_count"] = int(cur_state.get("followup_count", 0)) + 1
            if decision.used_scaffold:
                cur_state["used_scaffold"] = True
            data["question_states"][cur_q.question_id] = cur_state
            prompt_text = sanitize_offer_text(decision.interviewer_prompt)
        else:
            data["section_summaries"].setdefault(cur_q.section_id, f"已完成问题 {cur_q.question_id} 的核心追问。")
            if next_q.question_id not in data["asked_ids"]:
                data["asked_ids"].append(next_q.question_id)
                data["question_states"].setdefault(
                    next_q.question_id, {"followup_count": 0, "skip_count": 0, "used_scaffold": False}
                )
            data["current_question_id"] = next_q.question_id

            if routing["circuit_breaker"] or routing["effective_move"] in {"use_overflow", "candidate_qa"}:
                prompt_text = await self._generate_move_prompt(
                    brief=brief,
                    blueprint=blueprint,
                    target_q=next_q,
                    data=data,
                    now=now,
                    forced_move=routing["effective_move"],
                    fallback_prompt=(
                        "我想了解的差不多聊透了，最后留几分钟给你，关于我们团队、日常业务或者这份工作，你有什么想问我的吗？"
                        if routing["effective_move"] == "candidate_qa"
                        else f"这块先聊到这儿，我们接着看看下一部分：{next_q.focus[:70]}"
                    ),
                )
            else:
                prompt_text = sanitize_offer_text(decision.interviewer_prompt)

        data["timer"] = open_candidate_window(data["timer"], self.clock())
        return self._record_turn_settled(data, req, next_q.question_id, routing["effective_move"], prompt_text)

    async def _generate_move_prompt(
        self,
        *,
        brief: InterviewBrief,
        blueprint: Blueprint,
        target_q: BlueprintQuestion,
        data: dict[str, Any],
        now: float,
        forced_move: str,
        fallback_prompt: str,
    ) -> str:
        ctx = build_sliding_window_context(
            brief=brief,
            blueprint=blueprint,
            current_question=target_q,
            turns=data["turns"],
            section_summaries=data["section_summaries"],
            retrieved_chunks=data["retrieved_chunks"],
            question_states=data["question_states"],
            timer_state=data["timer"],
            now=now,
        )
        ctx["forced_move"] = forced_move
        try:
            raw = await self._call_model("ci_next_move", ctx)
            dec = NextMoveDecision.model_validate(raw)
            return sanitize_offer_text(dec.interviewer_prompt) or fallback_prompt
        except (ModelError, ValueError, TypeError, KeyError):
            return fallback_prompt

    def _record_turn_settled(
        self,
        data: dict[str, Any],
        req: ComprehensiveTurn,
        question_id: str,
        move: str,
        prompt: str,
    ) -> dict[str, Any]:
        clean_prompt = sanitize_offer_text(prompt)
        data["last_interviewer_prompt"] = clean_prompt
        data["last_move"] = move
        data["turns"].append(
            {
                "role": "interviewer",
                "question_id": question_id,
                "move": move,
                "text": clean_prompt,
            }
        )
        data["processed_events"][req.event_id] = {"request": req.model_dump(), "status": "settled"}
        data["route"] = "wait"
        return {"data": data, "pending_event": None}

    async def _node_finalize(self, state: ComprehensiveState) -> dict[str, Any]:
        data = copy.deepcopy(state["data"])
        brief = InterviewBrief.model_validate(data["brief"])
        now = self.clock()
        data["timer"] = freeze_candidate_window(data["timer"], now, "completed")
        ev = state.get("pending_event") or {}
        early = bool(data.get("early_terminated") or ev.get("early"))

        candidate_answers = [
            str(t.get("text") or "")
            for t in data.get("turns", [])
            if t.get("role") == "user" and t.get("text")
        ]

        debrief_payload = {
            "rules_text": build_rules_text(brief),
            "session_id": brief.session_id,
            "brief_id": brief.brief_id,
            "role_family": brief.role_family,
            "round": brief.round,
            "active_elapsed_seconds": get_active_elapsed_seconds(data["timer"], now),
            "early_terminated": early,
            "skipped_ids": data.get("skipped_ids", []),
            "assistance_modes": data.get("assistance_modes", {}),
            "claims": [
                {"claim_id": c.claim_id, "project": c.project_name, "text": c.text}
                for p in brief.projects
                for c in p.claims
            ],
            "turns": [
                {
                    "role": t.get("role"),
                    "question_id": t.get("question_id"),
                    "text_data": wrap_untrusted_data("transcript", t.get("text", ""), max_chars=800),
                }
                for t in data.get("turns", [])
            ],
        }

        raw_debrief: dict[str, Any] | None = None
        try:
            raw_debrief = await self._call_model("ci_debrief", debrief_payload)
        except (ModelError, ValueError, TypeError, KeyError):
            raw_debrief = None

        debrief = sanitize_debrief(
            brief=brief,
            candidate_answers=candidate_answers,
            early_terminated=early,
            raw=raw_debrief,
        )
        debrief_dict = debrief.model_dump()

        data["debrief"] = debrief_dict
        data["status"] = "early_terminated" if early else "completed"
        closing_msg = "本场综合模拟面试已提前收口，基于已采集作答的复盘报告已生成。" if early else "本场综合模拟面试已结束，基于全部回答原文实证的复盘报告已生成。"
        data["last_interviewer_prompt"] = closing_msg
        data["last_move"] = "ready_to_end"

        # 不可变持久化复盘报告到 CareerRecords
        try:
            existing_debrief = self.records.get("ci_debrief", brief.session_id)
        except NotFoundError:
            existing_debrief = None
        if existing_debrief is None:
            self.records.put("ci_debrief", brief.session_id, debrief_dict)

        return {"data": data, "pending_event": None}

    # ------------------------------------------------------------------
    # 对外服务方法（供 FastAPI 路由与本地单测调用）
    # ------------------------------------------------------------------

    async def start(self, request: StartComprehensiveInterview) -> dict[str, Any]:
        sid = request.session_id or ("ci_" + uuid.uuid4().hex[:16])
        if request.session_id is None:
            request = request.model_copy(update={"session_id": sid})

        async with self._lock_for(sid):
            config = self._config(sid)
            snapshot = await self.graph.aget_state(config)
            if snapshot.values:
                raise ConflictError(f"Comprehensive session already exists: {sid}")

            brief = self.assembler.assemble(request)
            initial_state: ComprehensiveState = {
                "data": {
                    "brief": brief.model_dump(),
                    "generation": self._generation(),
                },
                "pending_event": None,
            }
            await self.graph.ainvoke(initial_state, config)
            self.records.put(
                "ci_session",
                sid,
                {
                    "session_id": sid,
                    "brief_id": brief.brief_id,
                    "role_family": brief.role_family,
                    "round": brief.round,
                    "company": brief.job.company,
                    "role": brief.job.role,
                    "created_at": brief.created_at,
                },
            )
            return await self.get(sid)

    async def get(self, session_id: str) -> dict[str, Any]:
        config = self._config(session_id)
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values or "data" not in snapshot.values:
            raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
        return self._public_view(snapshot.values["data"])

    async def turn(self, session_id: str, req: ComprehensiveTurn) -> dict[str, Any]:
        async with self._lock_for(session_id):
            config = self._config(session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values or "data" not in snapshot.values:
                raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
            data = snapshot.values["data"]

            cached = data.get("processed_events", {}).get(req.event_id)
            if cached:
                if cached["request"] != req.model_dump():
                    raise ConflictError("An event ID cannot change its payload")
                return self._public_view(data)

            if data["status"] in {"completed", "early_terminated"}:
                raise ConflictError("Interview session is already finalized")

            await self.graph.ainvoke(Command(resume={"kind": "turn", "payload": req.model_dump()}), config)
            after = await self.graph.aget_state(config)
            return self._public_view(after.values["data"])

    async def finish(self, session_id: str, *, early: bool = False) -> dict[str, Any]:
        async with self._lock_for(session_id):
            config = self._config(session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values or "data" not in snapshot.values:
                raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
            data = snapshot.values["data"]
            if data["status"] in {"completed", "early_terminated"}:
                return self._public_view(data)

            await self.graph.ainvoke(Command(resume={"kind": "finish", "early": early}), config)
            after = await self.graph.aget_state(config)
            return self._public_view(after.values["data"])

    async def stream_events(self, session_id: str, req: ComprehensiveStreamRequest):
        """异步生成器：输出符合 text/event-stream 格式的 token 与 done/error 事件。"""
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def _producer() -> None:
            try:
                async with self._lock_for(session_id):
                    config = self._config(session_id)
                    snapshot = await self.graph.aget_state(config)
                    if not snapshot.values or "data" not in snapshot.values:
                        raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
                    data = snapshot.values["data"]

                    if data["status"] in {"completed", "early_terminated"}:
                        raise ConflictError("Interview session is already finalized")

                    cached = data.get("stream_cache", {}).get(req.event_id)
                    if cached:
                        if cached["request"] != req.model_dump():
                            raise ConflictError("An event ID cannot change its payload")
                        if cached["status"] == "done":
                            await queue.put(("token", {"text": cached["text"]}))
                            await queue.put(("done", {"view": self._public_view(data), "move": cached["move"]}))
                            return
                        if req.intent != "retry":
                            await queue.put(("error", {"recoverable": True, "partial_text": cached.get("partial_text", ""), "error": cached.get("error", "")}))
                            return

                    sent_len = {"n": 0}

                    async def _on_text(full_text: str) -> None:
                        if len(full_text) < sent_len["n"]:
                            sent_len["n"] = 0
                        delta = full_text[sent_len["n"] :]
                        sent_len["n"] = len(full_text)
                        if delta:
                            await queue.put(("token", {"delta": delta, "text": full_text}))

                    key = (session_id, req.event_id)
                    self._stream_sinks[key] = _on_text
                    try:
                        await self.graph.ainvoke(
                            Command(resume={"kind": "stream", "event_id": req.event_id, "intent": req.intent}),
                            config,
                        )
                    finally:
                        self._stream_sinks.pop(key, None)

                    after = await self.graph.aget_state(config)
                    after_data = after.values["data"]
                    res = after_data.get("stream_cache", {}).get(req.event_id, {})
                    if res.get("status") == "error":
                        await queue.put(
                            (
                                "error",
                                {
                                    "recoverable": True,
                                    "partial_text": res.get("partial_text", ""),
                                    "error": res.get("error", "stream_failed"),
                                    "view": self._public_view(after_data),
                                },
                            )
                        )
                    else:
                        await queue.put(("done", {"view": self._public_view(after_data), "move": after_data.get("last_move")}))
            except Exception as err:
                await queue.put(("error", {"recoverable": False, "error": str(err)}))
            finally:
                await queue.put(("__eof__", None))

        task = asyncio.create_task(_producer())
        try:
            while True:
                ev_name, payload = await queue.get()
                if ev_name == "__eof__":
                    break
                yield f"event: {ev_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        finally:
            await task

    async def recap(self, session_id: str) -> dict[str, Any]:
        try:
            rec = self.records.get("ci_debrief", session_id)
        except NotFoundError:
            rec = None
        if rec is None:
            config = self._config(session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values:
                raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
            raise ConflictError("Interview debrief is not ready yet; finish the interview first")
        return rec

    async def export_markdown(self, session_id: str) -> dict[str, Any]:
        debrief_dict = await self.recap(session_id)
        debrief = ComprehensiveDebrief.model_validate(debrief_dict)
        config = self._config(session_id)
        snapshot = await self.graph.aget_state(config)
        data = snapshot.values["data"]
        brief = InterviewBrief.model_validate(data["brief"])
        md = export_debrief_markdown(
            brief=brief,
            debrief=debrief,
            turns=data.get("turns", []),
            active_elapsed_seconds=get_active_elapsed_seconds(data["timer"], None),
        )
        return {"session_id": session_id, "filename": f"mock-interview-{session_id}.md", "markdown": md}

    async def drill(self, session_id: str, req: ComprehensiveDrillRequest) -> dict[str, Any]:
        async with self._lock_for(session_id):
            config = self._config(session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values or "data" not in snapshot.values:
                raise NotFoundError(f"Comprehensive interview session not found: {session_id}")
            data = snapshot.values["data"]
            if data["status"] not in {"completed", "early_terminated"} or not data.get("debrief"):
                raise ConflictError("Finish the interview before running single-question drill")

            brief = InterviewBrief.model_validate(data["brief"])
            debrief = ComprehensiveDebrief.model_validate(data["debrief"])

            try:
                drill_store_rec = self.records.get("ci_drill", session_id)
            except NotFoundError:
                drill_store_rec = None
            drill_log = copy.deepcopy(drill_store_rec) if drill_store_rec else {"events": {}, "attempts": {}}

            prev = drill_log["events"].get(req.event_id)
            if prev:
                if prev["request"] != req.model_dump():
                    raise ConflictError("An event ID cannot change its payload")
                return prev["feedback"]

            history_for_q = drill_log["attempts"].get(req.question_id, [])
            attempt_no = len(history_for_q) + 1

            spoken_parts = [
                str(t.get("text") or "")
                for t in data.get("turns", [])
                if t.get("role") == "user" and t.get("text")
            ]
            spoken_parts.extend(str(item.get("answer") or "") for item in history_for_q)
            spoken_parts.append(req.answer)
            spoken_parts.extend(c.text for p in brief.projects for c in p.claims if c.confirmed)
            spoken_corpus = "\n".join(spoken_parts)

            raw_fb: dict[str, Any] | None = None
            try:
                raw_fb = await self._call_model(
                    "ci_drill",
                    {
                        "rules_text": build_rules_text(brief),
                        "question_id": req.question_id,
                        "attempt": attempt_no,
                        "top_priority_fix": debrief.top_priority_fix,
                        "answer_data": wrap_untrusted_data("drill_answer", req.answer, max_chars=2500),
                        "previous_attempts": [
                            {"attempt": item["attempt"], "answer_data": wrap_untrusted_data("prev_drill", item["answer"], max_chars=800)}
                            for item in history_for_q[-3:]
                        ],
                    },
                )
            except (ModelError, ValueError, TypeError, KeyError):
                raw_fb = None

            fb = sanitize_drill_feedback(
                question_id=req.question_id,
                attempt=attempt_no,
                spoken_corpus=spoken_corpus,
                raw=raw_fb,
            )
            fb_dict = fb.model_dump()

            history_for_q.append({"attempt": attempt_no, "answer": req.answer, "feedback": fb_dict})
            drill_log["attempts"][req.question_id] = history_for_q
            drill_log["events"][req.event_id] = {"request": req.model_dump(), "feedback": fb_dict}
            self.records.put("ci_drill", session_id, drill_log, replace=True)
            return fb_dict

    def _public_view(self, data: dict[str, Any]) -> dict[str, Any]:
        """构造严格脱敏的前端公开视图，绝不泄露考纲 Blueprint 或内部静态/静默证据。"""
        brief = InterviewBrief.model_validate(data["brief"])
        blueprint = Blueprint.model_validate(data["blueprint"])
        cur_q = _current_question(blueprint, data.get("current_question_id"))
        timer = data["timer"]
        now = self.clock()
        q_state = data.get("question_states", {}).get(cur_q.question_id, {}) if cur_q else {}
        sec = _question_section(blueprint, cur_q.section_id) if cur_q else None

        current_question_public = None
        if cur_q and data["status"] not in {"completed", "early_terminated"}:
            current_question_public = {
                "question_id": cur_q.question_id,
                "section_id": cur_q.section_id,
                "section_title": sec["title"] if sec else cur_q.section_id,
                "origin_type": cur_q.origin_type,
                "requires_clarify": bool(sec.get("requires_clarify", False)) if sec else False,
                "requires_code_box": bool(sec.get("requires_code_box", False)) if sec else False,
                "skip_count": int(q_state.get("skip_count", 0)),
                "followup_count": int(q_state.get("followup_count", 0)),
            }

        incomplete = data.get("incomplete_stream")
        return {
            "session_id": brief.session_id,
            "brief_id": brief.brief_id,
            "role_family": brief.role_family,
            "round": brief.round,
            "duration_minutes": brief.duration_minutes,
            "target_company": brief.job.company,
            "target_role": brief.job.role,
            "status": data["status"],
            "current_question": current_question_public,
            "interviewer_prompt": data.get("last_interviewer_prompt", ""),
            "last_move": data.get("last_move"),
            "timer": {
                "duration_seconds": int(timer["duration_seconds"]),
                "active_elapsed_seconds": get_active_elapsed_seconds(timer, now),
                "remaining_seconds": get_remaining_seconds(timer, now),
                "frozen_reason": timer.get("frozen_reason"),
                "qa_window_active": should_enter_candidate_qa(timer, brief.duration_minutes, now),
                "time_exceeded": is_time_exceeded(timer, now),
            },
            "cold_start_notice": data.get("cold_start_notice", ""),
            "warnings": brief.warnings,
            "turns": [
                {
                    "role": t.get("role"),
                    "question_id": t.get("question_id"),
                    "text": t.get("text"),
                    "command": t.get("command"),
                    "move": t.get("move"),
                    "input_channel": t.get("input_channel"),
                }
                for t in data.get("turns", [])
            ],
            "has_incomplete_stream": bool(incomplete),
            "incomplete_partial_text": incomplete.get("partial_text", "") if incomplete else "",
            "debrief_ready": data.get("debrief") is not None,
        }
