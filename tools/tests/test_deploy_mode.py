#!/usr/bin/env python3
"""公网展示部署模式：默认关闭、拒绝平台自动化与密钥写入、限频、同源检查。不访问平台、不碰真实数据。"""

from __future__ import annotations

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = PROJECT_ROOT / "web"
for _path in (str(WEB_DIR), str(PROJECT_ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)
sys.dont_write_bytecode = True

import deploy_mode  # noqa: E402
import server  # noqa: E402


class PureLogicTests(unittest.TestCase):
    def test_disabled_unless_flag_is_exactly_one(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OFFERPILOT_DEPLOY", None)
            self.assertFalse(deploy_mode.enabled())
        for value in ("0", "true", ""):
            with patch.dict(os.environ, {"OFFERPILOT_DEPLOY": value}):
                self.assertFalse(deploy_mode.enabled())
        with patch.dict(os.environ, {"OFFERPILOT_DEPLOY": "1"}):
            self.assertTrue(deploy_mode.enabled())

    def test_nothing_is_blocked_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OFFERPILOT_DEPLOY_RESTRICT", None)
            self.assertIsNone(deploy_mode.blocked_reason("/api/run-tests", {}))
            self.assertIsNone(deploy_mode.blocked_reason("/api/action", {"action": "offerpilot-start"}))
            self.assertIsNone(deploy_mode.blocked_reason("/api/action", {"action": "save-ai-settings"}))

    @patch.dict(os.environ, {"OFFERPILOT_DEPLOY_RESTRICT": "1"})
    def test_platform_automation_and_key_writes_are_blocked_when_restricted(self):
        for path in ("/api/run-tests", "/api/export", "/api/offerpilot/tasks",
                     "/api/offerpilot/tasks/abc/stop", "/api/offerpilot/preflight",
                     "/api/offerpilot/conversations/sync"):
            self.assertIsNotNone(deploy_mode.blocked_reason(path, {}), path)
        for action in ("offerpilot-start", "offerpilot-reply", "offerpilot-resume-request",
                       "save-ai-settings", "test-ai-connection"):
            self.assertIsNotNone(deploy_mode.blocked_reason("/api/action", {"action": action}), action)
        for action in ("save-profile", "parse-jd", "get-ai-settings", "add-variant"):
            self.assertIsNone(deploy_mode.blocked_reason("/api/action", {"action": action}), action)

    def test_same_origin_check_replaces_loopback_check(self):
        self.assertTrue(deploy_mode.same_origin("demo.example.com", None))
        self.assertTrue(deploy_mode.same_origin("demo.example.com", "https://demo.example.com"))
        self.assertFalse(deploy_mode.same_origin("demo.example.com", "https://evil.example.org"))
        self.assertFalse(deploy_mode.same_origin("", None))
        self.assertFalse(deploy_mode.same_origin("demo.example.com", "javascript:alert(1)"))

    def test_proxy_rewritten_host_is_accepted_for_modelscope_and_forwarded_host(self):
        # 魔搭网关把 Host 改成内部地址，Origin 仍是创空间域名。
        self.assertTrue(deploy_mode.same_origin("10.0.0.8:7860", "https://castenwang-offerpilot.ms.show"))
        self.assertTrue(deploy_mode.same_origin("10.0.0.8:7860", "https://www.modelscope.cn"))
        self.assertTrue(deploy_mode.same_origin("10.0.0.8:7860", "https://my.site", "my.site"))
        self.assertFalse(deploy_mode.same_origin("10.0.0.8:7860", "https://evil.ms.show.attacker.com"))
        self.assertFalse(deploy_mode.same_origin("10.0.0.8:7860", "https://notms.show"))
        with patch.dict(os.environ, {"OFFERPILOT_ALLOWED_ORIGINS": ".example.org"}):
            self.assertTrue(deploy_mode.same_origin("10.0.0.8:7860", "https://a.example.org"))

    def test_rate_limiter_caps_per_client_and_globally_then_resets(self):
        now = [0.0]
        limiter = deploy_mode.RateLimiter(per_client=2, total=3, window=10, clock=lambda: now[0])
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        self.assertFalse(limiter.allow("c"), "global cap reached")
        now[0] = 11.0
        self.assertTrue(limiter.allow("a"))

    def test_model_paths_are_rate_limited_but_static_reads_are_not(self):
        self.assertTrue(deploy_mode.uses_model("/api/workbench-agent/messages", {}))
        self.assertTrue(deploy_mode.uses_model("/api/action", {"action": "interview-reply"}))
        self.assertFalse(deploy_mode.uses_model("/api/action", {"action": "save-profile"}))

    def test_client_id_prefers_first_forwarded_address(self):
        self.assertEqual(deploy_mode.client_id({"X-Forwarded-For": "1.2.3.4, 10.0.0.1"}, "10.0.0.2"), "1.2.3.4")
        self.assertEqual(deploy_mode.client_id({}, "10.0.0.2"), "10.0.0.2")

    def test_port_follows_PORT_and_defaults_to_7860(self):
        with patch.dict(os.environ, {"PORT": "9001"}):
            self.assertEqual(deploy_mode.listen_port(), 9001)
        with patch.dict(os.environ, {"PORT": "abc"}):
            self.assertEqual(deploy_mode.listen_port(), 7860)

    def test_without_key_variable_nothing_is_seeded(self):
        self.assertFalse(deploy_mode.seed_model_from_env({}))


class ServerTests(unittest.TestCase):
    def _serve(self):
        httpd = server.make_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return httpd.server_address[1]

    def _request(self, port, method, path, headers=None, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        conn.close()
        return result

    def test_default_mode_refuses_public_binding_and_foreign_hosts(self):
        os.environ.pop("OFFERPILOT_DEPLOY", None)
        with self.assertRaises(ValueError):
            server.make_server("0.0.0.0", 0)
        port = self._serve()
        status, _, _ = self._request(port, "GET", "/favicon.ico", {"Host": "demo.example.com"})
        self.assertEqual(status, 403)

    def test_deploy_mode_allows_public_binding_but_blocks_risky_posts_when_restricted(self):
        with patch.dict(os.environ, {"OFFERPILOT_DEPLOY": "1", "OFFERPILOT_DEPLOY_RESTRICT": "1"}):
            httpd = server.make_server("0.0.0.0", 0)
            httpd.server_close()
            port = self._serve()
            host = {"Host": "demo.example.com"}
            status, headers, _ = self._request(port, "GET", "/favicon.ico", host)
            self.assertEqual(status, 204)
            self.assertIn("modelscope.cn", headers["Content-Security-Policy"])
            self.assertNotIn("X-Frame-Options", headers)
            self.assertIn("frame-ancestors https://modelscope.cn", headers["Content-Security-Policy"])
            status, _, body = self._request(port, "POST", "/api/run-tests", host, {})
            self.assertEqual(status, 403)
            self.assertIn("公网展示版", json.loads(body)["error"])
            status, _, _ = self._request(port, "POST", "/api/action", host, {"action": "offerpilot-start"})
            self.assertEqual(status, 403)
            status, _, _ = self._request(port, "POST", "/api/action", host, {"action": "save-ai-settings", "api_key": "x"})
            self.assertEqual(status, 403)
            status, _, _ = self._request(port, "GET", "/favicon.ico", {**host, "Origin": "https://evil.example.org"})
            self.assertEqual(status, 403)

    def test_default_mode_keeps_frame_denial(self):
        os.environ.pop("OFFERPILOT_DEPLOY", None)
        port = self._serve()
        status, headers, _ = self._request(port, "GET", "/favicon.ico", {"Host": "127.0.0.1"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])


class PackagingTests(unittest.TestCase):
    def test_dockerfile_listens_on_7860_and_starts_in_deploy_mode(self):
        text = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("EXPOSE 7860", text)
        self.assertIn("--deploy", text)
        self.assertIn("rm -rf web/data", text)

    def test_deploy_script_ships_only_tracked_files_and_keeps_the_token_out_of_args(self):
        text = (PROJECT_ROOT / "tools" / "deploy_modelscope.sh").read_text(encoding="utf-8")
        self.assertIn("git -C \"$ROOT\" archive HEAD", text)
        self.assertNotIn("--force", text)
        self.assertNotIn("push -f", text)

    def test_dockerignore_excludes_personal_data(self):
        ignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").split()
        for entry in ("web/data", "workspace", "resume-source.md", ".env", ".venv"):
            self.assertIn(entry, ignore)


if __name__ == "__main__":
    unittest.main()
