"""Measure real HTTP deltas, reconnect and stop without personal data."""
import argparse
import json
from pathlib import Path
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=8772)
parser.add_argument("--live", action="store_true")
args = parser.parse_args()
base = f"http://127.0.0.1:{args.port}/api/workbench-agent"
out = Path(__file__).resolve().parents[1] / "outputs/workbench-token-stream"
out.mkdir(parents=True, exist_ok=True)


def call(path, payload=None):
    request = urllib.request.Request(base + path + "?mode=user", headers={"Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None)
    return json.load(urllib.request.urlopen(request, timeout=30))


def frames(response):
    kind, data = None, []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("event:"):
            kind = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            yield kind, json.loads("\n".join(data))
            kind, data = None, []


def verify(text, *, stop=False, reconnect=False, attachment=False):
    sid = call("/conversations", {"title": "合成资料流式验证"})["id"]
    path = "/conversations/" + sid
    payload = {"event_id": "synthetic-stream-check", "kind": "experience", "material_id": "mat_confirmed",
               "role": "产品经理", "model_consent": True} if attachment else {"event_id": "synthetic-stream-check", "text": text}
    started = time.monotonic()
    call(path + ("/attachments" if attachment else "/messages"), payload)
    partial, first, deltas, resets, cursor, resume_count, view = None, None, 0, 0, 0, 0, None
    stopping = False
    while True:
        resume = False
        with urllib.request.urlopen(base + path + f"/stream?mode=user&after={cursor}", timeout=150) as response:
            assert response.headers["Content-Type"].startswith("text/event-stream")
            for kind, packet in frames(response):
                assert "PRIVATE_REASONING" not in json.dumps(packet)
                if kind == "snapshot":
                    view, partial = packet["view"], packet["view"].get("streaming_message")
                    cursor = view["cursor"]
                elif kind == "text_reset":
                    partial = packet["streaming_message"]
                    resets += 1
                elif kind == "text_delta":
                    assert partial and partial["id"] == packet["id"]
                    assert len(partial["text"]) == packet["offset"], (partial, packet)
                    partial["text"] += packet["delta"]
                    deltas += 1
                elif kind == "settled":
                    break
                if partial and partial["text"]:
                    if first is None:
                        first = time.monotonic() - started
                        assert view["status"] in {"queued", "running"}
                        print("First text while model still running", flush=True)
                    if stop and not stopping:
                        result = call(path + "/stop", {})
                        assert result["status"] == "stopped"
                        stopping = True
                    if reconnect and not resume_count and deltas >= 3:
                        resume_count += 1
                        resume = True
                        break
            if resume:
                continue
        break
    ended = time.monotonic() - started
    view = call(path)
    expected = "stopped" if stop else "waiting_approval" if attachment else "completed"
    assert view["status"] == expected, view.get("error_code")
    assert first is not None and first < ended
    if not stop:
        assert deltas > 1, deltas
    if stop:
        assert view["messages"][-1]["state"] == "stopped"
    if reconnect:
        assert resume_count == 1
        assert view["messages"][-1]["text"].count("这是合成模型逐段返回的文字") == 1
    if attachment:
        assert view["pending"]["kind"] == "confirm_material"
        assert not view["artifacts"] and not view["saved_versions"]
    return {"status": view["status"], "delta_frames": deltas, "reset_frames": resets, "reconnects": resume_count,
            "first_text_seconds": round(first, 3), "finished_seconds": round(ended, 3), "before_completion": True}


report = {"data": "isolated_synthetic_only", "provider": "live" if args.live else "local_sse_fixture"}
try:
    if args.live:
        report["chat"] = verify("请用两段自然中文说明你如何帮助我准备求职简历，控制在200字左右。请直接回答，不用查询我的资料。")
        report["material"] = verify("", attachment=True)
    else:
        report["chat_and_reconnect"] = verify("测试流式回复", reconnect=True)
        report["stop"] = verify("保持流式输出", stop=True)
        report["material"] = verify("", attachment=True)
    report["passed"] = True
finally:
    (out / ("live-http.json" if args.live else "contract-http.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
