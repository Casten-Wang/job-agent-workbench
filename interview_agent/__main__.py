import argparse
import os
import asyncio
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Local FastAPI + LangGraph interview service")
    parser.add_argument("--db", type=Path, default=Path("outputs/interview-hub/interview.db"))
    parser.add_argument("--checkpoints", type=Path, default=Path("outputs/interview-agent/checkpoints.db"))
    parser.add_argument("--owner", default="local-demo")
    parser.add_argument("--port", type=int, default=18747)
    parser.add_argument("--import-legacy", type=Path, help="Import one explicit old Pi JSON state without modifying it")
    args = parser.parse_args()
    # External tracing is opt-in; preserve caller-provided LangSmith settings.
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    if args.import_legacy:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        from interview_hub.store import Store
        from .graph import InterviewWorkflow
        from .repository import Repository
        from .model_adapter import ModelAdapter

        async def migrate():
            args.checkpoints.parent.mkdir(parents=True, exist_ok=True)
            agent = await ModelAdapter().start()
            try:
                async with AsyncSqliteSaver.from_conn_string(str(args.checkpoints)) as saver:
                    workflow = InterviewWorkflow(Repository(Store(args.db), args.owner), agent, saver)
                    result = await workflow.import_legacy(args.import_legacy)
                    print(json.dumps({"session_id": result["session_id"], "status": result["status"], "model_called": False}))
            finally:
                await agent.close()

        asyncio.run(migrate())
        return
    token = os.environ.get("INTERVIEW_AGENT_TOKEN")
    if not token or len(token) < 20:
        parser.error("Set INTERVIEW_AGENT_TOKEN to a local service token of at least 20 characters")
    from .api import create_app
    import uvicorn
    uvicorn.run(create_app(args.db, args.checkpoints, args.owner, token), host="127.0.0.1", port=args.port,
                workers=1, access_log=False)


if __name__ == "__main__":
    main()
