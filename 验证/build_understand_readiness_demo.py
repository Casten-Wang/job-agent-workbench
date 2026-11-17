"""Connect existing readiness questions to verified UA lessons for this sample."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from github_source.ingest import write_json


def main():
    original = ROOT / "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd"
    output = ROOT / "outputs/understand-anything/itsdangerous-672971d66a2e"
    ua = output / "project/.ua"
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    baseline = read(original / "experience-card-demo.json")
    graph = read(ua / "knowledge-graph.json")
    lessons = read(ua / "code-lessons.json")
    validation = read(output / "reference-validation.json")
    if not validation["valid"] or baseline["commit_sha"] != graph["project"]["gitCommitHash"]:
        raise ValueError("Validated references for the same snapshot are required")
    by_origin = {(e["origin"]["file_path"], e["origin"]["section_index"]): e
                 for e in validation["evidence"] if e["origin"]["kind"] == "lesson_section"}
    mapping = [
        [("src/itsdangerous/signer.py", 215)],
        [("src/itsdangerous/signer.py", 227)],
        [("src/itsdangerous/timed.py", 45), ("src/itsdangerous/timed.py", 137)],
    ]
    bundle = {**baseline, "ua_graph": "project/.ua/knowledge-graph.json",
              "integration_mode": "existing_current_agent_questions_with_real_UA_lessons_and_verified_source_links",
              "automated_question_generation_service": False, "answers": [],
              "assessment_status": "not_started", "ability_verdict": None}
    for question, targets in zip(bundle["questions"], mapping):
        support = []
        for path, line in targets:
            index, section = next((i, s) for i, s in enumerate(lessons["files"][path]["sections"])
                                  if s["lineRange"][0] <= line <= s["lineRange"][1])
            evidence = by_origin[path, index]
            support.append({"path": path, "section_index": index, "title": section["title"],
                            "lineRange": section["lineRange"], "tourOrder": section["tourOrder"],
                            "explanation": section["explanation"], "evidence_id": evidence["evidence_id"],
                            "source_url": evidence["source_url"]})
        question["ua_learning_support"] = support
        question["feedback_mode"] = "Source-guided learning after an answer; no answer has been assessed."
    bundle["learning_task_example"]["ua_tour_orders"] = [3, 5]
    write_json(output / "resume-readiness-demo.json", bundle)
    checks = {"same_claim_id_as_previous_readiness_demo": bundle["claim_id"] == baseline["claim_id"],
              "same_source_version": bundle["commit_sha"] == validation["snapshot_commit_sha"],
              "every_question_has_verified_ua_lesson": all(q["ua_learning_support"] for q in bundle["questions"]),
              "does_not_claim_personal_authorship_or_ability": bundle["personal_contribution"] == "unconfirmed" and bundle["ability_verdict"] is None}
    result = {"checks": checks, "passed": all(checks.values()), "questions": len(bundle["questions"])}
    write_json(output / "readiness-integration-check.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
