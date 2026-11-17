"""save_reviewed_greeting: 校验长度、岗位忙碌时拒绝，并只写入已核对文案。"""
import contextlib
import sys
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))
import offerpilot_runtime


def _server(acquired=True):
    server = MagicMock()
    server.job_mutation_lock = threading.RLock()

    @contextlib.contextmanager
    def claim(job_id, kind):
        yield acquired

    server.greeting_activity.claim = claim
    return server


class ReviewedGreetingTests(unittest.TestCase):
    def test_rejects_empty_and_overlong_text(self):
        with patch.object(offerpilot_runtime, "load_backend", return_value=_server()):
            for text in ("", "   ", "字" * 301):
                with self.subTest(length=len(text)), self.assertRaises(ValueError):
                    offerpilot_runtime.save_reviewed_greeting("j1", text)

    def test_busy_job_is_not_overwritten(self):
        with patch.object(offerpilot_runtime, "load_backend", return_value=_server(acquired=False)):
            with self.assertRaises(ValueError):
                offerpilot_runtime.save_reviewed_greeting("j1", "你好，我对该岗位很感兴趣")

    def test_saves_edited_selection_without_sending(self):
        server = _server()
        select = MagicMock()
        fake_db = types.SimpleNamespace(select_job_greeting=select, update_job_status=MagicMock())
        fake_pkg = types.ModuleType("offerpilot")
        fake_pkg.db = fake_db
        with patch.object(offerpilot_runtime, "load_backend", return_value=server), \
                patch.dict(sys.modules, {"offerpilot": fake_pkg, "offerpilot.db": fake_db}):
            result = offerpilot_runtime.save_reviewed_greeting("j1", "你好，我对该岗位很感兴趣")
        self.assertTrue(result["ok"])
        self.assertEqual(select.call_args.args[1:3], ("j1", "edited"))
        self.assertTrue(select.call_args.kwargs["confirmed"])


if __name__ == "__main__":
    unittest.main()
