"""ModelSettings follows the 设置 AI panel configuration.

The panel writes key, base URL and model into the gitignored OfferPilot config,
which is the only source: process environment variables and other local
credential files are deliberately ignored.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _path in (PROJECT_ROOT / "tools", PROJECT_ROOT / "web"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from workbench_services import ModelSettings  # noqa: E402

API_KEY = "fixture-ai-key-0000"
BASE_URL = "https://model.example.com/v1"
MODEL = "fixture-chat-model"
ENV_ONLY = {
    "INTERVIEW_API_KEY": "environment-only-key",
    "INTERVIEW_MODEL": "environment-only-model",
    "INTERVIEW_BASE_URL": "https://environment.example.com/v1",
    "STEP_API_KEY": "environment-only-step-key",
}


class _FakeRuntime:
    """Stand-in for the embedded OfferPilot backend module."""

    CONFIG_PATH = Path("/fixture/config.yaml")

    def __init__(self, config, key):
        self.config = config
        self.key = key
        self.loaded_paths = []

    def load_config(self, path):
        self.loaded_paths.append(Path(path))
        return self.config

    def get_ai_api_key(self, config):
        return self.key if config is self.config else None


def _config(**ai):
    return {"ai": {"service": "custom", "base_url": BASE_URL, "model": MODEL,
                   "api_key": API_KEY, **ai}}


class WorkbenchModelSyncTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)

    def _settings(self, server, env=None):
        with patch.dict(os.environ, ENV_ONLY if env is None else env), \
                patch("offerpilot_runtime.load_backend", return_value=server):
            return ModelSettings(self.root)

    def test_model_settings_follow_the_ai_panel(self):
        server = _FakeRuntime(_config(), API_KEY)
        settings = self._settings(server)
        config = settings.model_config()
        self.assertEqual(config["base_url"], BASE_URL)
        self.assertEqual(config["model"], MODEL)
        self.assertEqual(config["api_key"], API_KEY)
        self.assertTrue(settings.status()["configured"])
        self.assertEqual(settings.status()["model"], MODEL)
        self.assertEqual(server.loaded_paths, [_FakeRuntime.CONFIG_PATH])
        self.assertEqual(settings.endpoint["INTERVIEW_BASE_URL"], BASE_URL)
        self.assertEqual(settings.endpoint["INTERVIEW_MODEL"], MODEL)
        environment = settings.configured_environment("next-key")
        self.assertEqual(environment["INTERVIEW_BASE_URL"], BASE_URL)
        self.assertEqual(environment["INTERVIEW_MODEL"], MODEL)
        self.assertEqual(environment["INTERVIEW_API_KEY"], "next-key")
        self.assertEqual(environment["INTERVIEW_PROVIDER"], "custom")

    def test_environment_credentials_never_enter_the_endpoint(self):
        settings = self._settings(_FakeRuntime(_config(), API_KEY))
        config = settings.model_config()
        self.assertEqual(config["api_key"], API_KEY)
        self.assertEqual(config["model"], MODEL)
        self.assertEqual(config["base_url"], BASE_URL)
        self.assertEqual(settings.generation["model"], MODEL)
        environment = settings.configured_environment("panel-key")
        for name in ("INTERVIEW_API_KEY", "INTERVIEW_MODEL", "INTERVIEW_BASE_URL",
                     "STEP_API_KEY", "STEPFUN_API_KEY"):
            with self.subTest(name=name):
                self.assertNotIn(environment.get(name), ENV_ONLY.values())
        self.assertEqual(environment["INTERVIEW_API_KEY"], "panel-key")
        self.assertEqual(environment["INTERVIEW_MODEL"], MODEL)
        self.assertEqual(environment["INTERVIEW_BASE_URL"], BASE_URL)

    def test_status_never_exposes_the_key(self):
        settings = self._settings(_FakeRuntime(_config(), API_KEY))
        status = settings.status()
        self.assertTrue(status["configured"])
        self.assertNotIn(API_KEY, json.dumps(status, ensure_ascii=False))
        self.assertNotIn(API_KEY, json.dumps(settings.generation, ensure_ascii=False))

    def test_repeated_sync_of_the_same_configuration_is_a_no_op(self):
        server = _FakeRuntime(_config(), API_KEY)
        settings = self._settings(server)
        revision = settings.revision
        with patch("offerpilot_runtime.load_backend", return_value=server):
            settings.sync_workbench_config()
        self.assertEqual(settings.revision, revision)
        self.assertIsNone(settings.pending_key)

    def test_incomplete_or_unavailable_config_is_ignored(self):
        settings = self._settings(_FakeRuntime({"ai": {}}, ""))
        self.assertFalse(settings.status()["configured"])
        self.assertEqual(settings.endpoint, {})
        self.assertIsNone(settings.model_config())
        with patch("offerpilot_runtime.load_backend", side_effect=RuntimeError("unavailable")):
            settings.sync_workbench_config()
        self.assertEqual(settings.endpoint, {})
        # 环境变量不是备用来源：配置缺失时仍保持未配置。
        self.assertFalse(settings.status()["configured"])
        self.assertIsNone(settings.model_config())


if __name__ == "__main__":
    unittest.main()
