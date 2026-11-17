"""Isolated browser fixture: only synthetic sources and temporary user storage."""

from pathlib import Path
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_resume_web_flow import ResumeWebFlowTests, career_user_runtime
from unittest.mock import patch


def main():
    fixture = ResumeWebFlowTests()
    fixture.setUp()
    def upstream(method, path, payload=None):
        response = fixture.engine.client.request(method, path, json=payload,
            headers={"Authorization": "Bearer personal-career-integration-test-token"})
        response.raise_for_status()
        return response.json()
    fixture.stack.enter_context(patch.object(career_user_runtime, "upstream", upstream))
    project = fixture.engine.prepare()
    output = ROOT / "outputs/knowledge-verification"
    output.mkdir(parents=True, exist_ok=True)
    stop = output / "stop"
    if stop.exists():
        stop.unlink()
    print(json.dumps({"url": fixture.url, "project_id": project["project_id"], "synthetic": True}), flush=True)
    try:
        while not stop.exists():
            time.sleep(0.2)
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
