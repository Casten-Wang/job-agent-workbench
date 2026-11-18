"""Configure credentials using hidden input and current-user Windows DPAPI."""

import argparse
import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def apply_saved():
    from local_secrets import load
    saved = load(ROOT / "web/data/user/career-agent/model-credentials.dpapi.json")
    for name in ("LANGFUSE_BASE_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_TRACING"):
        if name in saved:
            os.environ.setdefault(name, saved[name])
    if os.getenv("LANGFUSE_TRACING", "").lower() == "true":
        os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_CAPTURE_CONTENT"] = "false"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Langfuse Cloud or self-hosted origin")
    parser.add_argument("--disable", action="store_true")
    args = parser.parse_args()
    from local_secrets import load, save
    path = ROOT / "web/data/user/career-agent/model-credentials.dpapi.json"
    saved = load(path)
    if args.disable:
        saved["LANGFUSE_TRACING"] = "false"
    else:
        url = (args.base_url or input("Langfuse base URL: ")).strip().rstrip("/")
        public = getpass.getpass("Langfuse public key (hidden): ").strip()
        secret = getpass.getpass("Langfuse secret key (hidden): ").strip()
        sys.path.insert(0, str(ROOT.parent))
        from interview_agent.langfuse_monitor import configured
        values = {"LANGFUSE_BASE_URL": url, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
        os.environ.update(values)
        if not configured():
            parser.error("Use an HTTPS origin (HTTP allowed only for localhost) and nonempty keys")
        from langfuse import Langfuse
        try:
            lf = Langfuse(public_key=public, secret_key=secret, base_url=url, timeout=5)
            try:
                valid = lf.auth_check()
            finally:
                lf.shutdown()
        except Exception:
            valid = False
        if not valid:
            parser.exit(1, "Langfuse authentication failed; existing saved configuration preserved.\n")
        saved.update(values, LANGFUSE_TRACING="true")
    save(path, saved)
    print("Saved with Windows DPAPI. Restart the workbench to apply.")


if __name__ == "__main__":
    main()
