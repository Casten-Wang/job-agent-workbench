"""A local SSE model provider for end-to-end tests, using synthetic data only."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

from interview_agent.tests.test_workbench import ContractAgent


def start_provider():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            structured = "response_format" in body
            stage = body["response_format"]["json_schema"]["name"] if structured else body["tools"][0]["function"]["name"].removeprefix("submit_")
            value = json.loads(body["messages"][1]["content"])
            text = value.get("messages", [{}])[-1].get("text", "")
            if stage == "workbench_decide" and "流式" in text:
                decision = {"action": "reply", "message": "这是合成模型逐段返回的文字😀。\n" + "先核对经历，再为目标岗位准备简历。" * 50, "arguments": {}}
            else:
                decision = asyncio.run(ContractAgent().decide(stage, value))
            raw = json.dumps({"decision": decision} if stage == "workbench_decide" else decision, ensure_ascii=False)
            if not body.get("stream"):
                payload = {"choices": [{"finish_reason": "stop" if structured else "tool_calls", "message":
                    {"content": raw} if structured else {"tool_calls": [{"id": "call_fixture", "type": "function", "function": {"name": "submit_" + stage, "arguments": raw}}]}}]}
                encoded = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.end_headers()
            try:
                for index in range(0, len(raw), 6):
                    chunk = raw[index:index + 6]
                    delta = {"content": chunk, "reasoning_content": "PRIVATE_REASONING"} if structured else {"tool_calls": [{"index": 0,
                        **({"id": "call_fixture", "type": "function"} if index == 0 else {}),
                        "function": {**({"name": "submit_" + stage} if index == 0 else {}), "arguments": chunk}}]}
                    packet = {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    self.wfile.write(("data: " + json.dumps(packet, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
                    time.sleep(.012)  # Test provider latency; production has no typing timer.
                packet = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop" if structured else "tool_calls"}]}
                self.wfile.write(("data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n").encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    return provider
