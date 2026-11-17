#!/usr/bin/env python3
"""Store manually edited experience variants without touching the Master Resume.

CLI:
    python3 -I tools/variants.py add --project <name> --variant <text-file>
    python3 -I tools/variants.py list --project <name>

Variants are stored in one local JSON array,
``web/data/user/variants.json`` — the same file ``web/backend.py``'s
``add_variant`` reads and writes — so the web page and this CLI share one
store.  Earlier versions wrote one JSON file per variant under
``tools/data/variants/`` (the ``variants_dir`` config key); those files are
still listed and filtered, but new records go only to the shared store.  An
optional ``variants_store`` config key points the shared store elsewhere
(used by tests).  The text is copied verbatim from the user's file: no
generation, rewriting, embellishment, or invented experience. The tool never
reads or writes ``resume.md``, ``resume-source.md``, or any workspace file.
No network, no credentials, no external dependencies.

A variant may optionally be linked to one job (``job_id``).  The field is
optional on purpose: records written before it existed stay readable, and
``job_id`` is only written when the caller supplies one.

``compare_variant(variant_text, master_text)`` compares two *text values* the
caller already has and returns the paragraphs the variant adds, removes or
changes.  It echoes the original wording only: it never rewrites a paragraph,
never invents experience and never touches a master resume file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

from filters import load_config  # noqa: E402  (local module, path set above)

_PROJECT_ROOT = _TOOLS_DIR.parent
_SLUG_RE = re.compile(r"[^0-9A-Za-z一-鿿]+")
_MAX_JOB_ID_CHARS = 160
# One local store shared with web/backend.py's add_variant.  web/data/ is
# git-ignored, so the records never leave this machine or enter the repository.
_STORE_RELATIVE = Path("web") / "data" / "user" / "variants.json"
_LEGACY_DIR_RELATIVE = Path("tools") / "data" / "variants"


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    slug = _SLUG_RE.sub("-", normalized).strip("-").casefold()
    return slug or "project"


def _resolve(configured: Any) -> Path | None:
    if not configured:
        return None
    path = Path(str(configured))
    return path if path.is_absolute() else _PROJECT_ROOT / path


def variants_store_path(config: dict[str, Any] | None = None) -> Path:
    """The single JSON array shared with ``web/backend.py``'s ``add_variant``.

    ``variants_store`` overrides it (tests point it at a temporary file).  The
    default is ``web/data/user/variants.json``, exactly the file the local web
    workbench reads through ``Store.variants()``.
    """

    cfg = config if config is not None else load_config()
    return _resolve(cfg.get("variants_store")) or _PROJECT_ROOT / _STORE_RELATIVE


def variants_dir(config: dict[str, Any] | None = None) -> Path:
    """Legacy per-record directory, read-only.

    Earlier versions wrote one JSON file per variant here.  Those files remain
    readable (``list_variants`` merges them), but new records go to
    :func:`variants_store_path` so the web page and this CLI share one store.
    """

    cfg = config if config is not None else load_config()
    return _resolve(cfg.get("variants_dir")) or _PROJECT_ROOT / _LEGACY_DIR_RELATIVE


def project_slug(value: Any) -> str:
    """Project identity used to compare records written by either writer."""

    return _slug(str(value or ""))


def normalize_job_id(value: Any) -> str | None:
    """Optional job reference: a short single-line string, or ``None``."""

    return _normalized_job_id(value)


def _normalized_job_id(value: Any) -> str | None:
    """Optional job reference: a short single-line string, or ``None``."""

    if not isinstance(value, str) or isinstance(value, bool):
        return None
    cleaned = value.strip()
    if not cleaned or any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        return None
    return cleaned[:_MAX_JOB_ID_CHARS]


def _record_key(project: str, text: str, job_id: str | None = None) -> str:
    key = project + "\0" + text
    if job_id:
        key += "\0" + job_id
    return key


def record_id(project: str, text: str, job_id: str | None = None) -> str:
    """Stable id shared by both writers, distinct per project and linked job."""

    digest = hashlib.sha256(_record_key(project, text, job_id).encode("utf-8")).hexdigest()[:12]
    return "variant-" + digest


def _read_store(path: Path) -> list[dict[str, Any]]:
    """Records from the shared JSON array; a damaged file is never overwritten."""

    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"variants store {path} cannot be read: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"variants store {path} must be a JSON array")
    return [row for row in data if isinstance(row, dict)]


def _write_store(path: Path, rows: list[dict[str, Any]]) -> None:
    """Atomic replace, so a crash never leaves a half-written store."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _matches(record: dict[str, Any], project: str, text: str, job_id: str | None) -> bool:
    return (
        project_slug(record.get("project")) == project_slug(project)
        and str(record.get("sha256") or "") == hashlib.sha256(text.encode("utf-8")).hexdigest()
        and _normalized_job_id(record.get("job_id")) == job_id
    )


def add_variant(
    project: str,
    variant_path: str | Path,
    config: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Append one user-edited variant file to the shared local store.

    ``job_id`` is optional and additive: when it is absent, the record is the
    same kind earlier versions wrote.  Adding the exact same text, project and
    job again returns the existing record with ``duplicate`` true instead of
    writing twice.  ``path`` is the shared store file, not a per-record file.
    """

    if not project.strip():
        raise ValueError("--project must not be empty")
    try:
        text = Path(variant_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read variant text file: {exc}") from exc
    if not text.strip():
        raise ValueError("variant text file is empty; nothing was invented or stored")

    created_at = now or dt.datetime.now(dt.timezone.utc).astimezone()
    linked_job = _normalized_job_id(job_id)
    store_path = variants_store_path(config)
    rows = _read_store(store_path)
    for existing in rows:
        if _matches(existing, project, text, linked_job):
            return {"path": str(store_path), "record": existing, "duplicate": True}
    record: dict[str, Any] = {
        "id": record_id(project, text, linked_job),
        "project": project,
        "created_at": created_at.isoformat(),
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_variant_file": str(Path(variant_path)),
    }
    if linked_job:
        record["job_id"] = linked_job
    rows.append(record)
    _write_store(store_path, rows)
    return {"path": str(store_path), "record": record, "duplicate": False}


def _iter_records(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.is_dir():
        return []
    rows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict):
            rows.append((path, record))
    return rows


def _public_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path),
        "id": record.get("id"),
        "project": record.get("project"),
        "created_at": record.get("created_at"),
        "text": record.get("text"),
        "sha256": record.get("sha256"),
        # Records written before linked variants existed simply have ``None``.
        "job_id": _normalized_job_id(record.get("job_id")),
    }


def _all_records(config: dict[str, Any] | None) -> list[tuple[Path, dict[str, Any]]]:
    """Shared store first, then legacy per-file records, de-duplicated.

    Earlier versions wrote one file per variant; those stay readable.  When the
    same record exists in both places the shared-store copy wins.
    """

    store_path = variants_store_path(config)
    rows = [(store_path, record) for record in _read_store(store_path)]
    seen = {
        (
            project_slug(record.get("project")),
            str(record.get("sha256") or ""),
            _normalized_job_id(record.get("job_id")),
            str(record.get("created_at") or ""),
        )
        for _, record in rows
    }
    for path, record in _iter_records(variants_dir(config)):
        key = (
            project_slug(record.get("project")),
            str(record.get("sha256") or ""),
            _normalized_job_id(record.get("job_id")),
            str(record.get("created_at") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append((path, record))
    return rows


def list_variants(
    project: str,
    config: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """List stored variants for one project, oldest record content first.

    ``job_id`` is an optional filter. A record without the field never matches
    a real job id, so old records stay readable but are not misattributed.
    """

    linked = _normalized_job_id(job_id)
    if job_id is not None and linked is None:
        raise ValueError("job_id must be a non-empty single-line string")
    wanted = _slug(project)
    results: list[dict[str, Any]] = []
    for path, record in _all_records(config):
        if _slug(str(record.get("project", ""))) != wanted:
            continue
        if job_id is not None and _normalized_job_id(record.get("job_id")) != linked:
            continue
        results.append(_public_record(path, record))
    results.sort(key=lambda item: (str(item.get("created_at") or ""), item["path"]))
    return results


def list_variants_for_job(
    job_id: str, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """List every stored variant linked to *job_id*, across projects."""

    linked = _normalized_job_id(job_id)
    if linked is None:
        raise ValueError("job_id must be a non-empty single-line string")
    results = [
        _public_record(path, record)
        for path, record in _all_records(config)
        if _normalized_job_id(record.get("job_id")) == linked
    ]
    results.sort(key=lambda item: (str(item.get("created_at") or ""), item["path"]))
    return results


def _paragraphs(text: Any) -> list[str]:
    """Split one text value into blank-line separated paragraphs, verbatim."""

    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", normalized):
        stripped = block.strip()
        if stripped:
            blocks.append(stripped)
    return blocks


def _comparison_key(block: str) -> str:
    """Whitespace and full-width differences are not edits to the wording."""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", block)).strip()


def compare_variant(variant_text: Any, master_text: Any) -> dict[str, Any]:
    """Paragraph-level differences of *variant_text* against *master_text*.

    Returns ``{identical, summary, segments}``. ``segments`` lists only the
    differences in document order: ``{kind: "added", text}``,
    ``{kind: "removed", text}`` or ``{kind: "changed", before, after}``.
    Every string is copied from the two inputs; nothing is rewritten or
    generated, and no file is read or written.
    """

    variant_blocks = _paragraphs(variant_text)
    master_blocks = _paragraphs(master_text)
    matcher = difflib.SequenceMatcher(
        None,
        [_comparison_key(block) for block in master_blocks],
        [_comparison_key(block) for block in variant_blocks],
        autojunk=False,
    )
    segments: list[dict[str, Any]] = []
    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for tag, start, end, other_start, other_end in matcher.get_opcodes():
        if tag == "equal":
            summary["unchanged"] += end - start
            continue
        old = master_blocks[start:end]
        new = variant_blocks[other_start:other_end]
        if tag == "insert":
            for block in new:
                segments.append({"kind": "added", "text": block})
            summary["added"] += len(new)
        elif tag == "delete":
            for block in old:
                segments.append({"kind": "removed", "text": block})
            summary["removed"] += len(old)
        else:  # replace: pair by position, extra paragraphs are added/removed
            paired = min(len(old), len(new))
            for index in range(paired):
                segments.append({"kind": "changed", "before": old[index], "after": new[index]})
            summary["changed"] += paired
            for block in old[paired:]:
                segments.append({"kind": "removed", "text": block})
                summary["removed"] += 1
            for block in new[paired:]:
                segments.append({"kind": "added", "text": block})
                summary["added"] += 1
    return {
        "identical": not segments,
        "summary": summary,
        "segments": segments,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Store and list manually edited experience variants as local JSON. "
            "Never modifies the Master Resume; never generates experience."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    def add_config_option(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--config",
            dest="sub_config",
            help="optional alternate config path (defaults to tools/config.json)",
        )

    add = subparsers.add_parser("add", help="store one user-edited variant text file")
    add.add_argument("--project", required=True, help="source project name")
    add.add_argument("--variant", required=True, help="path to the edited text file")
    add.add_argument("--job-id", dest="job_id", help="optional local job id to link")
    add_config_option(add)
    listing = subparsers.add_parser("list", help="list variants for one project")
    listing.add_argument("--project", required=True, help="source project name")
    listing.add_argument("--job-id", dest="job_id", help="only variants linked to this job")
    add_config_option(listing)
    # Also accept --config before the subcommand for convenience.  The
    # subparser value wins when both are supplied.
    parser.add_argument(
        "--config", help="optional alternate config path (defaults to tools/config.json)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    chosen_config = getattr(args, "sub_config", None) or args.config
    cfg = load_config(chosen_config) if chosen_config else load_config()
    try:
        if args.command == "add":
            outcome = add_variant(args.project, args.variant, cfg, job_id=args.job_id)
            print(
                json.dumps(
                    {
                        "command": "add",
                        "path": outcome["path"],
                        "project": outcome["record"]["project"],
                        "created_at": outcome["record"]["created_at"],
                        "sha256": outcome["record"]["sha256"],
                        "job_id": outcome["record"].get("job_id"),
                        "duplicate": outcome["duplicate"],
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "list":
            items = list_variants(args.project, cfg, job_id=args.job_id)
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:  # pragma: no cover - argparse enforces the choices
            parser.error("unknown command")
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
