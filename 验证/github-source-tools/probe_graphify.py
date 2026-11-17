from pathlib import Path
import hashlib
import importlib.metadata
import inspect
import json
import time
import urllib.request

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixture"
OUTPUT = HERE / "probe-output"
FIXTURE.mkdir(exist_ok=True)
OUTPUT.mkdir(exist_ok=True)
(FIXTURE / "models.py").write_text(
    'class UserService:\n'
    '    def normalize(self, name: str) -> str:\n'
    '        return name.strip().title()\n', encoding="utf-8")
(FIXTURE / "main.py").write_text(
    'from pathlib import Path\n'
    'from models import UserService\n'
    'Path(__file__).with_name("EXECUTED.txt").write_text("executed")\n\n'
    'def greet(name: str) -> str:\n'
    '    service = UserService()\n'
    '    return "Hello " + service.normalize(name)\n', encoding="utf-8")

from graphify.extract import extract

start = time.perf_counter()
files = sorted(FIXTURE.glob("*.py"))
result = extract(files, root=FIXTURE, cache_root=OUTPUT, parallel=False)
(OUTPUT / "raw-extraction.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
checks = {
    "fixture_code_not_executed": not (FIXTURE / "EXECUTED.txt").exists(),
    "expected_symbols": all(any(n.get("label") == label for n in result["nodes"])
                            for label in ["UserService", ".normalize()", "greet()"]),
    "all_input_files_extracted": len(result["extracted_sources"]) == len(files),
    "no_failed_sources": not result["failed_sources"],
    "has_cross_file_edge": any(e.get("relation") in ("imports", "calls", "uses")
                              for e in result["edges"]),
    "local_ast_zero_tokens": result["input_tokens"] == 0 and result["output_tokens"] == 0,
}
summary = {
    "probe": "graphify_python_structure_only",
    "tested_distribution": "graphifyy",
    "tested_version": importlib.metadata.version("graphifyy"),
    "python_version": __import__("platform").python_version(),
    "source_reference_commit": "d4a5b323ef8501518b82c58a05fe21b35ce24992",
    "installation": "PyPI wheel version 0.9.109; minimum Python AST dependencies only; full optional language/platform dependency set not installed",
    "extract_signature": str(inspect.signature(extract)),
    "result_keys": list(result),
    "input_files": [str(p.relative_to(FIXTURE)) for p in files],
    "nodes": len(result["nodes"]),
    "edges": len(result["edges"]),
    "elapsed_seconds": round(time.perf_counter() - start, 4),
    "checks": checks,
    "sample_nodes": result["nodes"][:8],
    "sample_edges": result["edges"][:12],
}
request = urllib.request.Request(
    "https://raw.githubusercontent.com/Graphify-Labs/graphify/"
    + summary["source_reference_commit"] + "/graphify/extract.py",
    headers={"User-Agent": "resume-graphify-probe"})
try:
    with urllib.request.urlopen(request, timeout=25) as response:
        remote = response.read()
    local = Path(inspect.getfile(extract)).read_bytes()
    summary["extract_module_matches_pinned_commit"] = remote == local
    summary["extract_module_sha256"] = hashlib.sha256(local).hexdigest()
    summary["pinned_extract_module_sha256"] = hashlib.sha256(remote).hexdigest()
except Exception as exc:
    summary["pinned_module_comparison_error"] = type(exc).__name__
(OUTPUT / "probe-result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k not in ("sample_nodes", "sample_edges")}, ensure_ascii=False))
raise SystemExit(0 if all(checks.values()) else 1)

