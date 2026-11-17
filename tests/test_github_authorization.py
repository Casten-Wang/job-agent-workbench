import json
from pathlib import Path
import tempfile
import unittest

import httpx

from github_source.authorization import GitHubAuthorization, _protect
from github_source.github_api import GitHubClient, GitHubError, _SafeRedirect
from test_github_api import FakeOpener, Response, COMMIT, TREE
import urllib.request


class GitHubAuthorizationTests(unittest.TestCase):
    def test_dpapi_round_trip(self):
        value = b"synthetic-local-secret-not-a-real-token"
        protected = _protect(value)
        self.assertEqual(_protect(protected, decrypt=True), value)
        import os
        if os.name == "nt":
            self.assertNotIn(value, protected)

    def test_device_flow_never_returns_secrets_and_respects_slow_down(self):
        now = [0]
        calls = []
        token_results = [{"error": "slow_down"}, {"access_token": "synthetic-oauth-value", "expires_in": 3600}]

        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/login/device/code":
                return httpx.Response(200, json={"device_code": "backend-only-device-value", "user_code": "ABCD-EFGH",
                    "verification_uri": "https://github.com/login/device", "interval": 5, "expires_in": 900})
            if request.url.path == "/login/oauth/access_token":
                return httpx.Response(200, json=token_results.pop(0))
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-oauth-value")
            return httpx.Response(200, json={"login": "example-user"})

        with tempfile.TemporaryDirectory() as folder:
            auth = GitHubAuthorization(folder, client=httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda: now[0])
            self.assertFalse(auth.status()["configured"])
            with self.assertRaises(GitHubError):
                auth.start()
            auth.configure("public_client_id_123")
            started = auth.start()
            self.assertNotIn("device_code", started)
            self.assertNotIn("access_token", json.dumps(started))
            self.assertEqual(auth.poll(started["ticket"])["status"], "pending")
            self.assertEqual(len(calls), 1)
            now[0] = 5
            self.assertEqual(auth.poll(started["ticket"])["interval"], 10)
            now[0] = 10
            auth.poll(started["ticket"])
            self.assertEqual(len(calls), 2)
            now[0] = 15
            connected = auth.poll(started["ticket"])
            self.assertEqual(connected["login"], "example-user")
            self.assertNotIn("synthetic-oauth-value", json.dumps(connected))
            self.assertEqual(auth.token(), "synthetic-oauth-value")
            auth.close()
            restored = GitHubAuthorization(folder)
            self.assertTrue(restored.status()["connected"])
            restored.disconnect()
            self.assertFalse(restored.status()["connected"])
            restored.close()

    def test_invalid_ticket_expiry_and_foreign_authorization_url(self):
        now = [0]
        def handler(request):
            return httpx.Response(200, json={"device_code": "private", "user_code": "ABCD-EFGH",
                "verification_uri": "https://github.com/login/device", "interval": 5, "expires_in": 1})
        with tempfile.TemporaryDirectory() as folder:
            auth = GitHubAuthorization(folder, client=httpx.Client(transport=httpx.MockTransport(handler)), clock=lambda:now[0])
            auth.configure("public_client_id_123")
            started = auth.start()
            with self.assertRaises(GitHubError):
                auth.poll("wrong-ticket")
            now[0] = 2
            self.assertEqual(auth.poll(started["ticket"])["status"], "expired")
            auth.close()

    def test_authorized_private_repo_and_redirect_strip_authorization(self):
        client = GitHubClient(token="synthetic-read-token")
        opener = FakeOpener([Response({"private": True, "default_branch": "main"}),
                             Response({"sha": COMMIT, "commit": {"tree": {"sha": TREE}}})])
        client._opener = opener
        self.assertEqual(client.resolve_repository("owner/private")["commit_sha"], COMMIT)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer synthetic-read-token")
        request = urllib.request.Request("https://api.github.com/repos/owner/private/zipball/" + COMMIT,
                                         headers={"Authorization": "Bearer synthetic-read-token"})
        redirected = _SafeRedirect(client).redirect_request(request, None, 302, "Found", {}, "https://codeload.github.com/owner/private/zip/" + COMMIT)
        self.assertFalse(redirected.has_header("Authorization"))
