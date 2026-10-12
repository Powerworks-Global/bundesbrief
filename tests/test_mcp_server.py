import asyncio
import json
import unittest

from mcp.server.fastmcp import FastMCP

from bundesbrief.mcp_server import DATA_DIR, create_server, register_tools


def _call(mcp: FastMCP, name: str, args: dict | None = None) -> dict | list:
    """Call a tool and return its decoded result.

    FastMCP wraps a list-returning tool as (content_blocks, structured_result) and a
    dict-returning tool as a plain list with one JSON TextContent block — handle both.
    """
    result = asyncio.run(mcp.call_tool(name, args or {}))
    if isinstance(result, tuple):
        _, structured = result
        return structured["result"]
    return json.loads(result[0].text)


class TestMcpServer(unittest.TestCase):
    def setUp(self) -> None:
        self.mcp = FastMCP(name="test-bundesbrief")
        register_tools(self.mcp)

    def test_registers_expected_tools(self) -> None:
        tools = asyncio.run(self.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, {"list_affairs", "get_affair", "verify_ledger"})

    def test_list_affairs_covers_all_sample_documents(self) -> None:
        affairs = _call(self.mcp, "list_affairs")
        sample_count = len(list(DATA_DIR.glob("*.txt")))
        self.assertEqual(len(affairs), sample_count)
        modes = {a["mode"] for a in affairs}
        self.assertEqual(modes, {"ACT", "SUGGEST", "HALT"})

    def test_get_affair_returns_full_contract_for_known_id(self) -> None:
        affairs = _call(self.mcp, "list_affairs")
        affair_id = affairs[0]["affair_id"]
        contract = _call(self.mcp, "get_affair", {"affair_id": affair_id})
        self.assertEqual(contract["affair_id"], affair_id)
        self.assertIn("telemetry", contract)
        self.assertIn("policy", contract)

    def test_get_affair_reports_error_for_unknown_id(self) -> None:
        result = _call(self.mcp, "get_affair", {"affair_id": "does-not-exist"})
        self.assertIn("error", result)

    def test_verify_ledger_reports_valid_chain(self) -> None:
        _call(self.mcp, "list_affairs")  # ensure seeded
        report = _call(self.mcp, "verify_ledger")
        self.assertTrue(report["valid"])
        self.assertGreater(report["entries"], 0)

    def test_create_server_builds_with_all_tools(self) -> None:
        server = create_server()
        tools = asyncio.run(server.list_tools())
        self.assertEqual(len(tools), 3)


if __name__ == "__main__":
    unittest.main()
