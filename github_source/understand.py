"""Check UA coordinates against an immutable snapshot, without judging semantics."""

import hashlib
import json
from pathlib import Path

from .ingest import blob_sha, cite, safe_path


def _read_object(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError(f"Cannot read a JSON object from {Path(path).name}") from None
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {Path(path).name}")
    return value


def _line_range(value):
    return (isinstance(value, list) and len(value) == 2
            and all(type(n) is int for n in value) and 1 <= value[0] <= value[1])


def validate_understanding(snapshot_dir, ua_dir):
    """Return issues, warnings and verified citations; do not modify either input.

    A valid result means the references resolve to the saved source version.
    It does not establish that graph summaries or learning explanations are true.
    Missing source coordinates remain navigation data and never get invented lines.
    """
    snapshot_dir, ua_dir = Path(snapshot_dir), Path(ua_dir)
    manifest = _read_object(snapshot_dir / "manifest.json")
    graph = _read_object(ua_dir / "knowledge-graph.json")
    if not isinstance(manifest.get("files"), list) or not manifest.get("commit_sha"):
        raise ValueError("Snapshot manifest is missing its source inventory or commit")
    entries = {e["path"]: e for e in manifest["files"]
               if isinstance(e, dict) and e.get("status") == "downloaded" and isinstance(e.get("path"), str)}
    issues, warnings, evidence = [], [], []
    verified_files = set()
    counts = {"nodes": 0, "edges": 0, "layers": 0, "tour_steps": 0,
              "navigation_only_nodes": 0, "node_references_checked": 0,
              "lesson_files": 0, "lesson_sections_checked": 0}

    def issue(code, location, message):
        issues.append({"code": code, "location": location, "message": message})

    def warning(code, location, message):
        warnings.append({"code": code, "location": location, "message": message})

    def array(container, key, location):
        value = container.get(key)
        if not isinstance(value, list):
            issue("invalid_array", location, f"{key} must be an array")
            return []
        return value

    project = graph.get("project")
    graph_commit = project.get("gitCommitHash") if isinstance(project, dict) else None
    bound = graph_commit == manifest["commit_sha"]
    if not bound:
        issue("commit_mismatch", "project.gitCommitHash", "Graph commit does not match the selected snapshot")

    def verify_file(path, location):
        try:
            target = safe_path(snapshot_dir / "source", path)
        except ValueError:
            issue("unsafe_source_path", location, "Source path is not a safe project-relative path")
            return False
        entry = entries.get(path)
        if entry is None:
            issue("source_not_downloaded", location, "Source file was not downloaded in this snapshot")
            return False
        try:
            data = target.read_bytes()
        except OSError:
            issue("source_unavailable", location, "Saved source file cannot be read")
            return False
        if (hashlib.sha256(data).hexdigest() != entry.get("sha256")
                or blob_sha(data) != entry.get("sha")):
            issue("source_content_changed", location, "Saved source no longer matches its recorded fingerprints")
            return False
        verified_files.add(path)
        return True

    def reference(path, line_range, location, origin):
        if not _line_range(line_range):
            issue("invalid_line_range", location, "lineRange must be two positive integer line numbers in order")
            return
        if not bound:
            return
        try:
            item = cite(snapshot_dir, path, *line_range)
        except (ValueError, OSError, UnicodeError, KeyError):
            issue("invalid_source_reference", location, "Source range is unavailable, out of bounds, or no longer matches the snapshot")
            return
        evidence.append({"origin": origin, **item})

    nodes = array(graph, "nodes", "nodes")
    counts["nodes"] = len(nodes)
    node_ids = set()
    node_paths = {}
    for index, node in enumerate(nodes):
        location = f"nodes[{index}]"
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"]:
            issue("invalid_node", location, "Node must have a nonempty string id")
            continue
        node_id = node["id"]
        if node_id in node_ids:
            issue("duplicate_node_id", location, "Node id is repeated")
        node_ids.add(node_id)
        path = node.get("filePath")
        line_range = node.get("lineRange")
        valid_range = line_range is None or _line_range(line_range)
        if not valid_range:
            issue("invalid_line_range", location + ".lineRange", "lineRange must be two positive integer line numbers in order")
        if path is None:
            counts["navigation_only_nodes"] += 1
            warning("navigation_only_node", location, "Node has no filePath; no source citation was created")
            continue
        valid_file = verify_file(path, location + ".filePath")
        if valid_file:
            node_paths[node_id] = path
        if line_range is None:
            counts["navigation_only_nodes"] += 1
            warning("navigation_only_node", location, "Node has no lineRange; no source citation was created")
        elif valid_file and valid_range:
            counts["node_references_checked"] += 1
            reference(path, line_range, location + ".lineRange", {"kind": "node", "node_id": node_id})

    edges = array(graph, "edges", "edges")
    counts["edges"] = len(edges)
    seen_edges = set()
    for index, edge in enumerate(edges):
        location = f"edges[{index}]"
        if not isinstance(edge, dict):
            issue("invalid_edge", location, "Edge must be an object")
            continue
        source, target = edge.get("source"), edge.get("target")
        if not isinstance(source, str) or not isinstance(target, str) or source not in node_ids or target not in node_ids:
            issue("dangling_edge", location, "Edge endpoints must reference existing node ids")
            continue
        key = (source, target, str(edge.get("type")))
        if key in seen_edges:
            issue("duplicate_edge", location, "Edge source, target and type are repeated")
        seen_edges.add(key)

    def check_refs(item, location):
        refs = array(item, "nodeIds", location + ".nodeIds")
        for ref in refs:
            if not isinstance(ref, str) or ref not in node_ids:
                issue("dangling_node_reference", location + ".nodeIds", "Reference must resolve to an existing node id")
        return [ref for ref in refs if isinstance(ref, str) and ref in node_ids]

    layers = array(graph, "layers", "layers")
    counts["layers"] = len(layers)
    layer_ids = set()
    for index, layer in enumerate(layers):
        location = f"layers[{index}]"
        if not isinstance(layer, dict) or not isinstance(layer.get("id"), str) or not layer["id"]:
            issue("invalid_layer", location, "Layer must have a nonempty string id")
            continue
        if layer["id"] in layer_ids:
            issue("duplicate_layer_id", location, "Layer id is repeated")
        layer_ids.add(layer["id"])
        check_refs(layer, location)

    tour = array(graph, "tour", "tour")
    counts["tour_steps"] = len(tour)
    tour_files = {}
    for index, step in enumerate(tour):
        location = f"tour[{index}]"
        if not isinstance(step, dict) or type(step.get("order")) is not int or step["order"] < 1:
            issue("invalid_tour_step", location, "Tour step must have a positive integer order")
            continue
        if step["order"] in tour_files:
            issue("duplicate_tour_order", location, "Tour order is repeated")
        refs = check_refs(step, location)
        tour_files[step["order"]] = {node_paths[ref] for ref in refs if ref in node_paths}

    lessons_path = ua_dir / "code-lessons.json"
    if not lessons_path.exists():
        warning("missing_code_lessons", "code-lessons.json", "No code lessons were supplied")
    else:
        lessons = _read_object(lessons_path)
        files = lessons.get("files")
        if not isinstance(files, dict):
            issue("invalid_lessons", "code-lessons.files", "Lesson files must be an object keyed by source path")
            files = {}
        counts["lesson_files"] = len(files)
        for path, lesson in files.items():
            location = "code-lessons.files[" + repr(path) + "]"
            valid_file = verify_file(path, location)
            if not isinstance(lesson, dict):
                issue("invalid_lesson", location, "Lesson must be an object")
                continue
            for index, section in enumerate(array(lesson, "sections", location + ".sections")):
                counts["lesson_sections_checked"] += 1
                section_location = location + f".sections[{index}]"
                if not isinstance(section, dict):
                    issue("invalid_lesson_section", section_location, "Lesson section must be an object")
                    continue
                order = section.get("tourOrder")
                if order is not None:
                    if type(order) is not int or order not in tour_files:
                        issue("invalid_lesson_tour_order", section_location, "Lesson anchor must reference an existing tour order")
                    elif path not in tour_files[order]:
                        issue("lesson_tour_file_mismatch", section_location, "Anchored tour step does not reference this source file")
                if valid_file:
                    reference(path, section.get("lineRange"), section_location + ".lineRange",
                              {"kind": "lesson_section", "file_path": path, "section_index": index})

    counts["source_files_verified"] = len(verified_files)
    counts["references_verified"] = len(evidence)
    return {"role": "reference_validation_only", "valid": not issues,
            "snapshot_commit_sha": manifest["commit_sha"], "graph_commit_sha": graph_commit,
            "semantic_accuracy_assessed": False, "personal_contribution": "unconfirmed",
            "ability_assessed": False, "counts": counts,
            "issues": issues, "warnings": warnings, "evidence": evidence}
