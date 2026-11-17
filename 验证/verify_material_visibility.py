"""Exercise material preparation/confirmation against an isolated HTTP fixture."""
import argparse
import json
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}/api/workbench-agent"
    report = Path(__file__).resolve().parents[1] / "outputs/material-visibility/live-verification.json"

    def call(path, payload=None):
        request = urllib.request.Request(base + path + "?mode=user",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    sid = call("/conversations", {"title": "合成材料可见性验收"})["id"]

    def wait():
        deadline, last = time.monotonic() + 240, None
        while time.monotonic() < deadline:
            view = call(f"/conversations/{sid}")
            phase = view.get("material_run", {}).get("status")
            if phase != last:
                print(json.dumps({"material_phase": phase, "status": view["status"]}), flush=True)
                last = phase
            if view["status"] not in {"queued", "running", "committing", "stopping"}:
                return view
            time.sleep(.3)
        raise AssertionError("Material verification exceeded its deadline")

    try:
        call(f"/conversations/{sid}/attachments", {"event_id": "synthetic-live-material", "kind": "experience",
            "name": "合成输入校验项目", "role": "后端开发", "model_consent": True,
            "text": "虚构测试项目，用于演示接口输入校验。我参与实现输入格式校验和错误提示，输出测试用例与接口说明；未负责整个项目，没有可核实的性能增长数据。"})
        ready = wait()
        assert ready["status"] == "waiting_approval", ready.get("error_code")
        preview = ready["material_run"]["preview"]
        assert preview["project_overview"] and preview["positioning"] and preview["claims"]
        evidence_ids = {e["evidence_id"] for e in preview["evidence"]}
        assert all(set(c["evidence_ids"]) <= evidence_ids and c["source_quote"] for c in preview["claims"])
        assert not ready["artifacts"] and not ready["material_id"]
        call(f"/conversations/{sid}/approvals", {"approval_id": ready["pending"]["id"], "approved": True,
            "claim_ids": [c["claim_id"] for c in preview["claims"]]})
        saved = wait()
        assert saved["status"] == "completed" and saved["material_run"]["status"] == "confirmed"
        assert saved["material_id"] and not saved["artifacts"]
        reopened = call(f"/conversations/{sid}")
        assert reopened["material_run"]["preview"] == preview
        result = {"passed": True, "source": "live_model_synthetic_data", "claim_count": len(preview["claims"]),
                  "preview_retained_after_confirmation": True, "material_id_created": True,
                  "resume_generation_is_separate": True}
    except Exception as error:
        result = {"passed": False, "source": "live_model_synthetic_data", "error_type": type(error).__name__,
                  "detail": str(error)[:300]}
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
