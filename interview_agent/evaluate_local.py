"""Evaluate local JSONL outputs without uploading datasets or calling any model."""

import argparse
import json
from pathlib import Path

from .evaluation import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="JSONL rows: stage, input, output, optional expected_scores")
    args = parser.parse_args()
    failed, count = 0, 0
    for index, line in enumerate(args.dataset.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        count += 1
        try:
            row = json.loads(line)
            scores = evaluate(row["stage"], row["input"], row["output"])
            expected = row.get("expected_scores")
            passed = (bool(scores) and all(scores.get(k) == v for k, v in expected.items())) if expected is not None else bool(scores) and all(v == 1 for v in scores.values())
            print(json.dumps({"row": index, "scores": scores, "passed": passed}))
        except Exception:
            passed = False
            print(json.dumps({"row": index, "error": "invalid_local_case"}))
        failed += not passed
    raise SystemExit(1 if failed or not count else 0)


if __name__ == "__main__":
    main()
