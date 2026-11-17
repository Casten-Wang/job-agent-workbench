"""Validate a saved public snapshot and create a grounded demonstration bundle.

This script neither executes the downloaded repository nor judges a person.
The explanatory statements and questions were prepared by the current agent
after reading the cited excerpts; this is not an automated semantic service.
"""

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from github_source.ingest import blob_sha, cite, safe_path, write_json


def main():
    snapshot = ROOT / "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd"
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    graph = json.loads((snapshot / "graph.json").read_text(encoding="utf-8"))
    contributions = json.loads((snapshot / "contributions.json").read_text(encoding="utf-8"))
    downloaded = [e for e in manifest["files"] if e["status"] == "downloaded"]
    integrity = []
    for entry in downloaded:
        data = safe_path(snapshot / "source", entry["path"]).read_bytes()
        integrity.append(blob_sha(data) == entry["sha"] and hashlib.sha256(data).hexdigest() == entry["sha256"])
    spans = [("src/itsdangerous/signer.py", 215, 225), ("src/itsdangerous/signer.py", 227, 258),
             ("src/itsdangerous/timed.py", 45, 55), ("src/itsdangerous/timed.py", 137, 158)]
    evidence = [cite(snapshot, path, start, end) for path, start, end in spans]
    ids = [e["evidence_id"] for e in evidence]
    bundle = {
        "mode": "public_project_demonstration_not_user_experience",
        "generation": "current_agent_reviewed_source_excerpts; automated semantic analysis service not implemented",
        "repository": manifest["repository"], "commit_sha": manifest["commit_sha"],
        "claim_id": "demo_itsdangerous_signed_value_expiry_v1",
        "project_fact": "项目支持消息签名和验签，并可通过时间戳与 max_age 检查签名时效。",
        "personal_contribution": "unconfirmed", "resume_wording": None,
        "resume_wording_blocker": "样例属于公开项目，尚无当前用户职责说明与确认，不生成个人业绩表述。",
        "evidence": evidence,
        "questions": [
            {"question_id": "demo_q1", "text": "Signer.sign 返回的数据由哪些部分组成？它是否隐藏原始消息？请结合返回语句解释。",
             "evidence_ids": [ids[0]],
             "expected_facts": ["返回原始 value、分隔符与签名。", "这段实现保留原始消息，不能把签名说成消息加密。"],
             "unknowns": ["候选人是否实现过这一模块。"]},
            {"question_id": "demo_q2", "text": "验签为什么可能尝试多个 secret_key？请先描述代码行为，再区分源码事实与对设计意图的推测。",
             "evidence_ids": [ids[0], ids[1]],
             "expected_facts": ["验签按 secret_keys 的反向顺序尝试。", "某个密钥验签通过即返回 True，全部失败返回 False。"],
             "unknowns": ["用户当时的设计动机不能由当前源码直接证明。"]},
            {"question_id": "demo_q3", "text": "TimestampSigner 中时间戳是否参与签名？传入 max_age 后，过期和未来时间分别走什么分支？不传 max_age 呢？",
             "evidence_ids": [ids[2], ids[3]],
             "expected_facts": ["时间戳先拼到 value 后再计算签名。", "给定 max_age 时 age 超上限或小于零会抛出 SignatureExpired。", "max_age 为 None 时不进入该年龄检查分支。"],
             "unknowns": ["部署环境的时钟同步情况不在当前证据范围内。"]}
        ],
        "answers": [], "assessment_status": "not_started", "ability_verdict": None,
        "learning_task_example": {
            "status": "example_not_a_diagnosed_user_gap", "materials": [ids[2], ids[3]],
            "action": "说明正常、超时、未来时间和未传 max_age 四种情况；逐个标出对应源码分支。",
            "completion_criterion": "四种情况均能解释条件与结果，并区分签名验证与时效检查。",
            "retest": "改为时钟比签发方慢的场景，解释现有实现会发生什么，以及还需哪些部署信息。"
        }
    }
    write_json(snapshot / "experience-card-demo.json", bundle)
    checks = {
        "all_downloaded_files_match_github_blob_and_local_hash": all(integrity),
        "snapshot_and_graph_use_same_commit": manifest["commit_sha"] == graph["commit_sha"],
        "source_references_are_commit_pinned": all(manifest["commit_sha"] in e["source_url"] for e in evidence),
        "budgeted_contribution_scope_is_marked_partial": contributions["status"] == "partial" and contributions["truncated"],
        "no_personal_ownership_or_ability_claim": bundle["resume_wording"] is None and bundle["ability_verdict"] is None,
        "automated_semantic_coverage_not_overstated": manifest["coverage"]["semantic_read_files"] == 0,
        "fixed_commit_resume_only_resolved_metadata": manifest["api_requests_last_run"] == 2,
    }
    result = {"scope": "single_saved_public_python_repository", "repository": manifest["repository"],
              "commit_sha": manifest["commit_sha"], "coverage": manifest["coverage"],
              "structure_analysis": manifest["structure_analysis"],
              "contributions": {"author_example": contributions["author"], "status": contributions["status"],
                                "commits": len(contributions["commits"]), "pull_requests": len(contributions["pull_requests"])},
              "evidence_items": len(evidence), "questions": len(bundle["questions"]),
              "checks": checks, "all_checks_passed": all(checks.values())}
    write_json(snapshot / "verification-result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
