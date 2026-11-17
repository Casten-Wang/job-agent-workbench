#!/usr/bin/env python3
"""Tests for the optional UPCV MCP metadata adapter (no network)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import upcv_adapter  # noqa: E402


class UpcvAdapterTests(unittest.TestCase):
    def test_status_without_key_does_not_claim_configured(self) -> None:
        result = upcv_adapter.status({})
        self.assertFalse(result["api_key_present"])
        self.assertTrue(result["network_required"])
        self.assertFalse(result["runtime_integrated"])
        self.assertEqual(result["tool_count"], 20)
        self.assertNotIn("api_key", result)
        self.assertNotIn("not-a-real-key", json.dumps(result))

    def test_status_with_key_reports_presence_only(self) -> None:
        result = upcv_adapter.status({"UPCV_API_KEY": "not-a-real-key"})
        self.assertTrue(result["api_key_present"])
        self.assertNotIn("not-a-real-key", json.dumps(result))

    def test_mcp_config_uses_env_reference_not_secret(self) -> None:
        config = upcv_adapter.mcp_config()
        server = config["mcpServers"]["upcv"]
        self.assertEqual(server["command"], "npx")
        self.assertEqual(server["args"], ["-y", "@upcv/mcp-server"])
        self.assertEqual(server["env"]["UPCV_API_KEY"], "${UPCV_API_KEY}")
        self.assertNotIn("sk-", json.dumps(config))

    def test_tool_names_are_unique(self) -> None:
        names = upcv_adapter.tool_names()
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("resume.print", names)
        self.assertIn("campus.searchJobs", names)


if __name__ == "__main__":
    unittest.main()
