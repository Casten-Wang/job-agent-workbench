"""Small, unauthenticated GitHub REST client for public source snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from .tls import tls_context


API_ROOT = "https://api.github.com"
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_TREE_REQUESTS = 1000
MAX_TREE_ITEMS = 200000
_OWNER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}\Z")
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")


class GitHubError(RuntimeError):
    """A safe message which does not contain response bodies or credentials."""


def parse_repository(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise GitHubError("Expected owner/repository or an HTTPS GitHub repository URL.")
    value = value.strip()
    if "://" in value:
        url = urllib.parse.urlsplit(value)
        if (url.scheme != "https" or url.netloc != "github.com" or url.query
                or url.fragment or url.username or url.password):
            raise GitHubError("Only plain HTTPS github.com repository URLs are supported.")
        value = url.path.removeprefix("/").removesuffix("/")
    parts = value.split("/")
    if (len(parts) != 2 or not _OWNER.fullmatch(parts[0])
            or not _REPO.fullmatch(parts[1]) or parts[1] in (".", "..")):
        raise GitHubError("Expected exactly owner/repository; branches belong in --ref.")
    return parts[0], parts[1]


def _repo_path(owner: str, repo: str) -> str:
    owner, repo = parse_repository(f"{owner}/{repo}")
    return f"/repos/{owner}/{repo}"


def _sha(value: str) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubError("GitHub returned an invalid commit or tree identifier.")
    return value.lower()


def _check_url(url: str) -> None:
    if any(ord(c) < 32 for c in url):
        raise GitHubError("Unsafe GitHub request or redirect URL.")
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in ("api.github.com", "codeload.github.com")
            or parsed.username or parsed.password or parsed.fragment):
        raise GitHubError("GitHub requests may only use HTTPS api.github.com or codeload.github.com.")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, client):
        super().__init__()
        self.client = client

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_url(newurl)
        self.client._count_request(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlsplit(req.full_url).hostname != urllib.parse.urlsplit(newurl).hostname:
            redirected.remove_header("Authorization")
        return redirected


class GitHubClient:
    """Public by default; an explicitly supplied token enables authorized repositories."""

    def __init__(self, request_timeout=30, *, token=None):
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self.request_timeout = request_timeout
        self._token = token
        self.authenticated = bool(token)
        self.api_requests = 0
        self.http_requests = 0
        self._opener = urllib.request.build_opener(_SafeRedirect(self), urllib.request.HTTPSHandler(context=tls_context()))

    @property
    def request_count(self):
        return self.api_requests

    def _count_request(self, url):
        self.http_requests += 1
        if urllib.parse.urlsplit(url).hostname == "api.github.com":
            self.api_requests += 1

    def _read(self, url, limit, accept):
        _check_url(url)
        request = urllib.request.Request(url, headers={
            "Accept": accept,
            "User-Agent": "resume-public-source-validation/0.1",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if self._token and urllib.parse.urlsplit(url).hostname == "api.github.com":
            request.add_header("Authorization", "Bearer " + self._token)
        self._count_request(url)
        try:
            with self._opener.open(request, timeout=self.request_timeout) as response:
                _check_url(response.geturl())
                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > limit:
                    raise GitHubError("GitHub response exceeds this prototype's download limit.")
                chunks = []
                size = 0
                while chunk := response.read(min(1024 * 1024, limit - size + 1)):
                    size += len(chunk)
                    if size > limit:
                        raise GitHubError("GitHub response exceeds this prototype's download limit.")
                    chunks.append(chunk)
                return b"".join(chunks)
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise GitHubError(f"GitHub returned HTTP {exc.code}; access is restricted or rate-limited.") from None
            if exc.code == 404:
                raise GitHubError("GitHub returned HTTP 404; repository/ref unavailable with public access.") from None
            raise GitHubError(f"GitHub returned HTTP {exc.code}.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise GitHubError("GitHub network request failed; check connection and retry.") from None

    def get_json(self, path, params=None):
        if (not isinstance(path, str) or not path.startswith("/") or path.startswith("//")
                or any(c in path for c in "?#\\") or any(ord(c) < 32 for c in path)):
            raise GitHubError("Expected a GitHub API path without a host or query string.")
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = self._read(url, MAX_JSON_BYTES, "application/vnd.github+json")
        try:
            return json.loads(data)
        except (ValueError, UnicodeError):
            raise GitHubError("GitHub returned invalid JSON.") from None

    def resolve_repository(self, repo, ref=None):
        owner, name = parse_repository(repo)
        path = _repo_path(owner, name)
        repository = self.get_json(path)
        if not self.authenticated and (repository.get("private") is not False or repository.get("visibility", "public") != "public"):
            raise GitHubError("This prototype only imports public repositories.")
        selected_ref = ref if ref is not None else repository.get("default_branch")
        if (not isinstance(selected_ref, str) or not selected_ref or len(selected_ref) > 1024
                or any(ord(c) < 33 for c in selected_ref)):
            raise GitHubError("A non-empty branch, tag or commit is required.")
        commit = self.get_json(path + "/commits/" + urllib.parse.quote(selected_ref, safe=""))
        try:
            commit_sha = _sha(commit["sha"])
            tree_sha = _sha(commit["commit"]["tree"]["sha"])
        except (KeyError, TypeError):
            raise GitHubError("GitHub did not return a commit with a source tree.") from None
        return {"repository": repository, "requested_ref": selected_ref,
                "commit_sha": commit_sha, "tree_sha": tree_sha}

    def get_tree(self, owner, repo, tree_sha):
        path = _repo_path(owner, repo) + "/git/trees/"
        tree_sha = _sha(tree_sha)
        result = self.get_json(path + tree_sha, {"recursive": "1"})
        if not result.get("truncated", False):
            rows = result.get("tree")
        else:
            # Discard the incomplete recursive response and enumerate every subtree.
            rows = []
            pending = [("", tree_sha)]
            requests = 0
            while pending:
                if requests >= MAX_TREE_REQUESTS:
                    raise GitHubError("Tree enumeration exceeded the subtree request limit; no complete tree saved.")
                prefix, current = pending.pop()
                page = self.get_json(path + current)
                requests += 1
                if page.get("truncated", False) or not isinstance(page.get("tree"), list):
                    raise GitHubError("A subtree was incomplete; no complete tree saved.")
                for entry in page["tree"]:
                    item = dict(entry)
                    item["path"] = prefix + item["path"]
                    if item.get("type") == "tree":
                        pending.append((item["path"] + "/", _sha(item["sha"])))
                    else:
                        rows.append(item)
                if len(rows) + len(pending) > MAX_TREE_ITEMS:
                    raise GitHubError("Tree enumeration exceeded the entry limit; no complete tree saved.")
        if not isinstance(rows, list) or len(rows) > MAX_TREE_ITEMS:
            raise GitHubError("GitHub returned an invalid or oversized file tree.")
        leaves = [dict(row) for row in rows if row.get("type") != "tree"]
        paths = [row.get("path") for row in leaves]
        if any(not isinstance(p, str) or not p for p in paths) or len(set(paths)) != len(paths):
            raise GitHubError("GitHub returned missing or duplicate file paths.")
        return sorted(leaves, key=lambda row: row["path"])

    def download_archive(self, owner, repo, commit_sha):
        path = _repo_path(owner, repo) + "/zipball/" + _sha(commit_sha)
        return self._read(API_ROOT + path, MAX_ARCHIVE_BYTES, "application/vnd.github+json")

    def _pages(self, path, params, page_limit):
        rows = []
        pages = 0
        more = False
        error = None
        for page in range(1, page_limit + 1):
            try:
                batch = self.get_json(path, {**params, "per_page": 100, "page": page})
                if not isinstance(batch, list):
                    raise GitHubError("GitHub returned an invalid contribution listing.")
                rows.extend(batch)
                pages += 1
                more = len(batch) >= 100
                if not more:
                    break
            except GitHubError as exc:
                error = str(exc)
                more = True
                break
        return rows, {"pages_fetched": pages, "page_limit": page_limit, "per_page": 100,
                      "truncated": more, "error": error}

    def get_contributions(self, owner, repo, commit_sha, author=None, page_limit=2):
        path = _repo_path(owner, repo)
        commit_sha = _sha(commit_sha)
        if not isinstance(page_limit, int) or not 1 <= page_limit <= 10:
            raise ValueError("page_limit must be between 1 and 10")
        fetched_at = datetime.now(timezone.utc).isoformat()
        result = {"fetched_at": fetched_at, "commit_sha": commit_sha,
                  "author": author, "commits": [], "pull_requests": [],
                  "ownership_verified": False}
        if author is None:
            return {**result, "status": "skipped_no_author", "skipped": True,
                    "truncated": False, "scope": "No GitHub account was supplied; personal attribution was not queried."}
        if not isinstance(author, str) or not _OWNER.fullmatch(author):
            raise GitHubError("Contribution author must be a GitHub account name.")
        commits, commit_scope = self._pages(path + "/commits", {"sha": commit_sha, "author": author}, page_limit)
        pulls, pull_scope = self._pages(path + "/pulls", {"state": "all", "sort": "created", "direction": "desc"}, page_limit)
        for row in commits:
            details = row.get("commit") or {}
            result["commits"].append({
                "sha": row.get("sha"), "html_url": row.get("html_url"),
                "message": details.get("message"),
                "author_login": (row.get("author") or {}).get("login"),
                "committer_login": (row.get("committer") or {}).get("login"),
                "authored_at": (details.get("author") or {}).get("date"),
                "fetched_at": fetched_at,
            })
        for row in pulls:
            if (row.get("user") or {}).get("login", "").casefold() != author.casefold():
                continue
            result["pull_requests"].append({
                **{key: row.get(key) for key in ("number", "title", "body", "html_url", "state", "merge_commit_sha", "created_at", "updated_at", "merged_at")},
                "author_login": row["user"]["login"], "head_sha": (row.get("head") or {}).get("sha"),
                "base_sha": (row.get("base") or {}).get("sha"),
                "snapshot_membership": "not_verified", "fetched_at": fetched_at,
            })
        truncated = commit_scope["truncated"] or pull_scope["truncated"]
        return {**result, "skipped": False, "truncated": truncated,
                "status": "partial" if truncated else "collected_with_scope",
                "scope": {
                    "commits": {**commit_scope, "source_url": API_ROOT + path + "/commits",
                                "history_start_sha": commit_sha, "github_author_filter": author},
                    "pull_requests": {**pull_scope, "source_url": API_ROOT + path + "/pulls",
                                      "listing": "Most recently created PRs across the repository, locally filtered by author; not a complete personal work history.",
                                      "snapshot_membership": "not_verified"},
                    "interpretation": "Account associations are contribution clues, not proof of authorship or independent implementation.",
                }}
