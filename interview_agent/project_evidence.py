"""Sample implementation bodies alongside a small amount of project context."""

import ast
from pathlib import Path

from github_source.ingest import cite, safe_path, source_lines


def project_evidence(directory, manifest):
    candidates = [item for item in manifest["files"] if item["status"] == "downloaded"
                  and not any(part.lower() in {"vendor", "node_modules", "dist", "build", "fixtures", "demo", "examples", "prompts", "tests", "test"}
                              for part in item["path"].split("/"))
                  and not Path(item["path"]).name.lower().startswith("test_")
                  and Path(item["path"]).suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".rs", ".md"}]
    context = sorted((item for item in candidates if Path(item["path"]).name.lower() == "readme.md"),
                     key=lambda item: (len(item["path"].split("/")), item["path"]))[:1]
    # Larger implementation files tend to contain workflows rather than wrappers.
    # Round-robin directories prevents one layer from occupying the whole sample.
    groups = {}
    for item in sorted(candidates, key=lambda item: (-item.get("size", 0), item["path"])):
        if Path(item["path"]).suffix.lower() != ".md":
            groups.setdefault(str(Path(item["path"]).parent), []).append(item)
    implementations = []
    while any(groups.values()):
        for items in groups.values():
            if items:
                implementations.append(items.pop(0))
    evidence, chars = [], 0
    for item in context + implementations:
        if len(evidence) >= 12:
            break
        path = item["path"]
        text = safe_path(directory / "source", path).read_text(encoding="utf-8")
        lines = source_lines(text)
        if not lines:
            continue
        start, end = 1, min(len(lines), 160)
        if Path(path).suffix.lower() == ".py":
            try:
                functions = [node for node in ast.walk(ast.parse(text)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and not node.name.startswith(("test_", "demo_", "cmd_demo"))
                             and node.name not in {"main", "build_parser"}]
                if functions:
                    node = max(functions, key=lambda node: node.end_lineno - node.lineno)
                    start, end = node.lineno, min(node.end_lineno, node.lineno + 179)
            except SyntaxError:
                pass
        # Keep an actual contiguous source range, within the shared token budget.
        original_end = end
        while end >= start and chars + len("\n".join(lines[start - 1:end])) > 40000:
            end -= 1
        if end - start + 1 < min(20, original_end - start + 1):
            continue
        selected = cite(directory, path, start, end)
        evidence.append(selected)
        chars += len(selected["text"])
    return evidence
