"""Synthetic provider scenarios for UI checks; no personal workspace access."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from interview_agent.tests.test_workbench import ContractAgent
from workbench_agent_smoke import main

original = ContractAgent.decide


async def decide(self, stage, value):
    if stage == "workbench_decide":
        text = value["messages"][-1]["text"]
        if text == "保持执行":
            await asyncio.Event().wait()  # Real cancellation of a pending provider.
        if text == "测试长回复":
            return {"action": "reply", "message": "\n".join(f"合成材料 {i + 1}：参与实现输入校验与失败处理。" for i in range(80)), "arguments": {}}
    return await original(self, stage, value)


ContractAgent.decide = decide
if __name__ == "__main__":
    main()
