"""Validate structured interview feedback and prepare a reviewable recap draft.

This module does not score answers. Observations come from the interview service
and remain pending user confirmation, even when they say an answer is consistent.
"""

from __future__ import annotations

import hashlib


STATUSES = {"consistent", "partial", "conflict", "insufficient_evidence", "not_assessed"}
ASSISTANCE = {"independent", "open_book", "hinted", "ai_assisted"}
GAP_TYPES = {"understanding", "expression", "responsibility", "metric_evidence", "material_coverage"}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _member(value, choices):
    return isinstance(value, str) and value in choices


def _ids(value):
    return (isinstance(value, list) and all(_text(item) for item in value)
            and len(value) == len(set(value)))


def _index(rows, key, label):
    if not isinstance(rows, list):
        raise ValueError(f"{label} must be an array")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not _text(row.get(key)) or row[key] in result:
            raise ValueError(f"{label} contain an invalid or duplicate identifier")
        result[row[key]] = row
    return result


def _range(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(n) is int for n in value) and 1 <= value[0] <= value[1])


def _material_index(material):
    if not isinstance(material, dict) or not _text(material.get("source_commit")):
        raise ValueError("Material must declare its fixed source commit")
    claims = _index(material.get("claims"), "claim_id", "Claims")
    evidence = _index(material.get("evidence"), "evidence_id", "Evidence")
    questions = _index(material.get("questions"), "question_id", "Questions")
    for item in evidence.values():
        path = item.get("path")
        if (item.get("commit_sha") != material["source_commit"]
                or not _text(path) or "\\" in path or ":" in path or any(ord(c) < 32 for c in path)
                or any(p in {"", ".", ".."} for p in path.split("/"))
                or not _range([item.get("line_start"), item.get("line_end")])
                or not _text(item.get("text")) or not _text(item.get("source_url"))):
            raise ValueError("Evidence must identify source lines at the fixed material version")
    for claim in claims.values():
        if (not _text(claim.get("text")) or not _ids(claim.get("evidence_ids"))
                or not set(claim["evidence_ids"]).issubset(evidence)
                or not _member(claim.get("personal_contribution"), {"confirmed", "unconfirmed"})):
            raise ValueError("Claim facts and evidence associations are invalid")
    for question in questions.values():
        claim_id = question.get("claim_id")
        claim = claims.get(claim_id) if isinstance(claim_id, str) else None
        if (claim is None or not _text(question.get("text"))
                or not _ids(question.get("evidence_ids"))
                or not set(question["evidence_ids"]).issubset(claim["evidence_ids"])):
            raise ValueError("Question must bind to a known claim and its declared evidence")
        support = question.get("ua_learning_support", [])
        if not isinstance(support, list):
            raise ValueError("Learning support must be an array")
        for section in support:
            if not isinstance(section, dict) or section.get("evidence_id") not in question["evidence_ids"]:
                raise ValueError("Learning support must use the question's declared source evidence")
            source = evidence[section["evidence_id"]]
            if (section.get("path") != source["path"]
                    or not _range(section.get("lineRange"))
                    or section["lineRange"] != [source["line_start"], source["line_end"]]
                    or not _text(section.get("title")) or not _text(section.get("explanation"))
                    or type(section.get("tourOrder")) is not int or section["tourOrder"] < 1):
                raise ValueError("Learning support does not match its cited source section")
    return claims, evidence, questions


def _has_answer(answer):
    return answer is not None and not answer.get("skipped", False) and _text(answer.get("text"))


def validate_result(material: dict, result: dict) -> None:
    """Reject malformed or cross-bound feedback without exposing its raw contents."""
    _, evidence, questions = _material_index(material)
    if not isinstance(result, dict):
        raise ValueError("Interview result must be an object")
    for field in ("material_id", "source_commit", "resume_version_id", "project_snapshot_id", "question_plan_id"):
        if field in result and (field != "material_id" or field in material) and result[field] != material.get(field):
            raise ValueError("Result metadata does not match its frozen interview material")
    if "summary" in result and not isinstance(result["summary"], str):
        raise ValueError("Result summary must be text")
    answers = _index(result.get("answers"), "question_id", "Answers")
    observations = _index(result.get("observations"), "question_id", "Observations")
    for question_id, answer in answers.items():
        if (question_id not in questions or not _member(answer.get("assistance_mode"), ASSISTANCE)
                or "text" in answer and not isinstance(answer["text"], str)
                or "skipped" in answer and type(answer["skipped"]) is not bool):
            raise ValueError("Answer must refer to a known question and declare its assistance mode")
    for question_id, observation in observations.items():
        status = observation.get("status")
        refs = observation.get("evidence_ids")
        if (question_id not in questions or not _member(status, STATUSES)
                or not _text(observation.get("notes")) or not _ids(refs)
                or "gap_type" in observation and not _member(observation["gap_type"], GAP_TYPES)):
            raise ValueError("Observation fields or question association are invalid")
        if not set(refs).issubset(questions[question_id]["evidence_ids"]):
            raise ValueError("Observation cites evidence unrelated to its question")
        if not _has_answer(answers.get(question_id)) and status in {"consistent", "partial", "conflict"}:
            raise ValueError("An absent or skipped answer cannot receive an answer judgement")
        if status == "conflict":
            if not refs or any(evidence[ref].get("extraction_kind", "extracted") != "extracted"
                               or not _member(evidence[ref].get("source_kind", "source_text"), {"source_text", "source_code", "code"})
                               for ref in refs):
                raise ValueError("Conflict observations require related original source evidence")


TASK_TEXT = {
    "understanding": (
        "沿关联源码追踪输入、关键分支与输出，分别写出正常与失败场景的执行过程。",
        "能将说明定位到列出的源码，并区分直接实现事实、推测和仍缺少的运行信息。",
        "改变一个输入或失败条件，再解释受影响的分支与需要的验证材料。"),
    "expression": (
        "保持事实和职责不变，按目标、本人动作、实现依据和结果或未知项重新讲述，并标出每句话的依据。",
        "表述中的职责与结果不扩大，关键说明可定位到材料；没有依据的数字保持待补证。",
        "换一种问法介绍同一段经历，并说明个人职责与项目整体功能的边界。"),
    "responsibility": (
        "核对本人、团队及参考实现的边界，补充本人改动或协作说明，逐条确认职责。",
        "本人确认过职责范围，并记录对应材料或待补证项；不按提交数量推导独立完成。",
        "换一个具体模块追问本人做了什么，以及哪些部分由他人完成。"),
    "metric_evidence": (
        "为效果数字补充测量口径、记录和对照基线；无法取得时提出移除该数字的草稿建议，保留已确认的实现工作。",
        "每个数字能追溯记录，缺失部分明确待补证；正文改动仍需用户采纳。",
        "更换测量条件，说明哪些结论仍受材料支持，哪些需要重新测量。"),
    "material_coverage": (
        "补充本题相关实现、版本或职责材料，再逐项核对上游反馈；目前不推导为理解不足。",
        "材料版本、位置与职责来源可定位；未取得的内容保持未知。",
        "在补齐材料后用一个新场景复核本题，不沿用资料不足时的结论。"),
    None: (
        "对照关联材料复核本题反馈，先澄清属于表达、理解、职责还是材料问题，再整理说明。",
        "缺口类别及其依据经用户确认，已知与未知分别记录，不能从一条反馈直接推导能力。",
        "用新的场景说明同一表述，并指出需要进一步确认的材料。"),
}


def _task(material, session, question, observation, evidence):
    support = question.get("ua_learning_support", [])
    materials = []
    if support:
        for section in support:
            source = evidence[section["evidence_id"]]
            materials.append({key: source[key] for key in ("evidence_id", "commit_sha", "path", "line_start", "line_end", "source_url")}
                             | {"title": section["title"], "tour_order": section["tourOrder"]})
    else:
        for ref in question["evidence_ids"]:
            materials.append({key: evidence[ref][key] for key in ("evidence_id", "commit_sha", "path", "line_start", "line_end", "source_url")})
    gap = "material_coverage" if observation["status"] == "insufficient_evidence" else observation.get("gap_type")
    action, criterion, retest = TASK_TEXT[gap]
    if observation["status"] == "conflict":
        action = "先确认回答所指的代码版本与本人职责，再对照关联原文澄清冲突；未澄清前不判定为理解不足。"
        criterion = "回答版本、源码位置和职责范围已核对，冲突属于事实、版本还是表述问题经用户确认。"
        retest = "在确认的同一版本下换一个相关场景复述实现，仍有资料缺口时保持待复核。"
    if not materials:
        action = "先补充能定位到项目版本的材料与本人职责说明，再复核本题反馈。"
        criterion = "相关材料已取得并明确版本、位置和来源；缺失项保持未知。"
    task_id = hashlib.sha256(f"{session.get('session_id')}:{question['question_id']}:{observation.get('gap_type')}".encode()).hexdigest()[:24]
    return {"task_id": task_id, "question_id": question["question_id"], "claim_id": question["claim_id"],
            "project_snapshot_id": material.get("project_snapshot_id"), "source_commit": material["source_commit"],
            "status": "pending_confirmation", "materials_status": "available" if materials else "missing",
            "materials": materials, "action": action, "completion_criterion": criterion,
            "retest": {"prompt": retest, "status": "not_started", "mastery_verified": False},
            "review_status": "pending_user_confirmation"}


def build_recap(material: dict, session: dict, result: dict, history: list | None = None) -> dict:
    """Aggregate feedback into proposals, preserving unknowns and source scope."""
    validate_result(material, result)
    if (not isinstance(session, dict) or not _text(session.get("session_id"))
            or not _text(session.get("material_id"))
            or not _member(session.get("mode"), {"resume_readiness", "mock_interview"})
            or not isinstance(session.get("target", {}), dict)):
        raise ValueError("Session must identify its material, mode and target")
    if "material_id" in material and session["material_id"] != material["material_id"]:
        raise ValueError("Session material does not match recap material")
    for field in ("source_commit", "project_snapshot_id", "resume_version_id"):
        if field in session and session[field] != material.get(field):
            raise ValueError("Session metadata does not match the frozen material")
    if "session_id" in result and result["session_id"] != session["session_id"]:
        raise ValueError("Result belongs to another interview session")
    if history is not None and not isinstance(history, list):
        raise ValueError("History must be an array")
    claims, evidence, questions = _material_index(material)
    answers = {answer["question_id"]: answer for answer in result["answers"]}
    observations = {item["question_id"]: item for item in result["observations"]}
    positives, needs_review, not_assessed, tasks = [], [], [], []
    suggestions = {}
    for question_id, question in questions.items():
        answer, observation = answers.get(question_id), observations.get(question_id)
        if not _has_answer(answer) or observation is None or observation["status"] == "not_assessed":
            reason = ("skipped" if answer and answer.get("skipped") else "no_answer" if not _has_answer(answer)
                      else "no_observation" if observation is None else "upstream_not_assessed")
            not_assessed.append({"question_id": question_id, "claim_id": question["claim_id"], "reason": reason,
                                 "upstream_observation": observation, "review_status": "pending_user_confirmation"})
            continue
        item = {"question_id": question_id, "claim_id": question["claim_id"], "status": observation["status"],
                "notes": observation["notes"], "gap_type": observation.get("gap_type"),
                "evidence_ids": list(observation["evidence_ids"]), "assistance_mode": answer["assistance_mode"],
                "assessment_source": "upstream_interview_service", "review_status": "pending_user_confirmation",
                "independent_readiness_verified": False, "retest_recommended": answer["assistance_mode"] != "independent"}
        if observation["status"] == "consistent":
            positives.append(item)
            continue
        needs_review.append(item)
        tasks.append(_task(material, session, question, observation, evidence))
        gap = observation.get("gap_type")
        action = ("clarify_scope_pending_confirmation" if gap == "responsibility"
                  else "collect_evidence" if gap in {"metric_evidence", "material_coverage"} or observation["status"] == "insufficient_evidence"
                  else "review_source_and_version" if observation["status"] == "conflict"
                  else "preserve_fact_and_prepare")
        key = (question["claim_id"], action)
        if key not in suggestions:
            suggestions[key] = {"claim_id": question["claim_id"], "action": action, "question_ids": [],
                                "personal_contribution": claims[question["claim_id"]]["personal_contribution"],
                                "preserve_confirmed_facts": True, "proposed_text": None,
                                "applied": False, "review_status": "pending_user_confirmation"}
        suggestions[key]["question_ids"].append(question_id)
    history_ids = set()
    for record in history or []:
        if isinstance(record, dict):
            old_id = record.get("session_id")
            if isinstance(old_id, str) and old_id != session.get("session_id"):
                history_ids.add(old_id)
    return {"role": "post_interview_recap_draft", "session_id": session.get("session_id"),
            "question_plan_id": material.get("question_plan_id"),
            "material_id": session.get("material_id", material.get("material_id")),
            "resume_version_id": material.get("resume_version_id"), "project_snapshot_id": material.get("project_snapshot_id"),
            "source_commit": material["source_commit"], "target": dict(session.get("target") or {}),
            "is_demo": material.get("is_demo", False), "review_status": "pending_user_confirmation",
            "assessment_basis": "upstream_structured_observations", "automated_answer_judgement": False,
            "ability_verdict": None, "mastery_verified": False, "applied_to_resume": False,
            "upstream_summary": result.get("summary"), "what_went_well": positives, "needs_review": needs_review,
            "upstream_generation": result.get("assessment_generation"), "pending_corrections": result.get("corrections", []),
            "not_assessed": not_assessed, "improvement_tasks": tasks, "resume_suggestions": list(suggestions.values()),
            "related_history_session_ids": sorted(history_ids),
            "limitations": ["本服务汇总上游结构化观察，没有自动判断回答正确度。",
                            "一致或辅助作答记录不等于独立掌握；缺答和缺反馈保持未评估。",
                            "职责、指标、简历改动与补强任务均待用户确认，不自动删除项目或覆盖简历。"]}
