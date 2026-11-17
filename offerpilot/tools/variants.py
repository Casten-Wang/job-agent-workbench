#!/usr/bin/env python3
"""Store manually edited experience variants without touching the Master Resume.

CLI:
    python3 -I tools/variants.py add --project <name> --variant <text-file>
    python3 -I tools/variants.py list --project <name>

Each variant is written as one JSON file under
``tools/data/variants/<slug>.json``.  The text is copied verbatim from the
user's file: no generation, rewriting, embellishment, or invented experience.
The tool never reads or writes ``resume.md``, ``resume-source.md``, or any
workspace file.  No network, no credentials, no external dependencies.
"""

from __future__ import annotations

import argparse
import datetime as dt
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


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    slug = _SLUG_RE.sub("-", normalized).strip("-").casefold()
    return slug or "project"


def variants_dir(config: dict[str, Any] | None = None) -> Path:
    cfg = config if config is not None else load_config()
    configured = Path(cfg["variants_dir"])
    return configured if configured.is_absolute() else _PROJECT_ROOT / configured


def _record_path(project: str, created_at: dt.datetime, text: str) -> Path:
    """Content-addressed filename: adding a variant never overwrites another."""

    digest = hashlib.sha256(
        (project + "\0" + text).encode("utf-8")
    ).hexdigest()[:12]
    stamp = created_at.strftime("%Y%m%dT%H%M%S")
    return Path(f"{_slug(project)}-{stamp}-{digest}.json")


def add_variant(
    project: str,
    variant_path: str | Path,
    config: dict[str, Any] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Copy one user-edited variant file into a new JSON record."""

    if not project.strip():
        raise ValueError("--project must not be empty")
    try:
        text = Path(variant_path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read variant text file: {exc}") from exc
    if not text.strip():
        raise ValueError("variant text file is empty; nothing was invented or stored")

    created_at = now or dt.datetime.now(dt.timezone.utc).astimezone()
    record = {
        "_note": "测试数据/用户手动修改的经历变体原文；本工具不生成、不改写、不虚构经历，也不覆盖 Master Resume。",
        "project": project,
        "created_at": created_at.isoformat(),
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_variant_file": str(Path(variant_path)),
    }
    directory = variants_dir(config)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / _record_path(project, created_at, text)
    # 'x' is deliberate: an existing file with the same content/time slug is
    # never overwritten.  The caller can retry with a different variant text.
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {"path": str(path), "record": record}


def list_variants(
    project: str, config: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """List stored variants for one project, newest record content first."""

    directory = variants_dir(config)
    if not directory.is_dir():
        return []
    wanted = _slug(project)
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict) or _slug(str(record.get("project", ""))) != wanted:
            continue
        results.append(
            {
                "path": str(path),
                "project": record.get("project"),
                "created_at": record.get("created_at"),
                "text": record.get("text"),
                "sha256": record.get("sha256"),
            }
        )
    results.sort(key=lambda item: (str(item.get("created_at") or ""), item["path"]))
    return results


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
    add_config_option(add)
    listing = subparsers.add_parser("list", help="list variants for one project")
    listing.add_argument("--project", required=True, help="source project name")
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
            outcome = add_variant(args.project, args.variant, cfg)
            print(
                json.dumps(
                    {
                        "command": "add",
                        "path": outcome["path"],
                        "project": outcome["record"]["project"],
                        "created_at": outcome["record"]["created_at"],
                        "sha256": outcome["record"]["sha256"],
                    },
                    ensure_ascii=False,
                )
            )
        elif args.command == "list":
            items = list_variants(args.project, cfg)
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:  # pragma: no cover - argparse enforces the choices
            parser.error("unknown command")
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
