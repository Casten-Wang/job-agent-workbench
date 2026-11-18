"""对话助理的文案与按钮状态：不暴露内部字段名；没有草稿时「草稿与结果」不可点并说明原因。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from interview_agent.workbench_contracts import INSTRUCTIONS  # noqa: E402

AGENT_JS = (ROOT / "web" / "static" / "workbench-agent.js").read_text(encoding="utf-8")
AGENT_CSS = (ROOT / "web" / "static" / "workbench-agent.css").read_text(encoding="utf-8")


class AssistantWordingTests(unittest.TestCase):
    def test_decide_prompt_forbids_internal_ids_in_user_text(self) -> None:
        prompt = INSTRUCTIONS["workbench_decide"]
        self.assertIn("不写 job_id、material_id 等编号或字段名", prompt)
        self.assertIn("还没有确认过的项目材料", prompt)
        # 原有约束保持：只能引用真实编号用于工具参数。
        self.assertIn("只能引用真实编号", prompt)

    def test_results_button_is_disabled_with_reason_when_nothing_to_show(self) -> None:
        self.assertIn("$('show-results').disabled=!hasResults;", AGENT_JS)
        self.assertIn("还没有可看的内容", AGENT_JS)
        self.assertIn(
            "const hasResults=Boolean(current?.artifacts?.length || materialResult()?.preview);",
            AGENT_JS,
        )

    def test_welcome_eyebrow_is_not_all_caps_and_tracking_is_tight(self) -> None:
        self.assertNotIn("node('p','OFFERPILOT','wa-eyebrow')", AGENT_JS)
        self.assertNotIn("letter-spacing:.16em", AGENT_CSS)


if __name__ == "__main__":
    unittest.main()
