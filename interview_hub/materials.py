"""Import verified public readiness material into an immutable interview bundle."""

import hashlib
import json
from pathlib import Path

from github_source.ingest import cite
from github_source.understand import validate_understanding


def import_demo(store, owner, snapshot, ua_dir, readiness_file):
    validation = validate_understanding(snapshot, ua_dir)
    if not validation["valid"]:
        raise ValueError("UA references must pass snapshot validation before import")
    manifest = json.loads((Path(snapshot) / "manifest.json").read_text(encoding="utf-8"))
    lessons = json.loads((Path(ua_dir) / "code-lessons.json").read_text(encoding="utf-8"))["files"]
    bundle = json.loads(Path(readiness_file).read_text(encoding="utf-8"))
    if (bundle.get("commit_sha") != manifest["commit_sha"]
            or bundle.get("mode") != "public_project_demonstration_not_user_experience"):
        raise ValueError("Expected the public demonstration for this fixed snapshot")
    evidence = {}
    for item in bundle["evidence"]:
        verified = cite(snapshot, item["path"], item["line_start"], item["line_end"])
        if item["evidence_id"] != verified["evidence_id"]:
            raise ValueError("Readiness evidence does not match its original source")
        evidence[verified["evidence_id"]] = verified
    questions = []
    for item in bundle["questions"]:
        learning = []
        for section in item.get("ua_learning_support", []):
            actual_sections = lessons.get(section["path"], {}).get("sections", [])
            matches = [(i, s) for i, s in enumerate(actual_sections) if s["lineRange"] == section["lineRange"]]
            if len(matches) != 1:
                raise ValueError("Learning section is not present in validated UA lessons")
            section_index, actual = matches[0]
            if any(section.get(k) != actual.get(k) for k in ("title", "explanation", "tourOrder")):
                raise ValueError("Cached learning content differs from the validated UA lesson")
            verified = cite(snapshot, section["path"], *section["lineRange"])
            if section["evidence_id"] != verified["evidence_id"]:
                raise ValueError("Lesson evidence does not match its original source")
            evidence[verified["evidence_id"]] = verified
            learning.append({"path": section["path"], "section_index": section_index, **actual,
                             "evidence_id": verified["evidence_id"], "source_url": verified["source_url"]})
        if not set(item["evidence_ids"]).issubset(evidence):
            raise ValueError("Question references unknown evidence")
        question_evidence = list(dict.fromkeys([*item["evidence_ids"], *[s["evidence_id"] for s in learning]]))
        questions.append({"question_id": item["question_id"], "claim_id": bundle["claim_id"],
                          "text": item["text"], "evidence_ids": question_evidence,
                          "expected_facts": item.get("expected_facts", []),
                          "ua_learning_support": learning})
    if len({q["question_id"] for q in questions}) != len(questions):
        raise ValueError("Question identifiers must be unique")
    material = {"schema_version": 1, "is_demo": True, "resume_version_id": None,
                "project_snapshot_id": f"github:{manifest['repository_id']}:{manifest['commit_sha']}",
                "source_repository": manifest["repository"], "source_commit": manifest["commit_sha"],
                "claims": [{"claim_id": bundle["claim_id"], "text": bundle["project_fact"],
                            "personal_contribution": "unconfirmed", "evidence_ids": list(evidence)}],
                "questions": questions, "evidence": list(evidence.values()),
                "evaluation_basis": "Model-prepared draft facts; source references verified, not a unique standard answer",
                "warnings": ["Public example, not the current user's personal experience.",
                             "No candidate answers or ability assessment have been made."]}
    encoded = json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    material_id = "mat_" + hashlib.sha256(encoded).hexdigest()[:24]
    material["material_id"] = material_id
    from .recap import validate_result
    validate_result(material, {"answers": [], "observations": []})
    return store.put_material(owner, material_id, material)
