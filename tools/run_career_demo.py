"""Start the workbench and isolated demo/personal engines; the model key comes only from 设置 > AI 接口设置."""

import argparse
import getpass
import os
from pathlib import Path
import secrets
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="OfferPilot public project verification demo")
    parser.add_argument("--engine-root", type=Path, default=ROOT,
                        help="Directory containing interview_agent and interview_hub")
    parser.add_argument("--knowledge-only", action="store_true", help="Start workbench and offline knowledge without a model key")
    parser.add_argument("--langsmith", action="store_true", help="Enable opt-in LangSmith tracing; reads its key hidden when absent")
    parser.add_argument("--deploy", action="store_true",
                        help="Public showcase mode for a container host (see web/deploy_mode.py): listens on 0.0.0.0:$PORT (default 7860), "
                             "no platform automation, model key only from OFFERPILOT_MODEL_* variables")
    parser.add_argument("--langsmith-project", default="offerpilot-local", help="LangSmith project name")
    args = parser.parse_args()
    if args.deploy:
        os.environ["OFFERPILOT_DEPLOY"] = "1"
    if not (args.engine_root / "interview_agent/api.py").is_file():
        parser.error("--engine-root must contain the existing Python interview service")
    if args.langsmith:
        if not os.environ.get("LANGSMITH_API_KEY"):
            os.environ["LANGSMITH_API_KEY"] = getpass.getpass("LangSmith API key (hidden): ")
        os.environ["LANGSMITH_TRACING"] = "true"
        # Use the explicit redacted AgentTrace runs; do not enable LangChain's
        # automatic callback tracer, which can serialize graph state.
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ.setdefault("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
        os.environ["LANGSMITH_PROJECT"] = args.langsmith_project
        os.environ.setdefault("LANGSMITH_AGENT_ID", "offerpilot-local-agent")
        os.environ.setdefault("LANGSMITH_AGENT_ENVIRONMENT", "production")
    else:
        os.environ.setdefault("LANGSMITH_TRACING", "false")
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    sys.path.insert(0, str(args.engine_root.resolve()))
    sys.path.insert(0, str(ROOT / "web"))
    sys.path.insert(0, str(ROOT / "tools"))
    from configure_langfuse import apply_saved
    apply_saved()
    import uvicorn
    from interview_agent.api import create_app
    from interview_hub.recap import validate_result
    from interview_hub.store import Store
    from career_agent_runtime import MATERIAL_ID, public_fixture
    from server import make_server
    from workbench_services import ModelSettings
    import workbench_runtime
    if args.deploy:
        import deploy_mode
        print("Deploy mode: model key %s" % ("seeded from OFFERPILOT_MODEL_* variables" if deploy_mode.seed_model_from_env()
                                              else "not set; model features stay unconfigured"), flush=True)
        print("Deploy mode: fictional showcase data %s" % ("seeded" if deploy_mode.seed_showcase_data() else "already present"), flush=True)
    settings = ModelSettings(ROOT, offline=args.knowledge_only)
    workbench_runtime.controller = settings
    import offerpilot_runtime
    offerpilot_runtime.workbench_model = settings.model_config

    material = public_fixture()
    validate_result(material, {"answers": [], "observations": []})
    directory = ROOT / "web/data/demo/career-agent"
    directory.mkdir(parents=True, exist_ok=True)
    owner = "offerpilot-public-demo"
    Store(directory / "interview.db").put_material(owner, MATERIAL_ID, material)
    token = secrets.token_urlsafe(32)
    os.environ["OFFERPILOT_CAREER_AGENT_TOKEN"] = token
    user_token = secrets.token_urlsafe(32)
    os.environ["OFFERPILOT_CAREER_USER_TOKEN"] = user_token
    user_directory = ROOT / "web/data/user/career-agent"
    user_directory.mkdir(parents=True, exist_ok=True)
    if args.deploy:
        import deploy_mode
        workbench = make_server("0.0.0.0", deploy_mode.listen_port())
    else:
        workbench = make_server("127.0.0.1", 8766)
    agent = uvicorn.Server(uvicorn.Config(create_app(directory / "interview.db", directory / "checkpoints.db", owner, token, agent=settings.model()),
                                        host="127.0.0.1", port=18747, access_log=False, log_level="error"))
    thread = threading.Thread(target=agent.run, daemon=True)
    personal = uvicorn.Server(uvicorn.Config(create_app(user_directory / "interview.db", user_directory / "checkpoints.db",
        "offerpilot-personal", user_token, agent=settings.model(), career_root=user_directory), host="127.0.0.1", port=18748,
        access_log=False, log_level="error"))
    personal_thread = threading.Thread(target=personal.run, daemon=True)
    thread.start()
    personal_thread.start()
    try:
        deadline = time.monotonic() + 20
        while not (agent.started and personal.started) and thread.is_alive() and personal_thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not (agent.started and personal.started):
            raise RuntimeError("Career service startup failed; check model configuration and ports 18747/18748")
        print("OfferPilot: http://127.0.0.1:8766/ · demo > 定制简历 > 开始项目核验", flush=True)
        print("Personal projects: user > 定制简历 > 连接 GitHub", flush=True)
        print("Model: from 设置 > AI 接口设置 · isolated demo/user databases · Ctrl+C stops services", flush=True)
        workbench.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        workbench.server_close()
        agent.should_exit = True
        personal.should_exit = True
        thread.join(timeout=10)
        personal_thread.join(timeout=10)


if __name__ == "__main__":
    main()
