"""Accumulate Chat Completions SSE while exposing only provisional public prose."""

import json
from pydantic_core import from_json


def public_text(stage, raw):
    try:
        value = from_json(raw, allow_partial="trailing-strings")
    except ValueError:
        return ""
    if not isinstance(value, dict):
        return ""
    if stage == "workbench_decide":
        decision = value.get("decision")
        if not isinstance(decision, dict) or decision.get("action") not in {"ask", "reply"}:
            return ""
        return decision.get("message") if isinstance(decision.get("message"), str) else ""
    parts = []
    for key, item in value.items():
        if stage == "prepare_experience" and key in {"summary", "project_overview"} and isinstance(item, str):
            parts.append(item)
        elif stage == "workbench_draft" and key == "greeting" and isinstance(item, str):
            parts.append(item)
        elif (stage, key) in {("prepare_experience", "claims"), ("workbench_draft", "bullets"), ("workbench_recommend", "items")} and isinstance(item, list):
            field = "reason" if key == "items" else "text"
            parts.extend(row[field] for row in item if isinstance(row, dict) and isinstance(row.get(field), str))
    return "\n\n".join(part for part in parts if part)


async def read_completion(client, url, payload, stage, on_text):
    """Return the ordinary completion envelope for the existing strict validator."""
    await on_text("")  # A retry replaces its provisional output, never appends it.
    async with client.stream("POST", url, json=payload) as response:
        if response.status_code != 200:
            return response.status_code, None
        content, calls, finish, previous = "", {}, None, ""
        lines = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                lines.append(line[5:].lstrip(" "))
                continue
            if line or not lines:
                continue
            raw, lines = "\n".join(lines), []
            if raw == "[DONE]":
                break
            packet = json.loads(raw)
            choices = packet.get("choices", [])
            if not choices:
                continue  # Optional final usage frame.
            if len(choices) != 1 or choices[0].get("index", 0) != 0:
                raise ValueError("Expected one streamed choice")
            choice = choices[0]
            delta = choice.get("delta", {})
            if isinstance(delta.get("content"), str):
                content += delta["content"]
            for fragment in delta.get("tool_calls") or []:
                index = fragment["index"]
                call = calls.setdefault(index, {"id": "", "type": None, "function": {"name": "", "arguments": ""}})
                if fragment.get("type"):
                    call["type"] = fragment["type"]
                if fragment.get("id"):
                    call["id"] = fragment["id"]
                function = fragment.get("function") or {}
                for field in ("name", "arguments"):
                    if isinstance(function.get(field), str):
                        call["function"][field] += function[field]
            if choice.get("finish_reason"):
                finish = choice["finish_reason"]
            preview = content if stage.startswith("workbench_") else (
                calls[0]["function"]["arguments"] if len(calls) == 1 and 0 in calls
                and calls[0]["function"]["name"] == "submit_" + stage else "")
            text = public_text(stage, preview)
            if text != previous:
                await on_text(text)
                previous = text
        if finish is None:
            raise ValueError("Stream ended before the completion finished")
        message = {"content": content}
        if calls:
            message["tool_calls"] = [calls[key] for key in sorted(calls)]
        return 200, {"choices": [{"finish_reason": finish, "message": message}]}
