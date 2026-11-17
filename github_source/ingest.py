"""Commit-pinned public source snapshots. Repository code is never executed."""

from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote
import zipfile


POLICY_VERSION = "public-source-v1"
EXCLUDED_DIRS = {".git", "node_modules", "vendor", "dist", "build", "__pycache__", ".venv", "venv"}
SECRET_NAMES = {".npmrc", ".pypirc", ".netrc", "credentials.json", "id_rsa", "id_ed25519"}
SECRET_PATTERN = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{22,}|AKIA[0-9A-Z]{16}")
WINDOWS_DEVICES = {"con", "prn", "aux", "nul"} | {f"{p}{i}" for p in ("com", "lpt") for i in range(1, 10)}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_path(root, name):
    """Use the same portable path restrictions on Windows and POSIX."""
    if not isinstance(name, str) or not name or "\\" in name or any(ord(c) < 32 for c in name):
        raise ValueError("Unsafe source path")
    parts = name.split("/")
    if any(p in ("", ".", "..") or any(c in p for c in ':<>"|?*')
           or p.endswith((".", " ")) or p.split(".")[0].lower() in WINDOWS_DEVICES for p in parts):
        raise ValueError("Unsafe source path")
    root = Path(root).absolute()
    if root.is_symlink():
        raise ValueError("Source root is a symlink")
    root = root.resolve()
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError("Source path escapes snapshot")
    for parent in (target, *target.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError("Source path traverses a symlink")
    return target


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def source_lines(text):
    # GitHub anchors count LF, not Unicode line separators inside string literals.
    parts = text.split("\n")
    return [line.removesuffix("\r") for line in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def classify(entry, max_file_bytes):
    path = entry["path"]
    try:
        safe_path(Path.cwd(), path)
    except ValueError:
        return "unsafe_path"
    if entry.get("type") == "tree":
        return "directory"
    if entry.get("type") == "commit" or entry.get("mode") == "160000":
        return "submodule_not_fetched"
    if entry.get("mode") == "120000":
        return "symlink_not_followed"
    name = PurePosixPath(path).name.lower()
    if any(p.lower() in EXCLUDED_DIRS for p in PurePosixPath(path).parts):
        return "dependency_or_generated"
    if (name.startswith(".env") and not name.endswith((".example", ".sample", ".template"))
            or name in SECRET_NAMES or name.endswith((".pem", ".key", ".p12", ".pfx"))):
        return "sensitive_path"
    if name.endswith((".min.js", ".map", ".lock")) or name in {"package-lock.json", "pnpm-lock.yaml"}:
        return "dependency_or_generated"
    if entry.get("size", 0) > max_file_bytes:
        return "file_size_budget"
    return None


def _save_source(directory, entry, data):
    if blob_sha(data) != entry["sha"]:
        raise ValueError("Downloaded content does not match tree blob")
    if data.startswith(b"version https://git-lfs.github.com/spec/v1"):
        entry.update(status="excluded", reason="lfs_content_not_fetched")
        return
    if b"\0" in data:
        entry.update(status="excluded", reason="binary")
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        entry.update(status="excluded", reason="non_utf8")
        return
    if SECRET_PATTERN.search(data):
        entry.update(status="excluded", reason="suspected_secret")
        return
    target = safe_path(directory / "source", entry["path"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    entry.update(status="downloaded", reason=None, byte_count=len(data),
                 sha256=hashlib.sha256(data).hexdigest(), line_count=len(source_lines(text)))


def coverage(manifest):
    files = [e for e in manifest["files"] if e.get("type") != "tree"]
    return {"inventory_complete": manifest["inventory_complete"], "tracked_items": len(files),
            "statuses": dict(Counter(e["status"] for e in files)),
            "exclusion_reasons": dict(Counter(e["reason"] for e in files if e.get("reason"))),
            "downloaded_bytes": sum(e.get("byte_count", 0) for e in files if e["status"] == "downloaded"),
            "structure_indexed_files": sum(e.get("structure_status") == "indexed" for e in files),
            "semantic_read_files": sum(e.get("semantic_status") == "read" for e in files)}


def _persist(directory, manifest):
    manifest["updated_at"] = utc_now()
    manifest["coverage"] = coverage(manifest)
    write_json(directory / "manifest.json", manifest)


def ingest(client, repo, output, ref=None, author=None, max_files=250,
           max_file_bytes=512 * 1024, max_total_bytes=20 * 1024 * 1024):
    if min(max_files, max_file_bytes, max_total_bytes) <= 0:
        raise ValueError("Budgets must be positive")
    resolved = client.resolve_repository(repo, ref)
    metadata = resolved["repository"]
    full_name = metadata["full_name"]
    owner, name = full_name.split("/")
    sha = resolved["commit_sha"]
    directory = Path(output).resolve() / f"{owner}--{name}" / sha
    directory.mkdir(parents=True, exist_ok=True)
    policy = {"version": POLICY_VERSION, "max_files": max_files,
              "max_file_bytes": max_file_bytes, "max_total_bytes": max_total_bytes}
    existing = directory / "manifest.json"
    if existing.exists():
        manifest = json.loads(existing.read_text(encoding="utf-8"))
        if (manifest["repository_id"] != metadata["id"] or manifest["commit_sha"] != sha
                or manifest["policy"] != policy):
            raise ValueError("Existing snapshot identity or budget differs; choose a new output directory")
    else:
        tree = client.get_tree(owner, name, resolved["tree_sha"])
        files = []
        names = set()
        selected = 0
        total = 0
        for item in sorted(tree, key=lambda e: e["path"]):
            entry = {k: item[k] for k in ("path", "type", "mode", "sha", "size") if k in item}
            reason = classify(entry, max_file_bytes)
            path_key = entry["path"].casefold()
            if path_key in names:
                reason = "case_collision"
            names.add(path_key)
            if not reason and (selected >= max_files or total + entry.get("size", 0) > max_total_bytes):
                reason = "snapshot_budget"
            if not reason:
                selected += 1
                total += entry.get("size", 0)
            entry.update(status="excluded" if reason else "pending", reason=reason,
                         structure_status="not_run", semantic_status="not_read")
            files.append(entry)
        manifest = {"schema_version": 1, "mode": "authenticated_user" if getattr(client, "authenticated", False) else "public_unauthenticated_prototype", "repository_id": metadata["id"],
                    "repository": full_name, "repository_url": metadata["html_url"],
                    "fork": metadata.get("fork", False), "requested_ref": resolved["requested_ref"],
                    "commit_sha": sha, "tree_sha": resolved["tree_sha"], "created_at": utc_now(),
                    "policy": policy, "inventory_complete": True, "state": "fetching", "files": files,
                    "contribution_status": "not_run", "personal_contribution": "unconfirmed"}
    manifest["state"] = "fetching"
    manifest.pop("error_type", None)
    for entry in manifest["files"]:
        if entry["status"] == "downloaded":
            target = safe_path(directory / "source", entry["path"])
            if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
                entry.update(status="pending", reason="local_content_changed")
        elif entry["status"] == "failed":
            entry.update(status="pending", reason=None)
    _persist(directory, manifest)
    try:
        pending = [e for e in manifest["files"] if e["status"] == "pending"]
        if pending:
            archive = client.download_archive(owner, name, sha)
            with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
                archive_files = {}
                selected_paths = {e["path"] for e in pending}
                for item in bundle.infolist():
                    if item.is_dir():
                        continue
                    parts = item.filename.split("/", 1)
                    if len(parts) != 2:
                        continue
                    source_path = parts[1]
                    if source_path not in selected_paths:
                        continue
                    safe_path(directory / "source", source_path)
                    if (item.external_attr >> 16) & 0o170000 == 0o120000:
                        continue
                    if source_path in archive_files:
                        raise ValueError("Duplicate archive path")
                    archive_files[source_path] = item
                for entry in pending:
                    try:
                        info = archive_files.get(entry["path"])
                        if info is None:
                            payload = client.get_json(f"/repos/{owner}/{name}/git/blobs/{entry['sha']}")
                            if payload.get("encoding") != "base64":
                                raise ValueError("Unsupported blob encoding")
                            data = base64.b64decode(payload["content"])
                        else:
                            if info.file_size > max_file_bytes:
                                raise ValueError("Archive file exceeds budget")
                            with bundle.open(info) as handle:
                                data = handle.read(max_file_bytes + 1)
                        if len(data) > max_file_bytes:
                            raise ValueError("File exceeds budget")
                        _save_source(directory, entry, data)
                    except Exception as error:
                        entry.update(status="failed", reason=type(error).__name__)
                    _persist(directory, manifest)
        contributions_path = directory / "contributions.json"
        if (not contributions_path.exists() or manifest.get("contribution_author") != author
                or manifest.get("contribution_status") == "failed"):
            manifest["contribution_requested_author"] = author
            try:
                contributions = client.get_contributions(owner, name, sha, author=author)
                write_json(contributions_path, contributions)
                manifest.update(contribution_status=contributions.get("status", "fetched"), contribution_author=author)
                manifest.pop("contribution_error", None)
            except Exception as error:
                manifest["contribution_status"] = "failed"
                manifest["contribution_error"] = type(error).__name__
        manifest["state"] = "partial" if any(e["status"] in {"failed", "pending"} for e in manifest["files"]) or manifest["contribution_status"] in {"failed", "partial"} else "fetched_with_declared_scope"
    except BaseException as error:
        manifest.update(state="interrupted" if isinstance(error, KeyboardInterrupt) else "failed", error_type=type(error).__name__)
        _persist(directory, manifest)
        raise
    finally:
        manifest["api_requests_last_run"] = client.request_count
        _persist(directory, manifest)
    write_report(directory, manifest)
    return directory, manifest


def write_report(directory, manifest):
    c = manifest["coverage"]
    text = (f"# GitHub 数据源提取结果\n\n仓库：{manifest['repository']}\n\n"
            f"固定提交：{manifest['commit_sha']}\n\n状态：{manifest['state']}\n\n"
            f"文件清单完整：{c['inventory_complete']}；非目录项目：{c['tracked_items']}。\n\n"
            f"状态计数：{json.dumps(c['statuses'], ensure_ascii=False)}\n\n"
            f"排除或失败原因：{json.dumps(c['exclusion_reasons'], ensure_ascii=False)}\n\n"
            f"结构索引文件：{c['structure_indexed_files']}；语义阅读文件：{c['semantic_read_files']}。\n\n"
            f"贡献查询状态：{manifest['contribution_status']}；查询账号：{manifest.get('contribution_requested_author')}；已保存材料账号：{manifest.get('contribution_author')}。\n\n"
            "本结果仅为项目材料，不代表用户拥有这些工作或已经掌握相关能力。\n\n"
            "源码、测试及仓库脚本均未执行。敏感文件筛选为启发式检查，不构成无密钥保证。\n")
    (directory / "REPORT.md").write_text(text, encoding="utf-8")


def cite(directory, path, start, end):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    entry = next((e for e in manifest["files"] if e["path"] == path and e["status"] == "downloaded"), None)
    if entry is None:
        raise ValueError("Path was not downloaded in this snapshot")
    data = safe_path(directory / "source", path).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"] or blob_sha(data) != entry["sha"]:
        raise ValueError("Local source was modified; re-ingest the fixed commit")
    lines = source_lines(data.decode("utf-8"))
    if start < 1 or end < start or end > len(lines):
        raise ValueError("Line range is outside the original file")
    sha = manifest["commit_sha"]
    return {"evidence_id": hashlib.sha256(f"{manifest['repository_id']}:{sha}:{path}:{start}:{end}".encode()).hexdigest()[:24],
            "repository_id": manifest["repository_id"], "commit_sha": sha, "path": path,
            "line_start": start, "line_end": end, "blob_sha": entry["sha"], "sha256": entry["sha256"],
            "source_kind": "source_text", "extraction_kind": "extracted", "personal_contribution": "unconfirmed",
            "source_url": f"{manifest['repository_url']}/blob/{sha}/{quote(path, safe='/')}#L{start}-L{end}",
            "text": "\n".join(lines[start - 1:end])}
