"""MCP exposure of the cross-check signal — folded into get_affair, offline.

The tool surface stays exactly three tools; an agent client sees the
cross-check block (score + discrepancies + backend label) inside
get_affair's output, so it can tell a measured Apertus agreement from a
stub harness figure without leaving the tool result.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from mcp.server.fastmcp import FastMCP

from bundesbrief.mcp_server import create_server, register_tools


def _call(mcp: FastMCP, name: str, args: dict | None = None):
    result = asyncio.run(mcp.call_tool(name, args or {}))
    if isinstance(result, tuple):
        _, structured = result
        return structured["result"]
    return json.loads(result[0].text)


class TestMcpCrossCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with patch.dict("os.environ", {}, clear=True):  # stub backend, offline
            cls.mcp = FastMCP(name="test-bb-xcheck")
            register_tools(cls.mcp)

    def test_tool_surface_still_three_tools(self) -> None:
        names = {t.name for t in asyncio.run(create_server().list_tools())}
        self.assertEqual(names, {"list_affairs", "get_affair", "verify_ledger"})

    def test_get_affair_carries_cross_check_block(self) -> None:
        affairs = _call(self.mcp, "list_affairs")
        affair_id = affairs[0]["affair_id"]
        payload = _call(self.mcp, "get_affair", {"affair_id": affair_id})
        block = payload["cross_check"]
        self.assertTrue(block["ran"])
        self.assertEqual(block["agreement_score"], 1.0)
        self.assertIsInstance(block["discrepancies"], list)
        # the honesty field survives into the agent-facing surface:
        self.assertTrue(block["backend"].startswith("stub:"))
        self.assertIn("NOT the Apertus model", block["backend"])

    def test_contract_fields_unchanged_alongside_the_block(self) -> None:
        affairs = _call(self.mcp, "list_affairs")
        affair_id = affairs[0]["affair_id"]
        payload = _call(self.mcp, "get_affair", {"affair_id": affair_id})
        self.assertEqual(payload["affair_id"], affair_id)
        self.assertIn("telemetry", payload)
        self.assertIn("policy", payload)
        self.assertIn("payload_hash", payload)

    def test_unknown_affair_error_shape_unchanged(self) -> None:
        result = _call(self.mcp, "get_affair", {"affair_id": "no-such-affair"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
