#!/usr/bin/env python3
"""Optional UPCV/ClawJob MCP adapter metadata (no network, no credentials).

The upstream project is ``HireTechUpUp/upcv-mcp-server`` (MIT). It is a
cloud-backed MCP server: it needs ``UPCV_API_KEY`` and calls
``https://clawjob.upcv.tech`` by default. This module does **not** install,
start, or call that server. It only describes the optional integration and
emits an MCP client configuration that references an environment variable.

Why not wire it into the offline runtime: the local workbench promises no
external HTTP/LLM dependency, no credential store, and no automatic
submission. UPCV is therefore an opt-in external enhancement, not a default
code path. A user who wants it must configure the key in their own
environment and enable the MCP server in their MCP client.

CLI:
    python3 -I tools/upcv_adapter.py --status
    python3 -I tools/upcv_adapter.py --print-config
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping

sys.dont_write_bytecode = True

DEFAULT_API_URL = "https://clawjob.upcv.tech"
PACKAGE = "@upcv/mcp-server"
LICENSE = "MIT"

# Names taken from the upstream README. Kept as data for an explicit UI/report;
# this module does not call any of them.
TOOLS: dict[str, tuple[str, ...]] = {
    "resume": (
        "resume.list",
        "resume.get",
        "resume.create",
        "resume.update",
        "resume.delete",
        "resume.print",
        "template.list",
    ),
    "editing": (
        "resume.updateBasics",
        "resume.updateSection",
        "resume.updateSectionItem",
        "resume.deleteSectionItem",
        "resume.updateMetadata",
    ),
    "sections": (
        "section.create",
        "section.delete",
        "resume.reorderLayout",
    ),
    "campus": (
        "campus.searchRecruitments",
        "campus.getRecruitment",
        "campus.recommend",
        "campus.searchJobs",
        "campus.getJob",
    ),
}


def tool_names() -> list[str]:
    return [name for group in TOOLS.values() for name in group]


def status(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Return JSON-safe integration status; never include the key value."""

    source = os.environ if env is None else env
    key_present = bool(str(source.get("UPCV_API_KEY") or "").strip())
    api_url = str(source.get("UPCV_API_URL") or DEFAULT_API_URL).strip() or DEFAULT_API_URL
    return {
        "provider": "UP简历 / ClawJob",
        "package": PACKAGE,
        "license": LICENSE,
        "api_url": api_url,
        "api_key_env": "UPCV_API_KEY",
        "api_key_present": key_present,
        "network_required": True,
        "runtime_integrated": False,
        "mode": "optional_external_mcp",
        "tool_count": len(tool_names()),
        "tools": tool_names(),
        "note": (
            "云端 MCP 服务，不在本地离线工作台的默认运行路径中；"
            "需要用户显式配置 UPCV_API_KEY 并在 MCP 客户端启用。"
            "本模块不读取、不打印、不写入密钥值。"
        ),
    }


def mcp_config(api_url: str | None = None) -> dict[str, Any]:
    """Emit a client config that references the environment variable.

    The literal ``${UPCV_API_KEY}`` is a reference, not a credential. Some MCP
    clients expand it; others require the user to fill the env field. No secret
    is ever embedded in this file.
    """

    env = {"UPCV_API_KEY": "${UPCV_API_KEY}"}
    if api_url:
        env["UPCV_API_URL"] = api_url
    return {
        "mcpServers": {
            "upcv": {
                "command": "npx",
                "args": ["-y", PACKAGE],
                "env": env,
            }
        }
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Describe the optional UPCV/ClawJob MCP integration. No network "
            "request, no package install, no credential read beyond presence."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="print integration status")
    group.add_argument(
        "--print-config",
        action="store_true",
        help="print an MCP client config with an env-var reference",
    )
    parser.add_argument("--api-url", help="optional UPCV API base URL for the config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    value = status() if args.status else mcp_config(args.api_url)
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
