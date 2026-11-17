"""Graph-only structural signals for UA architecture and tour roles."""

from collections import Counter, defaultdict, deque
import json
from pathlib import Path
import sys


def main():
    ua = Path(sys.argv[1])
    graph = json.loads((ua / "intermediate/assembled-graph.json").read_text(encoding="utf-8"))
    file_types = {"file", "config", "document", "service", "pipeline", "schema", "table", "resource", "endpoint"}
    nodes = {n["id"]: n for n in graph["nodes"] if n["type"] in file_types}
    imports = [e for e in graph["edges"] if e["type"] == "imports" and e["source"] in nodes and e["target"] in nodes]
    edges = [e for e in graph["edges"] if e["source"] in nodes and e["target"] in nodes]
    groups, types = defaultdict(list), defaultdict(list)
    adjacency = {node: [] for node in nodes}
    neighbors = {node: set() for node in nodes}
    for key, node in nodes.items():
        groups[str(Path(node["filePath"]).parent).replace("\\", "/")].append(key)
        types[node["type"]].append(key)
    for edge in imports:
        adjacency[edge["source"]].append(edge["target"])
    for edge in edges:
        neighbors[edge["source"]].add(edge["target"])
        neighbors[edge["target"]].add(edge["source"])
    fan_in = Counter(e["target"] for e in imports)
    fan_out = Counter(e["source"] for e in imports)
    start = next((key for key, n in nodes.items() if n["filePath"].endswith("/__init__.py")), next(iter(nodes)))
    queue, depths, order = deque([start]), {start: 0}, []
    while queue:
        key = queue.popleft()
        order.append(key)
        for target in adjacency[key]:
            if target not in depths:
                depths[target] = depths[key] + 1
                queue.append(target)
    visited, clusters = set(), []
    for key in nodes:
        if key in visited:
            continue
        todo, cluster = [key], []
        while todo:
            current = todo.pop()
            if current in visited:
                continue
            visited.add(current)
            cluster.append(current)
            todo.extend(neighbors[current] - visited)
        clusters.append(cluster)
    result = {"scriptCompleted": True, "fileStats": {"totalFileNodes": len(nodes)},
              "directoryGroups": dict(groups), "nodeTypeGroups": dict(types),
              "fileFanIn": dict(fan_in), "fileFanOut": dict(fan_out),
              "importAdjacency": adjacency, "bfsTraversal": {"startNode": start, "order": order, "depthMap": depths},
              "crossCategoryEdges": dict(Counter(f"{nodes[e['source']]['type']}->{nodes[e['target']]['type']}:{e['type']}" for e in edges)),
              "clusters": clusters, "nodeSummaryIndex": {key: {k: n[k] for k in ("name", "type", "filePath", "summary", "tags")} for key, n in nodes.items()},
              "scope": "signals for this small library; absent infrastructure outside selected scope is not inferred"}
    destination = ua / "tmp/graph-structural-signals.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(nodes), "internal_imports": len(imports), "output": str(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
