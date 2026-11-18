"""Local deterministic checks. Only numeric results may leave this process."""

from pydantic import ValidationError


def evaluate(stage, inputs, output):
    from .decisions import OUTPUTS
    from .experience import experience_issues
    from .project_writing import writing_issues
    from .resume_profile import compact

    schema = OUTPUTS.get(stage)
    if schema is None:
        return {}
    candidate = {"decision": output} if stage == "workbench_decide" else output
    try:
        data = schema.model_validate(candidate).model_dump(exclude_none=True)
    except (ValidationError, TypeError, ValueError):
        return {"schema_valid": 0.0}
    scores = {"schema_valid": 1.0}
    if stage in {"prepare", "prepare_experience"}:
        evidence = inputs.get("evidence", [])
        allowed = {item["evidence_id"] for item in evidence}
        scores["evidence_references_valid"] = float(all(
            bool(claim["evidence_ids"]) and set(claim["evidence_ids"]).issubset(allowed)
            for claim in data["claims"]))
        scores["resume_writing_rules"] = float(not writing_issues(data))
        if stage == "prepare_experience":
            scores["experience_source_supported"] = float(not experience_issues(data, evidence))
    if stage == "profile_extract":
        source = compact(inputs.get("resume_text", ""))
        checks = []
        def supported(value, within):
            if isinstance(value, str) and value.strip():
                checks.append(compact(value) in within)
            elif isinstance(value, list):
                for item in value:
                    supported(item, within)
            elif isinstance(value, dict):
                for item in value.values():
                    supported(item, within)
        for section in ("basic", "job_intent", "skills", "summary"):
            supported(data[section], source)
        for section in ("education", "experiences", "projects"):
            for row in data[section]:
                quote = compact(row["source_quote"])
                checks.append(bool(quote) and quote in source)
                supported({k: v for k, v in row.items() if k != "source_quote"}, quote)
        if checks:
            scores["extracted_fields_supported"] = sum(checks) / len(checks)
    return scores
