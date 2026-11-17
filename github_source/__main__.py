"""Run with python -m github_source; no credentials are read."""

import argparse
import json
from pathlib import Path
import sys

from .github_api import GitHubClient
from .ingest import cite, ingest


def main():
    parser = argparse.ArgumentParser(description="Read-only, commit-pinned public GitHub source prototype")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("ingest", help="Download a public repository snapshot")
    fetch.add_argument("repository", help="owner/repo or https://github.com/owner/repo")
    fetch.add_argument("--ref", help="Branch, tag or full commit SHA; use SHA to resume a fixed version")
    fetch.add_argument("--author", help="Optional GitHub login for contribution clues; never proves authorship")
    fetch.add_argument("--output", default="outputs/github-source")
    fetch.add_argument("--max-files", type=int, default=250)
    fetch.add_argument("--max-file-bytes", type=int, default=512 * 1024)
    fetch.add_argument("--max-total-bytes", type=int, default=20 * 1024 * 1024)
    evidence = commands.add_parser("cite", help="Read verified original lines and output evidence JSON")
    evidence.add_argument("snapshot", type=Path)
    evidence.add_argument("--path", required=True)
    evidence.add_argument("--start", type=int, required=True)
    evidence.add_argument("--end", type=int, required=True)
    status = commands.add_parser("status", help="Show saved scope and processing state")
    status.add_argument("snapshot", type=Path)
    index = commands.add_parser("index", help="Index downloaded Python sources using optional Graphify environment")
    index.add_argument("snapshot", type=Path)
    understanding = commands.add_parser("ua-check", help="Verify Understand-Anything references against a fixed snapshot")
    understanding.add_argument("snapshot", type=Path)
    understanding.add_argument("--ua-dir", type=Path, required=True)
    understanding.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "ingest":
            directory, manifest = ingest(GitHubClient(), args.repository, args.output, ref=args.ref,
                                         author=args.author, max_files=args.max_files,
                                         max_file_bytes=args.max_file_bytes, max_total_bytes=args.max_total_bytes)
            print(json.dumps({"snapshot": str(directory), "state": manifest["state"], "coverage": manifest["coverage"]}, ensure_ascii=False, indent=2))
            return 0 if manifest["state"] == "fetched_with_declared_scope" else 2
        if args.command == "ua-check":
            from .understand import validate_understanding
            result = validate_understanding(args.snapshot, args.ua_dir)
            if args.output:
                from .ingest import write_json
                write_json(args.output, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result["issues"] else 0
        if args.command == "index":
            from .indexer import build_index
            print(json.dumps(build_index(args.snapshot), ensure_ascii=False, indent=2))
        elif args.command == "cite":
            print(json.dumps(cite(args.snapshot, args.path, args.start, args.end), ensure_ascii=False, indent=2))
        else:
            manifest = json.loads((args.snapshot / "manifest.json").read_text(encoding="utf-8"))
            print(json.dumps({k: manifest[k] for k in ("repository", "commit_sha", "state", "coverage")}, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("Interrupted; re-run with the saved commit SHA to resume.", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
