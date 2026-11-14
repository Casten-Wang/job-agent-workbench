#!/usr/bin/env python3
"""Offline mail watcher over a local directory of .eml/JSON samples.

Real IMAP connection is intentionally not implemented. Its configuration
signature is provided for a future, user-supplied adapter; this module never
reads credentials or opens a socket.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
sys.dont_write_bytecode = True

import mail_classifier  # noqa: E402


def watch_offline(directory: str | Path) -> dict[str, Any]:
    folder = Path(directory)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates: list[str] = []
    warnings: list[str] = []
    if not folder.is_dir():
        return {"count": 0, "records": [], "duplicates": [], "warnings": ["directory-missing"]}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in {".eml", ".json"}:
            continue
        try:
            mail = mail_classifier.load_mail(path)
            classified = mail_classifier.classify(mail)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"{path.name}: {type(exc).__name__}")
            continue
        message_id = classified.get("message_id") or path.name
        if message_id in seen:
            duplicates.append(str(message_id))
            continue
        seen.add(message_id)
        classified["source_file"] = path.name
        records.append(classified)
    return {"count": len(records), "records": records, "duplicates": duplicates, "warnings": warnings}


def imap_config_signature(host: str, user: str, password_env: str = "JOB_AGENT_IMAP_PASSWORD") -> dict[str, Any]:
    """Return a redacted config shape; never read or return the password."""
    return {
        "host": host,
        "user": user,
        "password_env": password_env,
        "password_present": bool(os.environ.get(password_env)),
        "status": "not_implemented_offline_build",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline local mail sample watcher")
    parser.add_argument("--dir", required=True)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    result = watch_offline(args.dir)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
