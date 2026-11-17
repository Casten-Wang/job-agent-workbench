"""AI settings in 08 设置: saved through the credential split, key never returned."""

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

WEB = Path(__file__).resolve().parents[2] / "web"
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

import backend
import offerpilot_runtime as runtime

SYNTHETIC_KEY = "sk-synthetic-ai-settings-key-0001"


class AiSettingsTests(unittest.TestCase):
    def setUp(self):
        if str(runtime.VENDOR_SRC) not in sys.path:
            sys.path.insert(0, str(runtime.VENDOR_SRC))
        try:
            from offerpilot import config as vendor_config
            from offerpilot.ai import credentials
        except Exception as exc:  # pragma: no cover - vendored deps missing
            self.skipTest(f"vendored offerpilot unavailable: {exc}")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.yaml"
        server = types.SimpleNamespace(
            CONFIG_PATH=self.path,
            load_config=vendor_config.load_config,
            get_ai_api_key=credentials.get_ai_api_key,
        )
        patcher = patch.object(runtime, "load_backend", return_value=server)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = patch.object(backend, "get_store")
        self.store = store.start()
        self.addCleanup(store.stop)

    def save(self, **overrides):
        payload = {"service": "deepseek", "model": "deepseek-chat", "base_url": "", "api_key": SYNTHETIC_KEY, **overrides}
        return backend.ACTIONS["save-ai-settings"]({"mode": "user", **payload})

    def test_actions_are_registered(self):
        self.assertIn("get-ai-settings", backend.ACTIONS)
        self.assertIn("save-ai-settings", backend.ACTIONS)

    def test_save_never_returns_or_logs_the_key_and_keeps_it_out_of_config_yaml(self):
        result = self.save()
        self.assertTrue(result["ok"])
        self.assertEqual(result["settings"]["service"], "deepseek")
        self.assertTrue(result["settings"]["key_configured"])
        self.assertNotIn(SYNTHETIC_KEY, repr(result))
        self.assertNotIn(SYNTHETIC_KEY, repr(self.store.return_value.log.call_args_list))
        self.assertNotIn(SYNTHETIC_KEY, self.path.read_text(encoding="utf-8"))
        read = backend.ACTIONS["get-ai-settings"]({"mode": "user"})
        self.assertTrue(read["key_configured"])
        self.assertNotIn(SYNTHETIC_KEY, repr(read))

    def test_empty_key_keeps_the_stored_key(self):
        self.save()
        again = self.save(model="deepseek-reasoner", api_key="")
        self.assertEqual(again["settings"]["model"], "deepseek-reasoner")
        self.assertTrue(again["settings"]["key_configured"])

    def test_invalid_values_are_rejected_with_400(self):
        for overrides in ({"service": "shell"}, {"model": ""}, {"model": "has space"}, {"base_url": "ftp://x"}, {"api_key": "k" * 600}):
            with self.subTest(overrides=overrides), self.assertRaises(backend.ApiError) as raised:
                self.save(**overrides)
            self.assertEqual(raised.exception.status, 400)

    def test_ui_markup_exposes_the_form_in_data_view(self):
        html = (WEB / "static" / "index.html").read_text(encoding="utf-8")
        data_view = html[html.index('id="view-data"'):]
        for anchor in ("ai-settings-form", "ai-settings-service", "ai-settings-model", "ai-settings-base-url", "ai-settings-key"):
            self.assertIn(f'id="{anchor}"', data_view)
        self.assertIn('type="password"', data_view[data_view.index('id="ai-settings-key"'):][:120])

    def test_connection_test_reports_success_failure_and_missing_key_without_leaking_key(self):
        self.assertIn("test-ai-connection", backend.ACTIONS)
        no_key = backend.ACTIONS["test-ai-connection"]({"mode": "user"})
        self.assertFalse(no_key["ok"])
        self.save()
        from offerpilot.ai import credentials
        with patch.object(credentials, "call_anthropic_text", return_value="成功") as call:
            ok = backend.ACTIONS["test-ai-connection"]({"mode": "user"})
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["model"], "deepseek-chat")
        self.assertEqual(call.call_args.args[2], 64)
        with patch.object(credentials, "call_anthropic_text", side_effect=RuntimeError("401 Bearer " + SYNTHETIC_KEY)):
            failed = backend.ACTIONS["test-ai-connection"]({"mode": "user"})
        self.assertFalse(failed["ok"])
        self.assertNotIn(SYNTHETIC_KEY, str(failed))
        with patch.object(credentials, "call_anthropic_text", return_value=None):
            empty = backend.ACTIONS["test-ai-connection"]({"mode": "user"})
        self.assertFalse(empty["ok"])


if __name__ == "__main__":
    unittest.main()
