"""Small diagnostic: record response shape only, never provider prose or secrets."""
import asyncio
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from interview_agent.model_adapter import ModelAdapter
from interview_agent.decisions import Hint


async def probe(key):
    adapter = await ModelAdapter({"STEP_API_KEY": key}).start()
    try:
        for mode in ("forced", "auto"):
            response = await adapter.client.post(adapter.base_url + "/chat/completions", json={
                "model": adapter.model, "max_tokens": 1024, "reasoning_effort": "low", "stream": False,
                "messages": [{"role": "system", "content": "Only call submit_hint once."},
                             {"role": "user", "content": 'Give a short hint in Chinese and cite evidence_ids ["e1"].'}],
                "tools": [{"type": "function", "function": {"name": "submit_hint", "description": "Submit a hint.", "parameters": Hint.model_json_schema()}}],
                "tool_choice": {"type": "function", "function": {"name": "submit_hint"}} if mode == "forced" else "auto"})
            report = {"mode": mode, "http_status": response.status_code}
            if response.status_code == 200:
                choice = response.json()["choices"][0]
                message = choice["message"]
                content = message.get("content") or ""
                report.update(finish_reason=choice["finish_reason"], message_keys=list(message),
                    tool_count=len(message.get("tool_calls") or []), text_length=len(content),
                    text_has_tool_marker="tool_call" in content,
                    returned_model=response.json().get("model"))
            print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(probe(getpass.getpass("Step API key (hidden): ")))
