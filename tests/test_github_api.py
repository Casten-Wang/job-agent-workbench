import io
import json
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from github_source.github_api import GitHubClient, GitHubError, _SafeRedirect, parse_repository


COMMIT = "c" * 40
TREE = "d" * 40
SUBTREE = "e" * 40
BLOB = "f" * 40


class Response(io.BytesIO):
    def __init__(self, payload, url="https://api.github.com/test", headers=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.url = url
        self.headers = headers or {}

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


def client_with(*responses):
    opener = FakeOpener(responses)
    with patch("urllib.request.build_opener", return_value=opener):
        client = GitHubClient()
    return client, opener


class GitHubAPITests(unittest.TestCase):
    def test_repository_validation_rejects_other_hosts_and_extra_paths(self):
        self.assertEqual(parse_repository("https://github.com/owner/repo/"), ("owner", "repo"))
        for value in ("https://evil.test/owner/repo", "https://github.com@evil.test/a/b", "https://github.com/a/b?x=1", "a/../b", "a/..", "a/b/tree/main", "a/b\n", "http://github.com/a/b", "//github.com/a/b", "https://github.com:443/a/b"):
            with self.subTest(value=value), self.assertRaises(GitHubError):
                parse_repository(value)

    def test_resolve_pins_default_branch_and_never_sends_authorization(self):
        client, opener = client_with(
            Response({"id": 1, "full_name": "owner/repo", "private": False, "default_branch": "main"}),
            Response({"sha": COMMIT, "commit": {"tree": {"sha": TREE}}}),
        )
        with patch.dict("os.environ", {"GITHUB_TOKEN": "do-not-use-this", "GH_TOKEN": "also-private"}):
            resolved = client.resolve_repository("owner/repo")
        self.assertEqual((resolved["requested_ref"], resolved["commit_sha"], resolved["tree_sha"]), ("main", COMMIT, TREE))
        self.assertTrue(opener.requests[1].full_url.endswith("/commits/main"))
        self.assertTrue(all(not req.has_header("Authorization") for req in opener.requests))
        self.assertEqual(client.request_count, 2)

    def test_branch_with_slash_is_encoded_as_a_ref(self):
        client, opener = client_with(Response({"private": False}), Response({"sha": COMMIT, "commit": {"tree": {"sha": TREE}}}))
        client.resolve_repository("owner/repo", "feature/test")
        self.assertTrue(opener.requests[-1].full_url.endswith("/commits/feature%2Ftest"))

    def test_private_repository_is_rejected_before_reading_files(self):
        client, opener = client_with(Response({"private": True, "default_branch": "main"}))
        with self.assertRaisesRegex(GitHubError, "only imports public"):
            client.resolve_repository("owner/private")
        self.assertEqual(len(opener.requests), 1)

    def test_truncated_tree_is_rebuilt_from_all_subtrees(self):
        client, opener = client_with(
            Response({"truncated": True, "tree": [{"path": "incomplete.txt", "type": "blob"}]}),
            Response({"truncated": False, "tree": [
                {"path": "README.md", "type": "blob", "sha": BLOB, "mode": "100644"},
                {"path": "src", "type": "tree", "sha": SUBTREE, "mode": "040000"}]}),
            Response({"truncated": False, "tree": [
                {"path": "app.py", "type": "blob", "sha": BLOB, "mode": "100644"}]}),
        )
        rows = client.get_tree("owner", "repo", TREE)
        self.assertEqual([r["path"] for r in rows], ["README.md", "src/app.py"])
        self.assertNotIn("?", opener.requests[1].full_url)
        self.assertNotIn("?", opener.requests[2].full_url)

    def test_non_recursive_truncation_fails_instead_of_claiming_complete(self):
        client, _ = client_with(Response({"truncated": True}), Response({"truncated": True, "tree": []}))
        with self.assertRaisesRegex(GitHubError, "subtree was incomplete"):
            client.get_tree("owner", "repo", TREE)

    def test_tree_budget_exhaustion_fails_explicitly(self):
        client, _ = client_with(Response({"truncated": True}))
        with patch("github_source.github_api.MAX_TREE_REQUESTS", 0), self.assertRaisesRegex(GitHubError, "request limit"):
            client.get_tree("owner", "repo", TREE)

    def test_duplicate_paths_fail(self):
        client, _ = client_with(Response({"tree": [{"path": "a", "type": "blob"}, {"path": "a", "type": "blob"}]}))
        with self.assertRaisesRegex(GitHubError, "duplicate"):
            client.get_tree("owner", "repo", TREE)

    def test_archive_is_pinned_and_size_bounded(self):
        client, opener = client_with(Response(b"ZIP", url="https://codeload.github.com/owner/repo/legacy.zip/" + COMMIT))
        self.assertEqual(client.download_archive("owner", "repo", COMMIT), b"ZIP")
        self.assertTrue(opener.requests[0].full_url.endswith("/zipball/" + COMMIT))
        client, _ = client_with(Response(b"too much"))
        with patch("github_source.github_api.MAX_ARCHIVE_BYTES", 3), self.assertRaisesRegex(GitHubError, "download limit"):
            client.download_archive("owner", "repo", COMMIT)

    def test_redirects_only_allow_expected_https_hosts(self):
        client, _ = client_with()
        handler = _SafeRedirect(client)
        request = urllib.request.Request("https://api.github.com/archive")
        allowed = handler.redirect_request(request, None, 302, "Found", {}, "https://codeload.github.com/a/b/zip/main")
        self.assertEqual(urllib.parse.urlsplit(allowed.full_url).hostname, "codeload.github.com")
        for target in ("https://evil.test/a", "http://codeload.github.com/a", "https://api.github.com@evil.test/a", "https://codeload.github.com:8443/a"):
            with self.subTest(target=target), self.assertRaises(GitHubError):
                handler.redirect_request(request, None, 302, "Found", {}, target)

    def test_final_response_url_is_checked(self):
        client, _ = client_with(Response(b"ZIP", url="https://evil.test/not-github"))
        with self.assertRaises(GitHubError):
            client.download_archive("owner", "repo", COMMIT)

    def test_api_path_cannot_override_host(self):
        client, opener = client_with()
        for path in ("https://evil.test", "//evil.test", "/x?redirect=evil", "/x\\a", "/x\n"):
            with self.subTest(path=path), self.assertRaises(GitHubError):
                client.get_json(path)
        self.assertEqual(opener.requests, [])

    def test_http_error_does_not_expose_body(self):
        error = urllib.error.HTTPError("https://api.github.com/x", 403, "Forbidden SECRET", {}, io.BytesIO(b"PRIVATE BODY"))
        client, _ = client_with(error)
        with self.assertRaises(GitHubError) as result:
            client.get_json("/x")
        self.assertNotIn("SECRET", str(result.exception))
        self.assertNotIn("PRIVATE", str(result.exception))
        self.assertIn("403", str(result.exception))

    def test_no_author_skips_personal_attribution(self):
        client, opener = client_with()
        result = client.get_contributions("owner", "repo", COMMIT)
        self.assertTrue(result["skipped"])
        self.assertFalse(result["ownership_verified"])
        self.assertEqual(opener.requests, [])

    def test_contributions_are_snapshot_pinned_and_bounded(self):
        commits = [{"sha": BLOB, "html_url": "https://github.com/owner/repo/commit/" + BLOB,
                    "author": {"login": "alice"}, "commit": {"message": "fix"}}] * 100
        pulls = [{"number": 4, "user": {"login": "Alice"}, "head": {"sha": BLOB}, "base": {"sha": TREE}},
                 {"number": 5, "user": {"login": "someone-else"}}]
        client, opener = client_with(Response(commits), Response(pulls))
        result = client.get_contributions("owner", "repo", COMMIT, "alice", page_limit=1)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["pull_requests"]), 1)
        self.assertEqual(result["pull_requests"][0]["snapshot_membership"], "not_verified")
        self.assertIn("sha=" + COMMIT, opener.requests[0].full_url)
        self.assertNotIn("author=", opener.requests[1].full_url)
        self.assertTrue(result["commits"][0]["fetched_at"])

    def test_contribution_pagination_and_partial_failure_keep_existing_rows(self):
        commits = [{"sha": BLOB, "commit": {}}] * 100
        client, _ = client_with(Response(commits), GitHubError("API failed safely"), Response([]))
        result = client.get_contributions("owner", "repo", COMMIT, "alice")
        self.assertEqual(len(result["commits"]), 100)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["scope"]["commits"]["pages_fetched"], 1)
        self.assertEqual(result["scope"]["commits"]["error"], "API failed safely")


if __name__ == "__main__":
    unittest.main()
