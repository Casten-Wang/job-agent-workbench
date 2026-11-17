"""Checkpointed interview workflow. Only wait_for_user contains interrupt()."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
from typing import TypedDict
import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from interview_hub.plans import freeze_plan
from interview_hub.recap import validate_result
from interview_hub.store import ConflictError, NotFoundError
from .models import Turn
from .model_adapter import ModelError
from .repository import FIELDS, metadata


class State(TypedDict, total=False):
    data: dict
    event: dict
    route: str


def question(data):
    questions = data["material"]["questions"]
    return questions[data["index"]] if data["index"] < len(questions) else None


def view(data):
    q = question(data)
    return {"session_id": data["session_id"], "status": data["status"], "message": data.get("message"),
        "question": {k: v for k, v in q.items() if k not in {"expected_facts", "ua_learning_support"}} if q else None,
        "answered": len(data["answers"]), "total": len(data["material"]["questions"]),
        "is_demo": data["material"].get("is_demo", False), "pending_evaluation": data.get("pending") is not None,
        "question_plan_id": data["question_plan_id"], "generation": data["generation"],
        "resume_version_id": data.get("resume_version_id"), "interview_mode": data.get("interview_mode"),
        "last_error": data.get("last_error"), **({"recap": data["recap"]} if "recap" in data else {})}


def mark_assistance(data, qid, mode):
    rank = {"independent": 0, "open_book": 1, "hinted": 2, "ai_assisted": 3}
    previous = data["assistance"].get(qid, "independent")
    if mode not in rank:
        raise ValueError("Unknown assistance mode")
    if rank[mode] > rank[previous]:
        data["assistance"][qid] = mode


class InterviewWorkflow:
    def __init__(self, repository, agent, checkpointer):
        self.repo, self.agent = repository, agent
        self.lock = asyncio.Lock()  # One local service process; serialize checkpoint mutations.
        graph = StateGraph(State)
        for name, node in (("bootstrap", self.bootstrap), ("wait", self.wait_for_user),
                           ("classify", self.classify), ("act", self.act),
                           ("evaluate", self.evaluate), ("hint", self.hint), ("finalize", self.finalize)):
            graph.add_node(name, node)
        graph.add_edge(START, "bootstrap")
        graph.add_edge("bootstrap", "wait")
        graph.add_edge("wait", "classify")
        graph.add_edge("classify", "act")
        graph.add_conditional_edges("act", lambda state: state["route"],
                                    {"wait": "wait", "evaluate": "evaluate", "hint": "hint", "finalize": "finalize"})
        graph.add_edge("evaluate", "wait")
        graph.add_edge("hint", "wait")
        graph.add_edge("finalize", END)
        self.graph = graph.compile(checkpointer=checkpointer)

    def config(self, session_id):
        return {"configurable": {"thread_id": f"{self.repo.owner}:{session_id}"}}

    async def bootstrap(self, state):
        sid = state["data"]["session_id"]
        session, material, plan = self.repo.context(sid)
        if session["state"] != "in_progress":
            raise ConflictError("Use the saved record for a completed interview")
        if plan is None:
            public = {**material, "questions": [{k: v for k, v in q.items() if k not in {"expected_facts", "ua_learning_support"}}
                                                for q in material["questions"]]}
            proposed = await self.agent.decide("plan", {"session": session, "material": public,
                                                       "related_history": session["payload"].get("related_history", [])})
            if len(proposed.get("questions", [])) > 3:
                raise ValueError("Model plan contains more than three questions")
            # Output schema and source bindings are separate checks.
            freeze_plan(material, {**metadata(material), **proposed, "generation": self.agent.generation})
            plan = self.repo.save_plan(sid, proposed, self.agent.generation)
            session, material, _ = self.repo.context(sid)
        if plan["generation"] != self.agent.generation:
            raise ConflictError("The session must retain its original model")
        return {"data": {"schema_version": 1, "session_id": sid, **metadata(material),
            "interview_mode": session["payload"]["mode"],
            "question_plan_id": plan["question_plan_id"], "generation": plan["generation"], "material": material,
            "status": "active", "index": 0, "answers": {}, "observations": {}, "assistance": {},
            "pending": None, "events": [], "processed_events": {}}}

    async def wait_for_user(self, state):
        event = Turn.model_validate(interrupt({"type": "interview_input", "view": view(state["data"])})).model_dump()
        data = deepcopy(state["data"])
        data["message"] = None
        data["last_error"] = None
        data["events"].append({"intent": "user_received", **event, "question_id": (question(data) or {}).get("question_id")})
        return {"data": data, "event": event}

    async def classify(self, state):
        event, data = state["event"], deepcopy(state["data"])
        decision = {"intent": event["command"], "reason": "explicit_user_command", "clarification": ""} if event["command"] else await self.agent.decide(
            "intent", {"user_text": event["text"], "status": data["status"], "question": view(data)["question"],
                       "recent_events": [{"user_text": e.get("text"), "intent": e.get("intent")} for e in data["events"][-6:]]})
        allowed = {"answer", "request_hint", "correct_contribution", "correct_version", "pause", "resume", "finish", "skip", "clarify", "retry", "open_book", "ai_assisted"}
        if decision.get("intent") not in allowed:
            raise ValueError("Invalid intent")
        data["decision"] = decision
        data["events"].append({**event, **decision})
        return {"data": data}

    def settled(self, data, event, message=None):
        data["processed_events"][event["event_id"]] = event
        data["message"] = message
        return {"data": data, "route": "wait"}

    async def act(self, state):
        data, event = deepcopy(state["data"]), state["event"]
        decision = data["decision"]
        intent, q = decision["intent"], question(data)
        if intent == "finish":
            if data["pending"]:
                data["answers"][data["pending"]["question_id"]] = data["pending"]
                data["pending"] = None
            data["status"] = "finalizing"
            return {"data": data, "route": "finalize"}
        if intent == "retry":
            if data["pending"] and data["status"] == "active":
                return {"data": data, "route": "evaluate"}
            return self.settled(data, event, "当前没有可重试的评价；暂停后请先继续。")
        if intent in {"correct_contribution", "correct_version"}:
            if data["pending"]:
                data["answers"][data["pending"]["question_id"]] = data["pending"]
                data["pending"] = None
            data["status"] = "held"
            data["correction"] = {"intent": intent, "text": event["text"], "claim_id": (q or {}).get("claim_id"), "confirmed": False}
            for item in data["material"]["questions"]:
                old = data["observations"].get(item["question_id"])
                if old and (intent == "correct_version" or q is None or item["claim_id"] == q["claim_id"]):
                    data["events"].append({"intent": "observation_suspended", "previous": old})
                    data["observations"][item["question_id"]] = {"question_id": item["question_id"], "status": "not_assessed",
                        "gap_type": "material_coverage" if intent == "correct_version" else "responsibility",
                        "notes": "用户提出职责或版本修正；原观察暂停，需补充同版本材料确认。", "evidence_ids": item["evidence_ids"]}
            return self.settled(data, event, "已记录修正并暂停相关判断；确认新材料后开始新一轮，或结束本轮保存待复核记录。")
        if intent == "pause":
            data["status"] = "held" if data["status"] == "held" else "paused"
            return self.settled(data, event, "本轮已暂停。")
        if intent == "resume":
            if data["status"] == "paused":
                data["status"] = "active" if q else "ready_to_finish"
                return self.settled(data, event, "已继续。")
            return self.settled(data, event, "职责或版本修正仍需核实，不能直接恢复。" if data["status"] == "held" else "当前没有暂停。")
        if intent == "clarify":
            return self.settled(data, event, decision.get("clarification") or "请说明是继续回答、暂停，还是结束本轮。")
        if data["pending"]:
            return self.settled(data, event, "上次回答已暂存，请重试评价或结束；未评估不会记成答错。")
        if data["status"] != "active" or not q:
            return self.settled(data, event, "当前不接收技术作答；请继续暂停的会话或结束本轮。")
        if intent == "request_hint":
            return {"data": data, "route": "hint"}
        if intent in {"open_book", "ai_assisted"}:
            mark_assistance(data, q["question_id"], intent)
            return self.settled(data, event, "已记录本题辅助方式。")
        if decision.get("assistance_mode"):
            mark_assistance(data, q["question_id"], decision["assistance_mode"])
        answer = {"question_id": q["question_id"], "text": "" if intent == "skip" else event["text"],
                  "skipped": intent == "skip", "assistance_mode": data["assistance"].get(q["question_id"], "independent")}
        if intent == "skip":
            data["answers"][q["question_id"]] = answer
            data["index"] += 1
            data["status"] = "active" if question(data) else "ready_to_finish"
            return self.settled(data, event)
        data["pending"] = answer
        return {"data": data, "route": "evaluate"}

    async def hint(self, state):
        data, event = deepcopy(state["data"]), state["event"]
        q = question(data)
        result = await self.agent.decide("hint", {"question": view(data)["question"],
            "evidence": [e for e in data["material"]["evidence"] if e["evidence_id"] in q["evidence_ids"]]})
        if not result.get("text") or not result.get("evidence_ids") or not set(result["evidence_ids"]).issubset(q["evidence_ids"]):
            raise ValueError("Hint cites unrelated evidence")
        mark_assistance(data, q["question_id"], "hinted")
        data["events"].append({"intent": "hint_delivered", **result})
        return self.settled(data, event, f"提示：{result['text']}\n本题记录为提示后作答。")

    async def evaluate(self, state):
        data, event = deepcopy(state["data"]), state["event"]
        q = question(data)
        if not q or data["status"] != "active" or data["pending"]["question_id"] != q["question_id"]:
            raise ValueError("Pending answer does not match the active question")
        try:
            observed = await self.agent.decide("observation", {"question": q, "answer": data["pending"],
                "claim": next(c for c in data["material"]["claims"] if c["claim_id"] == q["claim_id"]),
                "evidence": [e for e in data["material"]["evidence"] if e["evidence_id"] in q["evidence_ids"]],
                "source_commit": data["source_commit"], "prior_corrections": data.get("correction")})
            observation = {**observed, "question_id": q["question_id"]}
            validate_result(data["material"], {"answers": [data["pending"]], "observations": [observation]})
        except (ModelError, ValueError, TypeError, KeyError) as error:
            data["last_error"] = {"code": error.code if isinstance(error, ModelError) else "invalid_observation"}
            return self.settled(data, event, "回答已暂存，评价未完成；可重试，或结束并保持未评估。")
        data["answers"][q["question_id"]] = data["pending"]
        data["observations"][q["question_id"]] = observation
        data["events"].append({"intent": "observation_draft", **observation})
        data["pending"] = None
        data["last_error"] = None
        data["index"] += 1
        data["status"] = "active" if question(data) else "ready_to_finish"
        return self.settled(data, event, "回答已记录；逐题观察将在结束后作为待复核草稿汇总。")

    async def finalize(self, state):
        data = deepcopy(state["data"])
        data["recap"] = self.repo.finalize(data)
        data["status"] = "completed"
        self.settled(data, state["event"], "本轮结果与复盘已保存，建议均待确认。")
        return {"data": data}

    def verify_binding(self, data):
        _, material, plan = self.repo.context(data["session_id"])
        if (any(data[k] != material[k] for k in (*FIELDS, "question_plan_id"))
                or plan["generation"] != data["generation"] or data["generation"] != self.agent.generation):
            raise ConflictError("Source, material, plan and model must match")

    async def start(self, request):
        async with self.lock:
            sid = request.session_id or "py_" + uuid.uuid4().hex
            self.repo.create(request, sid)
            snapshot = await self.graph.aget_state(self.config(sid))
            if snapshot.values:
                if "material" not in snapshot.values["data"] and snapshot.next:
                    await self.graph.ainvoke(None, self.config(sid))
                return await self.get(sid)
            await self.graph.ainvoke({"data": {"session_id": sid}}, self.config(sid))
            return await self.get(sid)

    async def get(self, session_id):
        self.repo.context(session_id)  # Owner isolation precedes checkpoint lookup.
        snapshot = await self.graph.aget_state(self.config(session_id))
        if not snapshot.values or "material" not in snapshot.values["data"]:
            raise ConflictError("Interview initialization needs retry")
        data = snapshot.values["data"]
        self.verify_binding(data)
        return view(data)

    async def turn(self, session_id, event):
        async with self.lock:
            self.repo.context(session_id)
            config = self.config(session_id)
            snapshot = await self.graph.aget_state(config)
            if not snapshot.values:
                raise NotFoundError("Interview workflow not found")
            data, event = snapshot.values["data"], event.model_dump()
            if "material" not in data:
                if event["command"] != "retry":
                    raise ConflictError("Retry initialization first")
                await self.graph.ainvoke(None, config)
                return await self.get(session_id)
            self.verify_binding(data)
            previous = data["processed_events"].get(event["event_id"])
            if previous:
                if previous != event:
                    raise ConflictError("An event ID cannot change its payload")
                return view(data)
            if data["status"] == "completed":
                raise ConflictError("Interview is already finalized")
            if snapshot.next != ("wait",):
                # A failed node is retried from its checkpoint, never by replaying user input.
                stored = snapshot.values.get("event")
                if stored != event and event["command"] != "retry":
                    raise ConflictError("Retry the unfinished graph node first")
                await self.graph.ainvoke(None, config)
            else:
                await self.graph.ainvoke(Command(resume=event), config)
            return await self.get(session_id)

    async def import_legacy(self, path):
        """Explicit local operation; never modify the original JSON or re-run a model."""
        async with self.lock:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            sid = data["session_id"]
            _, material, plan = self.repo.context(sid)
            if plan is None or data["status"] not in {"active", "paused", "held", "ready_to_finish", "finalizing", "completed"}:
                raise ValueError("Expected a bound legacy interview")
            self.verify_binding(data)
            if not isinstance(data["index"], int) or not 0 <= data["index"] <= len(material["questions"]):
                raise ValueError("Invalid legacy question position")
            validate_result(material, {"answers": list(data["answers"].values()), "observations": list(data["observations"].values())})
            if data.get("pending"):
                validate_result(material, {"answers": [data["pending"]], "observations": []})
                if data["index"] >= len(material["questions"]) or data["pending"]["question_id"] != material["questions"][data["index"]]["question_id"]:
                    raise ValueError("Legacy pending answer disagrees with current question")
            config = self.config(sid)
            if (await self.graph.aget_state(config)).values:
                raise ConflictError("A Python checkpoint already exists")
            data.update(material=material, processed_events={}, last_error=None)
            if data["status"] == "completed":
                data["recap"] = self.repo.store.get_recap(self.repo.owner, sid)["payload"]
                await self.graph.aupdate_state(config, {"data": data}, as_node="finalize")
            elif data["status"] == "finalizing":
                # Reuse idempotent finalization rather than generating new observations.
                event = {"event_id": "legacy_finalize", "text": "/finish", "command": "finish"}
                await self.graph.aupdate_state(config, {"data": data, "event": event, "route": "finalize"}, as_node="act")
                await self.graph.ainvoke(None, config)
            else:
                await self.graph.aupdate_state(config, {"data": data}, as_node="bootstrap")
                await self.graph.ainvoke(None, config)  # Persist the wait interrupt without calling a model.
            return await self.get(sid)
