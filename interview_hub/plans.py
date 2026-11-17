"""Bind generated questions to a session's existing claims and source evidence."""

import hashlib
import json
import re

from .recap import validate_result


INTENTS = {"implementation", "design_tradeoff", "failure_boundary", "contribution", "verification"}


def freeze_plan(material, data):
    for field in ("material_id", "source_commit", "resume_version_id", "project_snapshot_id"):
        if field not in data or data[field] != material[field]:
            raise ValueError("Question plan must use the frozen session material")
    questions = data.get("questions")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 5:
        raise ValueError("A readiness plan contains one to five questions")
    normalized = []
    for question in questions:
        if (not isinstance(question, dict)
                or set(question) != {"question_id", "claim_id", "text", "evidence_ids", "intent", "reason"}
                or not isinstance(question["question_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", question["question_id"])
                or question["intent"] not in INTENTS
                or not isinstance(question["reason"], str) or not 1 <= len(question["reason"].strip()) <= 2000
                or not isinstance(question["text"], str) or not 1 <= len(question["text"].strip()) <= 2000
                or not isinstance(question["evidence_ids"], list) or not question["evidence_ids"]):
            raise ValueError("Question fields, intent and source references are required")
        support = {}
        for original in material["questions"]:
            for lesson in original.get("ua_learning_support", []):
                if lesson["evidence_id"] in question["evidence_ids"]:
                    support[lesson["evidence_id"]] = lesson
        normalized.append({**question, "expected_facts": [], "ua_learning_support": list(support.values())})
    effective = {**material, "questions": normalized}
    validate_result(effective, {"answers": [], "observations": []})
    provenance = data.get("generation")
    if (not isinstance(provenance, dict) or set(provenance) != {"provider", "model", "kind"}
            or provenance["kind"] not in {"live_model", "contract_test"}
            or any(not isinstance(provenance[k], str) or not 1 <= len(provenance[k]) <= 200 for k in ("provider", "model"))):
        raise ValueError("Plan must declare model or contract-test provenance")
    plan = {k: material[k] for k in ("material_id", "source_commit", "resume_version_id", "project_snapshot_id")}
    plan.update(questions=normalized, generation=provenance, review_status="pending_user_confirmation")
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {**plan, "question_plan_id": "plan_" + digest[:24]}


def apply_plan(material, plan):
    if plan is None:
        return material
    return {**material, "questions": plan["questions"], "question_plan_id": plan["question_plan_id"]}
