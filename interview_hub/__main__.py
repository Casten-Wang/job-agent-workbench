import argparse
import json
import os
from pathlib import Path

from .store import Store


def main():
    parser = argparse.ArgumentParser(description="Local interview material exchange and recap prototype")
    parser.add_argument("command", choices=["import-demo", "serve"])
    parser.add_argument("--db", type=Path, default=Path("outputs/interview-hub/interview.db"))
    parser.add_argument("--owner", default="local-demo")
    parser.add_argument("--port", type=int, default=18746)
    parser.add_argument("--token-env", default="INTERVIEW_HUB_TOKEN")
    args = parser.parse_args()
    store = Store(args.db)
    if args.command == "import-demo":
        from .materials import import_demo
        root = Path(__file__).resolve().parents[1]
        snapshot = root / "outputs/github-source/pallets--itsdangerous/672971d66a2ef9f85151e53283113f33d642dabd"
        ua = root / "outputs/understand-anything/itsdangerous-672971d66a2e/project/.ua"
        readiness = root / "outputs/understand-anything/itsdangerous-672971d66a2e/resume-readiness-demo.json"
        record = import_demo(store, args.owner, snapshot, ua, readiness)
        print(json.dumps({"material_id": record["material_id"], "db": str(args.db.resolve()), "is_demo": True}, ensure_ascii=False))
        return
    from .server import make_server
    token = os.environ.get(args.token_env)
    if not token:
        parser.error("Set the named environment variable to a local service token before starting")
    server = make_server(store, args.owner, token, args.port)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}", "scope": "local_single_owner_prototype"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
