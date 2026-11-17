"""Optional Graphify adapter for the Python grammar validated in this prototype."""

import hashlib
import importlib.metadata
import json
from pathlib import Path
from contextlib import redirect_stdout
import sys

from .ingest import _persist, safe_path, write_json, write_report


def build_index(directory):
    from graphify.extract import extract

    version = importlib.metadata.version("graphifyy")
    if version != "0.9.109":
        raise ValueError("This adapter was validated with graphifyy==0.9.109")
    directory = Path(directory).resolve()
    source = directory / "source"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    paths = []
    for entry in manifest["files"]:
        if entry["status"] != "downloaded":
            continue
        if not entry["path"].endswith(".py"):
            entry["structure_status"] = "outside_validated_python_scope"
            continue
        path = safe_path(source, entry["path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Source changed since ingestion; re-ingest before indexing")
        paths.append(path)
    with redirect_stdout(sys.stderr):
        result = extract(paths, root=source, cache_root=directory / "analysis-cache", parallel=False)
    failed = {str(Path(p).resolve()) for p in result.get("failed_sources", [])}
    skipped = {str(Path(p).resolve()) for p in result.get("skipped_sources", [])}
    extracted = {str(Path(p).resolve()) for p in result.get("extracted_sources", [])}
    node_files = {n.get("source_file") for n in result.get("nodes", [])}
    for entry in manifest["files"]:
        if entry["status"] != "downloaded" or not entry["path"].endswith(".py"):
            continue
        absolute = str(safe_path(source, entry["path"]).resolve())
        if absolute in failed:
            state = "failed"
        elif absolute in skipped:
            state = "skipped"
        elif absolute in extracted:
            state = "indexed" if entry["path"] in node_files else "parsed_no_nodes"
        else:
            state = "not_confirmed"
        entry["structure_status"] = state
    graph = {"schema_version": 1, "tool": "graphifyy", "tool_version": version,
             "scope": "python_static_structure_only", "repository_id": manifest["repository_id"],
             "commit_sha": manifest["commit_sha"], "semantic_analysis_run": False, **result}
    write_json(directory / "graph.json", graph)
    manifest["structure_analysis"] = {"tool": "graphifyy", "version": version,
                                      "scope": "python_static_structure_only", "nodes": len(result["nodes"]),
                                      "edges": len(result["edges"]), "failed_files": len(failed),
                                      "skipped_files": len(skipped), "model_input_tokens": result["input_tokens"],
                                      "model_output_tokens": result["output_tokens"]}
    _persist(directory, manifest)
    write_report(directory, manifest)
    return manifest["structure_analysis"]
