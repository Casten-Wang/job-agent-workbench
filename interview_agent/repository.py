"""Reuse immutable Interview Hub records without a second local HTTP service."""

from interview_hub.plans import apply_plan, freeze_plan
from interview_hub.recap import build_recap, validate_result
from interview_hub.store import ConflictError, NotFoundError


FIELDS = ("material_id", "source_commit", "resume_version_id", "project_snapshot_id")


def metadata(value):
    return {k: value[k] for k in FIELDS}


class Repository:
    def __init__(self, store, owner):
        self.store, self.owner = store, owner

    def create(self, request, session_id):
        material = self.store.get_material(self.owner, request.material_id)["payload"]
        if request.mode == "mock_interview" and not material["resume_version_id"]:
            raise ValueError("Mock interview requires a saved resume version")
        payload = {k: material[k] for k in FIELDS if k != "material_id"}
        payload.update(mode=request.mode, target=request.target)
        try:
            record = self.store.get_session(self.owner, session_id)
        except NotFoundError:
            record = None
        if record:
            if record["material_id"] != request.material_id or any(record["payload"].get(k) != v for k, v in payload.items()):
                raise ConflictError("Session context is immutable")
            return record
        history = {}
        for claim in material["claims"]:
            for row in self.store.history(self.owner, claim["claim_id"], limit=20):
                if row["recap"] is not None:
                    old = row["session"]
                    history[old["session_id"]] = {"session_id": old["session_id"],
                        "source_commit": old["payload"]["source_commit"], "resume_version_id": old["payload"]["resume_version_id"],
                        "target": old["payload"]["target"], "created_at": old["created_at"],
                        "review_status": row["recap"]["payload"]["review_status"],
                        "recap_path": f"/v1/sessions/{old['session_id']}/recap"}
        payload["related_history"] = sorted(history.values(), key=lambda r: r["created_at"], reverse=True)[:20]
        return self.store.create_session(self.owner, session_id, request.material_id, payload)

    def context(self, session_id):
        session = self.store.get_session(self.owner, session_id)
        material = self.store.get_material(self.owner, session["material_id"])["payload"]
        try:
            plan = self.store.get_plan(self.owner, session_id)["payload"]
        except NotFoundError:
            plan = None
        return session, apply_plan(material, plan), plan

    def save_plan(self, session_id, proposed, generation):
        session, material, _ = self.context(session_id)
        return self.store.save_plan(self.owner, session_id,
            freeze_plan(material, {**metadata(material), **proposed, "generation": generation}))["payload"]

    def finalize(self, data):
        session, material, _ = self.context(data["session_id"])
        if any(data[k] != material[k] for k in (*FIELDS, "question_plan_id")):
            raise ValueError("Result bindings disagree")
        try:
            summary = self.store.get_result(self.owner, data["session_id"])["payload"].get("summary")
        except NotFoundError:
            summary = "模型生成的逐题观察草稿；不代表独立掌握、本人贡献或整体能力，简历改动须另行确认。"
        result = {**metadata(material), "session_id": data["session_id"], "question_plan_id": material["question_plan_id"],
            "answers": list(data["answers"].values()), "observations": list(data["observations"].values()),
            "assessment_generation": data["generation"], "corrections": [data["correction"]] if data.get("correction") else [],
            "summary": summary}
        validate_result(material, result)
        self.store.save_result(self.owner, data["session_id"], result)
        try:
            return self.store.get_recap(self.owner, data["session_id"])["payload"]
        except NotFoundError:
            recap = build_recap(material, {**session["payload"], "session_id": data["session_id"], "material_id": session["material_id"]},
                result, history=session["payload"].get("related_history", []))
            return self.store.save_recap(self.owner, data["session_id"], recap)["payload"]
