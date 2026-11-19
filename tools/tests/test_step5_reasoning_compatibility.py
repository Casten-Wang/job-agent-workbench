"""Step 5 uses reasoning_effort rather than a disabled thinking request."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "vendor/offerpilot/src"))
from offerpilot.ai import credentials


class Step5ReasoningCompatibilityTests(unittest.TestCase):
    def call(self, mode, *, model="step-5-preview", base="https://api.stepfun.com/step_plan/v1"):
        config = {"ai": {"provider": "openai_compatible", "service": "custom",
                         "model": model, "base_url": base, "thinking": mode}}
        response = Mock()
        response.json.return_value = {"choices": [{"finish_reason": "stop", "message": {"content": "fixture output"}}]}
        with patch.object(credentials, "get_ai_api_key", return_value="fixture-key"), patch.object(
            credentials.httpx, "post", return_value=response
        ) as post:
            result = credentials.call_openai_compatible_text("fixture prompt", config, 16384, purpose="materials")
        self.assertEqual(result, "fixture output")
        self.assertEqual(post.call_count, 1)
        return post.call_args.kwargs["json"]

    def test_auto_and_disabled_use_supported_low_reasoning(self):
        for mode in ("auto", "disabled"):
            request = self.call(mode)
            self.assertEqual(request.get("reasoning_effort"), "low")
            self.assertNotIn("thinking", request)
            self.assertEqual(request["max_tokens"], 16384)

    def test_enabled_keeps_provider_default_reasoning(self):
        self.assertNotIn("reasoning_effort", self.call("enabled"))

    def test_other_models_keep_their_existing_protocol(self):
        self.assertEqual(self.call("auto", model="other-model")["thinking"], {"type": "disabled"})
        self.assertEqual(self.call("auto", base="https://example.test/v1")["thinking"], {"type": "disabled"})
