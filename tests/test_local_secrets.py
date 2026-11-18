import sys
import tempfile
from pathlib import Path
import unittest

from tools.local_secrets import load, save


class LocalSecretsTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'DPAPI 仅在 Windows 可用')
    def test_windows_dpapi_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "credentials.dpapi.json"
            save(path, {"step_api_key": "synthetic-step", "langsmith_api_key": "synthetic-langsmith"})
            self.assertNotIn("synthetic-step", path.read_text(encoding="utf-8"))
            self.assertNotIn("synthetic-langsmith", path.read_text(encoding="utf-8"))
            self.assertEqual(load(path), {"step_api_key": "synthetic-step", "langsmith_api_key": "synthetic-langsmith"})


if __name__ == "__main__":
    unittest.main()
