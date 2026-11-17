"""Full text snapshots for local retrieval; never execute repository contents."""

import base64
from copy import deepcopy
import hashlib
import json
from pathlib import PurePosixPath
from urllib.parse import quote

from github_source.github_api import GitHubError, parse_repository
from github_source.ingest import (
    SECRET_PATTERN, _save_source, blob_sha, classify, safe_path, source_lines, write_json,
)
from .document_text import DocumentError, EXTRACTOR_VERSION, MAX_DOCUMENT_BYTES, extract_document

MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_TOTAL_BYTES = 20 * 1024 * 1024
DOCUMENT_SUFFIXES = {".pdf", ".pptx"}
# These formats need a separate extractor; their exclusion is not a gap in
# the declared plain-text index, regardless of attachment size.
NON_TEXT_ATTACHMENTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
                        ".pdf", ".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx",
                        ".zip", ".7z", ".gz", ".tar", ".mp3", ".mp4", ".wav", ".woff", ".woff2", ".ttf"}


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def document_documents(directory, entry, data):
    target = safe_path(directory / 'documents', entry['path'])
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or fingerprint(target.read_bytes()) != fingerprint(data):
        target.write_bytes(data)
    sha = fingerprint(data)
    # Content fingerprints already identify the file; keep this cache at the
    # owner root so Windows paths do not repeat repository and commit names.
    cached = directory.parents[2] / 'document-text' / f'{sha}-v{EXTRACTOR_VERSION}.json'
    result = None
    if cached.is_file() and cached.stat().st_size <= 2 * 1024 * 1024:
        try:
            saved = json.loads(cached.read_text(encoding='utf-8'))
            if (saved['sha256'] == sha and saved['extractor_version'] == EXTRACTOR_VERSION
                    and all(fingerprint(u['text'].encode('utf-8')) == u['text_sha256'] for u in saved['units'])):
                result = saved
        except (ValueError, KeyError, TypeError):
            pass
    if result is None:
        result = extract_document(target)
        if not result['units_without_text']:
            write_json(cached, result)
    if any(SECRET_PATTERN.search(unit['text'].encode('utf-8')) for unit in result['units']):
        entry.update(status='excluded', reason='suspected_secret')
        return [], None
    readable = [unit for unit in result['units'] if unit['text']]
    entry.update(status='downloaded' if readable else 'excluded',
                 reason='document_no_text' if not readable else 'document_units_without_text' if result['units_without_text'] else None,
                 sha256=sha, document_units=result['unit_count'], text_units=len(readable),
                 ocr_units=sum(unit['needs_review'] for unit in readable),
                 units_without_text=result['units_without_text'],
                 extraction_errors=sorted({u['error'] for u in result['units'] if u.get('error')}))
    documents = [{**unit, 'path': entry['path'], 'sha256': sha, 'source_kind': 'document_text'} for unit in readable]
    metadata = {'path': entry['path'], 'sha256': sha, 'source_kind': 'document_text',
                'extractor_version': result['extractor_version'],
                'extracted_text_sha256': fingerprint(json.dumps([
                    [u['unit_type'],u['unit_number'],u['extraction_kind'],u['text_sha256']]
                    for u in result['units']], ensure_ascii=False).encode('utf-8')),
                'unit_count': result['unit_count'], 'text_units': len(readable),
                'units_without_text': result['units_without_text'],
                'ocr_units': sum(u['needs_review'] for u in readable),
                'line_count': sum(len(source_lines(u['text'])) for u in readable)}
    return documents, metadata


def github_documents(root, cache, source, client_factory, stopped, progress):
    """Reuse the pinned inventory and verified local files before asking GitHub."""
    owner, name = parse_repository(source["repository"])
    commit = source.get("source_commit")
    legacy = None
    directory = None
    manifest = None
    if commit:
        directory = safe_path(cache, f"{owner}--{name}/{commit}")
        legacy = safe_path(root / "sources", f"{owner}--{name}/{commit}")
        for candidate in (directory, legacy):
            path = safe_path(candidate, "manifest.json")
            if path.is_file():
                manifest = json.loads(path.read_text(encoding="utf-8"))
                break
    client = None
    if manifest is None:
        client = client_factory()
        resolved = client.resolve_repository(source["repository"], commit)
        if commit and resolved["commit_sha"] != commit:
            raise ValueError("Resolved version differs from the pinned commit")
        commit = resolved["commit_sha"]
        owner, name = parse_repository(resolved["repository"]["full_name"])
        directory = safe_path(cache, f"{owner}--{name}/{commit}")
        source.update(source_commit=commit, repository=f"{owner}/{name}")
        progress(source, [])
        manifest = {"repository": f"{owner}/{name}", "repository_id": resolved["repository"]["id"],
                    "commit_sha": commit, "inventory_complete": True,
                    "files": client.get_tree(owner, name, resolved["tree_sha"])}
    if (manifest["commit_sha"] != commit
            or manifest["repository"].lower() != source["repository"].lower()):
        raise ValueError("Snapshot identity differs from source")
    source.update(source_commit=commit, repository=manifest["repository"])
    manifest = deepcopy(manifest)
    # Save the pinned inventory before downloading, so interrupted first builds
    # resume from verified files without resolving a moving branch again.
    write_json(directory / "manifest.json", manifest)
    entries, total, document_total, names = [], 0, 0, set()
    documents, files = [], []
    network_failed = False
    for original in sorted(manifest["files"], key=lambda item: item["path"]):
        if stopped.is_set():
            raise InterruptedError("Knowledge build stopped")
        entry = {k: original[k] for k in ("path", "type", "mode", "sha", "size") if k in original}
        is_document = PurePosixPath(entry['path']).suffix.lower() in DOCUMENT_SUFFIXES
        file_limit = MAX_DOCUMENT_BYTES if is_document else MAX_FILE_BYTES
        reason = classify(entry, file_limit)
        if (reason in {None, "file_size_budget"}
                and not is_document
                and PurePosixPath(entry["path"]).suffix.lower() in NON_TEXT_ATTACHMENTS):
            reason = "non_text_attachment"
        if not reason and not is_document and original.get("reason") in {"binary", "non_utf8", "suspected_secret", "lfs_content_not_fetched"}:
            reason = original["reason"]
        if entry["path"].casefold() in names:
            reason = "case_collision"
        names.add(entry["path"].casefold())
        if not reason and is_document and document_total + entry.get('size', 0) > MAX_DOCUMENT_TOTAL_BYTES:
            reason = 'document_snapshot_budget'
        if not reason and not is_document and total + entry.get("size", 0) > MAX_TOTAL_BYTES:
            reason = 'snapshot_budget'
        if not reason:
            if is_document:
                document_total += entry.get('size', 0)
            else:
                total += entry.get("size", 0)
        entry.update(status="excluded" if reason else "pending", reason=reason)
        if reason:
            entries.append(entry)
            continue
        data = None
        invalid_local = False
        for candidate in (directory, legacy):
            if candidate is None:
                continue
            path = safe_path(candidate / ('documents' if is_document and candidate == directory else 'source'), entry["path"])
            if path.is_file():
                if path.stat().st_size > file_limit:
                    invalid_local = True
                    continue
                raw = path.read_bytes()
                if len(raw) <= file_limit and blob_sha(raw) == entry["sha"]:
                    data = raw
                    break
                invalid_local = True
        if data is None and not network_failed:
            try:
                client = client or client_factory()
                payload = client.get_json(f"/repos/{owner}/{name}/git/blobs/{entry['sha']}")
                if payload.get("encoding") != "base64":
                    raise ValueError("Unsupported blob encoding")
                data = base64.b64decode(''.join(payload["content"].split()), validate=True)
            except (GitHubError, ValueError, KeyError, OSError):
                network_failed = True
        if data is None:
            entry.update(status="failed", reason="local_content_changed" if invalid_local else "source_unavailable")
        else:
            try:
                if len(data) > file_limit or blob_sha(data) != entry['sha']:
                    raise ValueError("Source exceeds file budget")
                if is_document:
                    extracted, metadata = document_documents(directory, entry, data)
                    url = f"https://github.com/{owner}/{name}/blob/{commit}/{quote(entry['path'], safe='/')}"
                    documents.extend({**d, 'source_url': url} for d in extracted)
                    if metadata is not None:
                        files.append(metadata)
                else:
                    _save_source(directory, entry, data)
            except DocumentError as error:
                entry.update(status='failed', reason=error.code)
            except (ValueError, OSError):
                entry.update(status="failed", reason="content_validation_failed")
            if entry["status"] == "downloaded" and not is_document:
                text = data.decode("utf-8")
                sha = fingerprint(data)
                url = f"https://github.com/{owner}/{name}/blob/{commit}/"
                documents.append({"path": entry["path"], "text": text, "sha256": sha,
                                  "source_url": url + quote(entry["path"], safe="/"), "source_kind": "source_text"})
                files.append({"path": entry["path"], "sha256": sha, "line_count": len(source_lines(text))})
        entries.append(entry)
        if len(entries) % 10 == 0:
            progress(source, entries)
    manifest["files"] = entries
    write_json(directory / "manifest.json", manifest)
    return documents, entries, bool(manifest.get("inventory_complete")), files


def manual_documents(project):
    """Index the frozen original fields, not model-produced resume summaries."""
    labels = ("context", "contribution", "outcome", "source_text")
    documents = []
    for key in labels:
        text = project["experience"].get(key, "")
        if not text:
            continue
        data = text.encode("utf-8")
        if SECRET_PATTERN.search(data):
            continue
        documents.append({"path": f"experience/{key}.txt", "text": text, "sha256": fingerprint(data),
                          "source_url": f"urn:offerpilot:experience:{project['source_commit']}:{key}",
                          "source_kind": "user_supplied"})
    included = {document["path"] for document in documents}
    entries = [{"path": f"experience/{key}.txt",
                "status": "downloaded" if f"experience/{key}.txt" in included else "excluded",
                "reason": None if f"experience/{key}.txt" in included else "suspected_secret"}
               for key in labels if project["experience"].get(key)]
    files = [{"path": d["path"], "sha256": d["sha256"], "line_count": len(source_lines(d["text"]))} for d in documents]
    return documents, entries, True, files
