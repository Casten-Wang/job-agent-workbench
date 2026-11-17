"""Material preview/recovery UI fixture, with isolated synthetic data only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from interview_agent.model_adapter import ModelError
from interview_agent.tests.test_workbench import ContractAgent
from workbench_agent_smoke import main

original = ContractAgent.decide


async def decide(self, stage, value):
    if stage == "prepare_experience" and value["experience"]["name"] == "超时恢复演示" and not getattr(self, "material_failed_once", False):
        self.material_failed_once = True
        raise ModelError("model_timeout")
    result = await original(self, stage, value)
    if stage == "prepare_experience":
        result["claims"][0].update(fit_reason="对应后端岗位的输入校验要求。", boundary="参与实现，未负责整个项目。", risk="实际职责仍需本人核对。")
    return result


ContractAgent.decide = decide
if __name__ == "__main__":
    main()
